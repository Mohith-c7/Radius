"""Conservative symbol-level impact analysis for Python (feature F-08).

The file-level graph answers "which files import the changed file". This module
narrows that to "which files contain code that can reach the changed
*symbols*" (functions, methods, classes), using only the standard library
``ast``. It is built to over-approximate:

* A reference is a bare *name* (``Name.id``, ``Attribute.attr``, a function
  parameter name, or a component of a dotted string constant such as
  ``mock.patch("pkg.mod.func")``). A symbol is used by every symbol that
  mentions its simple name anywhere in the repository. Names bound together by
  ``import x as y`` or ``y = x`` are merged, so aliases and re-exports resolve.
* Anything the analysis cannot model returns ``fallback`` for the changed file
  and callers must use the file-level result: module-level edits, deleted
  definitions, implicit protocol methods (dunders other than ``__init__``),
  unparseable files, and dynamic imports / ``eval`` / non-constant ``getattr``
  reachable from a test.

See ``docs/MODULE_ARCHITECTURE.md`` (Symbol-level impact) for the limits.
"""

from __future__ import annotations

import ast
import re
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from posixpath import dirname

MODULE_SYMBOL = "<module>"
ALGO_VERSION = "symbol-impact-v1"

_DOTTED = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
_DYNAMIC_CALLS = frozenset({"__import__", "import_module", "eval", "exec", "globals"})
_FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _is_dunder(name: str) -> bool:
    return len(name) > 4 and name.startswith("__") and name.endswith("__")


@dataclass(frozen=True, slots=True)
class PySymbol:
    """One function, method, class or module pseudo-symbol."""

    path: str
    qualname: str
    kind: str  # function | method | class | module
    start: int
    end: int
    autouse: bool = False

    @property
    def id(self) -> str:
        return f"{self.path}::{self.qualname}"

    @property
    def simple_name(self) -> str:
        return self.qualname.rsplit(".", 1)[-1]


@dataclass(slots=True)
class _FileInfo:
    symbols: list[PySymbol] = field(default_factory=list)
    refs: dict[str, set[str]] = field(default_factory=dict)  # symbol id -> names
    lines: list[str] = field(default_factory=list)
    dynamic: list[str] = field(default_factory=list)
    parse_error: bool = False


@dataclass(frozen=True, slots=True)
class LineMapping:
    """Changed symbols of one file, or why symbol-level analysis is not possible."""

    symbols: tuple[str, ...] = ()  # symbol ids
    names: tuple[str, ...] = ()  # extra seed names (e.g. changed class attributes)
    fallback_reason: str | None = None


@dataclass(frozen=True, slots=True)
class SymbolImpact:
    """Impact of the changes to one file, at symbol level."""

    changed_file: str
    fallback_reason: str | None = None
    changed_symbols: tuple[str, ...] = ()
    impacted_symbols: frozenset[str] = frozenset()
    impacted_files: frozenset[str] = frozenset()
    # File-level dependents of files whose import-time code is impacted.
    module_reached_files: frozenset[str] = frozenset()
    # For each impacted symbol id: the symbol it was reached from (None = seed).
    parents: Mapping[str, str | None] = field(default_factory=dict)
    broad_scopes: frozenset[str] = frozenset()  # directories: every test below is impacted

    @property
    def is_symbol_level(self) -> bool:
        return self.fallback_reason is None

    def chain(self, symbol_id: str) -> tuple[str, ...]:
        """Return ``symbol_id -> ... -> changed symbol`` for reasoning output."""

        out: list[str] = []
        current: str | None = symbol_id
        while current is not None and current not in out:
            out.append(current)
            current = self.parents.get(current)
        return tuple(out)


