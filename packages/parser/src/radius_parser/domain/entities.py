"""Parser domain entities."""

from dataclasses import dataclass, field
from pathlib import Path

from radius_parser.domain.enums import (
    SourceLanguage,
    SymbolType,
    SymbolVisibility,
)
from radius_parser.domain.value_objects import (
    FileChecksum,
    SourceLocation,
    SourcePath,
    SymbolName,
)


@dataclass(frozen=True, slots=True)
class SourceFile:
    """Discovered source file metadata."""

    path: SourcePath
    language: SourceLanguage
    checksum: FileChecksum
    absolute_path: Path | None = None


@dataclass(frozen=True, slots=True)
class Symbol:
    """Normalized source symbol."""

    name: SymbolName
    symbol_type: SymbolType
    visibility: SymbolVisibility
    location: SourceLocation


@dataclass(frozen=True, slots=True)
class ImportReference:
    """Normalized import reference."""

    source: str
    location: SourceLocation | None = None

    def __post_init__(self) -> None:
        if not self.source.strip():
            msg = "Import source cannot be empty."
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ExportReference:
    """Normalized export reference."""

    name: str
    location: SourceLocation | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            msg = "Export name cannot be empty."
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ParsedSourceFile:
    """Normalized parser output for one source file."""

    source_file: SourceFile
    symbols: tuple[Symbol, ...] = ()
    imports: tuple[ImportReference, ...] = ()
    exports: tuple[ExportReference, ...] = ()


@dataclass(frozen=True, slots=True)
class RepositoryParseResult:
    """Normalized parser output for a repository snapshot."""

    repository_path: Path
    source_files: tuple[SourceFile, ...]
    parsed_files: tuple[ParsedSourceFile, ...] = field(default_factory=tuple)

    @property
    def file_count(self) -> int:
        """Return discovered source file count."""

        return len(self.source_files)

    @property
    def symbol_count(self) -> int:
        """Return extracted symbol count."""

        return sum(len(parsed.symbols) for parsed in self.parsed_files)
