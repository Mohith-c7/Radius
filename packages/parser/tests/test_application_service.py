"""Parser application service tests."""

from pathlib import Path

import pytest
from radius_parser.application import ParserApplicationService
from radius_parser.domain import (
    FileChecksum,
    ImportReference,
    ParsedSourceFile,
    SourceFile,
    SourceLanguage,
    SourceLocation,
    SourcePath,
    Symbol,
    SymbolName,
    SymbolType,
    SymbolVisibility,
)
from radius_parser.dto import ParseRepositoryCommand
from radius_shared.errors import ValidationError


class FakeDiscovery:
    """Returns a fixed discovered source file list."""

    def __init__(self, source_files: list[SourceFile]) -> None:
        self.source_files = source_files

    def discover(self, repository_path: Path) -> list[SourceFile]:
        return self.source_files


class FakePythonParser:
    """Returns deterministic parser output for Python files."""

    supported_language = SourceLanguage.PYTHON

    def parse(self, source_file: SourceFile) -> ParsedSourceFile:
        return ParsedSourceFile(
            source_file=source_file,
            symbols=(
                Symbol(
                    name=SymbolName("main"),
                    symbol_type=SymbolType.FUNCTION,
                    visibility=SymbolVisibility.PUBLIC,
                    location=SourceLocation(start_line=1),
                ),
            ),
            imports=(ImportReference(source="os"),),
        )


class FakeRegistry:
    """Registry that returns a Python parser only."""

    def __init__(self) -> None:
        self.parser = FakePythonParser()

    def get_parser(self, language: SourceLanguage):
        if language == SourceLanguage.PYTHON:
            return self.parser
        return None


def test_parse_repository_discovers_and_parses_supported_files(tmp_path: Path) -> None:
    source_files = [
        _source_file("src/app.py", SourceLanguage.PYTHON),
        _source_file("README.md", SourceLanguage.MARKDOWN),
    ]
    service = ParserApplicationService(FakeDiscovery(source_files), FakeRegistry())

    response = service.parse_repository(ParseRepositoryCommand(tmp_path))

    assert response.file_count == 2
    assert response.parsed_file_count == 1
    assert response.symbol_count == 1
    assert response.parsed_files[0].imports == ("os",)


def test_parse_repository_filters_changed_paths(tmp_path: Path) -> None:
    source_files = [
        _source_file("src/app.py", SourceLanguage.PYTHON),
        _source_file("src/skip.py", SourceLanguage.PYTHON),
    ]
    service = ParserApplicationService(FakeDiscovery(source_files), FakeRegistry())

    response = service.parse_repository(
        ParseRepositoryCommand(
            repository_path=tmp_path,
            changed_paths=("src/app.py",),
        )
    )

    assert response.file_count == 1
    assert response.source_files[0].path == "src/app.py"


def test_parse_repository_rejects_missing_repository_path() -> None:
    service = ParserApplicationService(FakeDiscovery([]), FakeRegistry())

    with pytest.raises(ValidationError):
        service.parse_repository(ParseRepositoryCommand(Path("missing-repo")))


def _source_file(path: str, language: SourceLanguage) -> SourceFile:
    return SourceFile(
        path=SourcePath(path),
        language=language,
        checksum=FileChecksum("a" * 64),
    )
