"""Python definition index with change-detection fingerprints (stdlib ``ast``).

Symbols: functions, async functions, methods, properties, classes, nested
definitions (``outer.<locals>.inner``), lambdas assigned to a name, and a
``<module>`` pseudo-symbol holding the module-level statements that are not
definitions or imports. F-08's :class:`radius_graph.symbol_impact.PythonSymbolGraph`
answers "who references this name"; this index answers "what did this definition
look like" (signature, decorators, docstring, normalised own body), so the two
share only the module pseudo-symbol name.
"""

from __future__ import annotations

import ast
import io
import tokenize

from radius_analysis.symbol_changes.common import (
    MODULE_SYMBOL,
    Defn,
    FileIndex,
    dedupe_qualnames,
    link_children,
)

_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_PROPERTY_NAMES = frozenset({"property", "cached_property"})
_ACCESSORS = frozenset({"setter", "getter", "deleter"})
_SKIP_FIELDS = frozenset({"ctx", "type_comment", "kind", "lineno", "end_lineno"})


def _lambda_binding(node: ast.AST) -> tuple[str, ast.Lambda] | None:
    """``name = lambda ...`` (plain or annotated) -> (name, lambda node)."""

    if (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Lambda)
    ):
        return node.targets[0].id, node.value
    if (
        isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and isinstance(node.value, ast.Lambda)
    ):
        return node.target.id, node.value
    return None


def _is_docstring(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _fp(node: object, out: list[str], *, skip_imports: bool = False) -> None:
    """Flatten ``node`` into structural tokens; nested definitions are omitted."""

    stack: list[object] = [node]
    while stack:
        cur = stack.pop()
        if isinstance(cur, str) and cur.startswith("\x00"):
            out.append(cur[1:])
            continue
        if isinstance(cur, ast.AST):
            if isinstance(cur, _DEFS) or _lambda_binding(cur) is not None:
                continue  # nested definitions are separate symbols: not part of this body
            if skip_imports and isinstance(cur, (ast.Import, ast.ImportFrom)):
                continue
            out.append(type(cur).__name__)
            children: list[object] = []
            for name, value in ast.iter_fields(cur):
                if name in _SKIP_FIELDS:
                    continue
                children.append(f"\x00{name}=")
                children.append(value)
            stack.extend(reversed(children))
        elif isinstance(cur, list):
            out.append("[")
            stack.append("\x00]")
            stack.extend(reversed(cur))
        else:
            out.append(repr(cur))


def _body_tokens(body: list[ast.stmt], *, skip_imports: bool = False) -> tuple[str, ...]:
    stmts = body[1:] if body and _is_docstring(body[0]) else body
    out: list[str] = []
    for stmt in stmts:
        _fp(stmt, out, skip_imports=skip_imports)
    return tuple(out)


def _decorator_kind(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[bool, str | None]:
    """Return (is_property, accessor) for ``@property`` / ``@x.setter``."""

    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Name) and target.id in _PROPERTY_NAMES:
            return True, None
        if isinstance(target, ast.Attribute):
            if target.attr in _ACCESSORS:
                return True, target.attr
            if target.attr in _PROPERTY_NAMES:
                return True, None
    return False, None


def _args_text(args: ast.arguments) -> str:
    return ast.unparse(args)


def _type_params(node: ast.AST) -> str:
    params = getattr(node, "type_params", None) or []
    return "[" + ", ".join(ast.unparse(p) for p in params) + "]" if params else ""


class _Collector:
    def __init__(self) -> None:
        self.defs: list[Defn] = []

    def walk(self, body: list[ast.stmt], prefix: str, ctx: str, parent: int | None) -> None:
        for stmt in body:
            if isinstance(stmt, ast.ClassDef):
                self._class(stmt, prefix, parent)
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._function(stmt, prefix, ctx, parent)
            else:
                bound = _lambda_binding(stmt)
                if bound is not None:
                    self._lambda(stmt, bound, prefix, parent)
                    continue
                for child in _nested_bodies(stmt):
                    self.walk(child, prefix, ctx, parent)

    def _range(self, node: ast.stmt) -> tuple[int, int]:
        starts = [node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])]
        return min(starts), node.end_lineno or node.lineno

    def _decorators(self, node: ast.stmt) -> tuple[str, ...]:
        return tuple(ast.unparse(d) for d in getattr(node, "decorator_list", []))

    def _class(self, node: ast.ClassDef, prefix: str, parent: int | None) -> None:
        qual = f"{prefix}{node.name}"
        bases = [ast.unparse(b) for b in node.bases] + [ast.unparse(k) for k in node.keywords]
        sig = f"{_type_params(node)}({', '.join(bases)})"
        start, end = self._range(node)
        idx = len(self.defs)
        self.defs.append(
            Defn(
                qualname=qual,
                kind="class",
                start=start,
                end=end,
                signature=sig,
                display=f"class {node.name}{sig}",
                body=_body_tokens(node.body),
                decorators=self._decorators(node),
                docstring=ast.get_docstring(node, clean=False),
                parent=parent,
            )
        )
        self.walk(node.body, f"{qual}.", "class", idx)

    def _function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        prefix: str,
        ctx: str,
        parent: int | None,
    ) -> None:
        is_async = isinstance(node, ast.AsyncFunctionDef)
        kind = "method" if ctx == "class" else "function"
        name = node.name
        if ctx == "class":
            is_prop, accessor = _decorator_kind(node)
            if is_prop:
                kind = "property"
                if accessor:
                    name = f"{node.name}.{accessor}"
        qual = f"{prefix}{name}"
        ret = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
        sig = f"{'async ' if is_async else ''}{_type_params(node)}({_args_text(node.args)}){ret}"
        start, end = self._range(node)
        idx = len(self.defs)
        self.defs.append(
            Defn(
                qualname=qual,
                kind=kind,
                start=start,
                end=end,
                signature=sig,
                display=f"{'async ' if is_async else ''}def {node.name}"
                f"{_type_params(node)}({_args_text(node.args)}){ret}",
                body=_body_tokens(node.body),
                decorators=self._decorators(node),
                docstring=ast.get_docstring(node, clean=False),
                parent=parent,
            )
        )
        self.walk(node.body, f"{qual}.<locals>.", "function", idx)

    def _lambda(
        self,
        stmt: ast.stmt,
        bound: tuple[str, ast.Lambda],
        prefix: str,
        parent: int | None,
    ) -> None:
        name, lam = bound
        body: list[str] = []
        _fp(lam.body, body)
        sig = f"({_args_text(lam.args)})"
        self.defs.append(
            Defn(
                qualname=f"{prefix}{name}",
                kind="lambda",
                start=stmt.lineno,
                end=stmt.end_lineno or stmt.lineno,
                signature=sig,
                display=f"{name} = lambda {_args_text(lam.args)}",
                body=tuple(body),
                parent=parent,
            )
        )


