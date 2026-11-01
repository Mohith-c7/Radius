"""Tests for scripts/radius_ci.py against a local stdlib HTTP server (no external network)."""

from __future__ import annotations

import importlib.util
import json
import socket
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "radius_ci.py"
_spec = importlib.util.spec_from_file_location("radius_ci", _SCRIPT)
radius_ci = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = radius_ci  # dataclasses resolve annotations via sys.modules
_spec.loader.exec_module(radius_ci)

ORG = "11111111-1111-1111-1111-111111111111"
ANALYSIS = "22222222-2222-2222-2222-222222222222"
SHA = "a" * 40
SECRET = "super-secret-key-value"
LOOKUP = "/api/v1/analyses/lookup"
ANALYSIS_PATH = f"/api/v1/analyses/{ANALYSIS}"
TESTS_PATH = f"{ANALYSIS_PATH}/tests"
RESULTS_PATH = f"{ANALYSIS_PATH}/tests/results"


def _analysis(status: str = "completed", sha: str = SHA) -> tuple[int, dict]:
    return 200, {"success": True, "data": {"id": ANALYSIS, "status": status, "commit_sha": sha}}


def _selection(*paths: str) -> tuple[int, dict]:
    return 200, {
        "success": True,
        "data": {
            "analysis_id": ANALYSIS,
            "cli_args": " ".join(paths),
            "selected_tests": [{"test": {"path": path}, "reason": "direct"} for path in paths],
        },
    }


def _ingestion(verdict: str, **attribution) -> tuple[int, dict]:
    selected = {
        "selected_count": 2,
        "executed_count": 2,
        "failed": [],
        "skipped": [],
        "not_reported": [],
        **attribution,
    }
    return 200, {
        "success": True,
        "data": {
            "total_tests": 2,
            "passed": 2,
            "failed": 0,
            "skipped": 0,
            "upload_count": 1,
            "upload": {
                "total_tests": 2, "passed": 2, "failed": 0, "skipped": 0, "duplicate": False,
            },
            "selected_tests": selected,
            "verification_status": verdict,
        },
    }


def _error(status: int, message: str) -> tuple[int, dict]:
    return status, {"success": False, "error": {"code": "X", "message": message}}


