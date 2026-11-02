#!/usr/bin/env python3
"""Upload CI test results (JUnit XML, optional coverage XML) to Radius.

Used by the ``actions/upload-results`` composite GitHub Action, but also runnable
by hand. Standard library only (Python 3.10+). Configuration comes from
environment variables so values are never interpolated into a shell script and
the API key never appears in argv.

Design rules:

* Uploading evidence must never break the user's CI by default. Every outcome
  (forks, missing secret, no files, API errors, unexpected exceptions) exits 0
  with a clear notice unless ``RADIUS_FAIL_ON_UPLOAD_ERROR=true``.
* Only test *result* files leave the runner, and by default they are reduced to
  an allow-list (see ``sanitize_junit``): suite/case names, file names, outcome
  and duration. Failure messages, stack traces, stdout/stderr and properties are
  dropped, because they can contain source lines or environment values.
* The API key is never printed (Actions masks secrets passed via ``secrets.*``) and is scrubbed from all output.
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

USER_AGENT = "radius-upload-results/1"
TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 4
MAX_RETRY_AFTER_SECONDS = 60.0
BACKOFF_BASE_SECONDS = 2.0
DEFAULT_MAX_FILE_MB = 10.0
MAX_FILES = 64
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

_HEX_SHA = re.compile(r"^[0-9a-fA-F]{7,64}$")
_UUID = re.compile(r"^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

# Allow-lists used when reducing JUnit reports before upload.
_KEEP_TAGS = frozenset(
    {"testsuites", "testsuite", "testcase", "failure", "error", "skipped"}
)
_KEEP_ATTRS = {
    "testsuites": {
        "name",
        "tests",
        "failures",
        "errors",
        "skipped",
        "disabled",
        "time",
    },
    "testsuite": {
        "name",
        "tests",
        "failures",
        "errors",
        "skipped",
        "disabled",
        "time",
        "timestamp",
        "file",
    },
    "testcase": {"name", "classname", "file", "time"},
    "failure": {"type"},
    "error": {"type"},
    "skipped": set(),
}
_FORBIDDEN_XML = (b"<!doctype", b"<!entity")


class UploadFailure(Exception):
    """A handled, user-facing failure. Never contains the API key."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise urllib.error.HTTPError(
            req.full_url, code, "redirects are not followed", headers, fp
        )


_OPENER = urllib.request.build_opener(_NoRedirect)


# Indirection so tests can run without real waiting.
def _sleep(seconds: float) -> None:
    time.sleep(seconds)


# --------------------------------------------------------------------------- output


class Reporter:
    """Prints GitHub workflow commands with the API key scrubbed."""

    def __init__(self, secret: str) -> None:
        self.secret = secret
        self.notices: list[str] = []

    def scrub(self, text: str) -> str:
        return text.replace(self.secret, "***") if self.secret else text

    def info(self, message: str) -> None:
        print(self.scrub(message), flush=True)

    def notice(self, message: str) -> None:
        self.notices.append(message)
        print(f"::notice title=Radius::{self.scrub(_escape(message))}", flush=True)

    def warning(self, message: str) -> None:
        self.notices.append(message)
        print(f"::warning title=Radius::{self.scrub(_escape(message))}", flush=True)

    def error(self, message: str) -> None:
        self.notices.append(message)
        print(f"::error title=Radius::{self.scrub(_escape(message))}", flush=True)


def _escape(message: str) -> str:
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _write_kv(path_env: str, key: str, value: str) -> None:
    path = os.environ.get(path_env)
    if not path:
        return
    safe = value.replace("\r", " ").replace("\n", " ")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{key}={safe}\n")


def _write_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")


# --------------------------------------------------------------------------- input


def _flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default
    return value if value >= 0 else default


def _validate_api(url: str) -> str:
    parsed = urllib.parse.urlparse(url.strip())
    loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
        raise UploadFailure(
            "api-url must be an https:// URL (plain http is accepted only for localhost)."
        )
    if not parsed.hostname or parsed.username or parsed.password:
        raise UploadFailure("api-url must be a plain URL without credentials.")
    return url.strip().rstrip("/")


