"""Git change analyzer interfaces."""

from pathlib import Path
from typing import Protocol

from radius_analysis.dto.commands import ChangedFileInput


class GitChangeAnalyzer(Protocol):
    """Contract for deterministic git diff analysis."""

    def analyze_diff(self, diff_text: str) -> tuple[ChangedFileInput, ...]:
        """Parse raw diff text into changed-file input records."""


class GitDiffProvider(Protocol):
    """Contract for retrieving raw git diff text."""

    def get_diff(self, repository_path: Path, base_ref: str, head_ref: str) -> str:
        """Return raw diff text for a repository ref range."""