class FakeRadius:
    """Scripted responses per (method, path); the last response repeats."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], list[tuple[int, dict | str]]] = {}
        self.requests: list[dict] = []

    def on(self, method: str, path: str, *responses: tuple[int, dict | str]) -> None:
        self.routes[(method, path)] = list(responses)

    def respond(self, method: str, raw_path: str, headers, body: bytes):
        parsed = urllib.parse.urlsplit(raw_path)
        self.requests.append(
            {
                "method": method,
                "path": parsed.path,
                "query": dict(urllib.parse.parse_qsl(parsed.query)),
                "headers": dict(headers),
                "body": body,
            }
        )
        queue = self.routes.get((method, parsed.path))
        if not queue:
            return 404, {"success": False, "error": {"code": "NOT_FOUND", "message": "no route"}}
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def paths(self, method: str | None = None) -> list[str]:
        return [r["path"] for r in self.requests if method is None or r["method"] == method]


@pytest.fixture()
def fake(monkeypatch):
    state = FakeRadius()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # silence server logs
            pass

        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length", 0) or 0)
            body = self.rfile.read(length) if length else b""
            status, payload = state.respond(self.command, self.path, self.headers, body)
            raw = payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
            self.send_response(status)
            if status in {301, 302, 307, 308}:
                self.send_header("Location", "http://evil.example/steal")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        do_GET = _handle  # noqa: N815
        do_POST = _handle  # noqa: N815

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("RADIUS_API_KEY", SECRET)
    # Never actually sleep in tests (polling and retry backoff).
    monkeypatch.setattr(radius_ci, "_sleep", lambda seconds: None)
    state.url = f"http://127.0.0.1:{server.server_address[1]}"
    yield state
    server.shutdown()
    server.server_close()


def _base(fake, command: str, *extra: str) -> list[str]:
    return [command, "--api", fake.url, "--org", ORG, *extra]


def _lookup_args(*extra: str) -> list[str]:
    return ["--repository", "acme/radius", "--pr", "12", "--commit", SHA, *extra]


def _run(argv, capsys):
    code = radius_ci.main(argv)
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err
    return code, captured


# --------------------------------------------------------------------------- resolve


def test_resolve_polls_lookup_until_analysis_completes(fake, capsys) -> None:
    fake.on(
        "GET",
        LOOKUP,
        _error(404, "No analysis found"),  # webhook not processed yet
        _analysis("pending"),
        _analysis("running"),
        _analysis("completed"),
    )

    code, captured = _run(_base(fake, "resolve", *_lookup_args("--poll-interval", "0")), capsys)

    assert code == 0
    assert captured.out.strip() == ANALYSIS
    assert len(fake.paths()) == 4
    first = fake.requests[0]
    assert first["query"] == {"repository": "acme/radius", "pullRequest": "12", "commitSha": SHA}
    assert first["headers"]["X-Radius-Organization-Id"] == ORG
    assert first["headers"]["X-Radius-Api-Key"] == SECRET
    assert "waiting for analysis (state: running)" in captured.err


def test_resolve_times_out_with_exit_code_3(fake, capsys, monkeypatch) -> None:
    fake.on("GET", LOOKUP, _analysis("running"))
    now = [0.0]
    monkeypatch.setattr(radius_ci, "_clock", lambda: now[0])
    monkeypatch.setattr(radius_ci, "_sleep", lambda s: now.__setitem__(0, now[0] + s))

    code, captured = _run(
        _base(fake, "resolve", *_lookup_args("--wait", "30", "--poll-interval", "10")), capsys
    )

    assert code == radius_ci.EXIT_TIMEOUT == 3
    assert "Timed out after 30s" in captured.err
    assert "last state: running" in captured.err
    assert len(fake.paths()) == 4  # t=0, 10, 20, 30


def test_resolve_failed_analysis_is_an_error(fake, capsys) -> None:
    fake.on("GET", LOOKUP, _analysis("failed"))

    code, captured = _run(_base(fake, "resolve", *_lookup_args()), capsys)

    assert code == 1
    assert "is failed" in captured.err
    assert "Re-run the analysis" in captured.err


def test_resolve_by_id_rejects_analysis_of_another_commit(fake, capsys) -> None:
    fake.on("GET", ANALYSIS_PATH, _analysis("completed", sha="b" * 40))

    code, captured = _run(
        _base(fake, "resolve", "--analysis", ANALYSIS, "--commit", SHA), capsys
    )

    assert code == 1
    assert "is for commit bbbbbbbbbbbb" in captured.err


def test_resolve_retries_transient_server_errors_while_polling(fake, capsys) -> None:
    fake.on("GET", LOOKUP, _error(503, "maintenance"), _analysis("completed"))

    code, captured = _run(_base(fake, "resolve", *_lookup_args("--poll-interval", "0")), capsys)

    assert code == 0
    assert captured.out.strip() == ANALYSIS


# --------------------------------------------------------------------------- plan


def test_plan_resolves_then_prints_selected_paths_and_github_outputs(
    fake, capsys, tmp_path, monkeypatch
) -> None:
    fake.on("GET", LOOKUP, _analysis("running"), _analysis("completed"))
    fake.on(
        "GET",
        TESTS_PATH,
        _selection("tests/test_a.py", "tests/test_b.py", "tests/test_a.py"),
    )
    github_output = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    tests_file = tmp_path / "radius-tests.txt"

    code, captured = _run(
        _base(
            fake,
            "plan",
            *_lookup_args("--poll-interval", "0", "--output", str(tests_file), "--github-output"),
        ),
        capsys,
    )

    assert code == 0
    assert captured.out.splitlines() == ["tests/test_a.py", "tests/test_b.py"]
    assert tests_file.read_text().splitlines() == ["tests/test_a.py", "tests/test_b.py"]
    assert fake.paths()[-1] == TESTS_PATH
    outputs = github_output.read_text()
    assert "analysis-id<<" in outputs and ANALYSIS in outputs
    assert "\n2\n" in outputs  # test-count
    assert "\ntrue\n" in outputs  # has-tests
    assert str(tests_file.resolve()) in outputs
    assert SECRET not in outputs


def test_plan_with_analysis_id_waits_for_completion(fake, capsys) -> None:
    fake.on("GET", ANALYSIS_PATH, _analysis("pending"), _analysis("completed"))
    fake.on("GET", TESTS_PATH, _selection("tests/test_a.py"))

    code, captured = _run(
        _base(fake, "plan", "--analysis", ANALYSIS, "--poll-interval", "0"), capsys
    )

    assert code == 0
    assert captured.out.splitlines() == ["tests/test_a.py"]
    assert fake.paths() == [ANALYSIS_PATH, ANALYSIS_PATH, TESTS_PATH]


def test_empty_plan_prints_nothing_and_reports_no_tests(fake, capsys, tmp_path, monkeypatch) -> None:
    fake.on("GET", ANALYSIS_PATH, _analysis())
    fake.on("GET", TESTS_PATH, _selection())
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out"))

    code, captured = _run(
        _base(fake, "plan", "--analysis", ANALYSIS, "--github-output"), capsys
    )

    assert code == 0
    assert captured.out == ""
    assert "selected no tests" in captured.err
    assert "\nfalse\n" in (tmp_path / "out").read_text()


@pytest.mark.parametrize("path", ["--rootdir=/tmp", "/etc/passwd", "tests/../../x.py", "a\nb"])
def test_plan_refuses_unsafe_paths(fake, capsys, path) -> None:
    fake.on("GET", ANALYSIS_PATH, _analysis())
    fake.on("GET", TESTS_PATH, _selection("tests/test_ok.py", path))

    code, captured = _run(_base(fake, "plan", "--analysis", ANALYSIS), capsys)

    assert code == 1
    assert "Refusing unsafe test path" in captured.err
    assert captured.out == ""


# --------------------------------------------------------------------------- upload


def test_upload_sends_each_junit_bound_to_commit(fake, tmp_path, capsys) -> None:
    fake.on("GET", ANALYSIS_PATH, _analysis())
    fake.on("POST", RESULTS_PATH, _ingestion("verified"))
    first = tmp_path / "junit-a.xml"
    second = tmp_path / "junit-b.xml"
    first.write_text("<testsuite name='a'/>", encoding="utf-8")
    second.write_text("<testsuite name='b'/>", encoding="utf-8")

    code, captured = _run(
        _base(
            fake, "upload", "--analysis", ANALYSIS, "--commit", SHA.upper(),
            "--junit", str(first), "--junit", str(second),
        ),
        capsys,
    )

    assert code == 0
    posts = [r for r in fake.requests if r["method"] == "POST"]
    assert [p["body"] for p in posts] == [b"<testsuite name='a'/>", b"<testsuite name='b'/>"]
    assert all(p["query"] == {"commit_sha": SHA} for p in posts)
    assert all(p["headers"]["Content-Type"] == "application/xml" for p in posts)
    assert "junit-a.xml: 2 tests, 2 passed, 0 failed, 0 skipped." in captured.out
    assert "Radius verdict: verified" in captured.out
    assert "Selected test files executed: 2/2." in captured.out


def test_upload_resolves_by_pull_request_and_commit(fake, tmp_path, capsys) -> None:
    fake.on("GET", LOOKUP, _analysis())
    fake.on("POST", RESULTS_PATH, _ingestion("verified"))
    junit = tmp_path / "junit.xml"
    junit.write_text("<testsuite/>", encoding="utf-8")

    code, _ = _run(_base(fake, "upload", *_lookup_args("--junit", str(junit))), capsys)

    assert code == 0
    assert fake.paths() == [LOOKUP, RESULTS_PATH]


def test_upload_requires_commit(fake, tmp_path, capsys) -> None:
    junit = tmp_path / "junit.xml"
    junit.write_text("<testsuite/>", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        radius_ci.main(_base(fake, "upload", "--analysis", ANALYSIS, "--junit", str(junit)))

    assert exc.value.code == 2
    assert "--commit" in capsys.readouterr().err
    assert fake.requests == []


@pytest.mark.parametrize(
    ("status", "message", "hint"),
    [
        (401, "Missing API key", "Authentication failed"),
        (403, "Invalid Radius API key for organization.", "Access denied"),
        (404, "Analysis was not found.", "Not found"),
        (409, "Results are for commit aaaaaaa, but analysis analysed bbbbbbb.", "Conflict"),
        (409, "Analysis is superseded by a newer head commit.", "stale analysis"),
        (422, "Report has no <testcase> entries.", "JUnit XML"),
        (500, "Internal error", "server error"),
    ],
)
def test_upload_errors_are_actionable_and_nonzero(
    fake, tmp_path, capsys, status, message, hint
) -> None:
    fake.on("GET", ANALYSIS_PATH, _analysis())
    fake.on("POST", RESULTS_PATH, _error(status, message))
    junit = tmp_path / "junit.xml"
    junit.write_text("<testsuite/>", encoding="utf-8")

    code, captured = _run(
        _base(fake, "upload", "--analysis", ANALYSIS, "--commit", SHA, "--junit", str(junit)),
        capsys,
    )

    assert code == 1
    assert f"HTTP {status}: {message}" in captured.err
    assert hint in captured.err


def test_fastapi_validation_detail_is_readable(fake, tmp_path, capsys) -> None:
    fake.on("GET", ANALYSIS_PATH, _analysis())
    fake.on(
        "POST",
        RESULTS_PATH,
        (422, {"detail": [{"loc": ["query", "commit_sha"], "msg": "Field required"}]}),
    )
    junit = tmp_path / "junit.xml"
    junit.write_text("<testsuite/>", encoding="utf-8")

    code, captured = _run(
        _base(fake, "upload", "--analysis", ANALYSIS, "--commit", SHA, "--junit", str(junit)),
        capsys,
    )

    assert code == 1
    assert "HTTP 422: commit_sha: Field required" in captured.err


def test_server_echoing_the_key_is_scrubbed(fake, capsys) -> None:
    fake.on("GET", ANALYSIS_PATH, _error(403, f"bad key {SECRET}"))

    code, captured = _run(_base(fake, "resolve", "--analysis", ANALYSIS), capsys)

    assert code == 1
    assert "bad key ***" in captured.err


def test_redirects_are_refused_so_the_key_is_not_forwarded(fake, capsys) -> None:
    fake.on("GET", ANALYSIS_PATH, (302, {}))

    code, captured = _run(_base(fake, "resolve", "--analysis", ANALYSIS), capsys)

    assert code == 1
    assert "redirect" in captured.err
    assert len(fake.requests) == 1


def test_missing_junit_file_fails_before_upload(fake, tmp_path, capsys) -> None:
    fake.on("GET", ANALYSIS_PATH, _analysis())

    code, captured = _run(
        _base(
            fake, "upload", "--analysis", ANALYSIS, "--commit", SHA,
            "--junit", str(tmp_path / "missing.xml"),
        ),
        capsys,
    )

    assert code == 1
    assert "JUnit report not found" in captured.err
    assert fake.paths("POST") == []


def test_network_error_is_reported_without_key(capsys, monkeypatch) -> None:
    monkeypatch.setenv("RADIUS_API_KEY", SECRET)
    monkeypatch.setattr(radius_ci, "_sleep", lambda seconds: None)
    monkeypatch.setattr(radius_ci, "TIMEOUT_SECONDS", 2)
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()  # nothing listens on this port now: connection refused

    code, captured = _run(
        ["resolve", "--api", f"http://127.0.0.1:{port}", "--org", ORG, "--analysis", ANALYSIS],
        capsys,
    )

    assert code == 1
    assert f"Could not reach Radius API at http://127.0.0.1:{port}" in captured.err


@pytest.mark.parametrize(
    "argv",
    [
        ["plan", "--api", "http://127.0.0.1:1", "--org", ORG, "--analysis", "not-a-uuid"],
        ["upload", "--api", "http://127.0.0.1:1", "--org", ORG, "--analysis", ANALYSIS,
         "--junit", __file__, "--commit", "zzzz-not-hex"],
        ["plan", "--api", "file:///etc/passwd", "--org", ORG, "--analysis", ANALYSIS],
        ["plan", "--api", "https://user:pw@radius.example", "--org", ORG, "--analysis", ANALYSIS],
        ["plan", "--api", "http://127.0.0.1:1", "--org", ORG, "--repository", "acme/radius"],
        ["plan", "--api", "http://127.0.0.1:1", "--org", ORG, "--repository", "bad repo",
         "--pr", "1", "--commit", SHA],
    ],
)
def test_invalid_inputs_fail_before_any_request(argv, capsys, monkeypatch) -> None:
    monkeypatch.setenv("RADIUS_API_KEY", SECRET)
    code, captured = _run(argv, capsys)

    assert code == 1
    assert "radius_ci:" in captured.err


def _upload_argv(fake, tmp_path, *extra: str) -> list[str]:
    junit = tmp_path / "junit.xml"
    junit.write_text("<testsuite/>", encoding="utf-8")
    return _base(
        fake, "upload", "--analysis", ANALYSIS, "--commit", SHA, "--junit", str(junit), *extra
    )


def test_upload_failed_verdict_exits_4_with_failing_files(fake, tmp_path, capsys) -> None:
    fake.on("GET", ANALYSIS_PATH, _analysis())
    fake.on(
        "POST",
        RESULTS_PATH,
        _ingestion("failed", failed=["tests/test_checkout.py"]),
    )

    code, captured = _run(_upload_argv(fake, tmp_path), capsys)

    assert code == radius_ci.EXIT_VERDICT_FAILED == 4
    assert "Radius verdict: failed" in captured.out
    assert "Failed: tests/test_checkout.py" in captured.out
    assert "a selected test failed" in captured.err


def test_insufficient_evidence_passes_unless_verified_is_required(
    fake, tmp_path, capsys, monkeypatch
) -> None:
    fake.on("GET", ANALYSIS_PATH, _analysis())
    fake.on(
        "POST",
        RESULTS_PATH,
        _ingestion("insufficient_evidence", executed_count=1, not_reported=["tests/test_b.py"]),
    )
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out"))

    lenient, captured = _run(_upload_argv(fake, tmp_path, "--github-output"), capsys)
    strict, strict_captured = _run(_upload_argv(fake, tmp_path, "--require-verified"), capsys)

    assert lenient == 0
    assert "Radius verdict: insufficient_evidence" in captured.out
    assert "Selected but not in any report: tests/test_b.py" in captured.out
    assert "insufficient_evidence" in (tmp_path / "out").read_text()
    assert strict == radius_ci.EXIT_NOT_VERIFIED == 5
    assert "--require-verified" in strict_captured.err


def test_require_verified_succeeds_when_verified(fake, tmp_path, capsys) -> None:
    fake.on("GET", ANALYSIS_PATH, _analysis())
    fake.on("POST", RESULTS_PATH, _ingestion("verified"))

    code, captured = _run(_upload_argv(fake, tmp_path, "--require-verified"), capsys)

    assert code == 0
    assert "Radius verdict: verified" in captured.out


def test_upload_waits_for_running_analysis_before_posting(fake, tmp_path, capsys) -> None:
    fake.on("GET", ANALYSIS_PATH, _analysis("running"), _analysis("completed"))
    fake.on("POST", RESULTS_PATH, _ingestion("verified"))

    code, _ = _run(_upload_argv(fake, tmp_path, "--poll-interval", "0"), capsys)

    assert code == 0
    assert fake.paths() == [ANALYSIS_PATH, ANALYSIS_PATH, RESULTS_PATH]


CONFIDENCE_PATH = ANALYSIS_PATH + "/confidence"


@pytest.mark.parametrize(
    ("status", "strict_code"),
    [("verified", 0), ("insufficient_evidence", 5), ("failed", 4)],
)
def test_verdict_command_gates_without_uploading(fake, capsys, status, strict_code) -> None:
    """With no selected tests nothing is uploaded, but the job must still gate."""

    fake.on("GET", ANALYSIS_PATH, _analysis())
    fake.on("GET", CONFIDENCE_PATH, (200, {"success": True, "data": {"verification_status": status}}))

    code, captured = _run(
        _base(fake, "verdict", "--analysis", ANALYSIS, "--require-verified"), capsys
    )

    assert code == strict_code
    assert f"Radius verdict: {status}" in captured.out
    assert SECRET not in captured.out + captured.err