def find_files(
    patterns: str, root: Path, max_bytes: int, report: Reporter
) -> list[Path]:
    """Resolve newline/comma separated globs under ``root``.

    Files outside ``root`` (via ``..`` or symlinks), non-regular files and files
    over ``max_bytes`` are skipped with a warning. Order is deterministic.
    """

    root = root.resolve()
    found: dict[Path, None] = {}
    for raw in re.split(r"[\r\n,]+", patterns):
        pattern = raw.strip()
        if not pattern:
            continue
        if os.path.isabs(pattern):
            pattern = os.path.relpath(pattern, root)
        for match in sorted(glob.glob(pattern, root_dir=str(root), recursive=True)):
            candidate = root / match
            try:
                resolved = candidate.resolve(strict=True)
            except OSError:
                continue
            if root != resolved and root not in resolved.parents:
                report.warning(f"Skipping {match}: resolves outside the workspace.")
                continue
            if not resolved.is_file():
                continue
            if resolved.stat().st_size > max_bytes:
                report.warning(
                    f"Skipping {match}: {resolved.stat().st_size} bytes exceeds the "
                    f"{max_bytes}-byte cap (max-file-size-mb)."
                )
                continue
            found[resolved] = None
    return list(found)[:MAX_FILES]


# --------------------------------------------------------------------------- XML


def _check_xml_bytes(data: bytes) -> None:
    lowered = data[:65536].lower()
    if any(token in lowered for token in _FORBIDDEN_XML):
        raise UploadFailure(
            "contains a DOCTYPE/ENTITY declaration, which Radius rejects"
        )
    if not data.strip():
        raise UploadFailure("is empty")


def sanitize_junit(data: bytes) -> bytes:
    """Reduce a JUnit report to names, files, outcomes and durations.

    Raises ``UploadFailure`` for malformed XML or a report that is not JUnit.
    """

    _check_xml_bytes(data)
    try:
        root = ET.fromstring(data)  # noqa: S314 - DOCTYPE/ENTITY refused above
    except ET.ParseError as exc:
        raise UploadFailure(f"is not well-formed XML ({exc})") from None
    if root.tag not in {"testsuite", "testsuites"}:
        raise UploadFailure(f"is not a JUnit report (root element <{root.tag}>)")

    def clean(node: ET.Element) -> ET.Element:
        keep = _KEEP_ATTRS[node.tag]
        out = ET.Element(node.tag, {k: v for k, v in node.attrib.items() if k in keep})
        for child in node:
            if child.tag in _KEEP_TAGS:
                out.append(clean(child))
        return out

    return ET.tostring(clean(root), encoding="utf-8", xml_declaration=True)


def validate_junit_as_is(data: bytes) -> bytes:
    sanitize_junit(data)  # same validation, bytes unchanged
    return data


def parse_coverage_xml(data: bytes) -> dict:
    """Return ``{"framework", "coverage_percent"}`` from Cobertura/coverage.py XML.

    Only the aggregate percentage is read; file paths and line data stay local.
    """

    _check_xml_bytes(data)
    try:
        root = ET.fromstring(data)  # noqa: S314
    except ET.ParseError as exc:
        raise UploadFailure(f"is not well-formed XML ({exc})") from None
    if root.tag != "coverage":
        raise UploadFailure(
            f"is not a Cobertura coverage report (root element <{root.tag}>)"
        )
    rate = root.attrib.get("line-rate")
    if rate is None:
        raise UploadFailure("has no line-rate attribute")
    try:
        percent = round(float(rate) * 100.0, 2)
    except ValueError:
        raise UploadFailure("has a non-numeric line-rate") from None
    if not 0.0 <= percent <= 100.0:
        raise UploadFailure("has a line-rate outside 0..1")
    return {"framework": "cobertura", "coverage_percent": percent}


# --------------------------------------------------------------------------- HTTP


def _retry_after(headers) -> float | None:  # noqa: ANN001
    value = headers.get("Retry-After") if headers else None
    if not value:
        return None
    try:
        return max(0.0, min(float(value.strip()), MAX_RETRY_AFTER_SECONDS))
    except ValueError:
        return None  # HTTP-date form: fall back to exponential backoff


