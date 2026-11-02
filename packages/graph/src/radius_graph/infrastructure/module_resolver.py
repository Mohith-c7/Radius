"""Deterministic repository-local import resolver."""

from __future__ import annotations

import json
import os
import posixpath
import re
from pathlib import Path, PurePosixPath

from radius_parser.domain.entities import ParsedSourceFile

from radius_graph.domain.value_objects import GraphNodeId
from radius_graph.infrastructure.ts_resolver import TsModuleResolver, is_js_ts_path


class ModuleResolver:
    """Resolve parser import references to repository file graph nodes."""

    def __init__(
        self,
        parsed_files: tuple[ParsedSourceFile, ...],
        path_aliases: dict[str, tuple[str, ...]] | None = None,
        repository_path: Path | None = None,
    ) -> None:
        self._index = self._build_index(parsed_files)
        self._aliases = dict(path_aliases or {})
        self._ts = TsModuleResolver(
            {
                self._normalize_path(item.source_file.path.value)
                for item in parsed_files
                if is_js_ts_path(item.source_file.path.value)
            },
            repository_path if repository_path and repository_path.is_dir() else None,
        )

    def resolve(
        self,
        importer_path: str,
        source: str,
    ) -> GraphNodeId | None:
        """Return the imported file node id when the import is repository-local."""

        if is_js_ts_path(importer_path):
            resolved = self._ts.resolve(importer_path, source)
            if resolved is not None:
                return GraphNodeId(f"file:{resolved}")
            # Bare specifiers that the tsconfig cannot map are external
            # packages; only relative imports or explicit legacy aliases may
            # still match through the generic index below.
            if not source.startswith(".") and not self._aliases:
                return None

        for candidate in self._candidates(importer_path, source):
            node_id = self._index.get(candidate)
            if node_id is not None:
                return node_id
        for target in self._alias_targets(source):
            for candidate in (target, f"{target}/__init__", f"{target}/index"):
                node_id = self._index.get(self._normalize_path(candidate))
                if node_id is None:
                    node_id = self._index.get(
                        PurePosixPath(self._normalize_path(candidate)).with_suffix("").as_posix()
                    )
                if node_id is not None:
                    return node_id
        return None

    def is_external(self, importer_path: str, source: str) -> bool:
        """Return whether an import does not resolve to a repository file.

        Bare package names (``react``) and unresolvable aliases are external,
        which is a classification, not an error.
        """

        return self.resolve(importer_path, source) is None

    def _alias_targets(self, source: str) -> tuple[str, ...]:
        """Expand TypeScript ``paths`` patterns (single ``*`` wildcard)."""

        if source.startswith((".", "/")):
            return ()
        targets: list[str] = []
        # Exact patterns first, then wildcards with the longest prefix (TS semantics).
        ordered = sorted(
            self._aliases.items(),
            key=lambda item: ("*" in item[0], -len(item[0].split("*", 1)[0])),
        )
        for pattern, replacements in ordered:
            if "*" not in pattern:
                if source == pattern:
                    targets.extend(replacements)
                continue
            prefix, suffix = pattern.split("*", 1)
            if source.startswith(prefix) and source.endswith(suffix) and len(source) >= len(
                prefix
            ) + len(suffix):
                matched = source[len(prefix) : len(source) - len(suffix) if suffix else None]
                targets.extend(item.replace("*", matched, 1) for item in replacements)
        return tuple(targets)

    def resolve_all(
        self,
        importer_path: str,
        source: str,
        names: tuple[str, ...] = (),
    ) -> tuple[GraphNodeId, ...]:
        """Resolve an import, including ``from package import submodule`` forms.

        ``from shop import cart`` depends on ``shop/__init__.py`` *and* on
        ``shop/cart.py`` when that submodule exists. Both edges are returned.
        """

        resolved: list[GraphNodeId] = []
        package = self.resolve(importer_path, source)
        if package is not None:
            resolved.append(package)
        separator = "" if source.endswith(".") else "."
        for name in names:
            submodule = self.resolve(importer_path, f"{source}{separator}{name}")
            if submodule is not None and submodule not in resolved:
                resolved.append(submodule)
        return tuple(resolved)

    @classmethod
    def _build_index(
        cls,
        parsed_files: tuple[ParsedSourceFile, ...],
    ) -> dict[str, GraphNodeId]:
        index: dict[str, GraphNodeId] = {}
        for parsed_file in parsed_files:
            source_path = parsed_file.source_file.path.value
            path = PurePosixPath(cls._normalize_path(source_path))
            file_id = GraphNodeId(f"file:{path.as_posix()}")
            for root in cls._import_roots(path):
                without_suffix = root.with_suffix("").as_posix()
                cls._put(index, file_id, root.as_posix(), without_suffix)
                cls._put(index, file_id, without_suffix.replace("/", "."))

                if root.stem in {"__init__", "index"}:
                    package_path = root.parent.as_posix()
                    if package_path != ".":
                        cls._put(
                            index,
                            file_id,
                            package_path,
                            package_path.replace("/", "."),
                        )
        return index

    @staticmethod
    def _import_roots(path: PurePosixPath) -> tuple[PurePosixPath, ...]:
        """Return the path plus the path relative to any ``src`` root.

        ``packages/billing/src/billing/tax.py`` is imported as ``billing.tax``
        in src-layout projects, so it is also indexed relative to ``src``.
        The full repository-relative path is indexed first and wins ties.
        """

        roots = [path]
        parts = path.parts
        for index, part in enumerate(parts[:-1]):
            if part == "src":
                roots.append(PurePosixPath(*parts[index + 1 :]))
        return tuple(roots)

    @classmethod
    def _candidates(cls, importer_path: str, source: str) -> tuple[str, ...]:
        normalized_source = cls._normalize_source(source)
        candidates = [
            normalized_source,
            normalized_source.replace("/", "."),
            normalized_source.replace(".", "/"),
        ]
        if source.startswith("."):
            candidates.extend(cls._relative_python_candidates(importer_path, source))
        if source.startswith(("./", "../")):
            candidates.extend(cls._relative_path_candidates(importer_path, source))

        expanded: list[str] = []
        for candidate in candidates:
            if not candidate:
                continue
            normalized = cls._normalize_path(candidate)
            expanded.extend(
                (
                    normalized,
                    f"{normalized}/__init__",
                    f"{normalized}/index",
                )
            )
        return tuple(dict.fromkeys(expanded))

    @classmethod
    def _relative_python_candidates(
        cls,
        importer_path: str,
        source: str,
    ) -> tuple[str, ...]:
        level = len(source) - len(source.lstrip("."))
        module = source[level:]
        importer = PurePosixPath(cls._normalize_path(importer_path))
        base_parts = list(importer.parent.parts)
        if level > 1:
            parent_count = level - 1
            base_parts = (
                base_parts[:-parent_count] if parent_count <= len(base_parts) else []
            )
        if module:
            base_parts.extend(part for part in module.split(".") if part)
        return ("/".join(base_parts),)

    @classmethod
    def _relative_path_candidates(
        cls,
        importer_path: str,
        source: str,
    ) -> tuple[str, ...]:
        parent = PurePosixPath(cls._normalize_path(importer_path)).parent
        return ((parent / source).as_posix(),)

    @staticmethod
    def _put(index: dict[str, GraphNodeId], node_id: GraphNodeId, *keys: str) -> None:
        for key in keys:
            if key and key != ".":
                index.setdefault(key, node_id)

    @staticmethod
    def _normalize_path(path: str) -> str:
        # normpath collapses ``a/b/../c`` -> ``a/c`` so relative ``../`` imports
        # can match indexed repository paths.
        normalized = posixpath.normpath(path.replace("\\", "/"))
        return PurePosixPath(normalized).as_posix()

    @staticmethod
    def _normalize_source(source: str) -> str:
        if source.startswith(("./", "../")):
            return source
        return source.replace("\\", "/")


