"""JS/TS tree-sitter parser behaviour on the fixture monorepo (F-09)."""

from pathlib import Path

import pytest
from radius_parser.application.services import ParserApplicationService
from radius_parser.domain import SourceLanguage, SymbolType, SymbolVisibility
from radius_parser.dto.commands import ParseRepositoryCommand
from radius_parser.infrastructure import (
    FilesystemSourceDiscovery,
    default_language_parser_registry,
)
from radius_parser.infrastructure.parser_registry import EXPERIMENTAL_LANGUAGES

FIXTURE = Path(__file__).parent / "fixtures" / "ts_monorepo"


def _service() -> ParserApplicationService:
    return ParserApplicationService(
        FilesystemSourceDiscovery(), default_language_parser_registry()
    )


@pytest.fixture(scope="module")
def result():
    return _service().parse_repository_result(ParseRepositoryCommand(FIXTURE))


def _parsed(result, path: str):
    for item in result.parsed_files:
        if item.source_file.path.value == path:
            return item
    raise AssertionError(f"{path} was not parsed")


def test_all_js_ts_suffixes_are_discovered(result) -> None:
    languages = {item.path.value: item.language for item in result.source_files}

    assert languages["apps/web/src/esm.mjs"] == SourceLanguage.JAVASCRIPT
    assert languages["apps/web/src/legacy.cjs"] == SourceLanguage.JAVASCRIPT
    assert languages["apps/web/src/main.tsx"] == SourceLanguage.TYPESCRIPT
    assert languages["apps/web/src/types.d.ts"] == SourceLanguage.TYPESCRIPT


def test_syntax_error_file_is_a_parse_failure_not_a_crash(result) -> None:
    assert result.parse_failures == ("apps/web/src/broken.ts",)
    assert "apps/web/src/main.tsx" in {
        item.source_file.path.value for item in result.parsed_files
    }


def test_tsx_imports_static_dynamic_require_and_type_only(result) -> None:
    sources = [i.source for i in _parsed(result, "apps/web/src/main.tsx").imports]

    assert sources == [
        "react",
        "./types",  # type-only import
        "@/components/Button",
        "@shared/util",
        "./lib",
        "@/lazy",  # dynamic import() with literal
        "./legacy.cjs",  # require() with literal
    ]


def test_barrel_reexports_are_imports_and_exports(result) -> None:
    barrel = _parsed(result, "apps/web/src/lib/index.ts")

    assert [i.source for i in barrel.imports] == ["./a", "./b"]
    assert [e.name for e in barrel.exports] == ["b"]


def test_tsx_symbols_have_line_ranges_and_exports(result) -> None:
    main = _parsed(result, "apps/web/src/main.tsx")
    symbols = {s.name.value: s for s in main.symbols}

    assert symbols["boot"].symbol_type == SymbolType.FUNCTION
    assert symbols["App"].symbol_type == SymbolType.FUNCTION  # arrow-function const
    assert (symbols["boot"].location.start_line, symbols["boot"].location.end_line) == (
        7,
        11,
    )
    assert [e.name for e in main.exports] == ["App", "boot"]


def test_mjs_and_cjs_are_parsed_with_the_javascript_grammar(result) -> None:
    esm = _parsed(result, "apps/web/src/esm.mjs")

    assert [i.source for i in esm.imports] == ["@shared/util"]
    assert [s.name.value for s in esm.symbols] == ["run"]
    assert _parsed(result, "apps/web/src/legacy.cjs").imports == ()


def test_declaration_forms(tmp_path: Path) -> None:
    (tmp_path / "forms.ts").write_text(
        "\n".join(
            (
                "export interface Shape { area(): number }",
                "export type Id = string | number;",
                "export enum Color { Red, Green }",
                "export abstract class Base {",
                "  abstract run(): void;",
                "  static make() { return 1; }",
                "  handler = () => 2;",
                "}",
                "export default class extends Base { run() {} }",
                "function helper(a: number): number;",
                "function helper(a: string): string;",
                "function helper(a: any) { return a; }",
                "const _hidden = function () {};",
                "namespace Util { export const x = 1; }",
            )
        ),
        encoding="utf-8",
    )
    parsed = _service().parse_repository_result(ParseRepositoryCommand(tmp_path))
    symbols = {s.name.value: s for s in parsed.parsed_files[0].symbols}

    assert symbols["Shape"].symbol_type == SymbolType.INTERFACE
    assert symbols["Id"].symbol_type == SymbolType.TYPE_ALIAS
    assert symbols["Color"].symbol_type == SymbolType.ENUM
    assert symbols["Base"].symbol_type == SymbolType.CLASS
    assert symbols["Base.run"].symbol_type == SymbolType.METHOD
    assert symbols["Base.make"].symbol_type == SymbolType.METHOD
    assert symbols["Base.handler"].symbol_type == SymbolType.METHOD
    assert symbols["default"].symbol_type == SymbolType.CLASS
    assert symbols["Util"].symbol_type == SymbolType.NAMESPACE
    # overload signatures collapse into the implementation's range
    assert symbols["helper"].location.start_line == 12
    # non-exported symbols are private once the module has explicit exports
    assert symbols["helper"].visibility == SymbolVisibility.PRIVATE
    assert symbols["_hidden"].visibility == SymbolVisibility.PRIVATE
    assert symbols["Shape"].visibility == SymbolVisibility.PUBLIC


def test_go_java_rust_parsers_are_flagged_experimental() -> None:
    registry = default_language_parser_registry()

    for language in (SourceLanguage.GO, SourceLanguage.JAVA, SourceLanguage.RUST):
        assert language in EXPERIMENTAL_LANGUAGES
        assert registry.is_experimental(language)
    for language in (
        SourceLanguage.PYTHON,
        SourceLanguage.TYPESCRIPT,
        SourceLanguage.JAVASCRIPT,
    ):
        assert not registry.is_experimental(language)


def test_experimental_languages_are_reported_on_the_result(
    tmp_path: Path, caplog
) -> None:
    (tmp_path / "main.go").write_text("package main\nfunc Run() {}\n", encoding="utf-8")

    with caplog.at_level("WARNING"):
        parsed = _service().parse_repository_result(ParseRepositoryCommand(tmp_path))

    assert parsed.experimental_languages == ("go",)
    assert "Experimental parsers" in caplog.text


def test_regex_parser_is_not_on_the_default_path(monkeypatch) -> None:
    from radius_parser.infrastructure import ecmascript_parser

    def boom(*_args, **_kwargs):
        raise AssertionError("regex fallback used on the default path")

    monkeypatch.setattr(ecmascript_parser, "regex_import_fallback", boom)
    parsed = _service().parse_repository_result(ParseRepositoryCommand(FIXTURE))

    assert len(parsed.parsed_files) > 5
