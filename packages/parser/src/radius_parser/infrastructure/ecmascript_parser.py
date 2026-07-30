"""Lightweight JavaScript and TypeScript source parser."""

from __future__ import annotations

import re

from radius_parser.domain.entities import (
    ExportReference,
    ImportReference,
    ParsedSourceFile,
    SourceFile,
    Symbol,
)
from radius_parser.domain.enums import SourceLanguage, SymbolType, SymbolVisibility
from radius_parser.domain.value_objects import SourceLocation, SymbolName

IMPORT_RE = re.compile(
    r"""^\s*(?:import\s+(?:type\s+)?(?:.+?\s+from\s+)?|export\s+.+?\s+from\s+)["'](?P<source>[^"']+)["']""",
)
REQUIRE_RE = re.compile(r"""require\(["'](?P<source>[^"']+)["']\)""")
CLASS_RE = re.compile(
    r"""^\s*(?:export\s+)?(?:abstract\s+)?class\s+"""
    r"""(?P<name>[A-Za-z_$][\w$]*)""",
)
INTERFACE_RE = re.compile(
    r"""^\s*(?:export\s+)?interface\s+(?P<name>[A-Za-z_$][\w$]*)""",
)
FUNCTION_RE = re.compile(
    r"""^\s*(?:export\s+)?(?:async\s+)?function\s+"""
    r"""(?P<name>[A-Za-z_$][\w$]*)""",
)
CONST_FN_RE = re.compile(
    r"""^\s*(?:export\s+)?(?:const|let|var)\s+"""
    r"""(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?"""
    r"""(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>""",
)
EXPORT_DECL_RE = re.compile(
    r"""^\s*export\s+(?:default\s+)?"""
    r"""(?:class|function|interface|const|let|var|enum|type)\s+"""
    r"""(?P<name>[A-Za-z_$][\w$]*)""",
)
EXPORT_LIST_RE = re.compile(r"""^\s*export\s*\{(?P<names>[^}]+)\}""")


class TypeScriptLikeParser:
    """Extract useful Phase 1 metadata from JS/TS-family source files."""

    def __init__(self, supported_language: SourceLanguage) -> None:
        self.supported_language = supported_language

    def parse(self, source_file: SourceFile) -> ParsedSourceFile:
        """Parse one JS/TS file using deterministic source patterns."""

        source = self._read_source(source_file)
        imports: list[ImportReference] = []
        symbols: list[Symbol] = []
        exports: dict[str, ExportReference] = {}

        for line_number, line in enumerate(source.splitlines(), start=1):
            location = SourceLocation(start_line=line_number)
            import_match = IMPORT_RE.search(line) or REQUIRE_RE.search(line)
            if import_match is not None:
                imports.append(
                    ImportReference(
                        source=import_match.group("source"),
                        location=location,
                    )
                )

            symbol = self._symbol_from_line(line, location)
            if symbol is not None:
                symbols.append(symbol)

            for name in self._exports_from_line(line):
                exports[name] = ExportReference(name=name, location=location)

        if not exports:
            exports = {
                symbol.name.value: ExportReference(
                    name=symbol.name.value,
                    location=symbol.location,
                )
                for symbol in symbols
                if symbol.visibility == SymbolVisibility.PUBLIC
            }

        return ParsedSourceFile(
            source_file=source_file,
            symbols=tuple(symbols),
            imports=tuple(imports),
            exports=tuple(exports[name] for name in sorted(exports)),
        )

    @staticmethod
    def _read_source(source_file: SourceFile) -> str:
        if source_file.absolute_path is None:
            return ""
        return source_file.absolute_path.read_text(encoding="utf-8")

    @staticmethod
    def _symbol_from_line(line: str, location: SourceLocation) -> Symbol | None:
        for pattern, symbol_type in (
            (CLASS_RE, SymbolType.CLASS),
            (INTERFACE_RE, SymbolType.INTERFACE),
            (FUNCTION_RE, SymbolType.FUNCTION),
            (CONST_FN_RE, SymbolType.FUNCTION),
        ):
            match = pattern.search(line)
            if match is not None:
                name = match.group("name")
                return Symbol(
                    name=SymbolName(name),
                    symbol_type=symbol_type,
                    visibility=(
                        SymbolVisibility.PRIVATE
                        if name.startswith("_")
                        else SymbolVisibility.PUBLIC
                    ),
                    location=location,
                )
        return None

    @staticmethod
    def _exports_from_line(line: str) -> tuple[str, ...]:
        declaration = EXPORT_DECL_RE.search(line)
        if declaration is not None:
            return (declaration.group("name"),)

        listed = EXPORT_LIST_RE.search(line)
        if listed is None:
            return ()
        names = []
        for item in listed.group("names").split(","):
            name = item.strip().split(" as ", maxsplit=1)[0].strip()
            if name:
                names.append(name)
        return tuple(names)


class JavaScriptParser(TypeScriptLikeParser):
    """JavaScript parser adapter."""

    def __init__(self) -> None:
        super().__init__(SourceLanguage.JAVASCRIPT)


class TypeScriptParser(TypeScriptLikeParser):
    """TypeScript parser adapter."""

    def __init__(self) -> None:
        super().__init__(SourceLanguage.TYPESCRIPT)
