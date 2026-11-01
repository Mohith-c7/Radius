#!/usr/bin/env python3
"""Radius CI helper: fetch the test plan and upload JUnit results.

Flow inside a CI job:

1. ``radius_ci.py plan``   -> print the test files Radius selected (one per line).
2. Run those tests in CI with JUnit output (e.g. ``pytest --junitxml=junit.xml``).
3. ``radius_ci.py upload`` -> send the JUnit report, bound to the head commit.

The API key is read from the ``RADIUS_API_KEY`` environment variable only and
is never printed. Standard library only, so it runs on any CI image with
Python 3.12+.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from uuid import UUID

TIMEOUT_SECONDS = 30
API_KEY_ENV = "RADIUS_API_KEY"
_HEX_SHA = re.compile(r"^[0-9a-fA-F]{7,64}$")


class RadiusCiError(Exception):
    """A user-facing failure; the message never contains the API key."""


def _validate_uuid(value: str, name: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError) as exc:
        raise RadiusCiError(f"{name} must be a UUID.") from exc


def _validate_sha(value: str) -> str:
    if not _HEX_SHA.match(value or ""):
        raise RadiusCiError("commit SHA must be 7-64 hexadecimal characters.")
    return value.lower()


def _validate_api(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RadiusCiError("--api must be an http(s) URL.")
    return url.rstrip("/")


def _headers(organization_id: str) -> dict[str, str]:
    headers = {"X-Radius-Organization-Id": organization_id}
    api_key = os.environ.get(API_KEY_ENV, "")
    if api_key:
        headers["X-Radius-API-Key"] = api_key
    return headers


def _error_message(body: bytes, status: int) -> str:
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except ValueError:
        payload = None
    message = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
        message = message or payload.get("detail")
    if not isinstance(message, str) or not message:
        message = body.decode("utf-8", errors="replace").strip()[:300] or "no response body"
    return f"Radius API returned HTTP {status}: {message}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so the API key header is never forwarded to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise urllib.error.HTTPError(req.full_url, code, "redirects are not followed", headers, fp)


_OPENER = urllib.request.build_opener(_NoRedirect)


def _request(
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
        raise RadiusCiError(_error_message(exc.read(), exc.code)) from None
    except urllib.error.URLError as exc:
        raise RadiusCiError(f"Could not reach Radius API: {exc.reason}") from None
    except TimeoutError:
        raise RadiusCiError(f"Radius API timed out after {TIMEOUT_SECONDS}s.") from None


def plan(api: str, organization_id: str, analysis_id: str) -> list[str]:
    """Return the selected test file paths for an analysis."""

    url = (
        f"{_validate_api(api)}/api/v1/analyses/"
        f"{_validate_uuid(analysis_id, 'analysis id')}/tests?format=cli"
    )
    body = _request("GET", url, _headers(_validate_uuid(organization_id, "organization id")))
    return [item for item in body.decode("utf-8", errors="replace").split() if item]


def upload(
    api: str,
    organization_id: str,
    analysis_id: str,
    junit_path: str,
    commit_sha: str,
) -> str:
    """Upload a JUnit report bound to ``commit_sha``; return a short summary."""

    path = Path(junit_path)
    if not path.is_file():
        raise RadiusCiError(f"JUnit report not found: {junit_path}")
    query = urllib.parse.urlencode({"commit_sha": _validate_sha(commit_sha)})
    url = (
        f"{_validate_api(api)}/api/v1/analyses/"
        f"{_validate_uuid(analysis_id, 'analysis id')}/tests/results?{query}"
    )
    headers = _headers(_validate_uuid(organization_id, "organization id"))
    headers["Content-Type"] = "application/xml"
    body = _request("POST", url, headers, data=path.read_bytes())
    try:
        data = json.loads(body).get("data") or {}
    except (ValueError, AttributeError):
        data = {}
    return (
        f"Uploaded results: {data.get('total_tests', '?')} tests, "
        f"{data.get('passed', '?')} passed, {data.get('failed', '?')} failed."
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "upload"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--api", required=True, help="Radius API base URL")
        cmd.add_argument("--org", required=True, help="Radius organization id")
        cmd.add_argument("--analysis", required=True, help="Radius analysis id")
    upload_cmd = sub.choices["upload"]
    upload_cmd.add_argument("--junit", required=True, help="JUnit XML report path")
    upload_cmd.add_argument("--commit", required=True, help="Head commit SHA tested")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "plan":
            for path in plan(args.api, args.org, args.analysis):
                print(path)
        else:
            print(upload(args.api, args.org, args.analysis, args.junit, args.commit))
    except RadiusCiError as exc:
        print(f"radius_ci: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
