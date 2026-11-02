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
    names: tuple[str, ...] = ()
    """Names imported from ``source`` (e.g. ``from pkg import a, b``).

    Used to resolve ``from package import submodule`` to the submodule file.
    """

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
    parse_failures: tuple[str, ...] = field(default_factory=tuple)
    """Repository-relative paths of files that could not be parsed.

    A failure degrades the dependency graph; it must be surfaced as missing
    evidence rather than aborting the analysis or being silently ignored.
    """

    experimental_languages: tuple[str, ...] = field(default_factory=tuple)
    """Languages parsed by experimental parsers in this run (Go/Java/Rust).

    Their imports are not resolved to files, so the graph is incomplete for
    them; consumers should treat that as reduced evidence.
    """

    @property
    def file_count(self) -> int:
        """Return discovered source file count."""

        return len(self.source_files)

    @property
    def symbol_count(self) -> int:
        """Return extracted symbol count."""

        return sum(len(parsed.symbols) for parsed in self.parsed_files)
