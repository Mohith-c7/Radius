"""Static call/reference symbol-to-test linker (LK-03, part 1).

For every discovered test the linker collects *roots* (what the test body, its
fixtures, its ``setUp`` hooks and its module-level code reference), expands them
through project functions up to ``max_depth`` calls (with decay) and matches the
reached entities against the changed symbols.

Reuse: F-08's ``PythonSymbolGraph`` supplies the over-approximate, name-based
reverse reachability that backs the *low-confidence name layer* (references the
resolver cannot type, e.g. ``obj.method()``); the resolver itself
(``pyindex.ProjectIndex``) is import-aware so that name collisions between
modules do not create links.

Scores (documented priors, ``static-link-v1``):

======================================  =====
test body calls the symbol               0.90
class instantiated and method accessed   0.70
symbol referenced / patched, not called  0.55 / 0.50
through a fixture (hop h)                x 0.85 per hop
through project helpers, depth d >= 1    0.75 * 0.7 ** (d - 1)
imported by the test module only         0.20
name-only (F-08 layer) at depth d        0.25 * 0.7 ** (d - 1)
dynamic code in test (low confidence)    0.10
======================================  =====
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass

from radius_graph.symbol_impact import LineMapping, PythonSymbolGraph

from radius_testing.linking.ecmascript import EcmaScriptTestLinker
from radius_testing.linking.model import (
    STATIC_ALGO_VERSION,
    LinkKind,
    LinkSet,
    LinkTarget,
    SymbolTestLink,
    clamp01,
    is_test_path,
)
from radius_testing.linking.pyindex import Entity, FuncRefs, ProjectIndex, TestItem

LINKER = "static"
DEFAULT_MAX_DEPTH = 3
DEFAULT_TIME_BUDGET_SECONDS = 20.0
MAX_BFS_NODES = 5000

SCORE_CALL = 0.90
SCORE_HEUR = 0.70
SCORE_REF = 0.55
SCORE_PATCH = 0.50
SCORE_IMPORT_ONLY = 0.20
SCORE_DYNAMIC = 0.10
FIXTURE_HOP_FACTOR = 0.85
CLASS_ONLY_FACTOR = 0.5
CLASS_MEMBER_FACTOR = 0.85
MODULE_FACTOR = 0.6
_BASE = {"call": SCORE_CALL, "heur": SCORE_HEUR, "ref": SCORE_REF, "patch": SCORE_PATCH}


def indirect_score(depth: int) -> float:
    return 0.75 * 0.7 ** (depth - 1)


def name_layer_score(depth: int) -> float:
    return 0.25 * 0.7 ** (depth - 1)


@dataclass(frozen=True, slots=True)
class _Root:
    entity: Entity | None  # None: a pseudo root (module-level code)
    refs: FuncRefs
    hops: int
    mode_cap: str | None
    label: str


@dataclass(frozen=True, slots=True)
class _Hit:
    target: LinkTarget
    score: float
    kind: LinkKind
    depth: int | None
    evidence: tuple[str, ...]
    low: bool = False


class StaticLinker:
    """Link changed symbols to tests by import-aware static analysis."""

    algo_version = STATIC_ALGO_VERSION

    def __init__(
        self,
        *,
        max_depth: int = DEFAULT_MAX_DEPTH,
        time_budget_seconds: float = DEFAULT_TIME_BUDGET_SECONDS,
        name_layer: bool = True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_depth < 0:
            raise ValueError("max_depth must be >= 0")
        self.max_depth = max_depth
        self.time_budget_seconds = time_budget_seconds
        self.name_layer = name_layer
        self._clock = clock
        self._resolved_names: dict[str, set[str]] = {}

    # ------------------------------------------------------------------ API
    def link(self, sources: Mapping[str, str], targets: Sequence[LinkTarget]) -> LinkSet:
        notes: list[str] = []
        self._resolved_names = {}
        deadline = self._clock() + self.time_budget_seconds
        py_targets = [t for t in targets if t.language == "python"]
        links: dict[tuple[str, str], SymbolTestLink] = {}

        def add(link: SymbolTestLink) -> None:
            old = links.get(link.key)
            if old is None or (link.score, link.evidence) > (old.score, old.evidence):
                links[link.key] = link

        if py_targets:
            index = ProjectIndex(sources)
            if index.parse_failures:
                notes.append("unparseable python files skipped: " + ", ".join(sorted(index.parse_failures)))
            items = index.discover_tests()
            truncated = self._link_python(index, items, py_targets, add, deadline, notes)
            if self.name_layer and not truncated:
                self._name_layer(sources, items, py_targets, add, deadline, notes)
        other = [t for t in targets if t.language != "python"]
        if other:
            ts = EcmaScriptTestLinker().link(sources, other)
            for link in ts.links:
                add(link)
            notes.extend(ts.notes)
        return LinkSet.of(
            links.values(),
            algo_version=self.algo_version,
            notes=notes,
            config={"max_depth": self.max_depth, "name_layer": self.name_layer},
        )

    # ------------------------------------------------------------- python
    def _link_python(
        self,
        index: ProjectIndex,
        items: Iterable[TestItem],
        targets: Sequence[LinkTarget],
        add: Callable[[SymbolTestLink], None],
        deadline: float,
        notes: list[str],
    ) -> bool:
        by_entity: dict[Entity, list[LinkTarget]] = {}
        by_path: dict[str, list[LinkTarget]] = {}
        for t in targets:
            by_entity.setdefault((t.path, t.entity_name), []).append(t)
            by_path.setdefault(t.path, []).append(t)
        reach_cache: dict[Entity, dict[Entity, tuple[int, tuple[Entity, ...]]]] = {}

        def reach(root: Entity) -> dict[Entity, tuple[int, tuple[Entity, ...]]]:
            if root not in reach_cache:
                reach_cache[root] = self._bfs(index, root)
            return reach_cache[root]

        for item in items:
            if self._clock() > deadline:
                notes.append("time budget exhausted: remaining tests were not linked statically")
                return True
            roots = self._roots(index, item)
            hits: dict[str, _Hit] = {}
            reached_names: set[str] = set()
            dynamic = [d for r in roots for d in r.refs.dynamic]

            for root in roots:
                for entity, ref in sorted(root.refs.entities.items()):
                    mode = ref.mode
                    reached = reach(entity)
                    for ent, (depth, chain) in reached.items():
                        reached_names.add(ent[1].rsplit(".", 1)[-1])
                        for tgt, factor, note in self._matches(index, ent, by_entity, by_path):
                            base = _BASE[mode] if depth == 0 else indirect_score(depth) * (
                                0.8 if mode in ("ref", "patch") else 1.0
                            )
                            score = clamp01(base * FIXTURE_HOP_FACTOR**root.hops * factor)
                            if root.hops:
                                kind, kdepth = LinkKind.FIXTURE_DEPENDENCY, root.hops
                            elif depth:
                                kind, kdepth = LinkKind.INDIRECT_CALL, depth
                            elif mode in ("ref", "patch"):
                                kind, kdepth = LinkKind.IMPORT_REFERENCE, None
                            else:
                                kind, kdepth = LinkKind.DIRECT_CALL, None
                            evidence = self._evidence(item, root, ref, chain, ent, note)
                            prev = hits.get(tgt.symbol_id)
                            if prev is None or score > prev.score:
                                hits[tgt.symbol_id] = _Hit(tgt, score, kind, kdepth, evidence)
                reached_names |= root.refs.resolved_names

            for hit in hits.values():
                add(self._to_link(hit, item))

            # import-only: the test module imports the entity but nothing reached it
            for ent, tgts in sorted(by_entity.items()):
                for tgt in tgts:
                    if tgt.symbol_id in hits:
                        continue
                    if self._imports_entity(index, item.path, ent):
                        add(
                            self._to_link(
                                _Hit(tgt, SCORE_IMPORT_ONLY, LinkKind.IMPORT_REFERENCE, None,
                                     (f"{item.path} imports {ent[0]}::{ent[1]} but the test does not reference it",)),
                                item,
                            )
                        )

            if dynamic:
                tops = self._import_tops(index, item.path)
                for tgt in targets:
                    if tgt.symbol_id in hits or tgt.path.split("/")[0] not in tops:
                        continue
                    add(
                        self._to_link(
                            _Hit(tgt, SCORE_DYNAMIC, LinkKind.IMPORT_REFERENCE, None,
                                 (f"dynamic code in test ({dynamic[0]}) may reach any symbol",), True),
                            item,
                        )
                    )
            item_names = reached_names
            self._resolved_names[item.test_id] = item_names
        return False

    def _roots(self, index: ProjectIndex, item: TestItem) -> list[_Root]:
        roots = [_Root(item.definition.entity, index.refs(item.definition.entity), 0, None, item.name)]
        for link in index.fixture_chain(item):
            roots.append(
                _Root(link.fixture.info.entity, index.refs(link.fixture.info.entity), link.hops,
                      None, f"fixture {link.fixture.name} ({link.via})")
            )  # fmt: skip
        for ent in index.setup_entities(item):
            roots.append(_Root(ent, index.refs(ent), 1, None, f"setup hook {ent[1]}"))
        module_refs = index.module_refs(item.path)
        if module_refs.entities or module_refs.dynamic:
            roots.append(_Root(None, module_refs, 1, None, f"module-level code of {item.path}"))
        if item.class_qual is not None:
            cls = (item.path, item.class_qual)
            roots.append(_Root(cls, index.refs(cls), 1, None, f"class {item.class_qual}"))
        return roots

    def _bfs(self, index: ProjectIndex, root: Entity) -> dict[Entity, tuple[int, tuple[Entity, ...]]]:
        """Entities reachable from ``root`` within ``max_depth`` project calls."""

        seen: dict[Entity, tuple[int, tuple[Entity, ...]]] = {root: (0, (root,))}
        queue: deque[Entity] = deque([root])
        while queue and len(seen) < MAX_BFS_NODES:
            cur = queue.popleft()
            depth, chain = seen[cur]
            if depth >= self.max_depth:
                continue
            for callee in sorted(index.refs(cur).entities):
                if callee not in seen:
                    seen[callee] = (depth + 1, (*chain, callee))
                    queue.append(callee)
        return seen

    @staticmethod
    def _matches(
        index: ProjectIndex,
        entity: Entity,
        by_entity: Mapping[Entity, list[LinkTarget]],
        by_path: Mapping[str, list[LinkTarget]],
    ) -> list[tuple[LinkTarget, float, str]]:
        out: list[tuple[LinkTarget, float, str]] = []
        for tgt in by_entity.get(entity, ()):
            out.append((tgt, 1.0, ""))
        path, qual = entity
        # reached a member of a changed class
        parts = qual.split(".")
        for i in range(1, len(parts)):
            for tgt in by_entity.get((path, ".".join(parts[:i])), ()):
                if tgt.kind == "class":
                    out.append((tgt, CLASS_MEMBER_FACTOR, f"member of changed class {tgt.entity_name}"))
        # reached only the class of a changed method
        info = index.definition(entity)
        if info is not None and info.kind == "class":
            for tgt in by_path.get(path, ()):
                if tgt.entity_name.startswith(qual + ".") and tgt.kind != "class":
                    out.append((tgt, CLASS_ONLY_FACTOR, f"class {qual} used; method {tgt.simple_name} not resolved"))
        # module-level code changed: any use of the module is affected
        for tgt in by_path.get(path, ()):
            if tgt.kind == "module" or tgt.qualified_name == "<module>":
                out.append((tgt, MODULE_FACTOR, "module-level code changed; module in use"))
        return out

    @staticmethod
    def _imports_entity(index: ProjectIndex, path: str, entity: Entity) -> bool:
        model = index.files.get(path)
        if model is None:
            return False
        for local, binding in model.imports.items():
            if binding.member is None:
                continue
            found = index.lookup_in_module(path, local)
            if found and found[0] == "ent" and found[1] == entity:
                return True
        return False

    @staticmethod
    def _import_tops(index: ProjectIndex, path: str) -> set[str]:
        tops = {path.split("/")[0]}
        model = index.files.get(path)
        if model is not None:
            for binding in model.imports.values():
                if binding.path:
                    tops.add(binding.path.split("/")[0])
        return tops

    @staticmethod
    def _evidence(
        item: TestItem, root: _Root, ref, chain: tuple[Entity, ...], ent: Entity, note: str  # noqa: ANN001
    ) -> tuple[str, ...]:
        parts: list[str] = []
        if root.hops:
            parts.append(f"via {root.label}")
        if len(chain) > 1:
            parts.append("calls " + " -> ".join(f"{p}::{q}" for p, q in chain))
        else:
            parts.append(f"{ref.mode} `{ref.text}` at line {ref.line}")
        if note:
            parts.append(note)
        return (f"{item.test_id}: " + "; ".join(parts),)

    def _to_link(self, hit: _Hit, item: TestItem) -> SymbolTestLink:
        evidence = list(hit.evidence)
        if item.param_count > 1:
            evidence.append(f"parametrized test ({item.param_count} cases); link is per function")
        return SymbolTestLink(
            symbol_id=hit.target.symbol_id,
            test_id=item.test_id,
            linker=LINKER,
            score=hit.score,
            kind=hit.kind,
            evidence=tuple(evidence),
            depth=hit.depth,
            algo_version=self.algo_version,
            low_confidence=hit.low,
        )

    # --------------------------------------------------- F-08 name layer
    def _name_layer(
        self,
        sources: Mapping[str, str],
        items: Sequence[TestItem],
        targets: Sequence[LinkTarget],
        add: Callable[[SymbolTestLink], None],
        deadline: float,
        notes: list[str],
    ) -> None:
        """Over-approximate name-based reach from F-08 for what the resolver could not type."""

        py_sources = {p: s for p, s in sources.items() if p.endswith(".py")}
        graph = PythonSymbolGraph(py_sources)
        by_symbol_id = {f"{i.path}::{i.definition.qualname}": i for i in items}
        for tgt in targets:
            if self._clock() > deadline:
                notes.append("time budget exhausted: name layer truncated")
                return
            sid = f"{tgt.path}::{tgt.entity_name}"
            if not any(s.id == sid for s in graph.symbols(tgt.path)):
                continue
            impact = graph.impact(tgt.path, LineMapping(symbols=(sid,)), dependents_of=lambda _p: frozenset())
            if not impact.is_symbol_level:
                notes.append(f"name layer skipped for {tgt.symbol_id}: {impact.fallback_reason}")
                continue
            for impacted in sorted(impact.impacted_symbols):
                chain = impact.chain(impacted)
                depth = len(chain) - 1
                if depth < 1 or depth > self.max_depth + 1:
                    continue
                if not is_test_path(impacted.split("::", 1)[0]):
                    continue
                for item in self._items_for_symbol(impacted, by_symbol_id, items):
                    names = self._resolved_names.get(item.test_id, set())
                    if tgt.simple_name in names:
                        continue  # resolved to this symbol (already linked) or to another definition
                    kind = LinkKind.IMPORT_REFERENCE if depth == 1 else LinkKind.INDIRECT_CALL
                    add(
                        SymbolTestLink(
                            symbol_id=tgt.symbol_id,
                            test_id=item.test_id,
                            linker=LINKER,
                            score=clamp01(name_layer_score(depth)),
                            kind=kind,
                            evidence=("name-based (F-08 reachability): " + " <- ".join(chain),),
                            depth=None if depth == 1 else depth - 1,
                            algo_version=self.algo_version,
                            low_confidence=True,
                        )
                    )

    @staticmethod
    def _items_for_symbol(
        impacted: str, by_symbol_id: Mapping[str, TestItem], items: Sequence[TestItem]
    ) -> list[TestItem]:
        if impacted in by_symbol_id:
            return [by_symbol_id[impacted]]
        path, _, qual = impacted.partition("::")
        if qual == "<module>":
            return []
        # a class-level or inherited symbol: every test of that definition
        return [i for i in items if i.definition.path == path and i.definition.qualname == qual]
