#!/usr/bin/env python3
"""Client for the Radius trusted-evidence reusable workflow.

The script is checked out from the immutable Radius workflow revision. Test
execution and JUnit production are separate from OIDC/attestation permissions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

AUDIENCE = "api://radius/evidence-upload"
SAFE_SLOT = re.compile(r"^[a-f0-9]{24}$")
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_REPORT_BYTES = 20 * 1024 * 1024
MAX_REPORT_SLOTS = 200


def _oidc_token() -> str:
    request_url = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL", "")
    request_token = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "")
    if not request_url or not request_token:
        raise RuntimeError("GitHub Actions OIDC is unavailable")
    parts = urllib.parse.urlsplit(request_url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    query.append(("audience", AUDIENCE))
    url = urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), parts.fragment)
    )
    request = urllib.request.Request(
        url, headers={"Authorization": f"bearer {request_token}"}
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        data = json.loads(response.read(64 * 1024))
    token = data.get("value") if isinstance(data, dict) else None
    if not isinstance(token, str) or not token:
        raise RuntimeError("GitHub Actions returned no OIDC token")
    return token


def _request_json(url: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read(MAX_MANIFEST_BYTES + 1)
    if len(body) > MAX_MANIFEST_BYTES:
        raise RuntimeError("Radius manifest exceeds 2 MiB")
    result = json.loads(body)
    if not isinstance(result, dict) or result.get("success") is not True:
        raise RuntimeError("Radius did not return a successful manifest response")
    data = result.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("Radius returned an invalid manifest")
    return data


def manifest_command(args: argparse.Namespace) -> int:
    url = (
        f"{args.api_url.rstrip('/')}/api/v1/analyses/"
        f"{args.analysis_id}/tests/manifest"
    )
    data = _request_json(url, _oidc_token())
    manifest = data.get("manifest")
    slots = manifest.get("slots") if isinstance(manifest, dict) else None
    digest = data.get("digest_sha256")
    if not isinstance(slots, list) or not isinstance(digest, str):
        raise RuntimeError("Radius returned an invalid manifest or digest")
    safe_slots = []
    for slot in slots:
        if not isinstance(slot, dict) or not SAFE_SLOT.fullmatch(str(slot.get("slot_id", ""))):
            raise RuntimeError("Radius returned an invalid report slot")
        paths = slot.get("test_paths")
        if not isinstance(paths, list) or not paths:
            raise RuntimeError("Radius returned an empty report slot")
        for path in paths:
            if not isinstance(path, str) or Path(path).is_absolute() or ".." in Path(path).parts:
                raise RuntimeError("Radius returned an unsafe test path")
        safe_slots.append({"slot_id": slot["slot_id"], "test_paths": paths})
    if len(safe_slots) > MAX_REPORT_SLOTS:
        raise RuntimeError(f"Manifest exceeds the {MAX_REPORT_SLOTS}-slot workflow limit")
    Path(args.output).write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    if os.environ.get("GITHUB_OUTPUT"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
            output.write(f"digest={digest}\n")
            output.write(f"slots={json.dumps(safe_slots, separators=(',', ':'))}\n")
    return 0


def run_slot_command(args: argparse.Namespace) -> int:
    data = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    manifest = data.get("manifest", {})
    slot = next(
        (item for item in manifest.get("slots", []) if item.get("slot_id") == args.slot_id),
        None,
    )
    if not SAFE_SLOT.fullmatch(args.slot_id) or slot is None:
        raise RuntimeError("Report slot is not in the server manifest")
    paths = slot.get("test_paths", [])
    for path in paths:
        if not isinstance(path, str) or Path(path).is_absolute() or ".." in Path(path).parts:
            raise RuntimeError("Server manifest contains an unsafe test path")
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", f"--junitxml={report}", *paths],
        check=False,
        shell=False,
    )
    Path(args.exit_code).write_text(str(completed.returncode), encoding="ascii")
    if report.exists() and report.stat().st_size <= MAX_REPORT_BYTES:
        return 0  # Keep failed test reports eligible for a signed diagnostic result.
    raise RuntimeError("pytest did not produce a bounded JUnit report")


def _unverified_claims(token: str) -> dict[str, Any]:
    """Read claims only to populate the predicate; the backend verifies the JWT."""

    try:
        import base64

        payload = token.split(".")[1]
        decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        claims = json.loads(decoded)
    except Exception as exc:
        raise RuntimeError("Cannot decode workflow identity claims") from exc
    if not isinstance(claims, dict):
        raise RuntimeError("Invalid workflow identity claims")
    return claims


def predicate_command(args: argparse.Namespace) -> int:
    data = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    token = _oidc_token()
    claims = _unverified_claims(token)
    artifact = Path(args.report).read_bytes()
    if not artifact or len(artifact) > MAX_REPORT_BYTES:
        raise RuntimeError("JUnit report is empty or exceeds 20 MiB")
    workflow_ref = str(claims.get("workflow_ref", ""))
    caller_path = workflow_ref.split("@", 1)[0]
    parts = caller_path.split("/")
    if len(parts) < 3:
        raise RuntimeError("Caller workflow identity is missing")
    predicate = {
        "schema_version": 1,
        "analysis_id": args.analysis_id,
        "repository_id": str(claims.get("repository_id", "")),
        "owner_id": str(claims.get("repository_owner_id", "")),
        "head_sha": str(data["manifest"]["head_sha"]).lower(),
        "manifest_digest": str(data["digest_sha256"]),
        "report_slot_id": args.slot_id,
        "run_id": str(claims.get("run_id", "")),
        "run_attempt": int(claims.get("run_attempt", 0)),
        "event_name": str(claims.get("event_name", "")),
        "caller_workflow_path": "/".join(parts[2:]),
        "caller_workflow_sha": str(claims.get("workflow_sha", "")).lower(),
        "reusable_workflow_sha": str(claims.get("job_workflow_sha", "")).lower(),
        "artifact_digest": "sha256:" + hashlib.sha256(artifact).hexdigest(),
    }
    if any(not predicate[key] for key in ("repository_id", "owner_id", "run_id", "caller_workflow_sha", "reusable_workflow_sha")):
        raise RuntimeError("Required workflow identity claim is missing")
    Path(args.output).write_text(json.dumps(predicate, sort_keys=True), encoding="utf-8")
    return 0


def upload_command(args: argparse.Namespace) -> int:
    token = _oidc_token()
    report = Path(args.report).read_bytes()
    if not report or len(report) > MAX_REPORT_BYTES:
        raise RuntimeError("JUnit report is empty or exceeds 20 MiB")
    boundary = "radius-" + hashlib.sha256(os.urandom(32)).hexdigest()
    fields = {
        "report_slot_id": args.slot_id,
        "pull_request_number": str(args.pr_number),
    }
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [f"--{boundary}\r\n".encode(),
             f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
             value.encode(), b"\r\n"]
        )
    chunks.extend(
        [f"--{boundary}\r\n".encode(),
         b'Content-Disposition: form-data; name="artifact"; filename="report.xml"\r\n',
         b"Content-Type: application/xml\r\n\r\n", report, b"\r\n",
         f"--{boundary}--\r\n".encode()]
    )
    request = urllib.request.Request(
        f"{args.api_url.rstrip('/')}/api/v1/analyses/{args.analysis_id}/tests/verified-results",
        data=b"".join(chunks),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            response.read(64 * 1024)
    except urllib.error.HTTPError as exc:
        detail = exc.read(4096).decode("utf-8", errors="replace")
        raise RuntimeError(f"Radius upload failed with HTTP {exc.code}: {detail}") from exc
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    manifest = commands.add_parser("manifest")
    manifest.add_argument("--api-url", required=True)
    manifest.add_argument("--analysis-id", required=True)
    manifest.add_argument("--output", required=True)
    manifest.set_defaults(handler=manifest_command)
    run_slot = commands.add_parser("run-slot")
    run_slot.add_argument("--manifest", required=True)
    run_slot.add_argument("--slot-id", required=True)
    run_slot.add_argument("--report", required=True)
    run_slot.add_argument("--exit-code", required=True)
    run_slot.set_defaults(handler=run_slot_command)
    predicate = commands.add_parser("predicate")
    predicate.add_argument("--manifest", required=True)
    predicate.add_argument("--analysis-id", required=True)
    predicate.add_argument("--slot-id", required=True)
    predicate.add_argument("--report", required=True)
    predicate.add_argument("--output", required=True)
    predicate.set_defaults(handler=predicate_command)
    upload = commands.add_parser("upload")
    upload.add_argument("--api-url", required=True)
    upload.add_argument("--analysis-id", required=True)
    upload.add_argument("--pr-number", required=True)
    upload.add_argument("--slot-id", required=True)
    upload.add_argument("--report", required=True)
    upload.set_defaults(handler=upload_command)
    args = parser.parse_args()
    try:
        return args.handler(args)
    except (OSError, ValueError, KeyError, RuntimeError, urllib.error.URLError) as exc:
        print(f"radius trusted evidence: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
