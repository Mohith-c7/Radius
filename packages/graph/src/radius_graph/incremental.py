"""Incremental graph builds: patch a base commit's snapshot instead of parsing everything.

The full build (:meth:`GraphApplicationService.build_graph`) is a union of per-file
fragments. A file's fragment (its file, symbol, import and export nodes and the edges
leaving its file and import nodes) depends only on its own content, except for the
``file -> file`` ``depends_on`` edges, which come from resolving its imports against
the set of parsed repository files (:class:`ModuleResolver`) and the tsconfig files.
Module nodes are shared and keyed by the import source.

So the head graph equals the base graph with the fragments of these files rebuilt:

* files changed between base and head (re-parsed; deleted ones dropped);
* files the base build could not parse (re-parsed, so the failure list is exact);
* unchanged files whose import resolution can differ because the set of parsed files
  changed (a file was added, deleted, or started or stopped parsing). An import lookup
  can only hit a new or vanished path through a candidate that contains that path's
  module name (taken from the import text) or, for relative imports, the importer's own
  directory. Unchanged importers whose text contains a changed path's name, or whose
  relative imports start at or below its directory, are rebuilt; this over-approximates.

Anything this reasoning does not cover raises :class:`IncrementalUnavailable` and the
caller does a full build: a changed tsconfig/jsconfig file or a JSON file one of them
``extends``, an exact (non-wildcard) tsconfig ``paths`` alias when the set of files
changes, a base snapshot that does not match the head tree, or an edge left dangling.
"""

from __future__ import annotations

import functools
import hashlib
import importlib.metadata
import posixpath
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from radius_parser.domain.entities import ParsedSourceFile, SourceFile

from radius_graph.domain.entities import DependencyGraph, GraphEdge, GraphNode
from radius_graph.domain.enums import GraphNodeType
from radius_graph.domain.value_objects import GraphNodeId
from radius_graph.infrastructure.module_resolver import ModuleResolver

#: Bump whenever parser output or graph construction changes, so snapshots built by
#: older code are never patched (they are only reused when the fingerprint matches).
GRAPH_BUILD_REVISION = "1"
#: Format of the stored ``graph_version`` before build fingerprints existed.
GRAPH_FORMAT_VERSION = "v1"
_GRAMMAR_PACKAGES = (
    "tree-sitter",
    "tree-sitter-javascript",
    "tree-sitter-typescript",
    "tree-sitter-go",
    "tree-sitter-java",
    "tree-sitter-rust",
)
_PACKAGE_STEMS = frozenset({"__init__", "index"})