def _nested_bodies(stmt: ast.stmt) -> list[list[ast.stmt]]:
    bodies: list[list[ast.stmt]] = []
    for name in ("body", "orelse", "finalbody"):
        value = getattr(stmt, name, None)
        if isinstance(value, list) and value and isinstance(value[0], ast.stmt):
            bodies.append(value)
    for handler in getattr(stmt, "handlers", []) or []:
        bodies.append(handler.body)
    for case in getattr(stmt, "cases", []) or []:
        bodies.append(case.body)
    return bodies


def _comments(source: str, lines: list[str]) -> list[tuple[int, int, str]]:
    out: list[tuple[int, int, str]] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                out.append((tok.start[0], tok.start[0], tok.string.strip()))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        out = [
            (i, i, text.strip())
            for i, text in enumerate(lines, start=1)
            if text.lstrip().startswith("#")
        ]
    return out


def index_python(source: str) -> FileIndex:
    """Index ``source``; ``parse_error`` is set instead of raising."""

    lines = source.split("\n")
    line_count = len(lines) - 1 if source.endswith("\n") else len(lines)
    index = FileIndex(language="python", line_count=line_count)
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
        lineno = getattr(exc, "lineno", None)
        index.parse_error = f"{type(exc).__name__}" + (f" at line {lineno}" if lineno else "")
        return index

    collector = _Collector()
    collector.walk(tree.body, "", "module", None)
    defs = collector.defs
    for stmt in tree.body:
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            index.import_lines.update(range(stmt.lineno, (stmt.end_lineno or stmt.lineno) + 1))

    module_tokens = _body_tokens(tree.body, skip_imports=True)
    module_doc = ast.get_docstring(tree, clean=False)
    if module_tokens or module_doc is not None:
        index.module_index = len(defs)
        defs.append(
            Defn(
                qualname=MODULE_SYMBOL,
                kind="module",
                start=1,
                end=max(line_count, 1),
                signature="",
                display=MODULE_SYMBOL,
                body=module_tokens,
                docstring=module_doc,
                parent=None,
            )
        )
    dedupe_qualnames(defs)
    link_children(defs)
    index.defs = defs
    index.comments = _comments(source, lines)
    return index
