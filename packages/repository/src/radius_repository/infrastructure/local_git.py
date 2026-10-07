"""Subprocess-backed local Git repository client."""

from __future__ import annotations

import subprocess
from pathlib import Path

from radius_shared.errors import ValidationError


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
    ) -> None:
        git_command = _with_extra_headers(command, extra_headers)
        try:
            subprocess.run(
                git_command,
                cwd=cwd,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            message = exc.stderr.strip() or exc.stdout.strip() or str(exc)
            raise ValidationError(message) from exc


def _with_extra_headers(
    command: tuple[str, ...],
    extra_headers: tuple[str, ...],
) -> tuple[str, ...]:
    if not extra_headers or command[0] != "git":
        return command
    options = tuple(
        item
        for header in extra_headers
        for item in ("-c", f"http.extraHeader={header}")
    )
    return ("git", *options, *command[1:])
