"""Best-effort TypeScript/JavaScript test linking (jest / vitest). PARTIAL.

Uses the F-09 tree-sitter grammars through ``radius_parser`` and only models:

* ``import {a as b} from './x'`` / ``import d from './x'`` / ``import * as ns``
  with *relative* specifiers resolved against the repository's files;
* ``describe`` / ``it`` / ``test`` blocks (``.each`` and ``.only`` variants) and
  the identifiers used inside each ``it`` callback.

Not modelled (documented limitation): ``require()``, path aliases (``@/x``,
tsconfig ``paths``), re-exports through barrel files, type information, jest
module mocks (``jest.mock('./x')`` is recorded as an import reference only), and
indirect calls through project helper functions. A link therefore means "the test
file imports the symbol's module and names it", scored below the Python static
linker's direct links.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from posixpath import dirname, normpath

from radius_testing.linking.model import (
    STATIC_ALGO_VERSION,
    LinkKind,
    LinkSet,
    LinkTarget,
    SymbolTestLink,
    is_test_path,
)

SCORE_NAMED_IN_TEST = 0.65
SCORE_IMPORTED_ONLY = 0.20
_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
_BLOCKS = {"describe", "it", "test", "suite"}
_MAX_FILE_BYTES = 1_000_000


@dataclass(frozen=True, slots=True)
class JsTest:
    test_id: str
    path: str
    name: str
    identifiers: frozenset[str]


@dataclass(slots=True)
class _JsFile:
    imports: dict[str, tuple[str, str | None]]  # local -> (resolved path or "", member or None)
    tests: list[JsTest]


def _text(node) -> str:  # noqa: ANN001 - tree-sitter node
    return node.text.decode("utf-8", errors="replace") if node.text else ""


def _unquote(s: str) -> str:
    return s.strip("'\"`")


def _walk(node):  # noqa: ANN001, ANN202
    stack = [node]
    while stack:
        cur = stack.pop()
        yield cur
        stack.extend(reversed(cur.children))


def resolve_specifier(from_path: str, spec: str, files: Sequence[str] | set[str]) -> str | None:
    if not spec.startswith("."):
        return None
    base = normpath((dirname(from_path) + "/" + spec) if dirname(from_path) else spec)
    stem = re.sub(r"\.(?:[cm]?[jt]sx?)$", "", base)
    for cand in (base, *(stem + s for s in _SUFFIXES), *(stem + "/index" + s for s in _SUFFIXES)):
        if cand in files:
            return cand
    return None


def parse_js_test_file(path: str, source: str, files: set[str]) -> _JsFile | None:
    from radius_parser.infrastructure.ecmascript_parser import parse_syntax_tree

    if len(source) > _MAX_FILE_BYTES:
        return None
    suffix = "." + path.rsplit(".", 1)[-1]
    try:
        root, _error = parse_syntax_tree(source, suffix)
    except Exception:  # noqa: BLE001 - grammar problems must never break linking
        return None
    imports: dict[str, tuple[str, str | None]] = {}
    for node in _walk(root):
        if node.type == "import_statement":
            src = node.child_by_field_name("source")
            spec = _unquote(_text(src)) if src is not None else ""
            resolved = resolve_specifier(path, spec, files) or ""
            for sub in _walk(node):
                if sub.type == "import_specifier":
                    name = sub.child_by_field_name("name")
                    alias = sub.child_by_field_name("alias")
                    if name is not None:
                        imports[_text(alias if alias is not None else name)] = (resolved, _text(name))
                elif sub.type == "namespace_import":
                    ids = [c for c in sub.children if c.type == "identifier"]
                    if ids:
                        imports[_text(ids[-1])] = (resolved, "*")
                elif sub.type == "import_clause":
                    for c in sub.children:
                        if c.type == "identifier":
                            imports[_text(c)] = (resolved, "default")
    tests: list[JsTest] = []
    _collect_blocks(root, path, [], tests)
    return _JsFile(imports, tests)


def _collect_blocks(node, path: str, stack: list[str], out: list[JsTest]) -> None:  # noqa: ANN001
    for child in node.children:
        block = _block_call(child)
        if block is None:
            _collect_blocks(child, path, stack, out)
            continue
        kind, title, body = block
        if kind in ("describe", "suite"):
            _collect_blocks(body, path, [*stack, title], out)
        else:
            ids = frozenset(_text(n) for n in _walk(body) if n.type in ("identifier", "property_identifier"))
            out.append(JsTest("::".join([path, *stack, title]), path, title, ids))


def _block_call(node):  # noqa: ANN001, ANN202
    """Return ``(kind, title, callback_body)`` for ``describe('x', () => {...})`` style calls."""

    call = node
    if node.type == "expression_statement" and node.children:
        call = node.children[0]
    if call.type != "call_expression":
        return None
    fn = call.child_by_field_name("function")
    args = call.child_by_field_name("arguments")
    if fn is None or args is None:
        return None
    head = _text(fn).split(".")[0]
    if head not in _BLOCKS:
        return None
    if fn.type == "call_expression":  # it.each(table)('name', fn)
        head = _text(fn.child_by_field_name("function")).split(".")[0]
    named = [c for c in args.children if c.is_named]
    if len(named) < 2 or named[0].type not in ("string", "template_string"):
        return None
    return head, _unquote(_text(named[0])), named[-1]


class EcmaScriptTestLinker:
    """Partial jest/vitest linker; see the module docstring for what it ignores."""

    algo_version = STATIC_ALGO_VERSION

    def link(self, sources: Mapping[str, str], targets: Sequence[LinkTarget]) -> LinkSet:
        files = set(sources)
        by_path: dict[str, list[LinkTarget]] = {}
        for t in targets:
            by_path.setdefault(t.path, []).append(t)
        links: list[SymbolTestLink] = []
        notes: list[str] = []
        parsed_any = False
        for path in sorted(sources):
            if not is_test_path(path) or path.endswith(".py"):
                continue
            parsed = parse_js_test_file(path, sources[path], files)
            if parsed is None:
                notes.append(f"could not parse {path}; skipped")
                continue
            parsed_any = True
            for local, (resolved, member) in sorted(parsed.imports.items()):
                for tgt in by_path.get(resolved, ()):
                    simple = tgt.simple_name
                    cls = tgt.entity_name.split(".")[0]
                    if member not in (simple, cls, "*", "default"):
                        continue
                    for test in parsed.tests or [JsTest(path, path, path, frozenset())]:
                        used = local in test.identifiers and (member != "*" or simple in test.identifiers)
                        links.append(
                            SymbolTestLink(
                                symbol_id=tgt.symbol_id,
                                test_id=test.test_id,
                                linker="static",
                                score=SCORE_NAMED_IN_TEST if used else SCORE_IMPORTED_ONLY,
                                kind=LinkKind.IMPORT_REFERENCE if not used else LinkKind.DIRECT_CALL,
                                evidence=(
                                    f"{path} imports `{local}` from {resolved}"
                                    + ("; identifier used in test body" if used else "; not used in this test"),
                                    "partial TS/JS analysis: no type resolution, no re-exports",
                                ),
                                algo_version=self.algo_version,
                                low_confidence=True,
                            )
                        )
        if by_path and not parsed_any:
            notes.append("no parseable jest/vitest test files found for TypeScript/JavaScript symbols")
        return LinkSet.of(links, algo_version=self.algo_version, notes=notes)


def discover_js_tests(sources: Mapping[str, str]) -> list[JsTest]:
    """Test records for the naming linker (``describe > it`` ids)."""

    files = set(sources)
    out: list[JsTest] = []
    for path in sorted(sources):
        if is_test_path(path) and not path.endswith(".py"):
            parsed = parse_js_test_file(path, sources[path], files)
            if parsed is not None:
                out.extend(parsed.tests or [JsTest(path, path, path, frozenset())])
    return out
