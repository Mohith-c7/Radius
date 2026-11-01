"""Python source parser backed by the standard library AST."""

from __future__ import annotations

import ast

from radius_parser.domain.entities import (
    ExportReference,
    ImportReference,
    ParsedSourceFile,
    SourceFile,
    Symbol,
)
from radius_parser.domain.enums import SourceLanguage, SymbolType, SymbolVisibility
from radius_parser.domain.value_objects import SourceLocation, SymbolName


class PythonAstParser:
    """Extract deterministic Python imports, symbols, and exports."""

    supported_language = SourceLanguage.PYTHON

    def parse(self, source_file: SourceFile) -> ParsedSourceFile:
        """Parse one Python file into normalized metadata."""

        source = self._read_source(source_file)
        tree = ast.parse(source)
        symbols: list[Symbol] = []
        imports: list[ImportReference] = []
        explicit_exports = self._explicit_exports(tree)

        # Imports are collected from the whole module, not just the top level:
        # imports inside functions, ``try`` blocks and ``if TYPE_CHECKING`` are
        # real (sometimes lazy) dependencies.
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(self._import_references(node))
            elif isinstance(node, ast.ImportFrom):
                imports.append(self._from_import_reference(node))

        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                symbols.append(self._symbol(node.name, SymbolType.CLASS, node))
                symbols.extend(self._method_symbols(node))
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                symbols.append(self._symbol(node.name, SymbolType.FUNCTION, node))

        exports = tuple(
            ExportReference(
                name=name,
                location=self._symbol_location_by_name(symbols, name),
            )
            for name in sorted(explicit_exports or self._public_symbol_names(symbols))
        )
        return ParsedSourceFile(
            source_file=source_file,
            symbols=tuple(symbols),
            imports=tuple(imports),
            exports=exports,
        )

    @staticmethod
    def _read_source(source_file: SourceFile) -> str:
        if source_file.absolute_path is None:
            return ""
        return source_file.absolute_path.read_text(encoding="utf-8")

    @staticmethod
    def _import_references(node: ast.Import) -> tuple[ImportReference, ...]:
        return tuple(
            ImportReference(
                source=alias.name,
                location=PythonAstParser._location(node),
            )
            for alias in node.names
        )

    @staticmethod
    def _from_import_reference(node: ast.ImportFrom) -> ImportReference:
        prefix = "." * node.level
        module = node.module or ""
        return ImportReference(
            source=f"{prefix}{module}",
            location=PythonAstParser._location(node),
            names=tuple(alias.name for alias in node.names if alias.name != "*"),
        )

    @classmethod
    def _method_symbols(cls, node: ast.ClassDef) -> tuple[Symbol, ...]:
        methods: list[Symbol] = []
        for child in node.body:
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                methods.append(
                    cls._symbol(f"{node.name}.{child.name}", SymbolType.METHOD, child)
                )
        return tuple(methods)

    @staticmethod
    def _symbol(name: str, symbol_type: SymbolType, node: ast.AST) -> Symbol:
        return Symbol(
            name=SymbolName(name),
            symbol_type=symbol_type,
            visibility=(
                SymbolVisibility.PRIVATE
                if name.split(".")[-1].startswith("_")
                else SymbolVisibility.PUBLIC
            ),
            location=PythonAstParser._location(node),
        )

    @staticmethod
    def _location(node: ast.AST) -> SourceLocation:
        return SourceLocation(
            start_line=getattr(node, "lineno", 1),
            start_column=getattr(node, "col_offset", 0) + 1,
            end_line=getattr(node, "end_lineno", None),
            end_column=(
                getattr(node, "end_col_offset", None) + 1
                if getattr(node, "end_col_offset", None) is not None
                else None
            ),
        )

    @staticmethod
    def _explicit_exports(tree: ast.Module) -> tuple[str, ...]:
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            has_all_target = any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in node.targets
            )
            if not has_all_target:
                continue
            if isinstance(node.value, ast.List | ast.Tuple):
                return tuple(
                    item.value
                    for item in node.value.elts
                    if isinstance(item, ast.Constant) and isinstance(item.value, str)
                )
        return ()

    @staticmethod
    def _public_symbol_names(symbols: list[Symbol]) -> tuple[str, ...]:
        return tuple(
            symbol.name.value
            for symbol in symbols
            if symbol.visibility == SymbolVisibility.PUBLIC
            and "." not in symbol.name.value
        )

    @staticmethod
    def _symbol_location_by_name(
        symbols: list[Symbol],
        name: str,
    ) -> SourceLocation | None:
        for symbol in symbols:
            if symbol.name.value == name:
                return symbol.location
        return None
