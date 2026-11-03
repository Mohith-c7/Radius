"""A-01/A-02: clone URLs are untrusted; git must never be tricked by them."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from radius_repository.domain.clone_url import (
    GitUrlPolicy,
    clone_url_matches,
    parse_allowed_hosts,
    validate_clone_url,
)
from radius_repository.infrastructure import local_git
from radius_repository.infrastructure.local_git import LocalGitRepositoryClient
from radius_shared.errors import ValidationError

GOOD = [
    ("https://github.com/acme/radius.git", "https://github.com/acme/radius.git"),
    ("https://github.com/acme/radius", "https://github.com/acme/radius.git"),
    ("https://GitHub.com/Acme/Rad.ius", "https://github.com/Acme/Rad.ius.git"),
    ("https://github.com:443/acme/radius.git", "https://github.com/acme/radius.git"),
]

BAD = [
    "--upload-pack=touch pwned",
    "--upload-pack=sh -c 'echo x'",
    "-c core.sshCommand=evil",
    " https://github.com/acme/radius.git",
    "https://github.com/acme/radius.git ",
    "https://github.com/acme/radius.git\n--upload-pack=x",
    "https://github.com/acme/ra dius.git",
    "https://github.com/acme/radius.git\x00",
    "file:///etc/passwd",
    "file://localhost/tmp/x",
    "/var/lib/radius/cache/other/repo-1",
    "../other/repo",
    "C:\\repos\\victim",
    "ext::sh -c 'touch pwned'",
    "git@github.com:acme/radius.git",
    "ssh://git@github.com/acme/radius.git",
    "git://github.com/acme/radius.git",
    "http://github.com/acme/radius.git",
    "ftp://github.com/acme/radius.git",
    "https://user:pw@github.com/acme/radius.git",
    "https://user@github.com/acme/radius.git",
    "https://github.com@evil.example/acme/radius.git",
    "https://evil.example/acme/radius.git",
    "https://github.com.evil.example/acme/radius.git",
    "https://evil.example\\@github.com/acme/radius.git",
    "https://github.com:8443/acme/radius.git",
    "https://github.com/acme/radius.git?x=1",
    "https://github.com/acme/radius.git#frag",
    "https://github.com/acme",
    "https://github.com/acme/radius/extra.git",
    "https://github.com//acme/radius.git",
    "https://github.com/./radius.git",
    "https://github.com/../radius.git",
    "https://github.com/acme/..",
    "https://github.com/acme/.",
    "https://github.com/acme/.git",
    "https://github.com/ac%6de/radius.git",
    "https://github.com/acme/" + "a" * 400,
    "",
    "   ",
]


@pytest.mark.parametrize(("raw", "canonical"), GOOD)
def test_valid_urls_are_canonicalised(raw: str, canonical: str) -> None:
    assert validate_clone_url(raw) == canonical


@pytest.mark.parametrize("raw", BAD)
def test_hostile_or_malformed_urls_are_refused(raw: str) -> None:
    with pytest.raises(ValidationError):
        validate_clone_url(raw)


@pytest.mark.parametrize("raw", [None, 5, ["https://github.com/a/b"], b"https://github.com/a/b"])
def test_non_strings_are_refused(raw: object) -> None:
    with pytest.raises(ValidationError):
        validate_clone_url(raw)


def test_enterprise_host_needs_an_explicit_setting() -> None:
    url = "https://ghe.example.com/acme/radius.git"
    with pytest.raises(ValidationError):
        validate_clone_url(url)
    policy = GitUrlPolicy(allowed_hosts=parse_allowed_hosts("ghe.example.com"))
    assert validate_clone_url(url, policy=policy) == url
    # Configuring GHES replaces the default: github.com is no longer trusted.
    with pytest.raises(ValidationError):
        validate_clone_url("https://github.com/a/b.git", policy=policy)


def test_parse_allowed_hosts() -> None:
    assert parse_allowed_hosts("") == ("github.com",)
    assert parse_allowed_hosts(None) == ("github.com",)
    assert parse_allowed_hosts(" GitHub.com , ghe.example.com.") == (
        "github.com",
        "ghe.example.com",
    )
    with pytest.raises(ValueError):
        parse_allowed_hosts("evil host")
    with pytest.raises(ValueError):
        parse_allowed_hosts("-oProxyCommand=x")


def test_clone_url_matches_identity() -> None:
    assert clone_url_matches("https://github.com/Acme/Radius.git", "acme", "radius")
    assert not clone_url_matches("https://github.com/acme/other.git", "acme", "radius")


# --- git itself -------------------------------------------------------------


def _git_available() -> bool:
    try:
        subprocess.run(("git", "--version"), check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


pytestmark_git = pytest.mark.skipif(not _git_available(), reason="git is required")


@pytestmark_git
def test_repro_unpatched_git_clone_runs_upload_pack_option(tmp_path: Path) -> None:
    """Demonstrates the A-01 primitive on this machine: an option-shaped URL
    given to a bare ``git clone <url> <dest>`` runs a command. It documents why
    the client must validate and use ``--``; it does not call Radius code."""

    marker = tmp_path / "unpatched-marker"
    helper = tmp_path / "helper.py"
    helper.write_text(f"open({str(marker)!r}, 'w').write('ran')\n", encoding="utf-8")
    payload = f"--upload-pack={Path(sys.executable).as_posix()} {helper.as_posix()}"
    subprocess.run(
        ("git", "clone", payload, str(tmp_path / "out")),
        capture_output=True,
        text=True,
        check=False,
    )
    if not marker.exists():
        # Newer git versions refuse option-shaped URLs, so the unpatched primitive does not reproduce
        # there. That is not a failure of Radius: the client still validates and uses `--`.
        pytest.skip("this git version does not run --upload-pack for an option-shaped URL")


@pytestmark_git
def test_client_refuses_upload_pack_payload_and_runs_nothing(tmp_path: Path) -> None:
    marker = tmp_path / "client-marker"
    helper = tmp_path / "helper.py"
    helper.write_text(f"open({str(marker)!r}, 'w').write('ran')\n", encoding="utf-8")
    payload = f"--upload-pack={Path(sys.executable).as_posix()} {helper.as_posix()}"
    with pytest.raises(ValidationError):
        LocalGitRepositoryClient().clone_or_fetch(payload, tmp_path / "dest")
    assert not marker.exists()
    assert not (tmp_path / "dest").exists()


@pytestmark_git
def test_defense_in_depth_unvalidated_option_url_is_inert_after_double_dash(
    tmp_path: Path,
) -> None:
    """Even if validation were bypassed, ``--`` makes the value a repository
    path, not an option."""

    marker = tmp_path / "dd-marker"
    helper = tmp_path / "helper.py"
    helper.write_text(f"open({str(marker)!r}, 'w').write('ran')\n", encoding="utf-8")
    payload = f"--upload-pack={Path(sys.executable).as_posix()} {helper.as_posix()}"
    client = LocalGitRepositoryClient()
    with pytest.raises(ValidationError):
        client._run(("git", "clone", "--", payload, str(tmp_path / "o2")), cwd=None)
    assert not marker.exists()


@pytestmark_git
def test_defense_in_depth_local_and_file_protocols_are_disabled(tmp_path: Path) -> None:
    """Another tenant's cached checkout (a local path / file:// URL) is not cloneable
    even if a URL slipped past validation."""

    victim = tmp_path / "victim"
    subprocess.run(("git", "init", "-q", str(victim)), check=True)
    (victim / "secret.txt").write_text("tenant-b", encoding="utf-8")
    subprocess.run(("git", "-C", str(victim), "add", "."), check=True)
    subprocess.run(
        (
            "git",
            "-C",
            str(victim),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.com",
            "commit",
            "-qm",
            "x",
        ),
        check=True,
    )
    client = LocalGitRepositoryClient()
    for index, url in enumerate((str(victim), victim.as_uri())):
        dest = tmp_path / f"clone{index}"
        with pytest.raises(ValidationError):
            client._run(("git", "clone", "--", url, str(dest)), cwd=None)
        assert not (dest / "secret.txt").exists()
    # Sanity: plain git (no hardening) does clone it, so the refusal is ours.
    plain = tmp_path / "plain"
    subprocess.run(("git", "clone", "-q", str(victim), str(plain)), check=True)
    assert (plain / "secret.txt").exists()


@pytestmark_git
def test_defense_in_depth_ext_transport_is_disabled(tmp_path: Path) -> None:
    marker = tmp_path / "ext-marker"
    helper = tmp_path / "helper.py"
    helper.write_text(f"open({str(marker)!r}, 'w').write('ran')\n", encoding="utf-8")
    url = f"ext::{Path(sys.executable).as_posix()} {helper.as_posix()}"
    with pytest.raises(ValidationError):
        LocalGitRepositoryClient()._run(
            ("git", "clone", "--", url, str(tmp_path / "o3")), cwd=None
        )
    assert not marker.exists()


def test_clone_argv_has_double_dash_and_hardening(monkeypatch, tmp_path: Path) -> None:
    captured: dict = {}

    def fake_run(command, **kwargs):
        captured["command"] = list(command)
        captured["env"] = kwargs["env"]
        captured["shell"] = kwargs.get("shell")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(local_git.subprocess, "run", fake_run)
    LocalGitRepositoryClient().clone_or_fetch(
        "https://github.com/acme/radius", tmp_path / "dest"
    )
    command = captured["command"]
    assert captured["shell"] is False
    assert command[: command.index("clone")][0] == "git"
    assert "protocol.allow=never" in command
    assert "protocol.https.allow=always" in command
    assert "core.fsmonitor=false" in command
    assert any(part.startswith("core.hooksPath=") for part in command)
    dd = command.index("--")
    assert command[dd + 1] == "https://github.com/acme/radius.git"
    assert command[dd + 2] == str(tmp_path / "dest")
    assert captured["env"]["GIT_ALLOW_PROTOCOL"] == "https"


def test_credentials_never_go_to_an_untrusted_host(tmp_path: Path) -> None:
    header = "Authorization: Basic ZmFrZTpmYWtl"
    with pytest.raises(ValidationError):
        LocalGitRepositoryClient().clone_or_fetch(
            "https://attacker.example/acme/radius.git",
            tmp_path / "dest",
            extra_headers=(header,),
        )
    with pytest.raises(ValidationError):
        local_git._git_environment((header,), "https://attacker.example/x.git")
    with pytest.raises(ValidationError):
        local_git._git_environment((header,), None)


@pytestmark_git
def test_existing_checkout_with_a_poisoned_origin_is_not_fetched(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    subprocess.run(("git", "init", "-q", str(repo)), check=True)
    subprocess.run(
        ("git", "-C", str(repo), "remote", "add", "origin", "https://evil.example/a/b.git"),
        check=True,
    )
    header = "Authorization: Basic ZmFrZTpmYWtl"
    with pytest.raises(ValidationError):
        LocalGitRepositoryClient().clone_or_fetch(
            "https://github.com/a/b.git", repo, extra_headers=(header,)
        )
    subprocess.run(
        ("git", "-C", str(repo), "remote", "set-url", "origin", "/some/local/path"),
        check=True,
    )
    with pytest.raises(ValidationError):
        LocalGitRepositoryClient().fetch_ref(repo, "main")


@pytestmark_git
@pytest.mark.parametrize(
    "ref",
    ["-f", "--orphan=x", "--output=/tmp/x", "a b", "a..b", "x;y", "", "refs/heads/x.lock", "a\nb"],
)
def test_checkout_rejects_option_like_or_malformed_refs(tmp_path: Path, ref: str) -> None:
    repo = tmp_path / "repo"
    subprocess.run(("git", "init", "-q", str(repo)), check=True)
    with pytest.raises(ValidationError):
        LocalGitRepositoryClient().checkout(repo, ref)


@pytestmark_git
def test_checkout_detaches_at_a_commit_sha(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    subprocess.run(("git", "init", "-q", str(repo)), check=True)
    ident = ("-c", "user.name=t", "-c", "user.email=t@example.com")
    (repo / "a.txt").write_text("1", encoding="utf-8")
    subprocess.run(("git", "-C", str(repo), "add", "."), check=True)
    subprocess.run(("git", "-C", str(repo), *ident, "commit", "-qm", "one"), check=True)
    first = subprocess.run(
        ("git", "-C", str(repo), "rev-parse", "HEAD"), capture_output=True, text=True, check=True
    ).stdout.strip()
    (repo / "a.txt").write_text("2", encoding="utf-8")
    subprocess.run(("git", "-C", str(repo), *ident, "commit", "-qam", "two"), check=True)
    LocalGitRepositoryClient().checkout(repo, first)
    head = subprocess.run(
        ("git", "-C", str(repo), "rev-parse", "HEAD"), capture_output=True, text=True, check=True
    ).stdout.strip()
    assert head == first
    assert (repo / "a.txt").read_text(encoding="utf-8") == "1"


@pytestmark_git
def test_hooks_in_the_checkout_do_not_run(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    subprocess.run(("git", "init", "-q", str(repo)), check=True)
    ident = ("-c", "user.name=t", "-c", "user.email=t@example.com")
    (repo / "a.txt").write_text("1", encoding="utf-8")
    subprocess.run(("git", "-C", str(repo), "add", "."), check=True)
    subprocess.run(("git", "-C", str(repo), *ident, "commit", "-qm", "one"), check=True)
    sha = subprocess.run(
        ("git", "-C", str(repo), "rev-parse", "HEAD"), capture_output=True, text=True, check=True
    ).stdout.strip()
    marker = tmp_path / "hook-marker"
    hook = repo / ".git" / "hooks" / "post-checkout"
    hook.write_text(
        f"#!{Path(sys.executable).as_posix()}\nopen({str(marker)!r}, 'w').write('ran')\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)
    LocalGitRepositoryClient().checkout(repo, sha)
    assert not marker.exists()