def _server_message(body: bytes) -> str:
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except ValueError:
        return ""
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"][:300]
        if isinstance(payload.get("detail"), str):
            return payload["detail"][:300]
    return ""


class ApiError(UploadFailure):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


_HINTS = {
    401: "Check the api-key secret (it must be a valid Radius API key).",
    403: "The API key is not allowed to upload results: it needs the `ci-upload` scope and "
    "access to this organization.",
    404: "Radius has no analysis for this PR head commit (is the Radius GitHub App installed on "
    "the repository, and did the analysis finish?).",
    409: "The commit does not match the analysed head, or the analysis is stale/failed.",
    422: "Radius rejected the report as invalid.",
}


def request(method, url, headers, data, report, *, sleep=None, attempts=MAX_ATTEMPTS):  # noqa: ANN001
    """Send one request. Retries network errors, 429 (honoring Retry-After) and 5xx."""

    sleep = sleep or _sleep
    for attempt in range(1, attempts + 1):
        wait = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with _OPENER.open(req, timeout=TIMEOUT_SECONDS) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read()
            if exc.code in RETRY_STATUSES and attempt < attempts:
                hinted = _retry_after(exc.headers) if exc.code == 429 else None
                wait = wait if hinted is None else hinted
                report.info(
                    f"Radius answered HTTP {exc.code}; retrying in {wait:g}s ({attempt}/{attempts - 1})."
                )
                sleep(wait)
                continue
            if 300 <= exc.code < 400:
                raise ApiError(
                    exc.code,
                    "Radius answered with a redirect; redirects are refused so the "
                    "API key is never sent elsewhere. Use the final https:// api-url.",
                ) from None
            detail = _server_message(body)
            hint = _HINTS.get(exc.code, "")
            message = (
                f"HTTP {exc.code}"
                + (f": {detail}" if detail else "")
                + (f" -> {hint}" if hint else "")
            )
            raise ApiError(exc.code, message) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            if attempt < attempts:
                report.info(
                    f"Could not reach Radius ({exc.__class__.__name__}); retrying in {wait:g}s."
                )
                sleep(wait)
                continue
            raise ApiError(
                0,
                f"Could not reach the Radius API after {attempts} attempts "
                f"({exc.__class__.__name__}).",
            ) from None
    raise ApiError(0, "unreachable")  # pragma: no cover


