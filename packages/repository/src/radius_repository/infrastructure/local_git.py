"""Subprocess-backed local Git repository client."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from radius_shared.errors import ValidationError
from radius_shared.redaction import REDACTED, redact_secrets


class LocalGitRepositoryClient:
    """Clone, fetch, and checkout repositories using the Git CLI."""

    def clone_or_fetch(
        self,
        clone_url: str,
        destination: Path,
        *,
        extra_headers: tuple[str, ...] = (),
    ) -> Path:
        """Clone a repository or fetch updates when it already exists."""

        if destination.exists():
            if not (destination / ".git").exists():
                msg = f"Destination is not a Git repository: {destination}."
                raise ValidationError(msg)
            self._run(
                ("git", "fetch", "--all", "--prune"),
                cwd=destination,
                extra_headers=extra_headers,
            )
            return destination

        destination.parent.mkdir(parents=True, exist_ok=True)
        self._run(
            ("git", "clone", clone_url, str(destination)),
            cwd=None,
            extra_headers=extra_headers,
            remote_url=clone_url,
        )
        return destination

    def checkout(self, repository_path: Path, branch_name: str) -> None:
        """Checkout a branch or ref in a local repository."""

        if not (repository_path / ".git").exists():
            msg = f"Repository path is not a Git checkout: {repository_path}."
            raise ValidationError(msg)
        self._run(("git", "checkout", branch_name), cwd=repository_path)

    def fetch_pull_request(
        self,
        repository_path: Path,
        pr_number: int,
        *,
        extra_headers: tuple[str, ...] = (),
    ) -> None:
        """Fetch PR head ref from origin into refs/remotes/origin/pr/<pr_number>."""

        if not (repository_path / ".git").exists():
            msg = f"Repository path is not a Git checkout: {repository_path}."
            raise ValidationError(msg)
        self._run(
            (
                "git",
                "fetch",
                "origin",
                f"+refs/pull/{pr_number}/head:refs/remotes/origin/pr/{pr_number}",
            ),
            cwd=repository_path,
            extra_headers=extra_headers,
        )

    def fetch_ref(
        self,
        repository_path: Path,
        remote_ref: str,
        *,
        extra_headers: tuple[str, ...] = (),
    ) -> None:
        """Fetch a specific remote ref from origin."""

        if not (repository_path / ".git").exists():
            msg = f"Repository path is not a Git checkout: {repository_path}."
            raise ValidationError(msg)
        self._run(
            ("git", "fetch", "origin", remote_ref),
            cwd=repository_path,
            extra_headers=extra_headers,
        )

    @staticmethod
    def _run(
        command: tuple[str, ...],
        cwd: Path | None,
        *,
        extra_headers: tuple[str, ...] = (),
        remote_url: str | None = None,
    ) -> None:
        """Run git, passing credentials only through the child's environment.

        ``extra_headers`` (e.g. ``Authorization: Basic ...``) are handed to git
        as ``GIT_CONFIG_COUNT/KEY_n/VALUE_n`` environment variables, git's
        documented way to set config for one process. Unlike ``-c`` they never
        appear in the command line (``ps``, process listings, crash reports),
        and unlike ``git config`` / a credential URL they are never written to
        ``.git/config``. The header is scoped to the remote's origin so it is
        not replayed to another host after a redirect.
        """

        if extra_headers and remote_url is None and cwd is not None:
            remote_url = _origin_remote_url(cwd)
        env = _git_environment(extra_headers, remote_url)
        try:
            subprocess.run(
                command,
                cwd=cwd,
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
        except subprocess.CalledProcessError as exc:
            message = exc.stderr.strip() or exc.stdout.strip() or str(exc)
            raise ValidationError(_scrub(message, extra_headers)) from exc


def _origin_remote_url(repository_path: Path) -> str | None:
    try:
        result = subprocess.run(
            ("git", "config", "--get", "remote.origin.url"),
            cwd=repository_path,
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return None
    return result.stdout.strip() or None


def _header_scope(remote_url: str | None) -> str:
    """Return the git config subsection for the remote's origin, or ``""``."""

    if remote_url:
        parts = urlsplit(remote_url)
        if parts.scheme in {"http", "https"} and parts.netloc:
            host = parts.netloc.rpartition("@")[2]
            return f"{parts.scheme}://{host}/"
    return ""


def _git_environment(
    extra_headers: tuple[str, ...],
    remote_url: str | None,
) -> dict[str, str] | None:
    """Child environment carrying the headers as per-process git config."""

    if not extra_headers:
        return None
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    scope = _header_scope(remote_url)
    key = f"http.{scope}.extraHeader" if scope else "http.extraHeader"
    try:
        count = int(env.get("GIT_CONFIG_COUNT", "0"))
    except ValueError:
        count = 0
    for header in extra_headers:
        env[f"GIT_CONFIG_KEY_{count}"] = key
        env[f"GIT_CONFIG_VALUE_{count}"] = header
        count += 1
    env["GIT_CONFIG_COUNT"] = str(count)
    return env


def _scrub(message: str, extra_headers: tuple[str, ...]) -> str:
    """Remove the credential (and its encodings) from git's error output."""

    for header in extra_headers:
        value = header.partition(":")[2].strip()
        for secret in {header, value, value.rpartition(" ")[2]}:
            if len(secret) >= 8:
                message = message.replace(secret, REDACTED)
    return redact_secrets(message.rstrip())
