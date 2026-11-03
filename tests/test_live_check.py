"""Unit tests for ``scripts/live_check.py`` (fake GitHub transport, no network)."""

from __future__ import annotations

import importlib.util
import sys
from email.utils import parsedate_to_datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from radius_github.fake_app import FakeGitHubApp

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "live_check.py"


def _load():
    spec = importlib.util.spec_from_file_location("live_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


live_check = _load()


@pytest.fixture(scope="module")
def keys() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private, public


class Run:
    def __init__(self, keys, tmp_path: Path, **env_overrides: str) -> None:
        private, public = keys
        self.github = FakeGitHubApp(public_key_pem=public)
        self.github.add_pull(3, head_sha="c" * 40, title="secret-title-xyz")
        key_file = tmp_path / "app.pem"
        key_file.write_text(private, encoding="utf-8")
        self.private = private
        self.env = {
            "GITHUB_APP_ID": "12345",
            "GITHUB_APP_PRIVATE_KEY_PATH": str(key_file),
            "RADIUS_LIVE_REPO": "acme/widgets",
            **env_overrides,
        }
        self.lines: list[str] = []

    def go(self, *, clock=None) -> int:
        server_now = parsedate_to_datetime(self.github.server_date).timestamp()
        return live_check.main(
            [],
            env=self.env,
            opener=self.github.opener,
            clock=clock or (lambda: server_now),
            out=self.lines.append,
        )

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def test_all_checks_pass_against_a_healthy_installation(keys, tmp_path) -> None:
    run = Run(keys, tmp_path)

    assert run.go() == 0, run.text
    assert "PREFLIGHT PASSED" in run.text
    for name in ("app jwt", "installation", "installation token", "check-run write", "pull requests"):
        assert any(line.startswith("[PASS]") and name in line for line in run.lines), name
    assert "#3" in run.text
    assert run.github.jwt_verified >= 2
    # read-only: no write other than minting the installation token
    writes = [r for r in run.github.requests if r[0] != "GET"]
    assert writes == [("POST", "/app/installations/9001/access_tokens")]


def test_output_never_contains_secrets_or_pull_request_titles(keys, tmp_path) -> None:
    run = Run(keys, tmp_path)
    run.go()
    body = "".join(line for line in run.private.splitlines() if "-----" not in line)

    assert body[:40] not in run.text
    assert "BEGIN" not in run.text
    assert "ghs_" not in run.text
    assert "eyJ" not in run.text
    assert "secret-title-xyz" not in run.text


def test_missing_check_write_permission_fails_with_actionable_hint(keys, tmp_path) -> None:
    run = Run(keys, tmp_path)
    run.github.permissions["checks"] = "read"

    assert run.go() == 1
    assert any("[FAIL]" in line and "checks:write" in line for line in run.lines)
    assert any("check-run write" in line and "[FAIL]" in line for line in run.lines)
    assert "Checks = Read & write" in run.text


def test_missing_pull_request_write_is_reported(keys, tmp_path) -> None:
    run = Run(keys, tmp_path)
    run.github.permissions["pull_requests"] = "read"

    assert run.go() == 1
    assert "pull_requests:write" in run.text


def test_app_not_installed_on_the_repository(keys, tmp_path) -> None:
    run = Run(keys, tmp_path)
    run.github.installed = False

    assert run.go() == 1
    assert any("[FAIL] installation" in line for line in run.lines)
    assert "exactly this repository" in run.text


def test_wrong_app_id_is_a_jwt_failure_with_clock_and_key_hint(keys, tmp_path) -> None:
    run = Run(keys, tmp_path, GITHUB_APP_ID="99999")

    assert run.go() == 1
    assert any("[FAIL] app jwt" in line for line in run.lines)
    assert "GITHUB_APP_ID" in run.text and "clock" in run.text


def test_clock_skew_is_flagged(keys, tmp_path) -> None:
    run = Run(keys, tmp_path)
    server_now = parsedate_to_datetime(run.github.server_date).timestamp()

    assert run.go(clock=lambda: server_now + 600) == 1
    assert any("[FAIL] clock" in line for line in run.lines)

    warn = Run(keys, tmp_path)
    assert warn.go(clock=lambda: server_now + 45) == 0
    assert any("[WARN] clock" in line for line in warn.lines)


def test_no_open_pull_requests_is_a_warning_not_a_failure(keys, tmp_path) -> None:
    run = Run(keys, tmp_path)
    run.github.pulls.clear()

    assert run.go() == 0
    assert any("[WARN] pull requests" in line for line in run.lines)


def test_pull_list_denied_fails(keys, tmp_path) -> None:
    run = Run(keys, tmp_path)
    run.github.fail[("GET", "/repos/acme/widgets/pulls")] = 403

    assert run.go() == 1
    assert any("[FAIL] pull requests" in line for line in run.lines)


def test_bad_key_material_is_reported_without_echoing_it(keys, tmp_path) -> None:
    run = Run(keys, tmp_path, GITHUB_APP_PRIVATE_KEY="not-a-key-ABC123")
    run.env.pop("GITHUB_APP_PRIVATE_KEY_PATH")

    assert run.go() == 1
    assert "does not look like a PEM" in run.text
    assert "ABC123" not in run.text
    assert run.github.requests == [], "no GitHub call is made with a broken key"

    garbled = Run(
        keys,
        tmp_path,
        GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\nQUJD\n-----END RSA PRIVATE KEY-----",
    )
    garbled.env.pop("GITHUB_APP_PRIVATE_KEY_PATH")
    assert garbled.go() == 1
    assert "could not be parsed" in garbled.text
    assert "QUJD" not in garbled.text


def test_single_line_key_with_escaped_newlines_is_accepted(keys, tmp_path) -> None:
    run = Run(keys, tmp_path)
    run.env.pop("GITHUB_APP_PRIVATE_KEY_PATH")
    run.env["GITHUB_APP_PRIVATE_KEY"] = "'" + run.private.strip().replace("\n", "\\n") + "'"

    assert run.go() == 0, run.text


def test_missing_configuration_and_repository(keys, tmp_path) -> None:
    run = Run(keys, tmp_path)
    run.env.pop("GITHUB_APP_ID")
    run.env.pop("GITHUB_APP_PRIVATE_KEY_PATH")
    run.env.pop("RADIUS_LIVE_REPO")

    assert run.go() == 1
    assert "GITHUB_APP_ID is not set" in run.text
    assert "neither GITHUB_APP_PRIVATE_KEY nor GITHUB_APP_PRIVATE_KEY_PATH" in run.text
    assert "owner/name" in run.text
    assert run.github.requests == []


def test_repository_argument_wins_over_environment(keys, tmp_path) -> None:
    run = Run(keys, tmp_path, RADIUS_LIVE_REPO="other/repo")
    server_now = parsedate_to_datetime(run.github.server_date).timestamp()

    code = live_check.main(
        ["acme/widgets"],
        env=run.env,
        opener=run.github.opener,
        clock=lambda: server_now,
        out=run.lines.append,
    )

    assert code == 0, run.text


def test_redact_removes_tokens_and_keys() -> None:
    text = "token ghs_abcdef123456 Bearer abc.def-ghi -----BEGIN RSA PRIVATE KEY-----\nxx\n-----END RSA PRIVATE KEY-----"
    cleaned = live_check.redact(text)
    assert "ghs_abc" not in cleaned and "abc.def" not in cleaned and "xx" not in cleaned
