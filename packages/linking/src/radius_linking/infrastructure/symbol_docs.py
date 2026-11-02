"""Build :class:`SymbolDoc` search documents from an LK-01 ``SymbolChangeSet``.

For each changed symbol the head file (or, for removed symbols, the base file)
is read through the LK-01 ``SnapshotReader`` port and the symbol's line range
is sliced out. Python bodies are analysed with ``ast`` (docstring, referenced
identifiers, string/number literals, decorators; comments via ``tokenize``);
other languages use conservative regexes. A class document excludes the bodies
of nested definitions so a class does not absorb its methods. Nothing here
executes code, touches the network, or raises on bad input: unreadable or
unparsable symbols degrade to a name/path/signature-only document.
"""

from __future__ import annotations

import ast
import io
import re
import textwrap
import tokenize
from collections.abc import Iterable
from typing import Protocol

from radius_analysis.symbol_changes import ChangedSymbol, SymbolChangeSet

from radius_linking.domain import SymbolDoc
from radius_linking.infrastructure.linkers.common import is_test_path

MAX_SLICE_CHARS = 20_000
MAX_ITEMS = 400
_PSEUDO = {"<module>", "<file>"}


class SnapshotLike(Protocol):
    def read(self, path: str) -> bytes | None: ...


_JS_COMMENT = re.compile(r"//([^\n]*)|/\*(.*?)\*/", re.DOTALL)
_HASH_COMMENT = re.compile(r"(?m)^[ \t]*#([^\n]*)")
_STRING = re.compile(
    r"\"((?:[^\"\\\n]|\\.){1,200})\"|'((?:[^'\\\n]|\\.){1,200})'|`([^`\n]{1,200})`"
)
_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w])")
_JSDOC = re.compile(r"/\*\*(.*?)\*/", re.DOTALL)


def _dedup(items: Iterable[str], limit: int = MAX_ITEMS) -> tuple[str, ...]:
    return tuple(dict.fromkeys(i for i in items if i))[:limit]


class _PyCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.identifiers: list[str] = []
        self.literals: list[str] = []
        self.decorators: list[str] = []

    def visit_Name(self, node: ast.Name) -> None:
        self.identifiers.append(node.id)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.identifiers.append(node.attr)
        self.generic_visit(node)

    def visit_arg(self, node: ast.arg) -> None:
        self.identifiers.append(node.arg)

    def visit_keyword(self, node: ast.keyword) -> None:
        if node.arg:
            self.identifiers.append(node.arg)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        v = node.value
        if isinstance(v, str):
            if v.strip() and len(v) <= 300:
                self.literals.append(v.strip())
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            self.literals.append(repr(v))