class PythonSymbolGraph:
    """Name-based symbol index over a set of Python sources."""

    def __init__(self, sources: Mapping[str, str]) -> None:
        self._files: dict[str, _FileInfo] = {}
        self._alias: dict[str, str] = {}
        for path in sorted(sources):
            self._files[path] = self._analyze_file(path, sources[path])
        self._by_id = {
            sym.id: sym for info in self._files.values() for sym in info.symbols
        }
        self._users: dict[str, list[str]] = {}
        for info in self._files.values():
            for symbol_id, names in info.refs.items():
                for name in names:
                    self._users.setdefault(self._canon(name), []).append(symbol_id)
        for users in self._users.values():
            users.sort()

    # ------------------------------------------------------------------ build
    def _analyze_file(self, path: str, source: str) -> _FileInfo:
        info = _FileInfo(lines=source.splitlines())
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError):
            info.parse_error = True
            return info
        module = PySymbol(path, MODULE_SYMBOL, "module", 1, max(len(info.lines), 1))
        info.symbols.append(module)
        info.refs[module.id] = set()
        for node in ast.walk(tree):
            self._collect_alias(node)
            self._collect_dynamic(node, info)
        self._collect_body(tree.body, path, "", None, info, module)
        return info

    def _collect_body(
        self,
        body: list[ast.stmt],
        path: str,
        prefix: str,
        owner_kind: str | None,
        info: _FileInfo,
        owner: PySymbol,
    ) -> None:
        """Register defs found in ``body``; other statements belong to ``owner``."""

        for stmt in body:
            if isinstance(stmt, _FUNC):
                kind = "method" if owner_kind == "class" else "function"
                sym = PySymbol(
                    path, prefix + stmt.name, kind, self._start(stmt), stmt.end_lineno or stmt.lineno,
                    autouse=self._autouse(stmt),
                )
                info.symbols.append(sym)
                info.refs[sym.id] = self._names(stmt, descend=True) | {
                    a.arg for a in self._all_args(stmt)
                }
                # Decorators and default values run when the def executes.
                a = stmt.args
                for expr in (*stmt.decorator_list, *a.defaults, *(d for d in a.kw_defaults if d)):
                    info.refs[owner.id] |= self._names(expr, descend=True)
            elif isinstance(stmt, ast.ClassDef):
                sym = PySymbol(
                    path, prefix + stmt.name, "class", self._start(stmt), stmt.end_lineno or stmt.lineno
                )
                info.symbols.append(sym)
                refs = set()
                for expr in (*stmt.decorator_list, *stmt.bases, *(k.value for k in stmt.keywords)):
                    refs |= self._names(expr, descend=True)
                info.refs[sym.id] = refs
                info.refs[owner.id] |= refs  # evaluated when the class statement runs
                self._collect_body(stmt.body, path, f"{sym.qualname}.", "class", info, sym)
            else:
                nested = self._nested_bodies(stmt)
                if nested:  # if/try/with/for/while: defs inside still count
                    info.refs[owner.id] |= self._names(stmt, descend=False)
                    for inner in nested:
                        self._collect_body(inner, path, prefix, owner_kind, info, owner)
                else:
                    info.refs[owner.id] |= self._names(stmt, descend=False)

    @staticmethod
    def _nested_bodies(stmt: ast.stmt) -> list[list[ast.stmt]]:
        if isinstance(stmt, ast.If | ast.For | ast.AsyncFor | ast.While):
            return [stmt.body, stmt.orelse]
        if isinstance(stmt, ast.With | ast.AsyncWith):
            return [stmt.body]
        if isinstance(stmt, ast.Try) or type(stmt).__name__ == "TryStar":
            return [stmt.body, *(h.body for h in stmt.handlers), stmt.orelse, stmt.finalbody]
        return []

    @staticmethod
    def _start(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> int:
        return min([node.lineno, *(d.lineno for d in node.decorator_list)])

    @staticmethod
    def _all_args(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.arg]:
        a = node.args
        out = [*a.posonlyargs, *a.args, *a.kwonlyargs]
        out += [x for x in (a.vararg, a.kwarg) if x is not None]
        return out

    @staticmethod
    def _autouse(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        for dec in node.decorator_list:
            for kw in getattr(dec, "keywords", ()):
                if kw.arg == "autouse":
                    return True
        return False

    def _names(self, node: ast.AST, *, descend: bool) -> set[str]:
        """Collect referenced names; ``descend=False`` stops at nested defs."""

        names: set[str] = set()
        stack: list[ast.AST] = [node]
        while stack:
            cur = stack.pop()
            if isinstance(cur, ast.Name):
                names.add(cur.id)
            elif isinstance(cur, ast.Attribute):
                names.add(cur.attr)
            elif isinstance(cur, ast.Constant) and isinstance(cur.value, str):
                if len(cur.value) < 200 and _DOTTED.match(cur.value):
                    names.update(cur.value.split("."))
            if not descend and cur is not node and isinstance(cur, _DEFS):
                continue
            stack.extend(ast.iter_child_nodes(cur))
        return names

    def _collect_alias(self, node: ast.AST) -> None:
        if isinstance(node, ast.Import | ast.ImportFrom):
            for alias in node.names:
                if alias.asname and alias.name != "*":
                    self._union(alias.name.split(".")[-1], alias.asname)
        elif isinstance(node, ast.Assign | ast.AnnAssign) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value_names = self._simple_names(node.value)
            for target in targets:
                for t in self._simple_names(target):
                    for v in value_names:
                        self._union(t, v)

    @staticmethod
    def _simple_names(node: ast.AST) -> list[str]:
        if isinstance(node, ast.Name):
            return [node.id]
        if isinstance(node, ast.Attribute):
            return [node.attr]
        if isinstance(node, ast.Tuple | ast.List):
            return [n for e in node.elts for n in PythonSymbolGraph._simple_names(e)]
        if isinstance(node, ast.IfExp):
            return PythonSymbolGraph._simple_names(node.body) + PythonSymbolGraph._simple_names(node.orelse)
        return []

    @staticmethod
    def _collect_dynamic(node: ast.AST, info: _FileInfo) -> None:
        if not isinstance(node, ast.Call):
            return
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
        if name in _DYNAMIC_CALLS:
            info.dynamic.append(f"{name}() at line {node.lineno}")
        elif name == "getattr" and (
            len(node.args) < 2
            or not (isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str))
        ):
            info.dynamic.append(f"getattr() with non-constant name at line {node.lineno}")

    def _canon(self, name: str) -> str:
        root = name
        while self._alias.get(root, root) != root:
            root = self._alias[root]
        # path compression
        while self._alias.get(name, name) != root:
            self._alias[name], name = root, self._alias[name]
        return root

    def _union(self, a: str, b: str) -> None:
        ra, rb = self._canon(a), self._canon(b)
        if ra != rb:
            self._alias[max(ra, rb)] = min(ra, rb)

    # ------------------------------------------------------------- inspection
    @property
    def files(self) -> frozenset[str]:
        return frozenset(self._files)

    def symbols(self, path: str) -> tuple[PySymbol, ...]:
        info = self._files.get(path)
        return tuple(info.symbols) if info else ()

    def dynamic_files(self) -> dict[str, tuple[str, ...]]:
        return {p: tuple(i.dynamic) for p, i in sorted(self._files.items()) if i.dynamic}

    def parse_failed(self, path: str) -> bool:
        info = self._files.get(path)
        return info is None or info.parse_error

    # --------------------------------------------------------- diff -> symbols
    def map_changes(
        self,
        path: str,
        added: Iterable[int],
        deleted_at: Iterable[int] = (),
        deleted_text: Iterable[str] = (),
    ) -> LineMapping:
        """Map changed lines of ``path`` (new-file numbering) to symbols."""

        info = self._files.get(path)
        if info is None:
            return LineMapping(fallback_reason="file not found in symbol index")
        if info.parse_error:
            return LineMapping(fallback_reason="file could not be parsed")
        added, deleted_at = set(added), set(deleted_at)
        if not added and not deleted_at:
            return LineMapping(fallback_reason="no changed lines recorded for file")
        for text in deleted_text:
            stripped = text.strip()
            if re.match(r"(async\s+def|def|class)\s", stripped) or stripped.startswith("@"):
                return LineMapping(fallback_reason="a definition or decorator was deleted")

        # A deletion sits between two lines of the new file: attribute it to both.
        lines = set(added)
        for anchor in deleted_at:
            lines.update({anchor - 1, anchor})
        inner = [s for s in info.symbols if s.kind != "module"]
        found: dict[str, PySymbol] = {}
        extra_names: set[str] = set()
        for line in sorted(lines):
            if line < 1 or line > len(info.lines):
                continue
            text = info.lines[line - 1].strip()
            covering = [s for s in inner if s.start <= line <= s.end]
            if not covering:
                if not text or text.startswith("#"):
                    # Blank/comment outside any definition only counts when it
                    # was added or removed itself; neighbours are not code.
                    continue
                return LineMapping(
                    fallback_reason=f"module-level code changed at line {line}"
                )
            sym = min(covering, key=lambda s: s.end - s.start)
            if sym.kind == "class":
                # Class body statement outside any method.
                if not text or text.startswith("#"):
                    continue
                names = self._class_body_names(info, sym, line)
                if names is None:
                    return LineMapping(
                        fallback_reason=f"unmodelled class-level code changed at line {line}"
                    )
                extra_names.update(names)
                found[sym.id] = sym
                for member in inner:
                    if member.qualname.startswith(sym.qualname + "."):
                        found[member.id] = member
                continue
            if sym.kind == "method" and _is_dunder(sym.simple_name) and sym.simple_name != "__init__":
                return LineMapping(
                    fallback_reason=f"implicit protocol method {sym.qualname} changed"
                )
            found[sym.id] = sym
        if not found:
            return LineMapping(fallback_reason="only blank or comment lines changed outside definitions")
        return LineMapping(symbols=tuple(sorted(found)), names=tuple(sorted(extra_names)))

    @staticmethod
    def _class_body_names(info: _FileInfo, cls: PySymbol, line: int) -> set[str] | None:
        """Names assigned on ``line`` inside class ``cls`` or ``None`` if unmodelled."""

        try:
            tree = ast.parse("\n".join(info.lines))
        except SyntaxError:  # pragma: no cover - parsed once already
            return None
        parts = cls.qualname.split(".")
        scope: list[ast.stmt] = tree.body
        node: ast.ClassDef | None = None
        for part in parts:
            node = next(
                (n for n in _walk_defs(scope) if isinstance(n, ast.ClassDef) and n.name == part), None
            )
            if node is None:
                return None
            scope = node.body
        assert node is not None
        for stmt in node.body:
            end = stmt.end_lineno or stmt.lineno
            if stmt.lineno <= line <= end and not isinstance(stmt, _DEFS):
                if isinstance(stmt, ast.Assign):
                    return {n for t in stmt.targets for n in PythonSymbolGraph._simple_names(t)}
                if isinstance(stmt, ast.AnnAssign):
                    return set(PythonSymbolGraph._simple_names(stmt.target))
                if isinstance(stmt, ast.Pass) or (
                    isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
                ):
                    return set()  # docstring / pass
                return None
        return set()  # the line belongs to the class header (decorators/bases)

    # ------------------------------------------------------------ reachability
    def impact(
        self,
        changed_file: str,
        mapping: LineMapping,
        *,
        dependents_of: Callable[[str], frozenset[str]],
    ) -> SymbolImpact:
        """Reverse-reachability from the changed symbols.

        ``dependents_of(path)`` returns every file that transitively imports
        ``path`` (see ``traversal.file_dependents``); it is used when a module's
        import-time code is impacted.
        """

        if mapping.fallback_reason is not None:
            return SymbolImpact(changed_file, fallback_reason=mapping.fallback_reason)

        parents: dict[str, str | None] = {}
        queue: deque[str] = deque()
        for sid in mapping.symbols:
            parents[sid] = None
            queue.append(sid)
        seed_names = {self._canon(n) for n in mapping.names}
        for canon in sorted(seed_names):
            for user in self._users.get(canon, ()):
                if user not in parents:
                    parents[user] = mapping.symbols[0] if mapping.symbols else None
                    queue.append(user)
        modules_reached: set[str] = set()
        broad: set[str] = set()
        fallback: str | None = None
        while queue and fallback is None:
            cur_id = queue.popleft()
            cur = self._by_id[cur_id]
            if cur.kind == "module":
                modules_reached.add(cur.path)
                continue
            if cur_id not in mapping.symbols and cur.kind == "method" and (
                _is_dunder(cur.simple_name) and cur.simple_name != "__init__"
            ):
                fallback = f"impact reaches implicit protocol method {cur.id}"
                break
            if cur.autouse or (
                cur.path.rsplit("/", 1)[-1] == "conftest.py" and cur.simple_name.startswith("pytest_")
            ):
                broad.add(dirname(cur.path))
            names = {self._canon(cur.simple_name)}
            if cur.kind == "method" and cur.simple_name == "__init__":
                names.add(self._canon(cur.qualname.rsplit(".", 2)[-2]))
            related: list[str] = []
            if cur.kind == "class":  # class-level dependency taints its members
                related = [
                    s.id
                    for s in self.symbols(cur.path)
                    if s.qualname.startswith(cur.qualname + ".")
                ]
            for name in sorted(names):
                for user in self._users.get(name, ()):
                    if user not in parents:
                        parents[user] = cur_id
                        queue.append(user)
            for rel in related:
                if rel not in parents:
                    parents[rel] = cur_id
                    queue.append(rel)
        if fallback is not None:
            return SymbolImpact(changed_file, fallback_reason=fallback)

        impacted_files = {self._by_id[sid].path for sid in parents} | {changed_file}
        reached_files: set[str] = set()
        for module_path in modules_reached:
            reached_files |= dependents_of(module_path) | {module_path}
        return SymbolImpact(
            changed_file=changed_file,
            changed_symbols=mapping.symbols,
            impacted_symbols=frozenset(parents),
            impacted_files=frozenset(impacted_files),
            module_reached_files=frozenset(reached_files),
            parents=dict(parents),
            broad_scopes=frozenset(broad),
        )


def _walk_defs(body: list[ast.stmt]) -> Iterable[ast.stmt]:
    for stmt in body:
        yield stmt
        for inner in PythonSymbolGraph._nested_bodies(stmt):
            yield from _walk_defs(inner)