class IncrementalUnavailable(Exception):  # noqa: N818 - a fallback signal, not an error
    """An incremental build is not provably identical here; build the full graph."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@functools.cache
def build_fingerprint() -> str:
    """``graph_version`` stored with every snapshot this code builds.

    It covers everything that decides the graph besides the files: this module's
    revision, the Python version (``ast`` output) and the tree-sitter grammar versions.
    A snapshot is reused as an incremental base only when its fingerprint is equal.
    """

    parts = [GRAPH_BUILD_REVISION, f"py{sys.version_info.major}.{sys.version_info.minor}"]
    for package in _GRAMMAR_PACKAGES:
        try:
            parts.append(f"{package}={importlib.metadata.version(package)}")
        except importlib.metadata.PackageNotFoundError:
            parts.append(f"{package}=-")
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]
    return f"{GRAPH_FORMAT_VERSION}+{digest}"


@dataclass(frozen=True, slots=True)
class ParsedBatch:
    """Parser output for the files an incremental build re-parsed."""

    parsed_files: tuple[ParsedSourceFile, ...]
    parse_failures: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IncrementalBuild:
    """The patched head graph (sorted like a stored snapshot) and what it took."""

    graph: DependencyGraph
    parse_failures: tuple[str, ...]
    reparsed_files: int
    reresolved_importers: int


def patch_graph(
    base: DependencyGraph,
    *,
    head_files: Sequence[SourceFile],
    changed_paths: Iterable[str],
    parse: Callable[[Sequence[SourceFile]], ParsedBatch],
    repository_path: Path,
    add_fragment: Callable[
        [ParsedSourceFile, dict[GraphNodeId, GraphNode], set[GraphEdge], ModuleResolver], None
    ],
) -> IncrementalBuild:
    """Return the head graph by patching ``base`` (the graph of an ancestor commit).

    ``head_files`` are the head checkout's parseable source files in discovery order
    (the order of a full build). ``changed_paths`` are every path that differs between
    the base commit and the head (added, modified, deleted; renames as delete + add).
    ``add_fragment`` is the full build's per-file step, so both builds share it.
    Raises :class:`IncrementalUnavailable` whenever equality with a full build is not
    guaranteed.
    """

    changed = frozenset(_normalize(path) for path in changed_paths)

    if _reaches_through_symlink(head_files, repository_path):
        # Content behind a symlink can change without the linked path changing in git.
        raise IncrementalUnavailable("a source file is reached through a symlink")
    head_by_path = {item.path.value: item for item in head_files}
    files_by_path: dict[str, GraphNodeId] = {}
    imports_by_path: dict[str, list[str]] = {}
    for node in base.nodes:
        if node.path is None:
            continue
        if node.node_type == GraphNodeType.FILE:
            files_by_path[node.path] = node.id
        elif node.node_type == GraphNodeType.IMPORT:
            imports_by_path.setdefault(node.path, []).append(node.label)
    base_files = frozenset(files_by_path)

    vanished = base_files - head_by_path.keys()
    if vanished - changed:
        raise IncrementalUnavailable("base snapshot has files the head does not")
    # Changed files, plus unchanged files the base could not parse (re-parsed so the
    # head's parse failures are exact; they must fail again).
    first_pass = [
        item
        for item in head_files
        if item.path.value in changed or item.path.value not in base_files
    ]
    batch = parse(first_pass)
    parsed = {item.source_file.path.value: item for item in batch.parsed_files}
    unchanged_missing = {
        item.path.value for item in first_pass if item.path.value not in changed
    }
    if unchanged_missing & parsed.keys():
        raise IncrementalUnavailable("base snapshot is missing a parseable unchanged file")

    head_ok = (base_files - changed) | parsed.keys()
    added = head_ok - base_files
    removed = base_files - head_ok
    affected = sorted(added | removed)

    resolver = ModuleResolver(
        tuple(
            parsed.get(item.path.value) or ParsedSourceFile(source_file=item)
            for item in head_files
            if item.path.value in head_ok
        ),
        repository_path=repository_path,
    )
    config_changes = _resolver_config_changes(resolver, changed)
    if config_changes:
        raise IncrementalUnavailable(f"configuration changed: {config_changes[0]}")
    importers: list[SourceFile] = []
    if affected:
        if _has_exact_ts_alias(resolver):
            raise IncrementalUnavailable("an exact tsconfig paths alias with a changed file set")
        importers = [
            head_by_path[path]
            for path in sorted((base_files - changed) & imports_by_path.keys())
            if _may_resolve_differently(
                path, imports_by_path[path], head_by_path[path], affected
            )
        ]
    failures = list(batch.parse_failures)
    if importers:
        second = parse(importers)
        if second.parse_failures or len(second.parsed_files) != len(importers):
            raise IncrementalUnavailable("an unchanged importer no longer parses")
        parsed.update((item.source_file.path.value, item) for item in second.parsed_files)

    rebuilt_paths = (base_files & changed) | {item.path.value for item in importers}
    dropped = {node.id for node in base.nodes if node.path in rebuilt_paths}
    nodes: dict[GraphNodeId, GraphNode] = {
        node.id: node for node in base.nodes if node.id not in dropped
    }
    edges: set[GraphEdge] = {edge for edge in base.edges if edge.source_id not in dropped}
    for path in [item.path.value for item in head_files]:
        fragment = parsed.get(path)
        if fragment is not None and (path in changed or path in rebuilt_paths or path in added):
            add_fragment(fragment, nodes, edges, resolver)
    _prune_module_nodes(nodes)
    for edge in edges:
        if edge.source_id not in nodes or edge.target_id not in nodes:
            raise IncrementalUnavailable("an edge points at a node that no longer exists")
    graph = DependencyGraph(
        nodes=tuple(sorted(nodes.values(), key=lambda node: node.id.value)),
        edges=tuple(
            sorted(
                edges,
                key=lambda edge: (
                    edge.source_id.value,
                    edge.target_id.value,
                    edge.edge_type.value,
                ),
            )
        ),
    )
    return IncrementalBuild(
        graph=graph,
        parse_failures=tuple(failures),
        reparsed_files=len(first_pass) + len(importers),
        reresolved_importers=len(importers),
    )


def _reaches_through_symlink(head_files: Sequence[SourceFile], repository_path: Path) -> bool:
    """Whether any source file, or a directory between it and the root, is a symlink."""

    root = repository_path.resolve()
    seen: set[Path] = set()
    for item in head_files:
        if item.absolute_path is None:
            return True
        current = item.absolute_path
        while current not in seen and current != root and current != current.parent:
            seen.add(current)
            if current.is_symlink():
                return True
            current = current.parent
    return False


def _normalize(path: str) -> str:
    return posixpath.normpath(path.replace("\\", "/"))


def _module_tokens(path: str) -> tuple[str | None, str]:
    """``(name an importer must spell, directory)`` of a path that appeared or vanished.

    The name is the file name up to its first dot (``x.d.ts`` -> ``x``); for a package
    file (``__init__``, ``index``) it is the package directory's name. ``None`` means no
    name is required (a package at the repository root), so every importer is rebuilt.
    """

    directory, name = posixpath.split(path)
    stem = name.split(".", 1)[0]
    if stem in _PACKAGE_STEMS:
        stem = posixpath.basename(directory)
    return (stem or None, directory)


def _may_resolve_differently(
    path: str,
    import_sources: Sequence[str],
    source_file: SourceFile,
    affected: Sequence[str],
) -> bool:
    """Whether an unchanged importer can resolve an import differently at the head."""

    directory = posixpath.dirname(path)
    relative = any(source.startswith(".") for source in import_sources)
    names: set[str] = set()
    for item in affected:
        name, item_directory = _module_tokens(item)
        if name is None:
            return True
        names.add(name)
        # Relative imports build candidates from the importer's directory upwards.
        if relative and (
            not item_directory
            or directory == item_directory
            or directory.startswith(f"{item_directory}/")
        ):
            return True
    try:
        text = (
            source_file.absolute_path.read_text(encoding="utf-8", errors="replace")
            if source_file.absolute_path is not None
            else None
        )
    except OSError:
        return True
    if text is None:
        return True
    return any(name in text for name in names)


def _resolver_config_changes(resolver: ModuleResolver, changed: frozenset[str]) -> list[str]:
    """Changed JSON files that can change import resolution (tsconfig, jsconfig, extends).

    A ``tsconfig*``/``jsconfig*`` file counts wherever it is (it may start or stop
    governing a directory); any other JSON file counts when the resolver read it.
    """

    reads = getattr(getattr(resolver, "_ts", None), "config_files", None)
    found = []
    for path in sorted(changed):
        if not path.lower().endswith(".json"):
            continue
        name = posixpath.basename(path).lower()
        if reads is None or name.startswith(("tsconfig", "jsconfig")) or path in reads:
            found.append(path)
    return found


def _has_exact_ts_alias(resolver: ModuleResolver) -> bool:
    configs = getattr(getattr(resolver, "_ts", None), "_configs", None)
    if configs is None:
        return True
    return any("*" not in pattern for config in configs.values() for pattern in config.paths)


def _prune_module_nodes(nodes: dict[GraphNodeId, GraphNode]) -> None:
    """Drop module nodes no import references any more (a full build never makes them)."""

    wanted = {
        GraphNodeId(f"module:{node.label}")
        for node in nodes.values()
        if node.node_type == GraphNodeType.IMPORT
    }
    for node_id in [
        node.id
        for node in nodes.values()
        if node.node_type == GraphNodeType.MODULE and node.id not in wanted
    ]:
        del nodes[node_id]
