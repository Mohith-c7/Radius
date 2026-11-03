#!/usr/bin/env python3
"""Radius CI helper: resolve the analysis, fetch its test plan, upload JUnit results.

Flow inside a CI job for a pull request head commit:

1. ``radius_ci.py plan --repository owner/name --pr N --commit SHA``
   waits until Radius has analysed that commit, then prints the selected
   test files (one per line). ``resolve`` does only the waiting/lookup and
   prints the analysis id.
2. Run those tests in CI with JUnit output (e.g. ``pytest --junitxml=junit.xml``).
3. ``radius_ci.py upload ... --junit junit.xml --commit SHA`` sends the report,
   bound to the commit it was produced from, and prints the resulting verdict.

``radius_ci.py verdict`` prints the current verdict without uploading (e.g. when
Radius selected no tests) and applies the same exit-code gate.

``radius_ci.py run`` is the laptop variant of steps 2 and 3 for a demo or a
machine without a CI runner that can reach the API: it waits for the analysis,
runs the repository's pytest suite locally with JUnit output, and uploads the
report bound to the checked-out ``HEAD`` commit (``--commit`` overrides). Use
``--dry-run`` to run the tests and show what would be uploaded without any
network call. ``--api`` and ``--org`` default to ``RADIUS_API_URL`` and
``RADIUS_ORG_ID``.

Exit codes: 0 success, 1 error (API rejected the request, network failure,
invalid input), 2 usage error, 3 timed out waiting for the analysis,
4 the uploaded results make the Radius verdict ``failed``, 5 the verdict is not
``verified`` and ``--require-verified`` was given.

The API key is read from the ``RADIUS_API_KEY`` environment variable only and
is never printed. Standard library only, so it runs on any CI image with
Python 3.10+.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

TIMEOUT_SECONDS = 30
API_KEY_ENV = "RADIUS_API_KEY"
API_URL_ENV = "RADIUS_API_URL"
ORG_ID_ENV = "RADIUS_ORG_ID"
DEFAULT_WAIT_SECONDS = 900
DEFAULT_POLL_SECONDS = 10
MAX_TRANSIENT_FAILURES = 3
EXIT_ERROR = 1
EXIT_TIMEOUT = 3
EXIT_VERDICT_FAILED = 4
EXIT_NOT_VERIFIED = 5
_HEX_SHA = re.compile(r"^[0-9a-fA-F]{7,64}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_TRANSIENT_STATUSES = frozenset({429, 502, 503, 504})
_READY_STATUSES = frozenset({"completed"})
_FAILED_STATUSES = frozenset({"failed", "cancelled"})


class RadiusCiError(Exception):
    """A user-facing failure; the message never contains the API key."""

    exit_code = EXIT_ERROR


class RadiusTimeoutError(RadiusCiError):
    """The analysis did not become ready before the deadline."""

    exit_code = EXIT_TIMEOUT


class RadiusVerdictError(RadiusCiError):
    """Results were accepted, but the verdict does not allow merging."""

    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class RadiusApiError(RadiusCiError):
    """The Radius API answered with an HTTP error status."""

    def __init__(self, status: int, server_message: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.server_message = server_message


class _TransientError(Exception):
    """Network failure or 429/5xx that is worth retrying while polling."""

    def __init__(self, error: RadiusCiError) -> None:
        super().__init__(str(error))
        self.error = error


# --------------------------------------------------------------------------- validation


def _validate_uuid(value: str, name: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise RadiusCiError(f"{name} must be a UUID (got {_preview(value)}).") from exc


def _validate_sha(value: str | None) -> str:
    if not _HEX_SHA.match(value or ""):
        raise RadiusCiError(
            "commit SHA must be 7-64 hexadecimal characters. In GitHub Actions pass "
            "${{ github.event.pull_request.head.sha }} (not GITHUB_SHA, which is the "
            "merge commit on pull_request events)."
        )
    return value.lower()


def _validate_api(url: str) -> str:
    parsed = urllib.parse.urlparse(url or "")
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RadiusCiError("--api must be an http(s) URL such as https://radius.example.com.")
    if parsed.username or parsed.password:
        raise RadiusCiError(
            "--api must not embed credentials; put the key in the RADIUS_API_KEY secret."
        )
    return url.rstrip("/")


def _validate_repository(value: str) -> str:
    if not _REPOSITORY.match(value or ""):
        raise RadiusCiError("--repository must look like owner/name (e.g. $GITHUB_REPOSITORY).")
    return value


def _preview(value: object) -> str:
    text = str(value)
    return repr(text if len(text) <= 40 else text[:37] + "...")


def _safe_test_path(path: str) -> str:
    """Reject paths that could be read as CLI options or escape the checkout.

    Test paths come from the pull request (file names are attacker-controlled
    on forks), and they end up as arguments to the test runner.
    """

    normalized = path.replace("\\", "/")
    if (
        not normalized
        or normalized.startswith(("-", "/"))
        or re.match(r"^[A-Za-z]:", normalized)
        or ".." in normalized.split("/")
        or any(ord(char) < 32 for char in normalized)
    ):
        raise RadiusCiError(f"Refusing unsafe test path from the plan: {_preview(path)}.")
    return path


# --------------------------------------------------------------------------- HTTP


def _api_key() -> str:
    return os.environ.get(API_KEY_ENV, "")


def _scrub(text: str) -> str:
    """Remove the API key from any text before it is printed."""

    key = _api_key()
    return text.replace(key, "***") if key else text


def _headers(organization_id: str) -> dict[str, str]:
    headers = {
        "X-Radius-Organization-Id": organization_id,
        "Accept": "application/json",
        "User-Agent": "radius-ci/2",
    }
    api_key = _api_key()
    if api_key:
        headers["X-Radius-API-Key"] = api_key
    return headers


def _server_message(body: bytes) -> str:
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except ValueError:
        payload = None
    message = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
        detail = payload.get("detail")
        if not message and isinstance(detail, str):
            message = detail
        elif not message and isinstance(detail, list) and detail:
            # FastAPI request validation errors.
            first = detail[0] if isinstance(detail[0], dict) else {}
            location = ".".join(str(part) for part in first.get("loc", ()) if part != "query")
            message = f"{location}: {first.get('msg', 'invalid value')}".strip(": ")
    if not isinstance(message, str) or not message:
        message = body.decode("utf-8", errors="replace").strip()[:300] or "no response body"
    return message


_HINTS = {
    401: (
        "Authentication failed. Check that the RADIUS_API_KEY secret is set and "
        "belongs to the organization passed with --org."
    ),
    403: (
        "Access denied. The API key is wrong for this organization, the key is "
        "read-only (uploading results needs a key with write scope), or the "
        "repository/analysis belongs to another organization. Check RADIUS_ORG_ID "
        "and RADIUS_API_KEY."
    ),
    404: (
        "Not found. Check the analysis id, or that the repository is connected to "
        "Radius and the pull request/commit has been analysed (is the Radius GitHub "
        "App installed and receiving pull_request events?)."
    ),
    409: (
        "Conflict. Either the analysis is not completed yet (wait for it: plan/resolve "
        "or upload --wait), or the results do not match it: the commit differs from "
        "the analysed head, the PR has a newer head (stale analysis), or the analysis "
        "failed/was cancelled. Resolve the analysis again for the current head SHA, "
        "re-run the tests on that commit, and upload again."
    ),
    422: (
        "Rejected as invalid. Check the commit SHA and that the report is JUnit XML "
        "with per-test <testcase> entries (e.g. pytest --junitxml)."
    ),
}


def _api_error(status: int, body: bytes) -> RadiusApiError:
    server = _scrub(_server_message(body))
    if status >= 500:
        hint = "Radius API server error; retry later or contact the Radius operator."
    else:
        hint = _HINTS.get(status, "Request rejected.")
    return RadiusApiError(status, server, f"HTTP {status}: {server}\n  -> {hint}")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so the API key header is never forwarded to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise urllib.error.HTTPError(req.full_url, code, "redirects are not followed", headers, fp)


_OPENER = urllib.request.build_opener(_NoRedirect)


def _host(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return f"{parsed.scheme}://{parsed.hostname}" + (f":{parsed.port}" if parsed.port else "")


# Indirections so tests can control time without patching the time module.
def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _clock() -> float:
    return time.monotonic()


def _request_once(
    method: str,
    url: str,
    headers: dict[str, str],
    data: bytes | None = None,
) -> bytes:
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with _OPENER.open(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            raise RadiusCiError(
                f"Radius API at {_host(url)} answered with a redirect (HTTP {exc.code}); "
                "redirects are refused so the API key is never sent elsewhere. Use the "
                "final https:// API URL in --api."
            ) from None
        error = _api_error(exc.code, exc.read())
        if exc.code in _TRANSIENT_STATUSES:
            raise _TransientError(error) from None
        raise error from None
    except urllib.error.URLError as exc:
        raise _TransientError(
            RadiusCiError(
                f"Could not reach Radius API at {_host(url)}: {_scrub(str(exc.reason))}. "
                "Check --api and that the runner can reach it."
            )
        ) from None
    except (TimeoutError, ConnectionError, OSError) as exc:
        raise _TransientError(
            RadiusCiError(
                f"Radius API at {_host(url)} did not answer ({exc.__class__.__name__}); "
                f"timeout is {TIMEOUT_SECONDS}s."
            )
        ) from None


def _request(
    method: str,
    url: str,
    headers: dict[str, str],
    data: bytes | None = None,
    *,
    retries: int = 2,
    backoff_seconds: float = 2.0,
) -> bytes:
    """Send a request, retrying network errors and 429/502/503/504."""

    attempt = 0
    while True:
        try:
            return _request_once(method, url, headers, data)
        except _TransientError as exc:
            if attempt >= retries:
                raise exc.error from None
            attempt += 1
            _log(f"{exc.error} (retry {attempt}/{retries})")
            _sleep(backoff_seconds * attempt)


def _json_data(body: bytes) -> dict:
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise RadiusCiError("Radius API returned a non-JSON response.") from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise RadiusCiError("Radius API response has no data object.")
    return data


def _log(message: str) -> None:
    print(f"radius_ci: {_scrub(message)}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- operations


@dataclass(frozen=True)
class Target:
    """How to find the analysis: an explicit id or (repository, PR, commit)."""

    api: str
    organization_id: str
    analysis_id: str | None = None
    repository: str | None = None
    pull_request: int | None = None
    commit_sha: str | None = None


def _target(args: argparse.Namespace) -> Target:
    api = _validate_api(args.api)
    organization_id = _validate_uuid(args.org, "organization id (--org)")
    commit = _validate_sha(args.commit) if args.commit else None
    if args.analysis:
        return Target(
            api, organization_id, analysis_id=_validate_uuid(args.analysis, "analysis id"),
            commit_sha=commit,
        )
    if not (args.repository and args.pr and commit):
        raise RadiusCiError(
            "Pass --analysis ID, or --repository owner/name --pr NUMBER --commit SHA "
            "to look the analysis up."
        )
    if args.pr < 1:
        raise RadiusCiError("--pr must be a positive pull request number.")
    return Target(
        api,
        organization_id,
        repository=_validate_repository(args.repository),
        pull_request=args.pr,
        commit_sha=commit,
    )


def _fetch_analysis(target: Target) -> dict:
    headers = _headers(target.organization_id)
    if target.analysis_id:
        url = f"{target.api}/api/v1/analyses/{target.analysis_id}"
    else:
        query = urllib.parse.urlencode(
            {
                "repository": target.repository,
                "pullRequest": target.pull_request,
                "commitSha": target.commit_sha,
            }
        )
        url = f"{target.api}/api/v1/analyses/lookup?{query}"
    return _json_data(_request_once("GET", url, headers))


def resolve(
    target: Target,
    *,
    wait_seconds: float = DEFAULT_WAIT_SECONDS,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
) -> dict:
    """Return the analysis once it is ``completed``; poll until ``wait_seconds``.

    A 404 from the lookup means Radius has not created the analysis yet (the
    webhook may still be in flight), so it is retried like a pending status.
    Network errors and 429/5xx are retried up to ``MAX_TRANSIENT_FAILURES``
    times in a row, so a wrong ``--api`` fails fast instead of waiting it out.
    """

    deadline = _clock() + max(0.0, wait_seconds)
    last_state = "not created yet"
    transient_failures = 0
    while True:
        try:
            analysis = _fetch_analysis(target)
            transient_failures = 0
        except RadiusApiError as exc:
            if exc.status != 404 or target.analysis_id:
                raise
            analysis, last_state = None, "not created yet"
        except _TransientError as exc:
            transient_failures += 1
            if transient_failures >= MAX_TRANSIENT_FAILURES:
                raise exc.error from None
            analysis, last_state = None, f"API unavailable ({exc.error})"
        if analysis is not None:
            status = str(analysis.get("status", "unknown"))
            last_state = status
            commit = str(analysis.get("commit_sha", "")).lower()
            if target.commit_sha and commit and not commit.startswith(target.commit_sha[:40]):
                raise RadiusCiError(
                    f"Analysis {analysis.get('id')} is for commit {commit[:12]}, not "
                    f"{target.commit_sha[:12]}. Use the analysis for the commit under test."
                )
            if status in _READY_STATUSES:
                return analysis
            if status in _FAILED_STATUSES:
                raise RadiusCiError(
                    f"Radius analysis {analysis.get('id')} is {status}; it has no usable "
                    "test plan. Re-run the analysis in Radius (or push a new commit) and "
                    "retry. The GitHub check shows the failure reason."
                )
        remaining = deadline - _clock()
        if remaining <= 0:
            raise RadiusTimeoutError(
                f"Timed out after {wait_seconds:.0f}s waiting for the Radius analysis "
                f"(last state: {last_state}). Increase --wait, or check the Radius worker "
                "and the GitHub App webhook delivery."
            )
        _log(f"waiting for analysis (state: {last_state}); {remaining:.0f}s left")
        _sleep(min(poll_seconds, remaining))


def selected_tests(target: Target, analysis_id: str) -> list[str]:
    """Return the selected test file paths for a ready analysis (deduplicated)."""

    url = f"{target.api}/api/v1/analyses/{analysis_id}/tests"
    data = _json_data(_request("GET", url, _headers(target.organization_id)))
    paths: list[str] = []
    for item in data.get("selected_tests") or ():
        test = item.get("test") if isinstance(item, dict) else None
        path = test.get("path") if isinstance(test, dict) else None
        if isinstance(path, str) and path and path not in paths:
            paths.append(_safe_test_path(path))
    if not paths and data.get("cli_args"):
        for path in str(data["cli_args"]).split():
            if path not in paths:
                paths.append(_safe_test_path(path))
    return paths


def upload(target: Target, analysis_id: str, junit_path: str, commit_sha: str) -> dict:
    """Upload one JUnit report bound to ``commit_sha``; return the response data."""

    path = Path(junit_path)
    if not path.is_file():
        raise RadiusCiError(
            f"JUnit report not found: {junit_path}. Did the test step run with "
            "--junitxml (pytest) or a JUnit reporter?"
        )
    body = path.read_bytes()
    if not body.strip():
        raise RadiusCiError(f"JUnit report is empty: {junit_path}.")
    query = urllib.parse.urlencode({"commit_sha": _validate_sha(commit_sha)})
    url = f"{target.api}/api/v1/analyses/{analysis_id}/tests/results?{query}"
    headers = _headers(target.organization_id)
    headers["Content-Type"] = "application/xml"
    # Exact replays are idempotent server-side, so retrying is safe.
    return _json_data(_request("POST", url, headers, data=body))


def upload_summary(junit_path: str, data: dict) -> str:
    """One line describing what a single upload contributed."""

    this = data.get("upload") if isinstance(data.get("upload"), dict) else data
    replay = " (identical report already recorded; not counted twice)" if this.get("duplicate") else ""
    return (
        f"Uploaded {Path(junit_path).name}: {this.get('total_tests', '?')} tests, "
        f"{this.get('passed', '?')} passed, {this.get('failed', '?')} failed, "
        f"{this.get('skipped', '?')} skipped{replay}."
    )


def _names(values: object, limit: int = 10) -> str:
    items = [str(item) for item in (values or ())] if isinstance(values, list | tuple) else []
    shown = ", ".join(items[:limit])
    return shown + (f" (+{len(items) - limit} more)" if len(items) > limit else "")


def verdict_summary(data: dict) -> str:
    """Describe the verdict and evidence gaps after the (accumulated) uploads."""

    status = data.get("verification_status") or "unknown"
    lines = [
        f"Radius verdict: {status} (all uploads for this analysis: "
        f"{data.get('total_tests', '?')} tests, {data.get('passed', '?')} passed, "
        f"{data.get('failed', '?')} failed, {data.get('skipped', '?')} skipped; "
        f"{data.get('upload_count', '?')} upload(s))."
    ]
    attribution = data.get("selected_tests")
    if isinstance(attribution, dict):
        lines.append(
            f"  Selected test files executed: {attribution.get('executed_count', '?')}"
            f"/{attribution.get('selected_count', '?')}."
        )
        for key, label in (
            ("failed", "Failed"),
            ("not_reported", "Selected but not in any report"),
            ("skipped", "Only skipped"),
        ):
            if attribution.get(key):
                lines.append(f"  {label}: {_names(attribution[key])}")
    if data.get("contradictory_cases"):
        lines.append(f"  Contradictory results: {_names(data['contradictory_cases'])}")
    if status == "insufficient_evidence":
        lines.append(
            "  Not enough evidence to verify: run every selected test file and upload "
            "its JUnit report (see the Radius check for remaining gaps)."
        )
    return "\n".join(lines)


def current_verdict(target: Target, analysis_id: str) -> dict:
    """Return the analysis' current confidence report."""

    url = f"{target.api}/api/v1/analyses/{analysis_id}/confidence"
    return _json_data(_request("GET", url, _headers(target.organization_id)))


