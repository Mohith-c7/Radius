"""TypeScript / JavaScript definition index on the F-09 tree-sitter parser.

Grammar loading is shared with ``radius_parser`` (``parse_syntax_tree``); this
module only walks the syntax tree. Symbols: functions (declarations, overload
signatures, ``const f = () => ...`` / function expressions), classes, methods,
accessors (``get``/``set``), arrow-function class fields, interfaces, type
aliases, enums and namespaces, plus a ``<module>`` pseudo-symbol.

Fingerprints are leaf-token streams: comments are dropped, nested definitions
become ``def:<name>`` placeholders, and purely cosmetic tokens (optional
semicolons, trailing commas, string quote style, JSX whitespace) are
normalised away so formatting-only edits compare equal.
"""

from __future__ import annotations

from radius_analysis.symbol_changes.common import (
    MODULE_SYMBOL,
    Defn,
    FileIndex,
    dedupe_qualnames,
    link_children,
)

_FUNCTION_VALUES = frozenset(
    {"arrow_function", "function_expression", "function", "generator_function"}
)
_SIMPLE_DEFS = {
    "function_declaration": "function",
    "generator_function_declaration": "function",
    "function_signature": "function",
    "class_declaration": "class",
    "abstract_class_declaration": "class",
    "interface_declaration": "interface",
    "type_alias_declaration": "type",
    "enum_declaration": "enum",
    "internal_module": "namespace",
    "module": "namespace",
}
_MEMBER_DEFS = frozenset({"method_definition", "abstract_method_signature", "method_signature"})
_FIELD_DEFS = frozenset({"public_field_definition", "field_definition"})
_NO_DESCENT = frozenset({"interface", "type", "enum"})
_CLOSERS = frozenset({")", "}", "]"})


def _text(node) -> str:
    return node.text.decode("utf-8", errors="replace")


def _leaf_tokens(
    node,
    replace: dict[int, str],
    *,
    lo: int | None = None,
    hi: int | None = None,
    skip_range: tuple[int, int] | None = None,
    skip_types: frozenset[str] = frozenset({"comment"}),
) -> list[str]:
    out: list[str] = []
    stack = [node]
    root_id = node.id
    while stack:
        cur = stack.pop()
        if lo is not None and cur.end_byte <= lo:
            continue
        if hi is not None and cur.start_byte >= hi:
            continue
        if cur.type in skip_types:
            continue
        if cur.id != root_id and cur.id in replace:
            if replace[cur.id]:
                out.append(replace[cur.id])
            continue
        if cur.child_count:
            stack.extend(reversed(cur.children))
            continue
        if skip_range is not None and cur.start_byte >= skip_range[0] and cur.end_byte <= skip_range[1]:
            continue
        ctype = cur.type
        parent = cur.parent
        ptype = parent.type if parent is not None else ""
        if ctype == ";" and ptype != "for_statement":
            continue
        if ctype == ",":
            nxt = cur.next_sibling
            if nxt is not None and nxt.type in _CLOSERS:
                continue
        if ctype in {'"', "'"} and ptype == "string":
            out.append('"')
            continue
        if ctype == "jsx_text":
            out.append(" ".join(_text(cur).split()))
            continue
        out.append(_text(cur))
    return out


class _Spec:
    """A definition found in phase 1, fingerprinted in phase 2."""

    __slots__ = (
        "body", "decorators", "defn_node", "export", "idx", "name_node", "outer", "parent",
        "sig_node", "start_row",
    )


