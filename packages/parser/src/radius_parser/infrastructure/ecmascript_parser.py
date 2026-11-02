"""JavaScript and TypeScript source parser backed by tree-sitter (DEC-017).

Imports, symbols and exports are read from a real syntax tree, never from
line-based patterns, so comments, strings, template literals and multi-line
statements cannot produce false results.

Grammar choice by file suffix:

* ``.ts``/``.mts``/``.cts`` -> TypeScript grammar
* ``.tsx`` -> TSX grammar
* ``.js``/``.jsx``/``.mjs``/``.cjs`` -> JavaScript grammar (handles JSX)

A file whose tree contains syntax errors raises :class:`SyntaxError`, which
``ParserApplicationService`` records in ``parse_failures`` exactly as it does
for Python files.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

from radius_parser.domain.entities import (
    ExportReference,
    ImportReference,
    ParsedSourceFile,
    SourceFile,
    Symbol,
)
from radius_parser.domain.enums import SourceLanguage, SymbolType, SymbolVisibility
from radius_parser.domain.value_objects import SourceLocation, SymbolName

logger = logging.getLogger(__name__)

TYPESCRIPT_SUFFIXES = frozenset({".ts", ".mts", ".cts"})
TSX_SUFFIXES = frozenset({".tsx"})
JAVASCRIPT_SUFFIXES = frozenset({".js", ".jsx", ".mjs", ".cjs"})

_FUNCTION_VALUE_TYPES = frozenset(
    {"arrow_function", "function_expression", "function", "generator_function"}
)
_CLASS_DECLARATIONS = frozenset({"class_declaration", "abstract_class_declaration"})
_METHOD_NODES = frozenset(
    {"method_definition", "method_signature", "abstract_method_signature"}
)
_FIELD_NODES = frozenset({"public_field_definition", "field_definition"})


def _grammar_for(suffix: str) -> str:
    if suffix in TSX_SUFFIXES:
        return "tsx"
    if suffix in JAVASCRIPT_SUFFIXES:
        return "javascript"
    return "typescript"


@lru_cache(maxsize=4)
def _tree_sitter_parser(grammar: str):
    import tree_sitter  # noqa: PLC0415 - optional heavy import

    if grammar == "javascript":
        import tree_sitter_javascript  # noqa: PLC0415

        language = tree_sitter.Language(tree_sitter_javascript.language())
    else:
        import tree_sitter_typescript  # noqa: PLC0415

        language = tree_sitter.Language(
            tree_sitter_typescript.language_tsx()
            if grammar == "tsx"
            else tree_sitter_typescript.language_typescript()
        )
    return tree_sitter.Parser(language)


def _parse_tree(source: str, suffix: str):
    return _tree_sitter_parser(_grammar_for(suffix)).parse(source.encode("utf-8"))


def parse_syntax_tree(source: str, suffix: str):
    """Public entry for other packages: return ``(root_node, first_error_node_or_None)``.

    Shares the grammar selection and parser cache used by the import/symbol
    extractors (LK-01 reuses it instead of duplicating grammar loading).
    """

    root = _parse_tree(source, suffix).root_node
    return root, _first_error(root)


def _text(node) -> str:
    return node.text.decode("utf-8", errors="replace")


def _string_value(node) -> str:
    """Return the literal value of a tree-sitter ``string`` node (no template parts)."""

    fragments = [
        _text(child)
        for child in node.named_children
        if child.type in {"string_fragment", "escape_sequence"}
    ]
    if any(
        child.type not in {"string_fragment", "escape_sequence"}
        for child in node.named_children
    ):
        return ""
    return "".join(fragments).strip()


def _location(node) -> SourceLocation:
    return SourceLocation(
        start_line=node.start_point[0] + 1,
        start_column=node.start_point[1] + 1,
        end_line=node.end_point[0] + 1,
        end_column=node.end_point[1] + 1,
    )


def _first_error(root) -> object | None:
    stack = [root]
    while stack:
        node = stack.pop()
        if node.is_error or node.is_missing:
            return node
        if node.has_error:
            stack.extend(reversed(node.children))
    return None


class TypeScriptLikeParser:
    """Extract imports, symbols and exports from JS/TS-family source files."""

    def __init__(self, supported_language: SourceLanguage) -> None:
        self.supported_language = supported_language

    def parse(self, source_file: SourceFile) -> ParsedSourceFile:
        """Parse one JS/TS file.

        Raises:
            SyntaxError: the file contains syntax errors (recorded by the
                application service as a parse failure).
        """

        source = self._read_source(source_file)
        suffix = (
            source_file.absolute_path.suffix.lower()
            if source_file.absolute_path is not None
            else ""
        )
        try:
            tree = _parse_tree(source, suffix)
        except Exception:  # noqa: BLE001 - grammar wheel missing or broken
            logger.error(
                "tree-sitter grammar unavailable for %s; using the REGEX IMPORT "
                "FALLBACK (imports only, no symbols). Install tree-sitter, "
                "tree-sitter-typescript and tree-sitter-javascript.",
                source_file.path.value,
                exc_info=True,
            )
            return ParsedSourceFile(
                source_file=source_file,
                imports=tuple(regex_import_fallback(source)),
            )

        error = _first_error(tree.root_node)
        if error is not None:
            line, column = error.start_point
            msg = f"{source_file.path.value}:{line + 1}:{column + 1}: syntax error"
            raise SyntaxError(msg)

        imports = self._collect_imports(tree.root_node)
        symbols, exports = _SymbolCollector().collect(tree.root_node)
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

    @classmethod
    def _imports(cls, source: str, suffix: str = ".ts") -> list[ImportReference]:
        """Extract import sources with tree-sitter.

        Only a grammar/runtime failure (not a syntax error in the source)
        reaches the loud, explicitly named regex fallback.
        """

        try:
            return cls._tree_sitter_imports(source, suffix)
        except Exception:  # noqa: BLE001 - any grammar/runtime failure falls back
            logger.error(
                "tree-sitter import extraction failed; using the REGEX IMPORT "
                "FALLBACK. Results may miss dynamic imports and contain false "
                "positives.",
                exc_info=True,
            )
            return regex_import_fallback(source)

    @classmethod
    def _tree_sitter_imports(cls, source: str, suffix: str) -> list[ImportReference]:
        return cls._collect_imports(_parse_tree(source, suffix).root_node)

    @staticmethod
    def _collect_imports(root) -> list[ImportReference]:
        found: dict[tuple[str, int], ImportReference] = {}

        def add(string_node) -> None:
            if string_node is None or string_node.type != "string":
                return
            value = _string_value(string_node)
            if not value:
                return
            line = string_node.start_point[0] + 1
            found.setdefault(
                (value, line),
                ImportReference(
                    source=value,
                    location=SourceLocation(
                        start_line=line,
                        start_column=string_node.start_point[1] + 1,
                    ),
                ),
            )

        stack = [root]
        while stack:
            node = stack.pop()
            node_type = node.type
            if node_type in {
                "import_statement",
                "export_statement",
                "import_require_clause",
            }:
                add(node.child_by_field_name("source"))
            elif node_type == "call_expression":
                function = node.child_by_field_name("function")
                arguments = node.child_by_field_name("arguments")
                is_loader = function is not None and (
                    function.type == "import"
                    or (function.type == "identifier" and function.text == b"require")
                )
                if is_loader and arguments is not None:
                    values = list(arguments.named_children)
                    if len(values) == 1:
                        add(values[0])
            stack.extend(node.children)
        return [
            found[key] for key in sorted(found, key=lambda item: (item[1], item[0]))
        ]


# --- explicit regex fallback (grammar unavailable only) -----------------------

_MODULE_IMPORT_RE = re.compile(
    r"""(?:^|[;\n])\s*(?:import|export)\b[^;'"`]*?\bfrom\s*["'](?P<source>[^"'\n]+)["']""",
)
_SIDE_EFFECT_IMPORT_RE = re.compile(
    r"""(?:^|[;\n])\s*import\s*["'](?P<source>[^"'\n]+)["']"""
)
_CALL_IMPORT_RE = re.compile(
    r"""\b(?:require|import)\s*\(\s*["'](?P<source>[^"'\n]+)["']\s*\)""",
)


def regex_import_fallback(source: str) -> list[ImportReference]:
    """Last-resort import extraction used ONLY when tree-sitter cannot load.

    Never on the default path; callers must log loudly before using it.
    """

    found: dict[tuple[str, int], ImportReference] = {}
    for pattern in (_MODULE_IMPORT_RE, _SIDE_EFFECT_IMPORT_RE, _CALL_IMPORT_RE):
        for match in pattern.finditer(source):
            line = source.count("\n", 0, match.start("source")) + 1
            found.setdefault(
                (match.group("source"), line),
                ImportReference(
                    source=match.group("source"),
                    location=SourceLocation(start_line=line),
                ),
            )
    return [found[key] for key in sorted(found, key=lambda item: (item[1], item[0]))]


# --- symbols and exports ------------------------------------------------------


class _SymbolCollector:
    """Walk top-level declarations and gather symbols plus exported names."""

    def __init__(self) -> None:
        self._symbols: dict[tuple[str, SymbolType], Symbol] = {}
        self._order: list[tuple[str, SymbolType]] = []
        self._exported: dict[str, ExportReference] = {}

    def collect(self, root) -> tuple[list[Symbol], dict[str, ExportReference]]:
        for child in root.named_children:
            self._statement(child, exported=False)

        symbols = [self._symbols[key] for key in self._order]
        exported_names = set(self._exported)
        has_explicit_exports = bool(exported_names)

        resolved: list[Symbol] = []
        for symbol in symbols:
            top_name = symbol.name.value.split(".")[0]
            underscore = symbol.name.value.split(".")[-1].startswith("_")
            if has_explicit_exports:
                public = top_name in exported_names and not underscore
            else:
                public = not underscore
            resolved.append(
                Symbol(
                    name=symbol.name,
                    symbol_type=symbol.symbol_type,
                    visibility=(
                        SymbolVisibility.PUBLIC if public else SymbolVisibility.PRIVATE
                    ),
                    location=symbol.location,
                )
            )

        exports = dict(self._exported)
        if not exports:
            # Scripts and CommonJS files declare no ES exports; every public
            # top-level symbol is treated as exported (legacy behaviour).
            exports = {
                symbol.name.value: ExportReference(
                    name=symbol.name.value, location=symbol.location
                )
                for symbol in resolved
                if symbol.visibility == SymbolVisibility.PUBLIC
                and "." not in symbol.name.value
            }
        return resolved, exports

    # statements -------------------------------------------------------------

    def _statement(self, node, *, exported: bool) -> None:
        kind = node.type
        if kind == "export_statement":
            self._export_statement(node)
        elif kind in {"ambient_declaration", "expression_statement"}:
            # ``declare ...`` wrappers and ``namespace X {}`` (an expression
            # statement wrapping ``internal_module``).
            for child in node.named_children:
                self._statement(child, exported=exported)
        else:
            self._declaration(node, exported=exported)

    def _declaration(self, node, *, exported: bool) -> list[str]:
        """Record symbols for a declaration node; return the declared names."""

        kind = node.type
        names: list[str] = []
        if kind in {"function_declaration", "generator_function_declaration"}:
            names.append(self._add(node, SymbolType.FUNCTION))
        elif kind == "function_signature":
            names.append(self._add(node, SymbolType.FUNCTION, overload=True))
        elif kind in _CLASS_DECLARATIONS:
            name = self._add(node, SymbolType.CLASS)
            names.append(name)
            self._members(node, name)
        elif kind == "interface_declaration":
            names.append(self._add(node, SymbolType.INTERFACE))
        elif kind == "type_alias_declaration":
            names.append(self._add(node, SymbolType.TYPE_ALIAS))
        elif kind == "enum_declaration":
            names.append(self._add(node, SymbolType.ENUM))
        elif kind in {"internal_module", "module"}:
            name_node = node.child_by_field_name("name")
            if name_node is not None and name_node.type == "identifier":
                names.append(self._add(node, SymbolType.NAMESPACE))
        elif kind in {"lexical_declaration", "variable_declaration"}:
            for declarator in node.named_children:
                if declarator.type != "variable_declarator":
                    continue
                name_node = declarator.child_by_field_name("name")
                if name_node is None or name_node.type != "identifier":
                    continue
                value = declarator.child_by_field_name("value")
                names.append(_text(name_node))
                if value is not None and value.type in _FUNCTION_VALUE_TYPES:
                    self._put(
                        _text(name_node), SymbolType.FUNCTION, _location(declarator)
                    )
                elif value is not None and value.type == "class":
                    self._put(_text(name_node), SymbolType.CLASS, _location(declarator))
                    self._members(value, _text(name_node))
        if exported:
            for name in names:
                self._export(name, node)
        return names

    def _export_statement(self, node) -> None:
        declaration = node.child_by_field_name("declaration")
        source = node.child_by_field_name("source")
        is_default = any(child.type == "default" for child in node.children)

        if declaration is not None:
            names = self._declaration(declaration, exported=True)
            if is_default and not names:
                self._export("default", node)
            return

        value = node.child_by_field_name("value")
        if value is not None:
            # ``export default <expression>`` / ``export default class {}``
            if value.type == "class":
                name_node = value.child_by_field_name("name")
                name = _text(name_node) if name_node is not None else "default"
                self._put(name, SymbolType.CLASS, _location(value))
                self._members(value, name)
                self._export(name, node)
            elif value.type in _FUNCTION_VALUE_TYPES:
                name_node = value.child_by_field_name("name")
                name = _text(name_node) if name_node is not None else "default"
                self._put(name, SymbolType.FUNCTION, _location(value))
                self._export(name, node)
            elif value.type == "identifier":
                self._export(_text(value), node)
            else:
                self._export("default", node)
            return

        for child in node.named_children:
            if child.type == "export_clause":
                for spec in child.named_children:
                    if spec.type != "export_specifier":
                        continue
                    name_node = spec.child_by_field_name("name")
                    alias_node = spec.child_by_field_name("alias")
                    if name_node is None:
                        continue
                    # Local exports keep the local name so they line up with
                    # symbols; re-exports have no local symbol, so the name
                    # visible to importers is used.
                    chosen = (
                        alias_node
                        if source is not None and alias_node is not None
                        else name_node
                    )
                    self._export(_text(chosen).strip("'\""), spec)
            elif child.type == "namespace_export":
                inner = child.named_children[0] if child.named_children else None
                if inner is not None:
                    self._export(_text(inner), child)
            elif child.type == "identifier" and source is None:
                # ``export = foo`` (TS) exports a local binding.
                self._export(_text(child), child)

    # helpers ----------------------------------------------------------------

    def _members(self, class_node, class_name: str) -> None:
        body = class_node.child_by_field_name("body")
        if body is None:
            return
        for member in body.named_children:
            name_node = member.child_by_field_name("name") or member.child_by_field_name(
                "property"
            )
            if name_node is None or name_node.type == "computed_property_name":
                continue
            if member.type in _METHOD_NODES:
                self._put(
                    f"{class_name}.{_text(name_node)}",
                    SymbolType.METHOD,
                    _location(member),
                    overload=member.type != "method_definition",
                )
            elif member.type in _FIELD_NODES:
                value = member.child_by_field_name("value")
                if value is not None and value.type in _FUNCTION_VALUE_TYPES:
                    self._put(
                        f"{class_name}.{_text(name_node)}",
                        SymbolType.METHOD,
                        _location(member),
                    )

    def _add(self, node, symbol_type: SymbolType, *, overload: bool = False) -> str:
        name_node = node.child_by_field_name("name")
        name = _text(name_node).strip("'\"") if name_node is not None else "default"
        self._put(name, symbol_type, _location(node), overload=overload)
        return name

    def _put(
        self,
        name: str,
        symbol_type: SymbolType,
        location: SourceLocation,
        *,
        overload: bool = False,
    ) -> None:
        if not name.strip():
            return
        key = (name, symbol_type)
        if key in self._symbols and overload:
            return  # a signature never replaces an existing declaration
        if key not in self._symbols:
            self._order.append(key)
        self._symbols[key] = Symbol(
            name=SymbolName(name),
            symbol_type=symbol_type,
            visibility=SymbolVisibility.PUBLIC,
            location=location,
        )

    def _export(self, name: str, node) -> None:
        if name.strip():
            self._exported.setdefault(
                name, ExportReference(name=name, location=_location(node))
            )


class JavaScriptParser(TypeScriptLikeParser):
    """JavaScript parser adapter."""

    def __init__(self) -> None:
        super().__init__(SourceLanguage.JAVASCRIPT)


class TypeScriptParser(TypeScriptLikeParser):
    """TypeScript parser adapter."""

    def __init__(self) -> None:
        super().__init__(SourceLanguage.TYPESCRIPT)


__all__ = [
    "JavaScriptParser",
    "TypeScriptLikeParser",
    "TypeScriptParser",
    "regex_import_fallback",
]