def report_summary(report: dict) -> str:
    status = report.get("verification_status") or "unknown"
    lines = [f"Radius verdict: {status}."]
    if report.get("summary"):
        lines.append(f"  {report['summary']}")
    gaps = [
        str(item.get("message"))
        for item in report.get("evidence") or ()
        if isinstance(item, dict) and item.get("label") == "verdict_gap"
    ]
    if gaps:
        lines.append(f"  Gaps: {_names(gaps)}")
    return "\n".join(lines)


def _gate(status: str, require_verified: bool) -> None:
    """Turn the verdict into the job's exit code (the merge gate in CI)."""

    if status == "failed":
        raise RadiusVerdictError(
            "Radius verdict is failed: a selected test failed on this commit.",
            EXIT_VERDICT_FAILED,
        )
    if require_verified and status != "verified":
        raise RadiusVerdictError(
            f"Radius verdict is {status}, and --require-verified was given.",
            EXIT_NOT_VERIFIED,
        )


# --------------------------------------------------------------------------- outputs


def _write_github_output(values: dict[str, str]) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        raise RadiusCiError("--github-output was given but GITHUB_OUTPUT is not set.")
    with open(output, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            delimiter = f"radius_{uuid.uuid4().hex}"
            handle.write(f"{key}<<{delimiter}\n{value}\n{delimiter}\n")


# --------------------------------------------------------------------------- CLI


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog="The API key is read from the RADIUS_API_KEY environment variable.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    commands = {
        "resolve": "Wait for the analysis of a PR head commit and print its id.",
        "plan": "Wait for the analysis and print the selected test files.",
        "upload": "Upload JUnit report(s) for the analysis, bound to a commit.",
        "verdict": "Print the analysis' current verdict and gate on it.",
        "run": "Run the repository's pytest suite locally, then upload the JUnit report.",
    }
    for name, help_text in commands.items():
        cmd = sub.add_parser(name, help=help_text, description=help_text)
        cmd.add_argument(
            "--api",
            required=not os.environ.get(API_URL_ENV),
            default=os.environ.get(API_URL_ENV),
            help=f"Radius API base URL (default: ${API_URL_ENV})",
        )
        cmd.add_argument(
            "--org",
            required=not os.environ.get(ORG_ID_ENV),
            default=os.environ.get(ORG_ID_ENV),
            help=f"Radius organization id (default: ${ORG_ID_ENV})",
        )
        cmd.add_argument("--analysis", help="Radius analysis id (skips the lookup)")
        cmd.add_argument("--repository", help="owner/name, e.g. $GITHUB_REPOSITORY")
        cmd.add_argument("--pr", type=int, help="Pull request number")
        if name in {"upload", "verdict", "run"}:
            cmd.add_argument(
                "--require-verified",
                action="store_true",
                help=(
                    "Exit 5 unless the verdict is verified (use when this job is a "
                    "required status check). Otherwise only a failed verdict exits 4."
                ),
            )
        cmd.add_argument(
            "--commit",
            required=name == "upload",
            help="PR head commit SHA (the commit the tests run on)"
            + ("; default for run: git HEAD of --repo-dir" if name == "run" else ""),
        )
        cmd.add_argument(
            "--wait",
            type=float,
            default=120 if name in {"upload", "run"} else DEFAULT_WAIT_SECONDS,
            help="Seconds to wait for the analysis to complete (default: %(default)s)",
        )
        cmd.add_argument(
            "--poll-interval",
            type=float,
            default=DEFAULT_POLL_SECONDS,
            help="Seconds between status checks (default: %(default)s)",
        )
        cmd.add_argument(
            "--github-output",
            action="store_true",
            help="Also write step outputs to $GITHUB_OUTPUT",
        )
    sub.choices["plan"].add_argument(
        "--output",
        help="Also write the selected paths (one per line) to this file",
    )
    sub.choices["upload"].add_argument(
        "--junit",
        required=True,
        action="append",
        help="JUnit XML report path (repeat for several reports)",
    )
    run = sub.choices["run"]
    run.add_argument("--repo-dir", default=".", help="Checkout to test (default: current directory)")
    run.add_argument("--junit", help="Upload this existing JUnit report instead of running pytest")
    run.add_argument(
        "--junit-out", help="Where pytest writes the report (default: a temporary directory)"
    )
    run.add_argument(
        "--selected-only",
        action="store_true",
        help="Run only the test files Radius selected for this analysis (default: whole suite)",
    )
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the tests and validate the report, but make no network call and upload nothing",
    )
    run.add_argument("pytest_args", nargs="*", help="Extra pytest arguments, after a literal --")
    return parser


