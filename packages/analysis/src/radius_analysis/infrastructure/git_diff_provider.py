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
        if not result.stdout.strip():
            merged_diff = self._diff_of_merged_head(repository_path, base_ref, head_ref)
            if merged_diff is not None:
                return merged_diff
        return result.stdout

    def _diff_of_merged_head(
        self, repository_path: Path, base_ref: str, head_ref: str
    ) -> str | None:
        """Diff a head that is already merged into base (merge-commit merges).

        Once a pull request is merged with a merge commit, its head is an
        ancestor of the base branch, so ``base...head`` is empty. The changes the
        pull request introduced are the head compared with the first parent of
        the merge commit that brought it in (the base branch just before merging).
        """

        for base in (base_ref, base_ref.removeprefix("origin/")):
            merges = subprocess.run(
                ["git", "rev-list", "--ancestry-path", "--merges", "--reverse", f"{head_ref}..{base}"],
                cwd=repository_path,
                capture_output=True,
                check=False,
                text=True,
            )
            if merges.returncode != 0:
                continue
            for merge in merges.stdout.split():
                parents = subprocess.run(
                    ["git", "rev-list", "--parents", "-n", "1", merge],
                    cwd=repository_path,
                    capture_output=True,
                    check=False,
                    text=True,
                ).stdout.split()
                # parents = [merge, first_parent, second_parent, ...]; the merge
                # that brought head in has head reachable from a non-first parent.
                if len(parents) < 3:
                    continue
                diff = subprocess.run(
                    ["git", "diff", "--find-renames", "--find-copies", f"{parents[1]}...{head_ref}"],
                    cwd=repository_path,
                    capture_output=True,
                    check=False,
                    text=True,
                )
                if diff.returncode == 0 and diff.stdout.strip():
                    return diff.stdout
            return None
        return None
