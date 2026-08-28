"""Local Git repository client interfaces."""

from pathlib import Path
from typing import Protocol


class GitRepositoryClient(Protocol):
    """Local Git operations required by Radius."""

    def clone_or_fetch(
        self,
        clone_url: str,
        destination: Path,
        *,
        extra_headers: tuple[str, ...] = (),
    ) -> Path:
        """Clone a repository or fetch updates if it already exists."""

    def checkout(self, repository_path: Path, branch_name: str) -> None:
        """Checkout a branch in a local repository."""