def _git_head(repo_dir: Path) -> str:
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv
            ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RadiusCiError(
            f"Could not read the commit of {repo_dir} (git rev-parse HEAD failed). "
            "Run inside the checkout, or pass --commit SHA."
        ) from exc
    return done.stdout.strip()


def _run_pytest(repo_dir: Path, junit_path: Path, extra: list[str]) -> int:
    """Run pytest in ``repo_dir``; the API key is removed from the child environment."""

    env = {k: v for k, v in os.environ.items() if k != API_KEY_ENV}
    command = [
        sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q",
        f"--junitxml={junit_path}", *extra,
    ]
    _log(f"running pytest in {repo_dir}")
    try:
        return subprocess.run(  # noqa: S603 - argv built here, no shell
            command, cwd=repo_dir, env=env, check=False
        ).returncode
    except OSError as exc:
        raise RadiusCiError(f"Could not start pytest: {exc}") from exc


def _junit_counts(junit_path: Path) -> dict[str, int]:
    import xml.etree.ElementTree as ET  # noqa: S405 - our own report, not remote input

    try:
        root = ET.parse(junit_path).getroot()  # noqa: S314
    except (ET.ParseError, OSError) as exc:
        raise RadiusCiError(f"JUnit report {junit_path} is not readable XML: {exc}") from exc
    counts = {"total": 0, "failed": 0, "skipped": 0}
    for case in root.iter("testcase"):
        counts["total"] += 1
        if case.find("failure") is not None or case.find("error") is not None:
            counts["failed"] += 1
        elif case.find("skipped") is not None:
            counts["skipped"] += 1
    if counts["total"] == 0:
        raise RadiusCiError(f"JUnit report {junit_path} has no <testcase> entries.")
    return counts


