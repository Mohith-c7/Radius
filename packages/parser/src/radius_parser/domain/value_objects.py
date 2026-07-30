"""Parser domain value objects."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourcePath:
    """Repository-relative source path."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            msg = "Source path cannot be empty."
            raise ValueError(msg)
        if self.value.startswith(("/", "\\")):
            msg = "Source path must be repository-relative."
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class FileChecksum:
    """Stable checksum for a discovered source file."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            msg = "File checksum cannot be empty."
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class SymbolName:
    """Normalized source symbol name."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            msg = "Symbol name cannot be empty."
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """Line/column range for a source construct."""

    start_line: int
    start_column: int = 1
    end_line: int | None = None
    end_column: int | None = None

    def __post_init__(self) -> None:
        if self.start_line < 1:
            msg = "Source location start line must be positive."
            raise ValueError(msg)
        if self.start_column < 1:
            msg = "Source location start column must be positive."
            raise ValueError(msg)
        if self.end_line is not None and self.end_line < self.start_line:
            msg = "Source location end line cannot precede start line."
            raise ValueError(msg)
