"""Refine file-level dependents with symbol-level impact (feature F-08).

Pure function over data already computed by the pipeline: the unified diff, the
Python sources of the snapshot, the file-level dependents and the dependency
graph. Every changed file either gets a *symbol-level* dependents set (always a
subset of the file-level set, plus tests injected through ``conftest.py``
fixtures) or falls back to its file-level set with a recorded reason.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from posixpath import dirname

from radius_graph.domain.entities import DependencyGraph
from radius_graph.symbol_impact import ALGO_VERSION, PythonSymbolGraph
from radius_graph.traversal import file_dependents

from radius_analysis.diff_hunks import parse_diff_line_changes


@dataclass(frozen=True, slots=True)
class RefinedImpact:
    """Dependents per changed file after symbol-level refinement."""

    dependents: dict[str, frozenset[str]]
    # test path -> human-readable reason tags (symbol path or fallback cause)
    test_evidence: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # changed path -> fallback reason (absent = symbol-level was used)
    fallbacks: dict[str, str] = field(default_factory=dict)
    changed_symbols: tuple[str, ...] = ()
    algo_version: str = ALGO_VERSION


def refine_dependents(
    *,
    diff_text: str | None,
    changed_paths: tuple[str, ...],
    file_level: Mapping[str, frozenset[str]],
    python_sources: Mapping[str, str],
    test_paths: frozenset[str],
    graph: DependencyGraph,
) -> RefinedImpact:
    """Return symbol-refined dependents, never smaller than what is provable."""

    dependents = {path: frozenset(file_level.get(path, frozenset())) for path in changed_paths}
    if not diff_text or not diff_text.strip():
        return RefinedImpact(dependents, fallbacks=_all(changed_paths, "no diff text available"))

    line_changes = parse_diff_line_changes(diff_text)
    symbol_graph = PythonSymbolGraph(python_sources)

    dynamic = symbol_graph.dynamic_files()
    if dynamic:
        reach = file_dependents(graph, sorted(dynamic))
        risky = sorted(
            f for f in dynamic if f in test_paths or reach.get(f, frozenset()) & test_paths
        )
        if risky:
            detail = f"{risky[0]}: {dynamic[risky[0]][0]}"
            reason = f"dynamic code reachable from tests ({detail})"
            # Dynamic imports/getattr can reach any module: keep the file-level
            # result and add every test that contains or reaches such code.
            extra = frozenset(risky) | frozenset(
                t for f in risky for t in reach.get(f, frozenset()) & test_paths
            )
            widened = {
                p: (d | extra if d and p not in test_paths else d) for p, d in dependents.items()
            }
            return RefinedImpact(
                widened,
                test_evidence=_fallback_tags(widened, test_paths, _all(changed_paths, reason)),
                fallbacks=_all(changed_paths, reason),
            )

    cache: dict[str, frozenset[str]] = {}

    def dependents_of(path: str) -> frozenset[str]:
        if path not in cache:
            cache[path] = file_dependents(graph, [path]).get(path, frozenset())
        return cache[path]

    fallbacks: dict[str, str] = {}
    evidence: dict[str, list[str]] = {}
    all_changed_symbols: list[str] = []
    for path in changed_paths:
        norm = path.replace("\\", "/")
        if path in test_paths:
            continue  # changed tests are selected by the file-level rules
        if not norm.endswith(".py"):
            fallbacks[path] = "not a Python file"
            continue
        changes = line_changes.get(norm)
        if changes is None:
            fallbacks[path] = "no hunks for file in diff"
            continue
        mapping = symbol_graph.map_changes(
            norm, changes.added, changes.deleted_at, changes.deleted_text
        )
        impact = symbol_graph.impact(norm, mapping, dependents_of=dependents_of)
        if not impact.is_symbol_level:
            fallbacks[path] = impact.fallback_reason or "unknown"
            continue
        if not file_level.get(path):
            fallbacks[path] = "file is not in the dependency graph"
            continue
        all_changed_symbols.extend(impact.changed_symbols)
        allowed = set(file_level[path])
        for member in file_level[path]:
            if member.rsplit("/", 1)[-1] == "conftest.py":
                allowed |= {t for t in test_paths if _under(t, dirname(member))}
        candidates = set(impact.impacted_files) | set(impact.module_reached_files)
        for scope in impact.broad_scopes:
            candidates |= {t for t in test_paths if _under(t, scope)}
        refined = frozenset((candidates & allowed) | {path})
        dependents[path] = refined
        for test in sorted(refined & test_paths):
            evidence.setdefault(test, []).append(_tag(impact, test, norm))

    for tag_path, tags in _fallback_tags(dependents, test_paths, fallbacks).items():
        evidence.setdefault(tag_path, []).extend(tags)
    return RefinedImpact(
        dependents=dependents,
        test_evidence={k: tuple(dict.fromkeys(v)) for k, v in sorted(evidence.items())},
        fallbacks=fallbacks,
        changed_symbols=tuple(sorted(set(all_changed_symbols))),
    )


def _all(paths: tuple[str, ...], reason: str) -> dict[str, str]:
    return dict.fromkeys(paths, reason)


def _under(path: str, directory: str) -> bool:
    return directory == "" or path.startswith(directory + "/")


def _fallback_tags(
    dependents: Mapping[str, frozenset[str]],
    test_paths: frozenset[str],
    fallbacks: Mapping[str, str],
) -> dict[str, tuple[str, ...]]:
    tags: dict[str, list[str]] = {}
    for path, reason in fallbacks.items():
        for test in sorted(dependents.get(path, frozenset()) & test_paths):
            tags.setdefault(test, []).append(f"file-level fallback for {path}: {reason}")
    return {k: tuple(v) for k, v in tags.items()}


def _tag(impact, test: str, changed: str) -> str:  # noqa: ANN001 - SymbolImpact
    in_test = sorted(sid for sid in impact.impacted_symbols if sid.startswith(test + "::"))
    # Prefer a real test symbol over the module pseudo-symbol.
    in_test.sort(key=lambda sid: sid.endswith("::<module>"))
    if in_test:
        chain = " -> ".join(impact.chain(in_test[0]))
        return f"symbol impact: {chain} (changed)"
    if test in impact.module_reached_files:
        return f"symbol impact: import-time code in {changed} reaches {test}"
    return f"symbol impact: pytest scope (autouse fixture/hook) covers {test}"
