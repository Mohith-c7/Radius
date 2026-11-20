"""Contract tests for the pinned reusable workflow helper."""

import base64
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "radius_trusted_evidence",
    ROOT / "scripts" / "radius_trusted_evidence.py",
)
assert SPEC and SPEC.loader
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


def _token(claims: dict) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


def test_run_slot_executes_only_server_manifest_paths_and_keeps_failed_report(
    tmp_path, monkeypatch
):
    manifest = {
        "manifest": {
            "slots": [{"slot_id": "a" * 24, "test_paths": ["tests/test_one.py"]}]
        }
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report = tmp_path / "report.xml"
    exit_code = tmp_path / "exit.txt"
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        report.write_text('<testsuite tests="1"><testcase name="x"/></testsuite>')
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(helper.subprocess, "run", fake_run)
    result = helper.run_slot_command(
        SimpleNamespace(
            manifest=str(manifest_path),
            slot_id="a" * 24,
            report=str(report),
            exit_code=str(exit_code),
        )
    )

    assert result == 0
    assert calls[0][-1] == "tests/test_one.py"
    assert calls[0][0:3] == [helper.sys.executable, "-m", "pytest"]
    assert exit_code.read_text(encoding="ascii") == "1"
    assert report.exists()


def test_run_slot_rejects_paths_outside_the_server_manifest_boundary(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"manifest": {"slots": [{"slot_id": "b" * 24, "test_paths": ["../evil.py"]}]}}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="unsafe test path"):
        helper.run_slot_command(
            SimpleNamespace(
                manifest=str(manifest_path),
                slot_id="b" * 24,
                report=str(tmp_path / "report.xml"),
                exit_code=str(tmp_path / "exit.txt"),
            )
        )


def test_predicate_binds_report_digest_to_manifest_and_workflow_claims(tmp_path, monkeypatch):
    report = tmp_path / "report.xml"
    report.write_bytes(b"<testsuite/>")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "manifest": {"head_sha": "a" * 40},
                "digest_sha256": "b" * 64,
            }
        ),
        encoding="utf-8",
    )
    claims = {
        "repository_id": "123",
        "repository_owner_id": "321",
        "run_id": "987",
        "run_attempt": "2",
        "event_name": "pull_request",
        "workflow_ref": "acme/repo/.github/workflows/radius.yml@refs/heads/main",
        "workflow_sha": "c" * 40,
        "job_workflow_sha": "d" * 40,
    }
    monkeypatch.setattr(helper, "_oidc_token", lambda: _token(claims))
    output = tmp_path / "predicate.json"
    helper.predicate_command(
        SimpleNamespace(
            manifest=str(manifest),
            analysis_id="analysis-id",
            slot_id="e" * 24,
            report=str(report),
            output=str(output),
        )
    )
    predicate = json.loads(output.read_text(encoding="utf-8"))
    assert predicate["head_sha"] == "a" * 40
    assert predicate["manifest_digest"] == "b" * 64
    assert predicate["caller_workflow_path"] == ".github/workflows/radius.yml"
    assert predicate["run_attempt"] == 2
    assert predicate["artifact_digest"].startswith("sha256:")



def test_workflow_signs_with_the_predicate_type_the_verifier_requires() -> None:
    from radius_testing.provenance import PREDICATE_TYPE

    workflow = (ROOT / ".github" / "workflows" / "radius-trusted-evidence.yml").read_text(
        encoding="utf-8"
    )
    declared = [
        line.split(":", 1)[1].strip()
        for line in workflow.splitlines()
        if line.strip().startswith("predicate-type:")
    ]
    assert declared == [PREDICATE_TYPE]
    assert PREDICATE_TYPE.startswith("https://github.com/Mohith-c7/Radius/")
    assert "example" not in PREDICATE_TYPE
