"""Subprocess-backed local Git repository client."""

from __future__ import annotations

import subprocess
from pathlib import Path

from radius_shared.errors import ValidationError


class LocalGitRepositoryClient:
    """Clone, fetch, and checkout repositories using the Git CLI."""

    def clone_or_fetch(self, clone_url: str, destination: Path) -> Path:
        """Clone a repository or fetch updates when it already exists."""

        if destination.exists():
            if not (destination / ".git").exists():
                msg = f"Destination is not a Git repository: {destination}."
                raise ValidationError(msg)
            self._run(("git", "fetch", "--all", "--prune"), cwd=destination)
            return destination

        destination.parent.mkdir(parents=True, exist_ok=True)
        self._run(("git", "clone", clone_url, str(destination)), cwd=None)
        return destination

    def checkout(self, repository_path: Path, branch_name: str) -> None:
        """Checkout a branch or ref in a local repository."""

        if not (repository_path / ".git").exists():
            msg = f"Repository path is not a Git checkout: {repository_path}."
            raise ValidationError(msg)
        self._run(("git", "checkout", branch_name), cwd=repository_path)

    @staticmethod
    def _run(command: tuple[str, ...], cwd: Path | None) -> None:
        try:
            subprocess.run(
                command,
                cwd=cwd,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            message = exc.stderr.strip() or exc.stdout.strip() or str(exc)
            raise ValidationError(message) from exc
