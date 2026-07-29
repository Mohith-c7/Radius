"""JavaScript and TypeScript parser tests."""

from pathlib import Path

from radius_parser.domain import FileChecksum, SourceFile, SourceLanguage, SourcePath
from radius_parser.infrastructure import JavaScriptParser, TypeScriptParser


def test_typescript_parser_extracts_imports_symbols_and_exports(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "service.ts"
    source_path.write_text(
        "\n".join(
            (
                "import type { User } from './types';",
                "import { calculate } from './core';",
                "export class Service {}",
                "export const run = () => calculate();",
                "const privateHelper = () => null;",
                "export { privateHelper as helper };",
            )
        ),
        encoding="utf-8",
    )

    parsed = TypeScriptParser().parse(
        _source_file(source_path, SourceLanguage.TYPESCRIPT)
    )

    assert [item.source for item in parsed.imports] == ["./types", "./core"]
    assert [symbol.name.value for symbol in parsed.symbols] == [
        "Service",
        "run",
        "privateHelper",
    ]
    assert [item.name for item in parsed.exports] == [
        "Service",
        "privateHelper",
        "run",
    ]


def test_javascript_parser_extracts_require_and_function_exports(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "index.js"
    source_path.write_text(
        "const core = require('./core');\nexport function handler() {}\n",
        encoding="utf-8",
    )

    parsed = JavaScriptParser().parse(
        _source_file(source_path, SourceLanguage.JAVASCRIPT)
    )

    assert [item.source for item in parsed.imports] == ["./core"]
    assert [symbol.name.value for symbol in parsed.symbols] == ["handler"]
    assert [item.name for item in parsed.exports] == ["handler"]


def _source_file(path: Path, language: SourceLanguage) -> SourceFile:
    return SourceFile(
        path=SourcePath(path.name),
        language=language,
        checksum=FileChecksum("a" * 64),
        absolute_path=path,
    )
