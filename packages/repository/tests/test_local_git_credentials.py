"""Git credentials must reach git only via the child environment, never argv/config/logs."""

from __future__ import annotations

import base64
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from radius_repository.infrastructure import local_git
from radius_repository.infrastructure.local_git import LocalGitRepositoryClient
from radius_shared.errors import ValidationError

TOKEN = "ghs_FAKEinstallationTOKEN1234567890abcdef"
BASIC = base64.b64encode(f"x-access-token:{TOKEN}".encode()).decode()
HEADER = f"Authorization: Basic {BASIC}"


class _Recorder(BaseHTTPRequestHandler):
    seen: list[str | None] = []

    def do_GET(self) -> None:  # noqa: N802
        type(self).seen.append(self.headers.get("Authorization"))
        self.send_response(404)
        self.end_headers()

    def log_message(self, *args) -> None:  # silence
        return


@pytest.fixture
def http_remote():
    _Recorder.seen = []
    server = HTTPServer(("127.0.0.1", 0), _Recorder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/acme/radius.git"
    server.shutdown()
    thread.join()


def test_credentials_are_not_in_argv_but_in_child_environment(monkeypatch, tmp_path) -> None:
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(local_git.subprocess, "run", fake_run)
    LocalGitRepositoryClient().clone_or_fetch(
        "https://github.com/acme/radius.git", tmp_path / "dest", extra_headers=(HEADER,)
    )

    assert not any(TOKEN in part or BASIC in part for part in captured["command"])
    assert not any("extraHeader" in part for part in captured["command"])
    env = captured["env"]
    assert env["GIT_CONFIG_COUNT"] == "1"
    # Scoped to the remote's origin so it is not replayed to other hosts.
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraHeader"
    assert env["GIT_CONFIG_VALUE_0"] == HEADER


def test_no_headers_leaves_environment_untouched(monkeypatch, tmp_path) -> None:
    captured = {}

    def fake_run(command, **kwargs):
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(local_git.subprocess, "run", fake_run)
    LocalGitRepositoryClient().clone_or_fetch("https://github.com/a/b.git", tmp_path / "d")
    assert captured["env"] is None


def test_real_git_sends_basic_auth_and_keeps_token_out_of_config_and_errors(
    http_remote, tmp_path
) -> None:
    destination = tmp_path / "dest"
    with pytest.raises(ValidationError) as excinfo:
        LocalGitRepositoryClient().clone_or_fetch(
            http_remote, destination, extra_headers=(HEADER,)
        )

    # The server received Basic auth with x-access-token:<token>.
    assert _Recorder.seen
    scheme, _, blob = (_Recorder.seen[0] or "").partition(" ")
    assert scheme == "Basic"
    assert base64.b64decode(blob).decode() == f"x-access-token:{TOKEN}"
    # git failed (404), and neither form of the credential is in the error text.
    message = str(excinfo.value)
    assert TOKEN not in message
    assert BASIC not in message
    # Nothing was persisted: a partially-created clone must not hold the token.
    for path in tmp_path.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert TOKEN.encode() not in data
            assert BASIC.encode() not in data


def test_fetch_in_existing_clone_scopes_header_to_origin_and_leaves_config_clean(
    http_remote, tmp_path
) -> None:
    repo = tmp_path / "repo"
    subprocess.run(("git", "init", "-q", str(repo)), check=True)
    subprocess.run(("git", "-C", str(repo), "remote", "add", "origin", http_remote), check=True)

    with pytest.raises(ValidationError) as excinfo:
        LocalGitRepositoryClient().clone_or_fetch(
            "ignored", repo, extra_headers=(HEADER,)
        )

    assert _Recorder.seen and _Recorder.seen[0] == HEADER.removeprefix("Authorization: ")
    config = (repo / ".git" / "config").read_text(encoding="utf-8")
    assert TOKEN not in config and BASIC not in config and "extraheader" not in config.lower()
    assert TOKEN not in str(excinfo.value) and BASIC not in str(excinfo.value)


def test_header_is_not_sent_to_a_different_origin(http_remote, tmp_path) -> None:
    repo = tmp_path / "repo"
    subprocess.run(("git", "init", "-q", str(repo)), check=True)
    # Remote on another "origin" (different port) than the one the header is for.
    subprocess.run(
        ("git", "-C", str(repo), "remote", "add", "origin", http_remote), check=True
    )
    env = local_git._git_environment((HEADER,), "https://github.com/acme/radius.git")
    result = subprocess.run(
        ("git", "fetch", "origin"), cwd=repo, env=env, capture_output=True, text=True
    )
    assert result.returncode != 0
    assert _Recorder.seen
    assert all(value is None for value in _Recorder.seen)


def test_scrub_removes_header_value_even_if_git_echoes_it() -> None:
    message = f"fatal: unable to access: sent '{HEADER}' to server"
    scrubbed = local_git._scrub(message, (HEADER,))
    assert BASIC not in scrubbed and TOKEN not in scrubbed
