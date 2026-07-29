"""Parser application command DTOs."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ParseRepositoryCommand:
    """Command to parse a local repository snapshot."""

    repository_path: Path
    changed_paths: tuple[str, ...] | None = None
