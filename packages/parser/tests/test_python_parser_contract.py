"""Parity: the Python parser output contract is unchanged by F-09."""

from pathlib import Path

from radius_parser.application.services import ParserApplicationService
from radius_parser.domain import SymbolType, SymbolVisibility
from radius_parser.dto.commands import ParseRepositoryCommand
from radius_parser.infrastructure import (
    FilesystemSourceDiscovery,
    default_language_parser_registry,
)

SOURCE = '''\
import os
from . import sibling
from pkg.mod import a, b

__all__ = ["Service"]


class Service:
    def run(self):
        import json
        return json

    async def _private(self):
        pass


def helper():
    pass
'''


def test_python_contract_is_stable(tmp_path: Path) -> None:
    (tmp_path / "svc.py").write_text(SOURCE, encoding="utf-8")
    (tmp_path / "bad.py").write_text("def broken(:\n", encoding="utf-8")
    service = ParserApplicationService(
        FilesystemSourceDiscovery(), default_language_parser_registry()
    )

    result = service.parse_repository_result(ParseRepositoryCommand(tmp_path))
    parsed = next(p for p in result.parsed_files if p.source_file.path.value == "svc.py")

    assert result.parse_failures == ("bad.py",)
    assert result.experimental_languages == ()
    assert sorted((i.source, i.names) for i in parsed.imports) == [
        (".", ("sibling",)),
        ("json", ()),
        ("os", ()),
        ("pkg.mod", ("a", "b")),
    ]
    assert [(s.name.value, s.symbol_type, s.visibility) for s in parsed.symbols] == [
        ("Service", SymbolType.CLASS, SymbolVisibility.PUBLIC),
        ("Service.run", SymbolType.METHOD, SymbolVisibility.PUBLIC),
        ("Service._private", SymbolType.METHOD, SymbolVisibility.PRIVATE),
        ("helper", SymbolType.FUNCTION, SymbolVisibility.PUBLIC),
    ]
    assert [e.name for e in parsed.exports] == ["Service"]
    service_symbol = parsed.symbols[0]
    assert (service_symbol.location.start_line, service_symbol.location.end_line) == (
        8,
        14,
    )