def _run_laptop(args: argparse.Namespace) -> None:
    repo_dir = Path(args.repo_dir).resolve()
    if not repo_dir.is_dir():
        raise RadiusCiError(f"--repo-dir {args.repo_dir} is not a directory.")
    if not args.commit:
        args.commit = _git_head(repo_dir)
    target = _target(args)  # validates every input before anything runs
    commit = _validate_sha(args.commit)
    extra = list(args.pytest_args or ())
    if extra and extra[0] == "--":
        extra = extra[1:]

    analysis_id = target.analysis_id
    if not args.dry_run:
        analysis = resolve(target, wait_seconds=args.wait, poll_seconds=args.poll_interval)
        analysis_id = _validate_uuid(str(analysis.get("id")), "analysis id from the API")
        if args.selected_only:
            paths = selected_tests(target, analysis_id)
            if not paths:
                raise RadiusCiError("Radius selected no tests; run without --selected-only.")
            extra = [*paths, *extra]

    cleanup = None
    try:
        if args.junit:
            junit = Path(args.junit)
        else:
            if args.junit_out:
                junit = Path(args.junit_out)
            else:
                import tempfile

                cleanup = tempfile.TemporaryDirectory(prefix="radius-ci-")
                junit = Path(cleanup.name) / "junit.xml"
            junit.parent.mkdir(parents=True, exist_ok=True)
            code = _run_pytest(repo_dir, junit, extra)
            # 0 = all passed, 1 = some tests failed (still evidence); anything else means
            # pytest itself did not run the suite, so there is nothing trustworthy to upload.
            if code not in (0, 1) or not junit.is_file():
                raise RadiusCiError(
                    f"pytest exited with code {code} before producing a usable report; "
                    "nothing was uploaded. Fix the test run first."
                )
        counts = _junit_counts(junit)
        _log(
            f"report: {counts['total']} tests, {counts['failed']} failed, "
            f"{counts['skipped']} skipped, for commit {commit[:12]}"
        )
        if args.dry_run:
            query = urllib.parse.urlencode({"commit_sha": commit})
            where = analysis_id or "<resolved from repository/pr/commit>"
            print(
                f"DRY RUN: would POST {junit.stat().st_size} bytes of JUnit XML to "
                f"{target.api}/api/v1/analyses/{where}/tests/results?{query} "
                f"(org {target.organization_id}); nothing was sent."
            )
            return
        data = upload(target, analysis_id, str(junit), commit)
        print(upload_summary(str(junit), data))
        status = str(data.get("verification_status") or "unknown")
        print(verdict_summary(data))
        if args.github_output:
            _write_github_output({"analysis-id": str(analysis_id), "verification-status": status})
        _gate(status, args.require_verified)
    finally:
        if cleanup is not None:
            cleanup.cleanup()


