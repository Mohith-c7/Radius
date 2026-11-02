"""Tests for actions/upload-results/upload.py against a local stdlib HTTP server."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "radius_upload_results", ROOT / "actions" / "upload-results" / "upload.py"
)
upload = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = upload
_spec.loader.exec_module(upload)

ORG = "11111111-1111-1111-1111-111111111111"
ANALYSIS = "22222222-2222-2222-2222-222222222222"
SHA = "a" * 40
SECRET = "rk_" + "live_" + "s3cr3t" + "value"
RESULTS = f"/api/v1/analyses/{ANALYSIS}/tests/results"
LOOKUP = "/api/v1/analyses/lookup"

JUNIT = (
    '<?xml version="1.0"?><testsuites><testsuite name="s" tests="2" failures="1" hostname="h">'
    '<properties><property name="TOKEN" value="envvalue"/></properties>'
    '<testcase classname="tests.test_a" name="test_ok" file="tests/test_a.py" time="0.1">'
    "<system-out>print(secret_source_line)</system-out></testcase>"
    '<testcase classname="tests.test_a" name="test_bad" time="0.2">'
    '<failure type="AssertionError" message="assert foo(1) == 2">Traceback: def foo(): return 1</failure>'
    "</testcase></testsuite></testsuites>"
)


class Fake:
    def __init__(self) -> None:
        self.queue: dict[tuple[str, str], list] = {}
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _serve(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                path = self.path.split("?")[0]
                outer.requests.append(
                    {
                        "method": self.command,
                        "path": path,
                        "query": self.path,
                        "body": body,
                        "headers": {k.lower(): v for k, v in self.headers.items()},
                    }
                )
                items = outer.queue.get((self.command, path), [])
                if len(items) > 1:
                    status, payload, extra = items.pop(0)
                elif items:
                    status, payload, extra = items[0]
                else:
                    status, payload, extra = 404, {}, {}
                raw = json.dumps(payload).encode()
                self.send_response(status)
                for key, value in extra.items():
                    self.send_header(key, value)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            do_GET = do_POST = _serve

            def log_message(self, *args) -> None:  # noqa: ANN002
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def on(self, method: str, path: str, *responses) -> None:
        self.queue[(method, path)] = [
            (r[0], r[1], r[2] if len(r) > 2 else {}) for r in responses
        ]

    def count(self, method: str, path: str) -> int:
        return sum(
            1 for r in self.requests if r["method"] == method and r["path"] == path
        )


@pytest.fixture
def fake():
    server = Fake()
    server.on("GET", LOOKUP, (200, {"success": True, "data": {"id": ANALYSIS}}))
    server.on(
        "POST",
        RESULTS,
        (200, {"success": True, "data": {"verification_status": "verified"}}),
    )
    yield server
    server.server.shutdown()
    server.server.server_close()


@pytest.fixture
def env(fake, tmp_path, monkeypatch):
    for name in list(os.environ):
        if name.startswith(("RADIUS_", "GITHUB_")):
            monkeypatch.delenv(name)
    values = {
        "RADIUS_API_KEY": SECRET,
        "RADIUS_API_URL": fake.url,
        "RADIUS_ORG_ID": ORG,
        "RADIUS_REPOSITORY": "o/r",
        "RADIUS_PR": "7",
        "RADIUS_COMMIT_SHA": SHA,
        "RADIUS_JUNIT_PATH": "junit.xml",
        "GITHUB_WORKSPACE": str(tmp_path),
        "GITHUB_OUTPUT": str(tmp_path / "out.txt"),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    (tmp_path / "junit.xml").write_text(JUNIT, encoding="utf-8")
    monkeypatch.setattr(upload, "_sleep", lambda seconds: None)
    return monkeypatch


def _outputs(tmp_path) -> dict:
    lines = (tmp_path / "out.txt").read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", 1) for line in lines)


def _posted(fake) -> dict:
    return [r for r in fake.requests if r["method"] == "POST"][0]


def test_success_uploads_sanitized_report(fake, env, tmp_path, capsys) -> None:
    assert upload.run() == 0
    posted = _posted(fake)
    assert f"commit_sha={SHA}" in posted["query"]
    assert posted["headers"]["x-radius-api-key"] == SECRET
    body = posted["body"].decode()
    assert "test_ok" in body and "tests/test_a.py" in body and "AssertionError" in body
    for leaked in ("secret_source_line", "envvalue", "foo(1)", "Traceback", "hostname"):
        assert leaked not in body
    out = _outputs(tmp_path)
    assert out["status"] == "uploaded" and out["analysis-id"] == ANALYSIS
    assert out["uploaded-count"] == "1" and out["verification-status"] == "verified"
    assert SECRET not in capsys.readouterr().out


def test_include_failure_details_sends_report_unchanged(fake, env) -> None:
    env.setenv("RADIUS_INCLUDE_FAILURE_DETAILS", "true")
    assert upload.run() == 0
    assert b"Traceback" in _posted(fake)["body"]


def test_dashboard_link_in_output_and_summary(fake, env, tmp_path) -> None:
    env.setenv("RADIUS_DASHBOARD_URL", "https://dash.example/")
    upload.run()
    link = f"https://dash.example/analyses/{ANALYSIS}"
    assert _outputs(tmp_path)["analysis-url"] == link
    assert link in (tmp_path / "summary.md").read_text(encoding="utf-8")


def test_429_retry_honors_retry_after(fake, env) -> None:
    sleeps: list[float] = []
    fake.on("POST", RESULTS, (429, {}, {"Retry-After": "7"}), (200, {"data": {}}))
    assert upload.run(sleep=sleeps.append) == 0
    assert fake.count("POST", RESULTS) == 2
    assert 7.0 in sleeps


def test_retry_after_is_capped(fake, env) -> None:
    sleeps: list[float] = []
    fake.on("POST", RESULTS, (429, {}, {"Retry-After": "99999"}), (200, {"data": {}}))
    upload.run(sleep=sleeps.append)
    assert max(sleeps) == upload.MAX_RETRY_AFTER_SECONDS


def test_5xx_retries_with_backoff_then_succeeds(fake, env) -> None:
    sleeps: list[float] = []
    fake.on("POST", RESULTS, (503, {}), (502, {}), (200, {"data": {}}))
    assert upload.run(sleep=sleeps.append) == 0
    assert fake.count("POST", RESULTS) == 3 and sleeps == [2.0, 4.0]


def test_persistent_5xx_does_not_fail_by_default(fake, env, tmp_path, capsys) -> None:
    fake.on("POST", RESULTS, (500, {}))
    assert upload.run() == 0
    assert fake.count("POST", RESULTS) == upload.MAX_ATTEMPTS
    assert _outputs(tmp_path)["status"] == "failed"
    assert "::warning" in capsys.readouterr().out


def test_4xx_not_retried_and_nonfatal_by_default(fake, env, capsys) -> None:
    fake.on("POST", RESULTS, (403, {"error": {"message": "missing scope"}}))
    assert upload.run() == 0
    out = capsys.readouterr().out
    assert fake.count("POST", RESULTS) == 1
    assert "ci-upload" in out and "missing scope" in out


def test_4xx_fails_when_opted_in(fake, env, capsys) -> None:
    env.setenv("RADIUS_FAIL_ON_UPLOAD_ERROR", "true")
    fake.on("POST", RESULTS, (409, {"error": {"message": "stale"}}))
    assert upload.run() == 1
    assert "::error" in capsys.readouterr().out


def test_lookup_404_polls_then_resolves(fake, env) -> None:
    fake.on("GET", LOOKUP, (404, {}), (200, {"data": {"id": ANALYSIS}}))
    assert upload.run() == 0
    assert fake.count("GET", LOOKUP) == 2


def test_lookup_never_found_is_nonfatal(fake, env, tmp_path) -> None:
    env.setenv("RADIUS_WAIT_SECONDS", "10")
    fake.on("GET", LOOKUP, (404, {}))
    assert upload.run() == 0
    assert _outputs(tmp_path)["status"] == "failed"
    assert fake.count("POST", RESULTS) == 0


def test_explicit_analysis_id_skips_lookup(fake, env) -> None:
    env.setenv("RADIUS_ANALYSIS_ID", ANALYSIS)
    env.delenv("RADIUS_PR")
    assert upload.run() == 0
    assert fake.count("GET", LOOKUP) == 0


def test_missing_results_is_a_warning_not_failure(fake, env, tmp_path, capsys) -> None:
    env.setenv("RADIUS_JUNIT_PATH", "nothing/*.xml")
    assert upload.run() == 0
    assert _outputs(tmp_path)["status"] == "skipped-no-results"
    assert fake.requests == []
    assert "No JUnit XML files matched" in capsys.readouterr().out


def test_fork_skips_without_any_request(fake, env, tmp_path, capsys) -> None:
    env.setenv("RADIUS_IS_FORK", "true")
    env.setenv("RADIUS_FAIL_ON_UPLOAD_ERROR", "true")
    assert upload.run() == 0
    assert _outputs(tmp_path)["status"] == "skipped-fork"
    assert fake.requests == []
    assert "forks have no access" in capsys.readouterr().out


def test_missing_secret_skips_gracefully(fake, env, tmp_path) -> None:
    env.setenv("RADIUS_API_KEY", "")
    env.setenv("RADIUS_FAIL_ON_UPLOAD_ERROR", "true")
    assert upload.run() == 0
    assert _outputs(tmp_path)["status"] == "skipped-no-secret"
    assert fake.requests == []


def test_glob_recursive_dedup_and_outside_workspace(fake, env, tmp_path) -> None:
    workspace = tmp_path / "ws"
    (workspace / "a" / "b").mkdir(parents=True)
    (workspace / "a" / "b" / "r1.xml").write_text(JUNIT, encoding="utf-8")
    (workspace / "a" / "r2.xml").write_text(
        JUNIT.replace("test_ok", "test_two"), encoding="utf-8"
    )
    (tmp_path / "outside_junit.xml").write_text(JUNIT, encoding="utf-8")
    env.setenv("GITHUB_WORKSPACE", str(workspace))
    env.setenv("RADIUS_JUNIT_PATH", "a/**/*.xml\na/r2.xml\n../outside_junit.xml")
    assert upload.run() == 0
    assert (
        fake.count("POST", RESULTS) == 2
    )  # r1 + r2; no duplicate; outside file skipped


def test_large_file_cap(fake, env, tmp_path, capsys) -> None:
    (tmp_path / "junit.xml").write_bytes(JUNIT.encode() + b" " * 2_000_000)
    env.setenv("RADIUS_MAX_FILE_MB", "1")
    assert upload.run() == 0
    assert fake.requests == []
    assert "exceeds" in capsys.readouterr().out


def test_malformed_xml_is_skipped_not_uploaded(fake, env, tmp_path, capsys) -> None:
    (tmp_path / "junit.xml").write_text(
        "<testsuite><testcase></testsuite>", encoding="utf-8"
    )
    assert upload.run() == 0
    assert fake.requests == []
    assert _outputs(tmp_path)["skipped-count"] == "1"
    assert "not well-formed" in capsys.readouterr().out


def test_doctype_and_non_junit_rejected() -> None:
    for bad in (b'<!DOCTYPE x [<!ENTITY a "b">]><testsuite/>', b"<html/>", b""):
        with pytest.raises(upload.UploadFailure):
            upload.sanitize_junit(bad)


def test_secret_never_printed_even_if_server_echoes_it(fake, env, capsys) -> None:
    fake.on("POST", RESULTS, (400, {"error": {"message": f"bad key {SECRET}"}}))
    env.setenv("GITHUB_ACTIONS", "true")
    upload.run()
    out = capsys.readouterr().out
    assert out.count(SECRET) == 1  # only the ::add-mask:: registration line
    assert f"::add-mask::{SECRET}" in out
    assert "***" in out


def test_coverage_percentage_only(fake, env, tmp_path) -> None:
    (tmp_path / "cov.xml").write_text(
        '<coverage line-rate="0.835"><packages><package name="p"/></packages></coverage>',
        encoding="utf-8",
    )
    fake.on("POST", "/api/v1/coverage", (202, {"success": True}))
    env.setenv("RADIUS_COVERAGE_PATH", "cov.xml")
    assert upload.run() == 0
    request = [r for r in fake.requests if r["path"] == "/api/v1/coverage"][0]
    assert json.loads(request["body"]) == {
        "framework": "cobertura",
        "coverage_percent": 83.5,
    }
    assert request["headers"]["x-analysis-id"] == ANALYSIS


def test_bad_coverage_does_not_block_junit(fake, env, tmp_path) -> None:
    (tmp_path / "cov.xml").write_text("<report/>", encoding="utf-8")
    env.setenv("RADIUS_COVERAGE_PATH", "cov.xml")
    assert upload.run() == 0
    assert fake.count("POST", RESULTS) == 1


def test_unexpected_exception_is_contained(fake, env) -> None:
    def boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise ZeroDivisionError

    env.setattr(upload, "find_files", boom)
    assert upload.run() == 0
    env.setenv("RADIUS_FAIL_ON_UPLOAD_ERROR", "true")
    assert upload.run() == 1


def test_insecure_api_url_rejected(fake, env, tmp_path) -> None:
    env.setenv("RADIUS_API_URL", "http://radius.example.com")
    assert upload.run() == 0
    assert _outputs(tmp_path)["status"] == "failed"
    assert fake.requests == []


def test_redirect_not_followed(fake, env, tmp_path) -> None:
    fake.on("POST", RESULTS, (302, {}, {"Location": "https://evil.example/"}))
    assert upload.run() == 0
    assert fake.count("POST", RESULTS) == 1
    assert _outputs(tmp_path)["status"] == "failed"