_JSONC_COMMENTS = re.compile(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/', re.DOTALL)
_TRAILING_COMMAS = re.compile(r",(\s*[}\]])")
_SKIP_DIRS = {"node_modules", ".git", "dist", "build", ".next", ".turbo"}
_MAX_TSCONFIG_BYTES = 1_000_000


def load_tsconfig_aliases(repository_path: Path) -> dict[str, tuple[str, ...]]:
    """Collect ``compilerOptions.paths``/``baseUrl`` aliases from tsconfig files.

    Targets are converted to repository-relative paths. ``extends`` is not
    followed (it may point outside the repository). Unreadable or malformed
    files are ignored. Aliases are merged repository-wide; when two tsconfig
    files define the same pattern, every target is kept (over-approximation,
    which only adds candidate edges).
    """

    root = repository_path.resolve()
    aliases: dict[str, list[str]] = {}
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for name in files:
            if not (name.startswith("tsconfig") and name.endswith(".json")):
                continue
            config_path = Path(current) / name
            options = _read_compiler_options(config_path, root)
            if options is None:
                continue
            config_dir = Path(current).relative_to(root).as_posix()
            base = _join(config_dir, str(options.get("baseUrl") or "."))
            paths = options.get("paths")
            if isinstance(paths, dict):
                for pattern, targets in paths.items():
                    if not isinstance(pattern, str) or not isinstance(targets, list):
                        continue
                    for target in targets:
                        if isinstance(target, str):
                            resolved = _join(base, target)
                            if resolved is not None:
                                aliases.setdefault(pattern, []).append(resolved)
            if options.get("baseUrl") and base is not None:
                aliases.setdefault("*", []).append(_join(base, "*") or "*")
    return {key: tuple(dict.fromkeys(value)) for key, value in aliases.items()}


def _read_compiler_options(config_path: Path, root: Path) -> dict | None:
    try:
        if config_path.is_symlink() or not config_path.resolve().is_relative_to(root):
            return None
        if config_path.stat().st_size > _MAX_TSCONFIG_BYTES:
            return None
        text = config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    text = _JSONC_COMMENTS.sub(lambda m: m.group(1) or "", text)
    text = _TRAILING_COMMAS.sub(r"\1", text)
    try:
        data = json.loads(text)
    except ValueError:
        return None
    options = data.get("compilerOptions") if isinstance(data, dict) else None
    return options if isinstance(options, dict) else None


def _join(base: str | None, target: str) -> str | None:
    """Join repository-relative paths; reject anything escaping the repository."""

    if base is None:
        return None
    joined = posixpath.normpath(posixpath.join(base, target.replace("\\", "/")))
    if joined.startswith("..") or joined.startswith("/"):
        return None
    return "" if joined == "." else joined