def _run(args: argparse.Namespace) -> None:
    if args.command == "run":
        _run_laptop(args)
        return
    target = _target(args)
    analysis = resolve(target, wait_seconds=args.wait, poll_seconds=args.poll_interval)
    analysis_id = _validate_uuid(str(analysis.get("id")), "analysis id from the API")
    outputs = {"analysis-id": analysis_id}

    if args.command == "resolve":
        print(analysis_id)
    elif args.command == "plan":
        paths = selected_tests(target, analysis_id)
        text = "".join(f"{path}\n" for path in paths)
        sys.stdout.write(text)
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
            outputs["tests-file"] = str(Path(args.output).resolve())
        outputs["test-count"] = str(len(paths))
        outputs["has-tests"] = "true" if paths else "false"
        if not paths:
            _log(
                "Radius selected no tests for this commit; nothing to run or upload. "
                "The verdict stays insufficient_evidence unless the change is docs-only."
            )
    elif args.command == "upload":
        data: dict = {}
        for junit in args.junit:
            data = upload(target, analysis_id, junit, args.commit)
            print(upload_summary(junit, data))
        status = str(data.get("verification_status") or "unknown")
        print(verdict_summary(data))
        outputs["verification-status"] = status
        if args.github_output:
            _write_github_output(outputs)
        _gate(status, args.require_verified)
        return
    elif args.command == "verdict":
        report = current_verdict(target, analysis_id)
        status = str(report.get("verification_status") or "unknown")
        print(report_summary(report))
        outputs["verification-status"] = status
        if args.github_output:
            _write_github_output(outputs)
        _gate(status, args.require_verified)
        return
    if args.github_output:
        _write_github_output(outputs)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _run(args)
    except RadiusCiError as exc:
        _log(str(exc))
        return exc.exit_code
    except _TransientError as exc:  # pragma: no cover - defensive
        _log(str(exc.error))
        return EXIT_ERROR
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
