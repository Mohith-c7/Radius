"""Deterministic repository-local import resolver."""

from __future__ import annotations

import posixpath
from pathlib import PurePosixPath

from radius_parser.domain.entities import ParsedSourceFile

from radius_graph.domain.value_objects import GraphNodeId


class ModuleResolver:
    """Resolve parser import references to repository file graph nodes."""

    def __init__(self, parsed_files: tuple[ParsedSourceFile, ...]) -> None:
        self._index = self._build_index(parsed_files)

    def resolve(
        self,
        importer_path: str,
        source: str,
    ) -> GraphNodeId | None:
        """Return the imported file node id when the import is repository-local."""

        for candidate in self._candidates(importer_path, source):
            node_id = self._index.get(candidate)
            if node_id is not None:
                return node_id
        return None

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