class _Collector:
    def __init__(self, language: str) -> None:
        self.language = language
        self.specs: list[_Spec] = []
        self.defs: list[Defn] = []
        self.replace: dict[int, str] = {}

    # ------------------------------------------------------------------ phase 1
    def scan(self, root) -> None:
        stack: list[tuple[object, str, str, int | None]] = [(root, "", "module", None)]
        while stack:
            container, prefix, ctx, parent = stack.pop()
            pending: list[tuple[object, str, str, int | None]] = []
            children = container.children
            child_ctx = "function" if ctx == "class" else ctx
            for node in children:
                if self._try_define(node, container, prefix, ctx, parent, pending):
                    continue
                if node.child_count:
                    pending.append((node, prefix, child_ctx, parent))
            stack.extend(reversed(pending))

    def _try_define(self, node, container, prefix, ctx, parent, pending) -> bool:
        ntype = node.type
        outer = node
        decl = node
        export = ""
        if ntype == "export_statement":
            inner = node.child_by_field_name("declaration")
            if inner is None:
                inner = node.child_by_field_name("value")
                if inner is not None and inner.type in _FUNCTION_VALUES | {"class"}:
                    return self._define_default(node, inner, prefix, ctx, parent, pending)
                return False
            decl = inner
            texts = [c.type for c in node.children if c.type in {"export", "default"}]
            export = " ".join(texts)
        elif ntype == "ambient_declaration":
            return False  # scanned as a normal container: its members are definitions
        if decl.type == "expression_statement" and decl.named_child_count == 1:
            first = decl.named_children[0]
            if first.type == "internal_module":
                decl = first
        dtype = decl.type
        if dtype in _SIMPLE_DEFS and decl.child_count:
            return self._define(decl, outer, _SIMPLE_DEFS[dtype], prefix, parent, pending, export)
        if ctx == "class" and dtype in _MEMBER_DEFS:
            return self._define_member(decl, container, prefix, parent, pending)
        if ctx == "class" and dtype in _FIELD_DEFS:
            value = decl.child_by_field_name("value")
            if value is not None and value.type in _FUNCTION_VALUES:
                return self._define_valued(decl, decl, value, "method", prefix, parent, pending, "")
            return False
        if dtype in {"lexical_declaration", "variable_declaration"}:
            return self._define_variables(decl, outer, prefix, parent, pending, export)
        return False

    def _name(self, node, fallback: str = "default") -> str:
        name = node.child_by_field_name("name")
        return _text(name) if name is not None else fallback

    def _start_row(self, outer, container=None) -> int:
        row = outer.start_point[0]
        prev = outer.prev_sibling
        while prev is not None and prev.type in {"comment", "decorator"} and prev.end_point[0] >= row - 1:
            row = prev.start_point[0]
            if prev.type == "decorator":
                self.replace[prev.id] = ""
            prev = prev.prev_sibling
        return row

    def _decorators(self, outer, decl) -> tuple[str, ...]:
        found: list[str] = []
        prev = outer.prev_sibling
        collected = []
        row = outer.start_point[0]
        while prev is not None and prev.type in {"comment", "decorator"} and prev.end_point[0] >= row - 1:
            if prev.type == "decorator":
                collected.append(prev)
            row = prev.start_point[0]
            prev = prev.prev_sibling
        nodes = list(reversed(collected))
        for holder in {outer.id: outer, decl.id: decl}.values():
            nodes.extend(c for c in holder.children if c.type == "decorator")
        for dec in nodes:
            found.append(" ".join(_leaf_tokens(dec, {})))
        return tuple(found)

    def _end_row(self, outer) -> int:
        row = outer.end_point[0] + 1
        if outer.end_point[1] == 0 and row > outer.start_point[0] + 1:
            row -= 1
        return row

    def _register(self, kind, qual, decl, outer, parent, body, sig_node, export, pending, name_node):
        spec = _Spec()
        spec.defn_node = decl
        spec.outer = outer
        spec.sig_node = sig_node
        spec.body = body
        spec.name_node = name_node
        spec.export = export
        spec.decorators = self._decorators(outer, decl)
        spec.start_row = self._start_row(outer)
        idx = len(self.defs)
        spec.idx = idx
        spec.parent = parent
        self.defs.append(
            Defn(
                qualname=qual,
                kind=kind,
                start=spec.start_row + 1,
                end=self._end_row(outer),
                signature="",
                display=qual,
                body=(),
                parent=parent,
            )
        )
        self.specs.append(spec)
        self.replace[outer.id] = ""  # nested definitions are separate symbols
        if body is not None and kind not in _NO_DESCENT:
            child_prefix = f"{qual}." if kind in {"class", "namespace"} else f"{qual}.<locals>."
            ctx = "class" if kind == "class" else "function"
            if kind == "namespace":
                ctx = "module"
            pending.append((body, child_prefix, ctx, idx))
        return idx

    def _define(self, decl, outer, kind, prefix, parent, pending, export) -> bool:
        name_node = decl.child_by_field_name("name")
        name = _text(name_node) if name_node is not None else "default"
        body = decl.child_by_field_name("body")
        if body is None and decl.type == "type_alias_declaration":
            body = decl.child_by_field_name("value")
        self._register(kind, f"{prefix}{name}", decl, outer, parent, body, decl, export, pending, name_node)
        return True

    def _define_default(self, node, inner, prefix, ctx, parent, pending) -> bool:
        kind = "class" if inner.type == "class" else "function"
        body = inner.child_by_field_name("body")
        self._register(kind, f"{prefix}default", inner, node, parent, body, inner, "export default", pending, None)
        return True

    def _define_member(self, decl, container, prefix, parent, pending) -> bool:
        name_node = decl.child_by_field_name("name")
        name = _text(name_node) if name_node is not None else "<anonymous>"
        kind = "method"
        accessor = next((c.type for c in decl.children if c.type in {"get", "set"}), None)
        if accessor:
            kind = "property"
            name = f"{name}.{accessor}"
        body = decl.child_by_field_name("body")
        self._register(kind, f"{prefix}{name}", decl, decl, parent, body, decl, "", pending, name_node)
        return True

    def _define_valued(self, decl, outer, value, kind, prefix, parent, pending, export) -> bool:
        name_node = decl.child_by_field_name("name")
        if name_node is None or name_node.type not in {
            "identifier", "property_identifier", "private_property_identifier", "type_identifier",
        }:
            return False
        body = value.child_by_field_name("body")
        self._register(
            kind, f"{prefix}{_text(name_node)}", decl, outer, parent, body, value, export, pending, name_node
        )
        return True

    def _define_variables(self, decl, outer, prefix, parent, pending, export) -> bool:
        declarators = [c for c in decl.children if c.type == "variable_declarator"]
        callable_decls = []
        for d in declarators:
            value = d.child_by_field_name("value")
            name_node = d.child_by_field_name("name")
            if (
                value is not None
                and name_node is not None
                and name_node.type == "identifier"
                and (value.type in _FUNCTION_VALUES or value.type == "class")
            ):
                callable_decls.append((d, value))
        if not callable_decls:
            return False
        single = len(declarators) == 1
        defined: set[int] = set()
        for d, value in callable_decls:
            kind = "class" if value.type == "class" else "function"
            if self._define_valued(
                d, outer if single else d, value, kind, prefix, parent, pending,
                export if single else "",
            ):
                defined.add(d.id)
        if not defined:
            return False
        for d in declarators:
            if d.id not in defined:
                pending.append((d, prefix, "function", parent))
        return True

    # ------------------------------------------------------------------ phase 2
    def finish(self) -> None:
        skip = frozenset({"comment", "decorator"})
        for spec in self.specs:
            defn = self.defs[spec.idx]
            hi = spec.body.start_byte if spec.body is not None else spec.defn_node.end_byte
            name_range = (
                (spec.name_node.start_byte, spec.name_node.end_byte)
                if spec.name_node is not None
                else None
            )
            sig = _leaf_tokens(
                spec.defn_node, self.replace, hi=hi, skip_range=name_range, skip_types=skip
            )
            if spec.export:
                sig = [*spec.export.split(), *sig]
            defn.signature = " ".join(sig)
            short = defn.qualname.rsplit(".", 1)[-1]
            defn.display = f"{short} {defn.signature}".strip()
            if spec.body is not None:
                defn.body = tuple(_leaf_tokens(spec.body, self.replace))
            defn.decorators = spec.decorators


