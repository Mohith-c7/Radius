"""GitHub App client additions for the pull-based flow (fake transport only)."""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from radius_github import GitHubAppClient, GitHubAppSettings, GitHubHTTPError
from radius_github.client import normalize_private_key
from radius_github.fake_app import FakeGitHubApp


@pytest.fixture(scope="module")
def keys() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private, public


def _client(keys, github: FakeGitHubApp, **settings) -> GitHubAppClient:
    return GitHubAppClient(
        GitHubAppSettings(
            GITHUB_APP_ID="12345", GITHUB_APP_PRIVATE_KEY=keys[0], **settings
        ),
        opener=github.opener,
        sleep=lambda _s: None,
    )


def test_discovery_token_and_repository_reads(keys) -> None:
    github = FakeGitHubApp(public_key_pem=keys[1])
    github.add_pull(5, head_sha="d" * 40)
    client = _client(keys, github)

    assert client.get_app()["slug"] == "radius-demo"
    installation = client.get_repository_installation("acme", "widgets")
    token = client.create_installation_token(installation["id"])
    assert token.permissions["checks"] == "write"
    assert token.repository_selection == "selected"
    repo = client.get_repository(token=token.token, owner="acme", repo="widgets")
    assert repo["id"] == 4242
    pull = client.get_pull_request(token=token.token, owner="acme", repo="widgets", number=5)
    assert pull["head"]["sha"] == "d" * 40
    assert client.last_server_date == github.server_date
    assert github.jwt_verified == 3


def test_http_errors_carry_the_status_code_and_stay_access_denied(keys) -> None:
    github = FakeGitHubApp(public_key_pem=keys[1], app_id="other")
    client = _client(keys, github)

    with pytest.raises(GitHubHTTPError) as excinfo:
        client.get_app()

    assert excinfo.value.status == 401
    assert "HTTP 401" in str(excinfo.value)
    assert "GET /app" in str(excinfo.value)


def test_private_key_forms(keys) -> None:
    private = keys[0].strip()
    escaped = private.replace("\n", "\\n")
    assert normalize_private_key(escaped) == private
    assert normalize_private_key(f"'{escaped}'") == private
    assert normalize_private_key(f'"{private}"\n') == private


def test_private_key_can_be_read_from_a_file(keys, tmp_path) -> None:
    path = tmp_path / "app.pem"
    path.write_text(keys[0], encoding="utf-8")

    settings = GitHubAppSettings(GITHUB_APP_ID="1", GITHUB_APP_PRIVATE_KEY_PATH=str(path))

    assert settings.enabled
    assert settings.github_app_private_key == keys[0]


def test_inline_key_wins_over_the_file_and_a_missing_file_is_a_clear_error(keys, tmp_path) -> None:
    inline = GitHubAppSettings(
        GITHUB_APP_ID="1",
        GITHUB_APP_PRIVATE_KEY="inline",
        GITHUB_APP_PRIVATE_KEY_PATH=str(tmp_path / "missing.pem"),
    )
    assert inline.github_app_private_key == "inline"

    with pytest.raises(ValueError, match="GITHUB_APP_PRIVATE_KEY_PATH") as excinfo:
        GitHubAppSettings(
            GITHUB_APP_ID="1", GITHUB_APP_PRIVATE_KEY_PATH=str(tmp_path / "missing.pem")
        )
    assert "BEGIN" not in str(excinfo.value)


def test_blank_installation_id_is_none(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_INSTALLATION_ID", "")
    assert GitHubAppSettings().github_installation_id is None
    assert GitHubAppSettings(GITHUB_INSTALLATION_ID="").github_installation_id is None
    assert GitHubAppSettings(GITHUB_INSTALLATION_ID="42").github_installation_id == 42
