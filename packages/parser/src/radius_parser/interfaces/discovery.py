"""Source discovery interfaces."""

from pathlib import Path
from typing import Protocol

from radius_parser.domain.entities import SourceFile


class SourceDiscovery(Protocol):
    """Contract for repository source-file discovery."""

    def discover(self, repository_path: Path) -> list[SourceFile]:
        """Return discovered source files for a repository snapshot."""