def _headers(org: str, key: str, extra: dict | None = None) -> dict:
    headers = {
        "X-Radius-Organization-Id": org,
        "X-Radius-API-Key": key,
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    headers.update(extra or {})
    return headers


def resolve_analysis(
    api, org, key, repository, pr, sha, wait_seconds, report, *, sleep=None, poll=5.0
) -> str:  # noqa: ANN001
    """Find the analysis for repo + PR + head SHA, polling 404 until ``wait_seconds``."""

    sleep = sleep or _sleep
    query = urllib.parse.urlencode(
        {"repository": repository, "pullRequest": pr, "commitSha": sha}
    )
    url = f"{api}/api/v1/analyses/lookup?{query}"
    waited = 0.0
    while True:
        try:
            _, body = request("GET", url, _headers(org, key), None, report, sleep=sleep)
            data = json.loads(body).get("data") or {}
            analysis_id = str(data.get("id", ""))
            if not _UUID.match(analysis_id):
                raise UploadFailure("Radius returned an analysis without a valid id.")
            return analysis_id
        except ApiError as exc:
            if exc.status == 404 and waited < wait_seconds:
                report.info(f"No analysis for {sha[:12]} yet; waiting {poll:g}s.")
                sleep(poll)
                waited += poll
                continue
            raise
        except ValueError:
            raise UploadFailure(
                "Radius returned an unreadable lookup response."
            ) from None


def upload_junit(api, org, key, analysis_id, sha, body, report, *, sleep=None) -> dict:  # noqa: ANN001
    query = urllib.parse.urlencode({"commit_sha": sha})
    url = f"{api}/api/v1/analyses/{analysis_id}/tests/results?{query}"
    _, raw = request(
        "POST",
        url,
        _headers(org, key, {"Content-Type": "application/xml"}),
        body,
        report,
        sleep=sleep,
    )
    try:
        return json.loads(raw).get("data") or {}
    except ValueError:
        return {}


def upload_coverage(api, org, key, analysis_id, payload, report, *, sleep=None) -> None:  # noqa: ANN001
    headers = _headers(
        org, key, {"Content-Type": "application/json", "X-Analysis-Id": analysis_id}
    )
    request(
        "POST",
        f"{api}/api/v1/coverage",
        headers,
        json.dumps(payload).encode(),
        report,
        sleep=sleep,
    )


# --------------------------------------------------------------------------- main


class Outcome:
    def __init__(self) -> None:
        self.status = "skipped"
        self.analysis_id = ""
        self.uploaded = 0
        self.skipped_files = 0
        self.verification = ""
        self.failed = False


def _finish(out: Outcome, report: Reporter, dashboard: str) -> None:
    _write_kv("GITHUB_OUTPUT", "status", out.status)
    _write_kv("GITHUB_OUTPUT", "analysis-id", out.analysis_id)
    _write_kv("GITHUB_OUTPUT", "uploaded-count", str(out.uploaded))
    _write_kv("GITHUB_OUTPUT", "skipped-count", str(out.skipped_files))
    _write_kv("GITHUB_OUTPUT", "verification-status", out.verification)
    link = (
        f"{dashboard}/analyses/{out.analysis_id}"
        if dashboard and out.analysis_id
        else ""
    )
    _write_kv("GITHUB_OUTPUT", "analysis-url", link)
    lines = [
        "### Radius test results upload",
        "",
        f"- Status: `{out.status}`",
        f"- Files uploaded: {out.uploaded}, skipped: {out.skipped_files}",
    ]
    if out.analysis_id:
        lines.append(
            f"- Analysis: [{out.analysis_id}]({link})"
            if link
            else f"- Analysis: `{out.analysis_id}`"
        )
    if out.verification:
        lines.append(f"- Verdict after upload: `{out.verification}`")
    for note in report.notices:
        lines.append(f"- {report.scrub(note)}")
    _write_summary("\n".join(lines))
    report.info(
        f"Radius upload: {out.status}; {out.uploaded} uploaded, {out.skipped_files} skipped."
        + (f" Analysis: {link or out.analysis_id}" if out.analysis_id else "")
    )


def run(sleep=None) -> int:  # noqa: ANN001
    key = os.environ.get("RADIUS_API_KEY", "")
    report = Reporter(key)
    fail_mode = _flag("RADIUS_FAIL_ON_UPLOAD_ERROR")
    out = Outcome()
    dashboard = os.environ.get("RADIUS_DASHBOARD_URL", "").strip().rstrip("/")
    # No explicit ::add-mask:: here: it would print the key. GitHub Actions already masks values
    # passed from `secrets.*`, and Reporter scrubs the key from everything this script prints.

    def problem(message: str) -> int:
        out.status = "failed"
        (report.error if fail_mode else report.warning)(
            message
            + (
                ""
                if fail_mode
                else " (not failing the job: fail-on-upload-error is false)"
            )
        )
        _finish(out, report, dashboard)
        return 1 if fail_mode else 0

    try:
        if _flag("RADIUS_IS_FORK"):
            out.status = "skipped-fork"
            report.notice(
                "Pull requests from forks have no access to repository secrets, so Radius "
                "results are not uploaded for this run. Evidence stays missing until a "
                "maintainer re-runs from a branch in this repository."
            )
            _finish(out, report, dashboard)
            return 0
        if not key:
            out.status = "skipped-no-secret"
            report.notice(
                "No Radius API key available (the secret is unset or empty, e.g. a "
                "Dependabot or fork run). Skipping upload."
            )
            _finish(out, report, dashboard)
            return 0

        api = _validate_api(os.environ.get("RADIUS_API_URL", ""))
        org = os.environ.get("RADIUS_ORG_ID", "").strip()
        sha = os.environ.get("RADIUS_COMMIT_SHA", "").strip().lower()
        repository = os.environ.get("RADIUS_REPOSITORY", "").strip()
        pr = os.environ.get("RADIUS_PR", "").strip()
        analysis_id = os.environ.get("RADIUS_ANALYSIS_ID", "").strip()
        if not _UUID.match(org):
            raise UploadFailure("organization-id must be a UUID.")
        if not _HEX_SHA.match(sha):
            raise UploadFailure(
                "commit-sha must be a 7-64 character hex SHA (use the PR head SHA, "
                "github.event.pull_request.head.sha)."
            )
        if analysis_id and not _UUID.match(analysis_id):
            raise UploadFailure("analysis-id must be a UUID.")
        if not analysis_id and not (
            _REPOSITORY.match(repository) and pr.isdigit() and int(pr) > 0
        ):
            raise UploadFailure(
                "Cannot resolve the analysis: this is not a pull_request run (no PR "
                "number). Pass analysis-id explicitly, or run on pull_request events."
            )

        max_bytes = int(_float("RADIUS_MAX_FILE_MB", DEFAULT_MAX_FILE_MB) * 1024 * 1024)
        root = Path(os.environ.get("GITHUB_WORKSPACE") or os.getcwd())
        junit_files = find_files(
            os.environ.get("RADIUS_JUNIT_PATH", ""), root, max_bytes, report
        )
        coverage_files = find_files(
            os.environ.get("RADIUS_COVERAGE_PATH", ""), root, max_bytes, report
        )
        if not junit_files:
            out.status = "skipped-no-results"
            report.warning(
                "No JUnit XML files matched junit-path. Did the test step run with a JUnit "
                "reporter (pytest --junitxml, jest-junit, surefire)? Nothing uploaded."
            )
            _finish(out, report, dashboard)
            return 0

        keep_details = _flag("RADIUS_INCLUDE_FAILURE_DETAILS")
        prepared: list[tuple[str, bytes]] = []
        for path in junit_files:
            name = path.relative_to(root.resolve()).as_posix()
            try:
                data = path.read_bytes()
                prepared.append(
                    (
                        name,
                        validate_junit_as_is(data)
                        if keep_details
                        else sanitize_junit(data),
                    )
                )
            except UploadFailure as exc:
                out.skipped_files += 1
                report.warning(
                    f"Skipping {name}: {exc}. Malformed or non-JUnit reports are never uploaded."
                )
        if not prepared:
            out.status = "skipped-no-results"
            _finish(out, report, dashboard)
            return 0

        analysis_id = analysis_id or resolve_analysis(
            api,
            org,
            key,
            repository,
            pr,
            sha,
            _float("RADIUS_WAIT_SECONDS", 120.0),
            report,
            sleep=sleep,
        )
        out.analysis_id = analysis_id

        errors = 0
        for name, body in prepared:
            try:
                data = upload_junit(
                    api, org, key, analysis_id, sha, body, report, sleep=sleep
                )
                out.uploaded += 1
                for field in ("verification_status", "verification", "status"):
                    value = data.get(field) if isinstance(data, dict) else None
                    if isinstance(value, str) and value:
                        out.verification = value
                        break
                report.info(f"Uploaded {name} ({len(body)} bytes).")
            except UploadFailure as exc:
                errors += 1
                report.warning(f"Upload of {name} failed: {exc}")
        for path in coverage_files:
            name = path.relative_to(root.resolve()).as_posix()
            try:
                payload = parse_coverage_xml(path.read_bytes())
                upload_coverage(
                    api, org, key, analysis_id, payload, report, sleep=sleep
                )
                report.info(
                    f"Uploaded coverage percentage from {name} ({payload['coverage_percent']}%)."
                )
            except UploadFailure as exc:
                errors += 1
                report.warning(f"Coverage {name} not uploaded: {exc}")
        if errors:
            out.status = "partial" if out.uploaded else "failed"
            if fail_mode:
                report.error(f"{errors} upload(s) failed.")
            _finish(out, report, dashboard)
            return 1 if fail_mode else 0
        out.status = "uploaded"
        _finish(out, report, dashboard)
        return 0
    except UploadFailure as exc:
        return problem(str(exc))
    except Exception as exc:  # noqa: BLE001 - uploading must never crash the user's CI
        return problem(f"Unexpected error ({exc.__class__.__name__}).")


if __name__ == "__main__":
    sys.exit(run())