def _py_doc(src: str, sym: ChangedSymbol) -> dict[str, object] | None:
    try:
        tree = ast.parse(textwrap.dedent(src))
    except (SyntaxError, ValueError):
        return None
    root = next(
        (
            n
            for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ),
        None,
    )
    col = _PyCollector()
    docstring = ""
    if root is None:
        for stmt in tree.body:
            col.visit(stmt)
    else:
        docstring = ast.get_docstring(root) or ""
        col.decorators = [_unparse(d) for d in root.decorator_list]
        for d in root.decorator_list:
            col.visit(d)
        if isinstance(root, ast.ClassDef):
            for stmt in root.body:
                if isinstance(
                    stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    continue  # nested definitions are their own symbols
                if _is_docstring(stmt):
                    continue
                col.visit(stmt)
            for base in root.bases:
                col.visit(base)
        else:
            args = root.args
            for a in [
                *args.posonlyargs,
                *args.args,
                *args.kwonlyargs,
                args.vararg,
                args.kwarg,
            ]:
                if a is not None:
                    col.identifiers.append(a.arg)
                    if a.annotation is not None:
                        col.visit(a.annotation)
            if root.returns is not None:
                col.visit(root.returns)
            for stmt in root.body:
                if _is_docstring(stmt):
                    continue
                col.visit(stmt)
    return {
        "docstring": docstring,
        "identifiers": col.identifiers,
        "literals": col.literals,
        "decorators": col.decorators,
    }


def _is_docstring(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - defensive
        return ""


def _py_comments(src: str) -> list[str]:
    out: list[str] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(textwrap.dedent(src)).readline):
            if tok.type == tokenize.COMMENT:
                out.append(tok.string.lstrip("#").strip())
    except (tokenize.TokenError, IndentationError, SyntaxError):
        out.extend(m.group(1).strip() for m in _HASH_COMMENT.finditer(src))
    return out


def _generic_doc(src: str, language: str) -> dict[str, object]:
    comments: list[str] = []
    if language in {"python", "ruby"}:
        comments = [m.group(1).strip() for m in _HASH_COMMENT.finditer(src)]
        stripped = _HASH_COMMENT.sub("", src)
    else:
        for m in _JS_COMMENT.finditer(src):
            comments.append((m.group(1) or m.group(2) or "").strip())
        stripped = _JS_COMMENT.sub(" ", src)
    docstring = ""
    jsdoc = _JSDOC.search(src)
    if jsdoc:
        docstring = " ".join(
            line.strip().lstrip("*").strip() for line in jsdoc.group(1).splitlines()
        ).strip()
    literals = [
        next(g for g in m.groups() if g is not None) for m in _STRING.finditer(stripped)
    ]
    no_strings = _STRING.sub(" ", stripped)
    literals += _NUMBER.findall(no_strings)
    return {
        "docstring": docstring,
        "comments": comments,
        "identifiers": _IDENT.findall(no_strings),
        "literals": literals,
        "decorators": re.findall(r"(?m)^\s*(@[^\n]+)", src),
    }


def build_symbol_doc(
    sym: ChangedSymbol, head: SnapshotLike, base: SnapshotLike | None = None
) -> SymbolDoc:
    """Build one document; never raises."""

    on_head = sym.new_range is not None
    path = sym.path if on_head else (sym.old_path or sym.path)
    rng = sym.new_range if on_head else sym.old_range
    reader = head if on_head else (base if base is not None else head)
    fields: dict[str, object] = {}
    comments: list[str] = []
    if rng is not None and sym.qualified_name not in _PSEUDO:
        try:
            raw = reader.read(path)
            if raw is not None:
                lines = raw.decode("utf-8", "replace").splitlines()
                src = "\n".join(lines[rng.start - 1 : rng.end])[:MAX_SLICE_CHARS]
                if sym.language == "python":
                    parsed = _py_doc(src, sym)
                    if parsed is not None:
                        fields = parsed
                        comments = _py_comments(src)
                    else:
                        fields = _generic_doc(src, "python")
                        comments = list(fields.pop("comments", []))  # type: ignore[arg-type]
                else:
                    fields = _generic_doc(src, sym.language)
                    comments = list(fields.pop("comments", []))  # type: ignore[arg-type]
        except Exception:  # keep the name/path-only document
            fields = {}
    signature = sym.new_signature or sym.old_signature or ""
    return SymbolDoc(
        symbol_id=sym.symbol_id,
        path=sym.path,
        qualified_name=sym.qualified_name,
        kind=sym.kind,
        language=sym.language,
        change_kind=sym.change_kind.value,
        is_behavioral=sym.is_behavioral,
        signature=signature,
        docstring=str(fields.get("docstring", "")),
        comments=_dedup(comments),
        identifiers=_dedup(fields.get("identifiers", ())),  # type: ignore[arg-type]
        literals=_dedup(fields.get("literals", ())),  # type: ignore[arg-type]
        decorators=_dedup(fields.get("decorators", ())),  # type: ignore[arg-type]
        is_test=is_test_path(sym.path),
    )


def build_symbol_docs(
    changeset: SymbolChangeSet, head: SnapshotLike, base: SnapshotLike | None = None
) -> list[SymbolDoc]:
    """Documents for every changed symbol, in the change set's deterministic order."""

    return [build_symbol_doc(s, head, base) for s in changeset.symbols]
