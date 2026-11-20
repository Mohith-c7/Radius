"""Subprocess-backed git diff provider."""

import subprocess
from pathlib import Path

from radius_shared.errors import ValidationError


class SubprocessGitDiffProvider:
    """Return git diff text for local repository refs."""

    def get_diff(self, repository_path: Path, base_ref: str, head_ref: str) -> str:
        """Return raw unified diff text for a repository ref range."""

        if not repository_path.exists() or not repository_path.is_dir():
            msg = f"Repository path does not exist: {repository_path}."
            raise ValidationError(msg)

        result = subprocess.run(
            [
                "git",
                "diff",
                "--find-renames",
                "--find-copies",
                f"{base_ref}...{head_ref}",
            ],
            cwd=repository_path,
            capture_output=True,
            check=False,
            text=True,
        )
        if result.returncode != 0 and base_ref.startswith("origin/"):
            fallback_base = base_ref.removeprefix("origin/")
            result = subprocess.run(
                [
                    "git",
                    "diff",
                    "--find-renames",
                    "--find-copies",
                    f"{fallback_base}...{head_ref}",
                ],
                cwd=repository_path,
                capture_output=True,
                check=False,
                text=True,
            )
        if result.returncode != 0:
            msg = result.stderr.strip() or "Unable to collect git diff."
            raise ValidationError(msg)
        return result.stdout

    def get_parent_ref(self, repository_path: Path, head_ref: str) -> str | None:
        """Resolve a head and its parent without treating git failures as empty diffs."""
        if not repository_path.exists() or not repository_path.is_dir():
            msg = f"Repository path does not exist: {repository_path}."
            raise ValidationError(msg)
        result = subprocess.run(
            ["git", "rev-parse", "--verify", f"{head_ref}^{{commit}}"],
            cwd=repository_path,
            capture_output=True,
            check=False,
            text=True,
        )
        if result.returncode != 0:
            raise ValidationError(result.stderr.strip() or "Unable to resolve head commit.")
        commit = result.stdout.strip()
        parent = subprocess.run(
            ["git", "cat-file", "-p", commit],
            cwd=repository_path,
            capture_output=True,
            check=False,
            text=True,
        )
        if parent.returncode != 0:
            raise ValidationError(parent.stderr.strip() or "Unable to inspect head commit.")
        for line in parent.stdout.splitlines():
            if line.startswith("parent "):
                return line.removeprefix("parent ").strip()
        return None