def index_ecmascript(source: str, suffix: str, language: str) -> FileIndex:
    """Index a TS/JS source; ``parse_error`` is set instead of raising."""

    from radius_parser.infrastructure.ecmascript_parser import parse_syntax_tree  # noqa: PLC0415

    lines = source.split("\n")
    line_count = len(lines) - 1 if source.endswith("\n") else len(lines)
    index = FileIndex(language=language, line_count=line_count)
    try:
        root, error = parse_syntax_tree(source, suffix)
    except ModuleNotFoundError:
        if language != "javascript":
            raise
        # Declared dependency missing in this environment: the TSX grammar is a
        # superset of JavaScript+JSX, so degrade gracefully instead of file-level.
        root, error = parse_syntax_tree(source, ".tsx")
    if error is not None:
        index.parse_error = f"SyntaxError at line {error.start_point[0] + 1}"
        return index

    collector = _Collector(language)
    collector.scan(root)

    imports: list = []
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "comment":
            index.comments.append(
                (node.start_point[0] + 1, node.end_point[0] + 1, _text(node).strip())
            )
            continue
        if node.type == "import_statement":
            imports.append(node)
            continue
        if node.child_count:
            stack.extend(reversed(node.children))
    index.comments.sort()
    for imp in imports:
        index.import_lines.update(range(imp.start_point[0] + 1, imp.end_point[0] + 2))
        collector.replace[imp.id] = ""

    collector.finish()
    defs = collector.defs
    module_tokens = _leaf_tokens(root, collector.replace)
    if module_tokens:
        index.module_index = len(defs)
        defs.append(
            Defn(
                qualname=MODULE_SYMBOL,
                kind="module",
                start=1,
                end=max(line_count, 1),
                signature="",
                display=MODULE_SYMBOL,
                body=tuple(module_tokens),
                parent=None,
            )
        )
    dedupe_qualnames(defs)
    link_children(defs)
    index.defs = defs
    return index
