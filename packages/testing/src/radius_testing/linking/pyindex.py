"""Import-aware Python project index used by the static and naming linkers.

Pure ``ast`` (no execution, no network). It answers three questions:

* *What does this name/attribute chain refer to?* (``resolve_chain``: imports,
  ``from x import y as z``, module attribute access, re-exports, ``self.x``,
  simple local aliases, dotted patch strings.)
* *Which tests exist?* (``discover_tests``: pytest functions/classes, unittest
  ``TestCase`` subclasses, inheritance from base test classes, parametrisation.)
* *Which fixtures does a test use?* (``fixture_chain``: parameter names,
  ``usefixtures``, autouse, ``conftest.py`` scoping, same-name overrides.)

Resolution is deliberately conservative: when a reference cannot be resolved to a
project definition it is dropped (or reported as an unresolved attribute name
for the low-confidence name layer), never guessed.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from posixpath import dirname

from radius_graph.symbol_impact import _DYNAMIC_CALLS

from radius_testing.linking.model import is_test_path, make_test_id

Entity = tuple[str, str]  # (path, qualified name); "<module>" for a whole module
_FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)
_MAX_REEXPORT_DEPTH = 6
_PATCH_NAMES = frozenset({"patch", "setattr", "delattr", "object", "multiple"})
_SETUP_NAMES = (
    "setUp", "setUpClass", "asyncSetUp", "setup_method", "setup_class", "setup", "teardown",
    "tearDown", "tearDownClass", "asyncTearDown", "teardown_method", "teardown_class",
)  # fmt: skip
_MODULE_SETUP = ("setUpModule", "tearDownModule", "setup_module", "teardown_module")
_STDLIB = frozenset(sys.stdlib_module_names)


@dataclass(frozen=True, slots=True)
class DefInfo:
    path: str
    qualname: str
    kind: str  # function | method | class
    node: ast.AST
    class_qual: str | None
    start: int
    end: int

    @property
    def entity(self) -> Entity:
        return (self.path, self.qualname)


@dataclass(frozen=True, slots=True)
class Binding:
    """What a local import name stands for."""

    path: str | None  # resolved module file (None: external or namespace package)
    dotted: str  # absolute dotted module name as written
    member: str | None  # imported member for ``from m import member``


@dataclass(slots=True)
class FileModel:
    path: str
    tree: ast.Module | None
    defs: dict[str, DefInfo] = field(default_factory=dict)
    imports: dict[str, Binding] = field(default_factory=dict)
    stars: list[str] = field(default_factory=list)  # resolved module paths
    assigns: dict[str, tuple[str, ...]] = field(default_factory=dict)
    raw_imports: list[tuple[str, str | None, str | None, int]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Ref:
    """A resolved reference from a function body to a project entity."""

    mode: str  # call | ref | patch | heur
    line: int
    text: str


@dataclass(slots=True)
class FuncRefs:
    entities: dict[Entity, Ref] = field(default_factory=dict)
    attr_names: set[str] = field(default_factory=set)
    fixtures_named: set[str] = field(default_factory=set)
    usefixtures: list[str] = field(default_factory=list)
    dynamic: list[str] = field(default_factory=list)
    resolved_names: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class FixtureDef:
    name: str
    autouse: bool
    info: DefInfo
    params: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TestItem:
    """One collected test function (parametrised cases are one item)."""

    test_id: str
    path: str  # file the test is collected from
    class_qual: str | None
    name: str
    definition: DefInfo
    framework: str  # pytest | unittest
    param_count: int = 1
    direct_params: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class FixtureLink:
    fixture: FixtureDef
    hops: int
    via: str  # human-readable request chain


def chain_of(node: ast.AST) -> tuple[str, ...] | None:
    """Return ``('a','b','c')`` for a pure ``a.b.c`` Name/Attribute expression."""

    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return tuple(reversed(parts))
    return None


def _decorator_name(dec: ast.expr) -> tuple[str | None, ast.Call | None]:
    call = dec if isinstance(dec, ast.Call) else None
    target = dec.func if call is not None else dec
    chain = chain_of(target)
    return (chain[-1] if chain else None), call


def _const_strs(node: ast.AST | None) -> list[str]:
    if node is None:
        return []
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.List | ast.Tuple | ast.Set):
        return [s for e in node.elts for s in _const_strs(e)]
    return []


class ProjectIndex:
    """Parsed view of a set of Python sources keyed by repo-relative posix path."""

    def __init__(self, sources: Mapping[str, str]) -> None:
        self.files: dict[str, FileModel] = {}
        self._dotted: dict[str, list[str]] = {}
        self._mro_cache: dict[Entity, tuple[Entity, ...]] = {}
        self._refs_cache: dict[Entity, FuncRefs] = {}
        self._module_refs_cache: dict[str, FuncRefs] = {}
        self._fixtures: dict[Entity, FixtureDef] = {}
        self.parse_failures: list[str] = []
        for path in sorted(sources):
            if path.endswith(".py"):
                self.files[path] = self._parse(path, sources[path])
        for path in self.files:
            parts = path[:-3].split("/")
            if parts[-1] == "__init__":
                parts = parts[:-1]
            for i in range(len(parts)):
                if i > 0 and len(parts) - i == 1 and parts[-1] in _STDLIB and parts[0] != "src":
                    continue  # do not let tests/json.py shadow the stdlib json
                self._dotted.setdefault(".".join(parts[i:]), []).append(path)
        for model in self.files.values():
            self._resolve_imports(model)
        for model in self.files.values():
            for info in model.defs.values():
                fx = self._fixture_def(info)
                if fx is not None:
                    self._fixtures[info.entity] = fx

    # ------------------------------------------------------------------ parse
    def _parse(self, path: str, source: str) -> FileModel:
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError):
            self.parse_failures.append(path)
            return FileModel(path, None)
        model = FileModel(path, tree)
        self._collect_defs(tree.body, path, "", None, model)
        for stmt in tree.body:
            self._collect_module_assign(stmt, model)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    model.raw_imports.append((alias.name, None, alias.asname, 0))
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    model.raw_imports.append((node.module or "", alias.name, alias.asname, node.level))
        return model

    def _collect_defs(
        self, body: list[ast.stmt], path: str, prefix: str, cls: str | None, model: FileModel
    ) -> None:
        for stmt in body:
            if isinstance(stmt, _FUNC):
                qual = prefix + stmt.name
                start = min([stmt.lineno, *(d.lineno for d in stmt.decorator_list)])
                model.defs.setdefault(
                    qual,
                    DefInfo(path, qual, "method" if cls else "function", stmt, cls, start, stmt.end_lineno or stmt.lineno),
                )
            elif isinstance(stmt, ast.ClassDef):
                qual = prefix + stmt.name
                start = min([stmt.lineno, *(d.lineno for d in stmt.decorator_list)])
                model.defs.setdefault(
                    qual, DefInfo(path, qual, "class", stmt, cls, start, stmt.end_lineno or stmt.lineno)
                )
                self._collect_defs(stmt.body, path, qual + ".", qual, model)
            elif isinstance(stmt, ast.If | ast.Try | ast.With | ast.For | ast.While):
                for inner in _nested_bodies(stmt):
                    self._collect_defs(inner, path, prefix, cls, model)

    @staticmethod
    def _collect_module_assign(stmt: ast.stmt, model: FileModel) -> None:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target, value = stmt.targets[0], stmt.value
            chain = chain_of(value)
            if isinstance(target, ast.Name) and chain:
                model.assigns[target.id] = chain

    def _resolve_imports(self, model: FileModel) -> None:
        for module, member, asname, level in model.raw_imports:
            if level:
                base = model.path.rsplit("/", 1)[0] if "/" in model.path else ""
                for _ in range(level - 1):
                    base = dirname(base)
                rel = ((base + "/") if base else "") + module.replace(".", "/") if module else base
                path = self._file_for_dir_module(rel) if module else self._init_of(rel)
                dotted = module
            else:
                path = self.module_path(module, model.path)
                dotted = module
            if member == "*":
                if path:
                    model.stars.append(path)
                continue
            if member is None:
                local = asname or module.split(".")[0]
                bind_dotted = module if asname else module.split(".")[0]
                bind_path = path if asname else self.module_path(bind_dotted, model.path)
                model.imports[local] = Binding(bind_path, bind_dotted, None)
            else:
                model.imports[asname or member] = Binding(path, dotted, member)
                if level and not module:  # ``from . import sibling``
                    sub = self._file_for_dir_module(
                        (rel + "/" if rel else "") + member
                    )
                    if sub:
                        model.imports[asname or member] = Binding(sub, member, None)

    def _init_of(self, directory: str) -> str | None:
        cand = (directory + "/__init__.py") if directory else "__init__.py"
        return cand if cand in self.files else None

    def _file_for_dir_module(self, rel: str) -> str | None:
        for cand in (rel + ".py", rel + "/__init__.py"):
            if cand in self.files:
                return cand
        return None

    def module_path(self, dotted: str, near: str = "") -> str | None:
        """Resolve a dotted module name to a project file (closest to ``near`` wins)."""

        if not dotted:
            return None
        cands = self._dotted.get(dotted)
        if not cands:
            return None
        if len(cands) == 1:
            return cands[0]

        def shared(p: str) -> int:
            a, b = p.split("/"), near.split("/")
            n = 0
            for x, y in zip(a, b, strict=False):
                if x != y:
                    break
                n += 1
            return n

        return sorted(cands, key=lambda p: (-shared(p), len(p), p))[0]

    # ---------------------------------------------------------------- lookup
    def definition(self, entity: Entity) -> DefInfo | None:
        model = self.files.get(entity[0])
        return model.defs.get(entity[1]) if model else None

    def lookup_in_module(self, path: str, name: str, depth: int = 0) -> tuple | None:
        """Find ``name`` at module level of ``path``: ``("ent", Entity)`` or ``("mod", path, dotted)``."""

        model = self.files.get(path)
        if model is None or depth > _MAX_REEXPORT_DEPTH:
            return None
        if name in model.defs and "." not in name:
            return ("ent", (path, name))
        if name in model.assigns:
            res = self._walk(model, model.assigns[name], depth + 1)
            if res is not None:
                return res
        binding = model.imports.get(name)
        if binding is not None:
            if binding.member is None:
                return ("mod", binding.path, binding.dotted)
            if binding.path is None:
                return None
            found = self.lookup_in_module(binding.path, binding.member, depth + 1)
            if found is not None:
                return found
            sub = self.module_path(binding.dotted + "." + binding.member, path)
            return ("mod", sub, binding.dotted + "." + binding.member) if sub else None
        for star in model.stars:
            found = self.lookup_in_module(star, name, depth + 1)
            if found is not None:
                return found
        return None

    def _walk(self, model: FileModel, chain: tuple[str, ...], depth: int = 0) -> tuple | None:
        head = self.lookup_in_module(model.path, chain[0], depth)
        return self._follow(head, chain[1:], model.path, depth)[0]

    def _follow(
        self, cur: tuple | None, rest: tuple[str, ...], near: str, depth: int = 0
    ) -> tuple[tuple | None, tuple[str, ...]]:
        """Walk attribute parts from ``cur``; return the last resolved node and the unresolved rest."""

        i = 0
        while cur is not None and i < len(rest):
            part = rest[i]
            if cur[0] == "mod":
                _, mpath, dotted = cur
                nxt = self.lookup_in_module(mpath, part, depth) if mpath else None
                if nxt is None:
                    sub = self.module_path(dotted + "." + part, near)
                    nxt = ("mod", sub, dotted + "." + part) if sub else None
                if nxt is None:
                    break
                cur = nxt
            else:
                member = self.find_member(cur[1], part)
                if member is None:
                    break
                cur = ("ent", member)
            i += 1
        return cur, rest[i:]

    def resolve_chain(
        self,
        path: str,
        chain: tuple[str, ...],
        *,
        class_qual: str | None = None,
        locals_: frozenset[str] = frozenset(),
        aliases: Mapping[str, tuple[str, ...]] | None = None,
    ) -> tuple[tuple | None, tuple[str, ...]]:
        """Resolve an attribute chain used inside ``path`` to a project node."""

        model = self.files.get(path)
        if model is None or not chain:
            return None, chain
        if aliases and chain[0] in aliases and aliases[chain[0]][0] != chain[0]:
            chain = aliases[chain[0]] + chain[1:]
        head = chain[0]
        if head in ("self", "cls") and class_qual is not None and len(chain) > 1:
            member = self.find_member((path, class_qual), chain[1])
            if member is None:
                return None, chain[1:]
            return self._follow(("ent", member), chain[2:], path)
        if head in locals_:
            return None, chain
        return self._follow(self.lookup_in_module(path, head), chain[1:], path)

    def resolve_dotted(self, near: str, dotted: str) -> tuple[tuple | None, tuple[str, ...]]:
        parts = tuple(dotted.split("."))
        for k in range(len(parts), 0, -1):
            mp = self.module_path(".".join(parts[:k]), near)
            if mp is not None:
                if k == len(parts):
                    return ("mod", mp, ".".join(parts)), ()
                return self._follow(("mod", mp, ".".join(parts[:k])), parts[k:], near)
        return None, parts

    # ------------------------------------------------------------ classes/MRO
    def mro(self, cls: Entity) -> tuple[Entity, ...]:
        if cls in self._mro_cache:
            return self._mro_cache[cls]
        self._mro_cache[cls] = (cls,)  # cycle guard
        out: list[Entity] = [cls]
        info = self.definition(cls)
        if info is not None and isinstance(info.node, ast.ClassDef):
            for base in info.node.bases:
                node = base.value if isinstance(base, ast.Subscript) else base
                chain = chain_of(node)
                if not chain:
                    continue
                res, rest = self.resolve_chain(cls[0], chain, class_qual=None)
                if res and res[0] == "ent" and not rest:
                    target = self.definition(res[1])
                    if target is not None and target.kind == "class":
                        for e in self.mro(res[1]):
                            if e not in out:
                                out.append(e)
        result = tuple(out)
        self._mro_cache[cls] = result
        return result

    def find_member(self, cls: Entity, name: str) -> Entity | None:
        info = self.definition(cls)
        if info is None:
            return None
        if info.kind != "class":
            return None
        for klass in self.mro(cls):
            cand = (klass[0], klass[1] + "." + name)
            if self.definition(cand) is not None:
                return cand
        return None

    def class_has_external_base(self, cls: Entity, names: Iterable[str]) -> bool:
        wanted = set(names)
        for klass in self.mro(cls):
            info = self.definition(klass)
            if info is None or not isinstance(info.node, ast.ClassDef):
                continue
            for base in info.node.bases:
                chain = chain_of(base)
                if chain and chain[-1] in wanted:
                    return True
        return False

    # ------------------------------------------------------------------ refs
    def refs(self, entity: Entity) -> FuncRefs:
        cached = self._refs_cache.get(entity)
        if cached is not None:
            return cached
        info = self.definition(entity)
        result = FuncRefs()
        self._refs_cache[entity] = result
        if info is None:
            return result
        if isinstance(info.node, ast.ClassDef):
            nodes: list[ast.AST] = [*info.node.decorator_list, *info.node.bases]
            nodes += [s for s in info.node.body if not isinstance(s, (*_FUNC, ast.ClassDef))]
        else:
            fn = info.node
            assert isinstance(fn, _FUNC)
            nodes = [*fn.decorator_list, *fn.args.defaults, *(d for d in fn.args.kw_defaults if d), *fn.body]
        collector = _Collector(self, info.path, info.class_qual if info.kind == "method" else (
            info.qualname if info.kind == "class" else None
        ), result)
        collector.prime(info.node)
        for n in nodes:
            collector.visit(n)
        collector.finish()
        return result

    def module_refs(self, path: str) -> FuncRefs:
        """References made by module-level statements (executed at import)."""

        cached = self._module_refs_cache.get(path)
        if cached is not None:
            return cached
        result = FuncRefs()
        self._module_refs_cache[path] = result
        model = self.files.get(path)
        if model is None or model.tree is None:
            return result
        collector = _Collector(self, path, None, result)
        for stmt in model.tree.body:
            if isinstance(stmt, ast.Import | ast.ImportFrom):
                continue
            if isinstance(stmt, _FUNC):
                for n in (*stmt.decorator_list, *stmt.args.defaults):
                    collector.visit(n)
            elif isinstance(stmt, ast.ClassDef):
                for n in (*stmt.decorator_list, *stmt.bases):
                    collector.visit(n)
            else:
                collector.visit(stmt)
        collector.finish()
        return result

    # --------------------------------------------------------------- fixtures
    def _fixture_def(self, info: DefInfo) -> FixtureDef | None:
        if not isinstance(info.node, _FUNC):
            return None
        for dec in info.node.decorator_list:
            name, call = _decorator_name(dec)
            if name in ("fixture", "yield_fixture"):
                fname = info.node.name
                autouse = False
                if call is not None:
                    for kw in call.keywords:
                        if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                            fname = str(kw.value.value)
                        if kw.arg == "autouse" and isinstance(kw.value, ast.Constant):
                            autouse = bool(kw.value.value)
                params = tuple(
                    a.arg
                    for a in (*info.node.args.posonlyargs, *info.node.args.args, *info.node.args.kwonlyargs)
                    if a.arg not in ("self", "cls")
                )
                return FixtureDef(fname, autouse, info, params)
        return None

    def fixture_scopes(self, item: TestItem) -> list[tuple[str, ...]]:
        """Ordered fixture scopes visible to ``item``: class MRO, module, conftest chain."""

        scopes: list[tuple[str, ...]] = []
        if item.class_qual is not None:
            for klass in self.mro((item.path, item.class_qual)):
                scopes.append(("class", klass[0], klass[1]))
        scopes.append(("module", item.path))
        directory = dirname(item.path)
        while True:
            conf = (directory + "/conftest.py") if directory else "conftest.py"
            if conf in self.files and conf != item.path:
                scopes.append(("module", conf))
            if not directory:
                break
            directory = dirname(directory)
        return scopes

    def _fixtures_in_scope(self, scope: tuple[str, ...], name: str) -> FixtureDef | None:
        if scope[0] == "class":
            for ent, cand in sorted(self._fixtures.items()):
                if (
                    ent[0] == scope[1]
                    and ent[1].startswith(scope[2] + ".")
                    and "." not in ent[1][len(scope[2]) + 1 :]
                    and cand.name == name
                ):
                    return cand
            return None
        found = self.lookup_in_module(scope[1], name)
        if found and found[0] == "ent" and found[1] in self._fixtures:
            return self._fixtures[found[1]]
        for ent, cand in sorted(self._fixtures.items()):  # fixtures renamed via name=
            if ent[0] == scope[1] and "." not in ent[1] and cand.name == name:
                return cand
        return None

    def find_fixture(
        self, scopes: list[tuple[str, ...]], name: str, start: int = 0
    ) -> tuple[int, FixtureDef] | None:
        for i in range(start, len(scopes)):
            fx = self._fixtures_in_scope(scopes[i], name)
            if fx is not None:
                return i, fx
        return None

    def fixture_chain(self, item: TestItem, *, max_hops: int = 6) -> list[FixtureLink]:
        """All fixtures ``item`` depends on, transitively, with hop counts."""

        scopes = self.fixture_scopes(item)
        refs = self.refs(item.definition.entity)
        requested: list[tuple[str, int, int, str]] = []  # name, start, hops, via
        fn = item.definition.node
        if isinstance(fn, _FUNC):
            for a in (*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs):
                if a.arg not in ("self", "cls") and a.arg not in item.direct_params:
                    requested.append((a.arg, 0, 1, a.arg))
        for name in [*refs.usefixtures, *sorted(refs.fixtures_named), *self._class_usefixtures(item)]:
            requested.append((name, 0, 1, name))
        for scope in scopes:  # autouse fixtures visible to the test
            for ent, fx in sorted(self._fixtures.items()):
                if not fx.autouse:
                    continue
                in_scope = (
                    scope[0] == "class" and ent[0] == scope[1] and ent[1].startswith(scope[2] + ".")
                ) or (scope[0] == "module" and ent[0] == scope[1] and "." not in ent[1])
                if in_scope:
                    requested.append((fx.name, 0, 1, f"autouse {fx.name}"))
        out: dict[Entity, FixtureLink] = {}
        queue = list(requested)
        while queue:
            name, start, hops, via = queue.pop(0)
            if hops > max_hops:
                continue
            found = self.find_fixture(scopes, name, start)
            if found is None:
                continue
            idx, fx = found
            key = fx.info.entity
            if key in out and out[key].hops <= hops:
                continue
            out[key] = FixtureLink(fx, hops, via)
            for param in fx.params:
                queue.append((param, idx + 1 if param == fx.name else 0, hops + 1, f"{via} -> {param}"))
        return sorted(out.values(), key=lambda f: (f.hops, f.fixture.info.path, f.fixture.info.qualname))

    def _class_usefixtures(self, item: TestItem) -> list[str]:
        out: list[str] = []
        if item.class_qual is None:
            return out
        for klass in self.mro((item.path, item.class_qual)):
            info = self.definition(klass)
            if info is None or not isinstance(info.node, ast.ClassDef):
                continue
            for dec in info.node.decorator_list:
                out.extend(_usefixtures_of(dec))
            for stmt in info.node.body:
                if isinstance(stmt, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "pytestmark" for t in stmt.targets
                ):
                    for node in ast.walk(stmt.value):
                        out.extend(_usefixtures_of(node))
        model = self.files.get(item.path)
        if model and model.tree:  # module-level ``pytestmark``
            for stmt in model.tree.body:
                if isinstance(stmt, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "pytestmark" for t in stmt.targets
                ):
                    for node in ast.walk(stmt.value):
                        out.extend(_usefixtures_of(node))
        return out

    def setup_entities(self, item: TestItem) -> list[Entity]:
        """unittest/xunit setup hooks that run around ``item``."""

        out: list[Entity] = []
        if item.class_qual is not None:
            for name in _SETUP_NAMES:
                member = self.find_member((item.path, item.class_qual), name)
                if member is not None:
                    out.append(member)
        for name in _MODULE_SETUP:
            ent = (item.path, name)
            if self.definition(ent) is not None:
                out.append(ent)
        return out

    # ------------------------------------------------------------ test discovery
    def discover_tests(self) -> list[TestItem]:
        items: list[TestItem] = []
        for path in sorted(self.files):
            if not is_test_path(path):
                continue
            model = self.files[path]
            for qual, info in sorted(model.defs.items()):
                if info.kind == "function" and "." not in qual and qual.startswith("test"):
                    if self._fixture_def(info) is not None:
                        continue
                    count, direct = self._parametrization(info)
                    items.append(
                        TestItem(make_test_id(path, None, qual), path, None, qual, info, "pytest", count, direct)
                    )
                elif info.kind == "class" and "." not in qual:
                    items.extend(self._class_items(path, info))
        return items

    def _class_items(self, path: str, cls: DefInfo) -> list[TestItem]:
        entity = cls.entity
        unittest = self.class_has_external_base(entity, ("TestCase", "IsolatedAsyncioTestCase", "AsyncTestCase"))
        if not (unittest or cls.qualname.startswith("Test") or self._inherits_test_class(entity)):
            return []
        if not unittest and self.find_member(entity, "__init__") is not None and not self._inherits_test_class(entity):
            return []  # pytest does not collect classes with __init__
        seen: dict[str, DefInfo] = {}
        for klass in self.mro(entity):
            kinfo = self.definition(klass)
            model = self.files[klass[0]]
            prefix = klass[1] + "."
            for qual, info in model.defs.items():
                if (
                    qual.startswith(prefix)
                    and "." not in qual[len(prefix) :]
                    and info.kind == "method"
                    and info.node.name.startswith("test")  # type: ignore[union-attr]
                ):
                    seen.setdefault(qual[len(prefix) :], info)
            del kinfo
        items = []
        for name, info in sorted(seen.items()):
            if self._fixture_def(info) is not None:
                continue
            count, direct = self._parametrization(info, cls)
            items.append(
                TestItem(
                    make_test_id(path, cls.qualname, name), path, cls.qualname, name, info,
                    "unittest" if unittest else "pytest", count, direct,
                )
            )  # fmt: skip
        return items

    def _inherits_test_class(self, entity: Entity) -> bool:
        return any(
            k != entity and (self.definition(k) is not None) and k[1].split(".")[-1].startswith("Test")
            for k in self.mro(entity)
        )

    @staticmethod
    def _parametrization(info: DefInfo, cls: DefInfo | None = None) -> tuple[int, frozenset[str]]:
        count = 1
        direct: set[str] = set()
        decs: list[ast.expr] = list(getattr(info.node, "decorator_list", []))
        if cls is not None and isinstance(cls.node, ast.ClassDef):
            decs += cls.node.decorator_list
        for dec in decs:
            name, call = _decorator_name(dec)
            if name != "parametrize" or call is None or len(call.args) < 2:
                continue
            indirect = any(kw.arg == "indirect" for kw in call.keywords)
            argnames = _const_strs(call.args[0])
            names = [n.strip() for s in argnames for n in s.split(",") if n.strip()]
            if not indirect:
                direct.update(names)
            values = call.args[1]
            if isinstance(values, ast.List | ast.Tuple):
                count *= max(len(values.elts), 1)
        return count, frozenset(direct)


def _usefixtures_of(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Call):
        chain = chain_of(node.func)
        if chain and chain[-1] == "usefixtures":
            return [s for a in node.args for s in _const_strs(a)]
    return []


def _nested_bodies(stmt: ast.stmt) -> list[list[ast.stmt]]:
    if isinstance(stmt, ast.If | ast.For | ast.While):
        return [stmt.body, stmt.orelse]
    if isinstance(stmt, ast.With):
        return [stmt.body]
    if isinstance(stmt, ast.Try):
        return [stmt.body, *(h.body for h in stmt.handlers), stmt.orelse, stmt.finalbody]
    return []


class _Collector:
    """Collects resolved references of one function/class/module body."""

    def __init__(self, index: ProjectIndex, path: str, class_qual: str | None, out: FuncRefs) -> None:
        self.index = index
        self.path = path
        self.class_qual = class_qual
        self.out = out
        self.locals: set[str] = set()
        self.aliases: dict[str, tuple[str, ...]] = {}
        self.classes_used: dict[Entity, str] = {}

    def prime(self, node: ast.AST) -> None:
        """Pre-scan locals (parameters, stored names) and simple ``x = a.b`` aliases."""

        if isinstance(node, _FUNC):
            a = node.args
            for arg in (*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg):
                if arg is not None:
                    self.locals.add(arg.arg)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Assign) and len(sub.targets) == 1:
                target = sub.targets[0]
                chain = chain_of(sub.value)
                if isinstance(target, ast.Name) and chain:
                    self.aliases[target.id] = chain
                    continue
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                self.locals.add(sub.id)
        # an alias target is a local, but resolves through its right-hand side
        self.locals -= set(self.aliases)

    def finish(self) -> None:
        for cls, text in self.classes_used.items():
            for attr in sorted(self.out.attr_names):
                member = self.index.find_member(cls, attr)
                if member is not None and member not in self.out.entities:
                    self.out.entities[member] = Ref("heur", 0, f"{text} instantiated/used and .{attr} accessed")

    # ------------------------------------------------------------------ walk
    def visit(self, node: ast.AST) -> None:
        if isinstance(node, ast.Call):
            self._call(node)
            return
        chain = chain_of(node) if isinstance(node, ast.Name | ast.Attribute) else None
        if chain is not None:
            self._record(chain, False, getattr(node, "lineno", 0))
            return
        if isinstance(node, ast.Attribute):  # receiver is an expression, e.g. f().x
            self.out.attr_names.add(node.attr)
        if isinstance(node, ast.Constant):
            return
        for child in ast.iter_child_nodes(node):
            self.visit(child)

    def _call(self, node: ast.Call) -> None:
        chain = chain_of(node.func)
        if chain is not None:
            self._record(chain, True, node.lineno)
            self._special(node, chain)
        else:
            self.visit(node.func)
        for arg in node.args:
            self.visit(arg)
        for kw in node.keywords:
            self.visit(kw.value)

    def _special(self, node: ast.Call, chain: tuple[str, ...]) -> None:
        fname = chain[-1]
        if fname in _DYNAMIC_CALLS:
            self.out.dynamic.append(f"{fname}() at line {node.lineno}")
        if fname == "getfixturevalue" and node.args:
            self.out.fixtures_named.update(_const_strs(node.args[0]))
        if fname == "usefixtures":
            self.out.usefixtures.extend(s for a in node.args for s in _const_strs(a))
        if fname == "getattr" or fname == "hasattr":
            const = node.args[1] if len(node.args) > 1 else None
            if fname == "getattr" and not (isinstance(const, ast.Constant) and isinstance(const.value, str)):
                self.out.dynamic.append(f"getattr() with non-constant name at line {node.lineno}")
        if fname in _PATCH_NAMES or fname in ("getattr", "hasattr"):
            self._patch_target(node, fname)

    def _patch_target(self, node: ast.Call, fname: str) -> None:
        args = list(node.args)
        for kw in node.keywords:
            if kw.arg == "target":
                args.insert(0, kw.value)
        if not args:
            return
        first = args[0]
        mode = "ref" if fname in ("getattr", "hasattr") else "patch"
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            dotted = first.value
            if "." in dotted and all(p.isidentifier() for p in dotted.split(".")):
                res, rest = self.index.resolve_dotted(self.path, dotted)
                self._accept(res, rest, mode, node.lineno, f"patch target {dotted!r}")
            return
        obj = chain_of(first)
        if obj and len(args) > 1 and isinstance(args[1], ast.Constant) and isinstance(args[1].value, str):
            name = args[1].value
            if name.isidentifier():
                self._record((*obj, name), False, node.lineno, mode=mode, note=f"{fname}({'.'.join(obj)}, {name!r})")

    def _record(
        self, chain: tuple[str, ...], is_call: bool, line: int, *, mode: str | None = None, note: str = ""
    ) -> None:
        res, rest = self.index.resolve_chain(
            self.path,
            chain,
            class_qual=self.class_qual,
            locals_=frozenset(self.locals),
            aliases=self.aliases,
        )
        text = note or ".".join(chain)
        if res is None:
            if len(chain) > 1:
                self.out.attr_names.add(chain[-1])
            return
        if rest:
            self.out.attr_names.add(rest[0])
        self._accept(res, rest, mode or ("call" if is_call and not rest else "ref"), line, text)

    def _accept(self, res: tuple | None, rest: tuple[str, ...], mode: str, line: int, text: str) -> None:
        if res is None or res[0] != "ent":
            return
        entity = res[1]
        self.out.resolved_names.add(entity[1].rsplit(".", 1)[-1])
        existing = self.out.entities.get(entity)
        if existing is None or _MODE_RANK[mode] > _MODE_RANK[existing.mode]:
            self.out.entities[entity] = Ref(mode, line, text)
        info = self.index.definition(entity)
        if info is not None and info.kind == "class":
            self.classes_used[entity] = text
            if mode == "call":
                init = self.index.find_member(entity, "__init__")
                if init is not None and init not in self.out.entities:
                    self.out.entities[init] = Ref("call", line, f"{text}(...) -> __init__")


_MODE_RANK = {"patch": 0, "ref": 1, "heur": 2, "call": 3}
