"""Parser response DTOs."""

from dataclasses import dataclass

from radius_parser.domain.entities import ParsedSourceFile, RepositoryParseResult


@dataclass(frozen=True, slots=True)
class SourceFileResponse:
    """Source file response DTO."""

    path: str
    language: str
    checksum: str


@dataclass(frozen=True, slots=True)
class ParsedSourceFileResponse:
    """Parsed source file response DTO."""

    path: str
    language: str
    checksum: str
    symbols: tuple[str, ...]
    imports: tuple[str, ...]
    exports: tuple[str, ...]

    @classmethod
    def from_entity(
        cls,
        parsed_file: ParsedSourceFile,
    ) -> "ParsedSourceFileResponse":
        """Create a response DTO from parsed source metadata."""

        source_file = parsed_file.source_file
        return cls(
            path=source_file.path.value,
            language=source_file.language.value,
            checksum=source_file.checksum.value,
            symbols=tuple(symbol.name.value for symbol in parsed_file.symbols),
            imports=tuple(item.source for item in parsed_file.imports),
            exports=tuple(item.name for item in parsed_file.exports),
        )


@dataclass(frozen=True, slots=True)
class RepositoryParseResponse:
    """Repository parser response DTO."""

    repository_path: str
    file_count: int
    parsed_file_count: int
    symbol_count: int
    source_files: tuple[SourceFileResponse, ...]
    parsed_files: tuple[ParsedSourceFileResponse, ...]

    @classmethod
    def from_entity(
        cls,
        result: RepositoryParseResult,
    ) -> "RepositoryParseResponse":
        """Create a response DTO from parser result."""

        return cls(
            repository_path=str(result.repository_path),
            file_count=result.file_count,
            parsed_file_count=len(result.parsed_files),
            symbol_count=result.symbol_count,
            source_files=tuple(
                SourceFileResponse(
                    path=source_file.path.value,
                    language=source_file.language.value,
                    checksum=source_file.checksum.value,
                )
                for source_file in result.source_files
            ),
            parsed_files=tuple(
                ParsedSourceFileResponse.from_entity(parsed_file)
                for parsed_file in result.parsed_files
            ),
        )
