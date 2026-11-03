"""A-13: owner/repo/ref are single URL path segments; dot segments never reach urljoin."""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from radius_github import GitHubAppClient, GitHubAppSettings
from radius_github.client import _seg
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


def test_segments_are_encoded_and_dot_segments_refused() -> None:
    assert _seg("acme") == "acme"
    assert _seg("a b/c?d#e") == "a%20b%2Fc%3Fd%23e"
    assert _seg(".github") == ".github"
    for bad in ("", ".", ".."):
        with pytest.raises(ValueError):
            _seg(bad)


def test_client_never_issues_a_request_for_a_dot_segment_repository(keys) -> None:
    github = FakeGitHubApp(public_key_pem=keys[1])
    client = GitHubAppClient(
        GitHubAppSettings(GITHUB_APP_ID="12345", GITHUB_APP_PRIVATE_KEY=keys[0]),
        opener=github.opener,
        sleep=lambda _s: None,
    )
    before = len(github.requests)
    for owner, repo in (("..", ".."), ("acme", ".."), (".", "x")):
        with pytest.raises(ValueError):
            client.get_repository_installation(owner, repo)
        with pytest.raises(ValueError):
            client.get_repository(token="t", owner=owner, repo=repo)
    assert len(github.requests) == before


def test_slashes_in_a_ref_cannot_add_path_segments(keys) -> None:
    github = FakeGitHubApp(public_key_pem=keys[1])
    urls: list[str] = []

    def opener(request, *args, **kwargs):
        urls.append(request.full_url)
        return github.opener(request, *args, **kwargs)

    client = GitHubAppClient(
        GitHubAppSettings(GITHUB_APP_ID="12345", GITHUB_APP_PRIVATE_KEY=keys[0]),
        opener=opener,
        sleep=lambda _s: None,
    )
    try:
        client.list_check_runs_for_ref(
            token="t", owner="acme", repo="widgets", ref="a/b", check_name="Radius"
        )
    except Exception:  # noqa: BLE001 - the fake may 404; only the requested URL matters
        pass
    assert urls, "the request should have reached the transport"
    assert all("/commits/a/b/" not in url for url in urls)
    assert any("/commits/a%2Fb/check-runs" in url for url in urls)
