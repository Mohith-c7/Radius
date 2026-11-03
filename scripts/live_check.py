#!/usr/bin/env python
"""Read-only preflight of a real GitHub App installation (no webhook needed).

    GITHUB_APP_ID=123456 \
    GITHUB_APP_PRIVATE_KEY_PATH=~/radius-demo/app.private-key.pem \
    RADIUS_LIVE_REPO=owner/test-repo \
        python scripts/live_check.py

Run it before the live demo (docs/operations/LIVE_GITHUB_DEMO.md). It prints one
PASS / WARN / FAIL line per check and exits 0 only when nothing FAILed.

What it does against GitHub (api.github.com, or ``GITHUB_API_BASE_URL``):

* ``GET /app`` with an App JWT: credentials, key format and clock;
* ``GET /repos/{owner}/{repo}/installation``: the App is installed on the repo;
* ``POST /app/installations/{id}/access_tokens``: mints a short-lived installation
  token (this changes nothing in your repository; the token expires in an hour);
* ``GET /repos/{owner}/{repo}`` and ``GET .../pulls?state=open``: read access.

It never creates a check run, comment, branch or file. "Check-run write" is judged
from the permissions GitHub grants the installation token, which is what GitHub
itself checks. Nothing secret is printed: not the key, the JWT or the token.

Inputs (environment):
    GITHUB_APP_ID                  numeric App id (or client id)
    GITHUB_APP_PRIVATE_KEY         PEM text (newlines may be written as \\n), or
    GITHUB_APP_PRIVATE_KEY_PATH    path to the downloaded .pem file
    RADIUS_LIVE_REPO               owner/name (an optional positional argument wins)
    GITHUB_API_BASE_URL            optional (GitHub Enterprise)
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def _bootstrap_path() -> None:
    import tomllib

    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    for entry in reversed(config["tool"]["pytest"]["ini_options"]["pythonpath"]):
        path = str(ROOT / entry)
        if path not in sys.path:
            sys.path.insert(0, path)


_bootstrap_path()

from radius_github import (  # noqa: E402
    GitHubAppClient,
    GitHubAppSettings,
    GitHubHTTPError,
    GitHubRateLimitError,
)
from radius_github.client import normalize_private_key  # noqa: E402

PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"
LEVELS = {"none": 0, "read": 1, "write": 2, "admin": 3}
#: What Radius needs from the installation (PRD / docs/operations/LIVE_GITHUB_DEMO.md).
REQUIRED_PERMISSIONS = {
    "metadata": "read",
    "contents": "read",
    "pull_requests": "write",
    "checks": "write",
}
CLOCK_WARN_SECONDS = 30
CLOCK_FAIL_SECONDS = 300
_SECRET_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{6,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|$)", re.S),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]*"),
)


def redact(text: str) -> str:
    """Remove anything that looks like a token, JWT or key from ``text``."""

    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    return text


@dataclass(frozen=True)
class Result:
    status: str
    name: str
    detail: str
    hint: str = ""


class Report:
    def __init__(self, out: Callable[[str], None]) -> None:
        self.results: list[Result] = []
        self._out = out

    def add(self, status: str, name: str, detail: str, hint: str = "") -> None:
        result = Result(status, name, redact(detail), redact(hint))
        self.results.append(result)
        self._out(f"[{status:<4}] {name}: {result.detail}")
        if result.hint:
            self._out(f"       -> {result.hint}")

    @property
    def failed(self) -> bool:
        return any(r.status == FAIL for r in self.results)

    def count(self, status: str) -> int:
        return sum(r.status == status for r in self.results)


def _missing(have: Mapping[str, str] | None, need: Mapping[str, str]) -> list[str]:
    """Permissions in ``need`` that ``have`` grants at a lower level (or not at all)."""

    have = have or {}
    return [
        f"{name}:{level}"
        for name, level in need.items()
        if LEVELS.get(have.get(name, "none"), 0) < LEVELS[level]
    ]


def _describe_http(exc: Exception) -> str:
    return redact(str(exc))


def _load_key(env: Mapping[str, str], report: Report) -> str | None:
    inline = env.get("GITHUB_APP_PRIVATE_KEY", "")
    path = env.get("GITHUB_APP_PRIVATE_KEY_PATH", "")
    if inline.strip():
        pem, source = inline, "GITHUB_APP_PRIVATE_KEY"
    elif path.strip():
        try:
            pem = Path(path).expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            report.add(
                FAIL,
                "private key",
                f"GITHUB_APP_PRIVATE_KEY_PATH cannot be read ({type(exc).__name__}).",
                "Check the path; on Windows use forward slashes or a quoted path.",
            )
            return None
        source = "GITHUB_APP_PRIVATE_KEY_PATH"
    else:
        report.add(
            FAIL,
            "private key",
            "neither GITHUB_APP_PRIVATE_KEY nor GITHUB_APP_PRIVATE_KEY_PATH is set.",
            "Generate a private key on the App's settings page and point "
            "GITHUB_APP_PRIVATE_KEY_PATH at the downloaded .pem file.",
        )
        return None
    pem = normalize_private_key(pem)
    if "PRIVATE KEY" not in pem:
        report.add(
            FAIL,
            "private key",
            f"{source} does not look like a PEM private key.",
            "It must start with -----BEGIN RSA PRIVATE KEY----- (or BEGIN PRIVATE KEY). "
            "Do not use the App's client secret or webhook secret.",
        )
        return None
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = serialization.load_pem_private_key(pem.encode(), password=None)
    except Exception as exc:  # noqa: BLE001 - never echo key material
        report.add(
            FAIL,
            "private key",
            f"{source} could not be parsed as an unencrypted PEM ({type(exc).__name__}).",
            "Newlines were probably lost. Use GITHUB_APP_PRIVATE_KEY_PATH, or a single "
            "line with literal \\n between the PEM lines.",
        )
        return None
    if not isinstance(key, rsa.RSAPrivateKey):
        report.add(FAIL, "private key", "the key is not an RSA key.", "GitHub Apps sign with RS256.")
        return None
    report.add(PASS, "private key", f"RSA {key.key_size}-bit key loaded from {source}.")
    return pem


def _check_clock(client: GitHubAppClient, report: Report, local_now: float) -> None:
    header = client.last_server_date
    if not header:
        report.add(INFO, "clock", "GitHub sent no Date header; skew not measured.")
        return
    try:
        skew = abs(parsedate_to_datetime(header).timestamp() - local_now)
    except (TypeError, ValueError):
        report.add(INFO, "clock", "could not parse GitHub's Date header; skew not measured.")
        return
    hint = "Sync the system clock (JWTs are rejected when it is off by more than a minute or so)."
    if skew > CLOCK_FAIL_SECONDS:
        report.add(FAIL, "clock", f"local clock differs from GitHub by {skew:.0f}s.", hint)
    elif skew > CLOCK_WARN_SECONDS:
        report.add(WARN, "clock", f"local clock differs from GitHub by {skew:.0f}s.", hint)
    else:
        report.add(PASS, "clock", f"local clock within {skew:.0f}s of GitHub.")


def _permission_check(
    report: Report, name: str, have: Mapping[str, str] | None, *, source: str
) -> None:
    missing = _missing(have, REQUIRED_PERMISSIONS)
    if not missing:
        report.add(PASS, name, f"{source} grants " + ", ".join(
            f"{k}:{v}" for k, v in REQUIRED_PERMISSIONS.items()) + " (or higher).")
        return
    report.add(
        FAIL,
        name,
        f"{source} lacks: " + ", ".join(missing) + ".",
        "App settings > Permissions & events: set Pull requests = Read & write, "
        "Checks = Read & write, Contents = Read-only, Metadata = Read-only. Then accept "
        "the new permissions on the installation (Settings > Applications > Configure; "
        "GitHub emails the owner and shows a banner).",
    )


def _classify_failure(exc: Exception) -> tuple[str, str]:
    """(detail, hint) for a GitHub failure."""

    if isinstance(exc, GitHubRateLimitError):
        return (
            _describe_http(exc),
            "GitHub rate limit hit. Wait for the reset time in the message and re-run.",
        )
    if isinstance(exc, GitHubHTTPError):
        if exc.status == 401:
            return (
                _describe_http(exc),
                "GitHub rejected the App JWT. Check GITHUB_APP_ID, that the key belongs to "
                "this App (not a revoked key), and that the clock is correct.",
            )
        if exc.status == 403:
            return (_describe_http(exc), "The App is not allowed to do this. Check permissions.")
        if exc.status == 404:
            return (
                _describe_http(exc),
                "Not found. Check the owner/repo spelling and that the App is installed on "
                "exactly this repository (Install App > select repositories).",
            )
    return (_describe_http(exc) or type(exc).__name__, "")


def run_checks(
    env: Mapping[str, str],
    report: Report,
    *,
    repo: str,
    opener: Any = None,
    clock: Callable[[], float] = time.time,
) -> None:
    """Run every preflight check, appending to ``report``. Never raises for GitHub errors."""

    app_id = env.get("GITHUB_APP_ID", "").strip()
    if not app_id:
        report.add(FAIL, "app id", "GITHUB_APP_ID is not set.", "It is shown at the top of the App's settings page.")
    elif not re.fullmatch(r"[A-Za-z0-9_.-]+", app_id):
        report.add(FAIL, "app id", "GITHUB_APP_ID contains unexpected characters.")
    else:
        report.add(PASS, "app id", f"GITHUB_APP_ID={app_id}")
    pem = _load_key(env, report)

    parts = repo.strip().strip("/").split("/")
    if len(parts) != 2 or not all(parts):
        report.add(FAIL, "repository", "set RADIUS_LIVE_REPO (or pass it as an argument) as owner/name.")
        return
    owner, name = parts
    if not app_id or pem is None or report.failed:
        report.add(INFO, "github", "skipped: fix the configuration above first.")
        return

    settings = GitHubAppSettings(
        GITHUB_APP_ID=app_id,
        GITHUB_APP_PRIVATE_KEY=pem,
        GITHUB_API_BASE_URL=env.get("GITHUB_API_BASE_URL") or "https://api.github.com",
        GITHUB_TIMEOUT_SECONDS=15,
    )
    client = GitHubAppClient(settings, opener=opener, clock=clock)

    # 1. App JWT
    try:
        app = client.get_app()
    except Exception as exc:  # noqa: BLE001
        detail, hint = _classify_failure(exc)
        report.add(FAIL, "app jwt", detail, hint)
        _check_clock(client, report, clock())
        return
    slug = app.get("slug") or app.get("name") or "?"
    report.add(PASS, "app jwt", f"GitHub accepted the App JWT (app: {slug}).")
    _check_clock(client, report, clock())
    _permission_check(report, "app permissions", app.get("permissions"), source="the App")

    # 2. installation
    try:
        installation = client.get_repository_installation(owner, name)
    except Exception as exc:  # noqa: BLE001
        detail, hint = _classify_failure(exc)
        report.add(FAIL, "installation", f"{owner}/{name}: {detail}", hint)
        return
    installation_id = installation.get("id")
    if not installation_id:
        report.add(FAIL, "installation", f"no installation covers {owner}/{name}.")
        return
    if installation.get("suspended_at"):
        report.add(
            FAIL,
            "installation",
            f"installation {installation_id} is suspended.",
            "Unsuspend it in the account's installed GitHub Apps settings.",
        )
        return
    report.add(
        PASS,
        "installation",
        f"installation {installation_id} covers {owner}/{name} "
        f"(repository_selection={installation.get('repository_selection', '?')}).",
    )
    if isinstance(installation.get("permissions"), dict):
        _permission_check(
            report, "installation permissions", installation["permissions"], source="the installation"
        )

    # 3. installation token
    try:
        token = client.create_installation_token(int(installation_id))
    except Exception as exc:  # noqa: BLE001
        detail, hint = _classify_failure(exc)
        report.add(FAIL, "installation token", detail, hint)
        return
    report.add(PASS, "installation token", "minted a short-lived installation token (not printed).")
    if token.permissions is not None:
        _permission_check(report, "token permissions", token.permissions, source="the token")
        checks_level = token.permissions.get("checks", "none")
        if checks_level == "write":
            report.add(PASS, "check-run write", "checks:write is present, so Radius can publish its Check Run.")
        else:
            report.add(
                FAIL,
                "check-run write",
                f"checks permission is '{checks_level}', Radius cannot publish a Check Run.",
                "Grant Checks = Read & write and accept it on the installation.",
            )
    else:
        report.add(WARN, "token permissions", "GitHub did not report token permissions; not verified.")

    # 4. repository + pull requests
    try:
        repository = client.get_repository(token=token.token, owner=owner, repo=name)
    except Exception as exc:  # noqa: BLE001
        detail, hint = _classify_failure(exc)
        report.add(FAIL, "repository", f"{owner}/{name}: {detail}", hint)
        return
    flags = []
    if repository.get("archived"):
        flags.append("ARCHIVED (read-only on GitHub: publishing will fail)")
    if repository.get("disabled"):
        flags.append("disabled")
    visibility = "private" if repository.get("private", True) else "public"
    report.add(
        FAIL if repository.get("archived") else PASS,
        "repository",
        f"{owner}/{name} readable ({visibility}, default branch "
        f"{repository.get('default_branch', '?')}, id {repository.get('id', '?')})"
        + (f"; {'; '.join(flags)}" if flags else "."),
        "Unarchive the repository or use another one." if repository.get("archived") else "",
    )
    try:
        pulls = client.list_pull_requests(token=token.token, owner=owner, repo=name, state="open")
    except Exception as exc:  # noqa: BLE001
        detail, hint = _classify_failure(exc)
        report.add(FAIL, "pull requests", detail, hint)
        return
    if pulls:
        numbers = ", ".join(f"#{p.get('number')}" for p in pulls[:10])
        report.add(PASS, "pull requests", f"{len(pulls)} open (e.g. {numbers}); readable.")
    else:
        report.add(
            WARN,
            "pull requests",
            "readable, but there are no open pull requests.",
            "Open a PR on a branch of the test repo so there is something to analyze.",
        )

    limit = client.last_rate_limit
    if limit is not None and limit.remaining is not None:
        report.add(INFO, "rate limit", f"{limit.remaining} requests remaining in the current window.")
    report.add(INFO, "webhook", "not used: Radius pulls from GitHub (connect-github / sync / analyze).")


def main(
    argv: list[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    opener: Any = None,
    clock: Callable[[], float] = time.time,
    out: Callable[[str], None] = print,
) -> int:
    parser = argparse.ArgumentParser(description="Read-only preflight of a GitHub App installation.")
    parser.add_argument("repo", nargs="?", help="owner/name (default: $RADIUS_LIVE_REPO)")
    args = parser.parse_args(argv)
    environ = dict(os.environ if env is None else env)
    repo = args.repo or environ.get("RADIUS_LIVE_REPO", "")
    out(f"Radius live GitHub preflight for {repo or '(no repository given)'}")
    report = Report(out)
    try:
        run_checks(environ, report, repo=repo, opener=opener, clock=clock)
    except Exception as exc:  # noqa: BLE001 - last resort; never print a traceback with secrets
        report.add(FAIL, "unexpected", f"{type(exc).__name__}: {redact(str(exc))[:200]}")
    out(
        f"\n{'PREFLIGHT FAILED' if report.failed else 'PREFLIGHT PASSED'}: "
        f"{report.count(PASS)} pass, {report.count(WARN)} warn, {report.count(FAIL)} fail"
    )
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
