"""Tests for scripts/radius_ci.py against a local HTTP stub (no external network)."""

from __future__ import annotations

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "radius_ci.py"
_spec = importlib.util.spec_from_file_location("radius_ci", _SCRIPT)
radius_ci = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(radius_ci)

ORG = "11111111-1111-1111-1111-111111111111"
ANALYSIS = "22222222-2222-2222-2222-222222222222"
SHA = "a" * 40
SECRET = "super-secret-key-value"


class _Stub(BaseHTTPRequestHandler):
    requests: list[dict] = []
    plan_body = b"tests/test_a.py tests/test_b.py"
    upload_status = 200

    def log_message(self, *args):  # silence server logs
        pass

    def _record(self, body: bytes = b"") -> None:
        _Stub.requests.append(
            {"method": self.command, "path": self.path, "headers": dict(self.headers), "body": body}
        )

    def do_GET(self):  # noqa: N802
        self._record()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(_Stub.plan_body)

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self._record(body)
        if _Stub.upload_status != 200:
            payload = {"success": False, "error": {"code": "CONFLICT", "message": "commit mismatch"}}
        else:
            payload = {"success": True, "data": {"total_tests": 2, "passed": 2, "failed": 0}}
        self.send_response(_Stub.upload_status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())


@pytest.fixture()
def api(monkeypatch):
    _Stub.requests = []
    _Stub.plan_body = b"tests/test_a.py tests/test_b.py"
    _Stub.upload_status = 200
    server = HTTPServer(("127.0.0.1", 0), _Stub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("RADIUS_API_KEY", SECRET)
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_plan_prints_one_path_per_line(api, capsys) -> None:
    assert radius_ci.main(["plan", "--api", api, "--org", ORG, "--analysis", ANALYSIS]) == 0

    assert capsys.readouterr().out.splitlines() == ["tests/test_a.py", "tests/test_b.py"]
    request = _Stub.requests[0]
    assert request["path"] == f"/api/v1/analyses/{ANALYSIS}/tests?format=cli"
    assert request["headers"]["X-Radius-Organization-Id"] == ORG
    assert request["headers"]["X-Radius-Api-Key"] == SECRET


def test_empty_plan_prints_nothing(api, capsys) -> None:
    _Stub.plan_body = b""

    assert radius_ci.main(["plan", "--api", api, "--org", ORG, "--analysis", ANALYSIS]) == 0
    assert capsys.readouterr().out == ""


def test_upload_sends_junit_bound_to_commit(api, tmp_path, capsys) -> None:
    junit = tmp_path / "junit.xml"
    junit.write_text("<testsuite/>", encoding="utf-8")

    code = radius_ci.main(
        ["upload", "--api", api, "--org", ORG, "--analysis", ANALYSIS, "--junit", str(junit), "--commit", SHA]
    )

    assert code == 0
    request = _Stub.requests[0]
    assert request["path"] == f"/api/v1/analyses/{ANALYSIS}/tests/results?commit_sha={SHA}"
    assert request["headers"]["Content-Type"] == "application/xml"
    assert request["body"] == b"<testsuite/>"
    assert "2 tests, 2 passed, 0 failed" in capsys.readouterr().out


def test_upload_error_is_nonzero_with_server_message_and_no_key(api, tmp_path, capsys) -> None:
    _Stub.upload_status = 409
    junit = tmp_path / "junit.xml"
    junit.write_text("<testsuite/>", encoding="utf-8")

    code = radius_ci.main(
        ["upload", "--api", api, "--org", ORG, "--analysis", ANALYSIS, "--junit", str(junit), "--commit", SHA]
    )

    captured = capsys.readouterr()
    assert code == 1
    assert "HTTP 409: commit mismatch" in captured.err
    assert SECRET not in captured.err + captured.out


@pytest.mark.parametrize(
    "argv",
    [
        ["plan", "--api", "http://127.0.0.1:1", "--org", ORG, "--analysis", "not-a-uuid"],
        ["upload", "--api", "http://127.0.0.1:1", "--org", ORG, "--analysis", ANALYSIS,
         "--junit", __file__, "--commit", "zzzz-not-hex"],
        ["plan", "--api", "file:///etc/passwd", "--org", ORG, "--analysis", ANALYSIS],
    ],
)
def test_invalid_inputs_fail_before_any_request(argv, capsys) -> None:
    assert radius_ci.main(argv) == 1
    assert "radius_ci:" in capsys.readouterr().err
