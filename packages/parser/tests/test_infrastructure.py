"""Parser infrastructure tests."""

from pathlib import Path

from radius_parser.domain import (
    ParsedSourceFile,
    SourceFile,
    SourceLanguage,
)
from radius_parser.infrastructure import (
    FilesystemSourceDiscovery,
    StaticLanguageParserRegistry,
)


class TypeScriptParser:
    """Minimal parser used for registry tests."""

    supported_language = SourceLanguage.TYPESCRIPT

    def parse(self, source_file: SourceFile) -> ParsedSourceFile:
        return ParsedSourceFile(source_file=source_file)


def test_filesystem_source_discovery_detects_languages_and_checksums(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "src" / "app.ts").write_text("export const x = 1;\n", encoding="utf-8")
    (tmp_path / "src" / "notes.txt").write_text("ignore me\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "skip.js").write_text("skip\n", encoding="utf-8")

    files = FilesystemSourceDiscovery().discover(tmp_path)

    assert [(file.path.value, file.language) for file in files] == [
        ("src/app.py", SourceLanguage.PYTHON),
        ("src/app.ts", SourceLanguage.TYPESCRIPT),
    ]
    assert all(len(file.checksum.value) == 64 for file in files)
    assert all(file.absolute_path is not None for file in files)


def test_static_language_parser_registry_returns_registered_parser() -> None:
    parser = TypeScriptParser()
    registry = StaticLanguageParserRegistry((parser,))

    assert registry.get_parser(SourceLanguage.TYPESCRIPT) is parser
    assert registry.get_parser(SourceLanguage.PYTHON) is None
