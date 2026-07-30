"""Python AST parser tests."""

from pathlib import Path

from radius_parser.domain import (
    FileChecksum,
    SourceFile,
    SourceLanguage,
    SourcePath,
    SymbolType,
)
from radius_parser.infrastructure import PythonAstParser


def test_python_ast_parser_extracts_imports_symbols_methods_and_exports(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "src" / "service.py"
    source_path.parent.mkdir()
    source_path.write_text(
        "\n".join(
            (
                "import os",
                "from .core import calculate",
                "__all__ = ['Service', 'run']",
                "class Service:",
                "    def execute(self):",
                "        return calculate()",
                "def run():",
                "    return Service().execute()",
                "def _helper():",
                "    return os.getcwd()",
            )
        ),
        encoding="utf-8",
    )

    parsed = PythonAstParser().parse(_source_file(source_path))

    assert [item.source for item in parsed.imports] == ["os", ".core"]
    assert [(symbol.name.value, symbol.symbol_type) for symbol in parsed.symbols] == [
        ("Service", SymbolType.CLASS),
        ("Service.execute", SymbolType.METHOD),
        ("run", SymbolType.FUNCTION),
        ("_helper", SymbolType.FUNCTION),
    ]
    assert [item.name for item in parsed.exports] == ["Service", "run"]


def test_python_ast_parser_defaults_exports_to_public_top_level_symbols(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "module.py"
    source_path.write_text(
        "class Visible:\n    pass\n\ndef _hidden():\n    pass\n",
        encoding="utf-8",
    )

    parsed = PythonAstParser().parse(_source_file(source_path))

    assert [item.name for item in parsed.exports] == ["Visible"]


def _source_file(path: Path) -> SourceFile:
    return SourceFile(
        path=SourcePath(path.name),
        language=SourceLanguage.PYTHON,
        checksum=FileChecksum("a" * 64),
        absolute_path=path,
    )
