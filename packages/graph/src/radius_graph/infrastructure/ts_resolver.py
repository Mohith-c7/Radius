"""TypeScript/JavaScript module resolution against repository files (DEC-017).

Implements the subset of the TypeScript ``node``/``bundler`` resolution that is
decidable from repository contents alone:

* relative specifiers with extension and ``index`` resolution
  (``.ts``, ``.tsx``, ``.d.ts``, ``.js``, ``.jsx``, ``.mts``, ``.cts``,
  ``.mjs``, ``.cjs``, ``/index.*``) and the ESM ``./x.js`` -> ``./x.ts`` rule
* ``compilerOptions.baseUrl`` and ``paths`` (exact and single-``*`` patterns,
  longest-prefix first)
* the **nearest** ``tsconfig.json`` (or ``jsconfig.json``) per importing file,
  so monorepos with several configs resolve independently
* ``extends`` chains (relative paths, arrays, JSON with comments and trailing
  commas); ``extends`` that leave the repository are ignored

Anything that does not resolve to a repository file (bare package names such as
``react``, unresolved aliases) is **external**, never an error.
"""

from __future__ import annotations

import json
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path

JS_TS_SUFFIXES = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")
_CONFIG_NAMES = ("tsconfig.json", "jsconfig.json")
_TRY_EXTENSIONS = (
    ".ts",
    ".tsx",
    ".d.ts",
    ".js",
    ".jsx",
    ".mts",
    ".cts",
    ".mjs",
    ".cjs",
    ".json",
)
# ESM style imports name the emitted extension; the source file has the TS one.
_EMITTED_TO_SOURCE = {
    ".js": (".ts", ".tsx", ".d.ts"),
    ".jsx": (".tsx",),
    ".mjs": (".mts", ".d.mts"),
    ".cjs": (".cts", ".d.cts"),
}
_JSONC_COMMENTS = re.compile(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/', re.DOTALL)
_TRAILING_COMMAS = re.compile(r",(\s*[}\]])")
_MAX_TSCONFIG_BYTES = 1_000_000
_MAX_EXTENDS_DEPTH = 10


def is_js_ts_path(path: str) -> bool:
    """Return whether ``path`` is a JS/TS-family source file."""

    return path.lower().endswith(JS_TS_SUFFIXES)


@dataclass(frozen=True)
class TsConfig:
    """Effective resolution options of one tsconfig (``extends`` flattened)."""

    directory: str
    base_url: str | None = None
    paths: dict[str, tuple[str, ...]] = field(default_factory=dict)
    paths_origin: str = ""
    """Directory of the config that defined ``paths`` (used when no baseUrl)."""


class TsModuleResolver:
    """Resolve JS/TS import specifiers to repository-relative file paths."""

    def __init__(
        self,
        files: frozenset[str] | set[str],
        repository_path: Path | None = None,
    ) -> None:
        self._files = frozenset(files)
        self._root = repository_path.resolve() if repository_path else None
        self._configs: dict[str, TsConfig] = {}
        self._cache: dict[str, TsConfig | None] = {}
        if self._root is not None:
            self._load_configs()

    # public ---------------------------------------------------------------

    def resolve(self, importer_path: str, specifier: str) -> str | None:
        """Return the repository file ``specifier`` points to, else ``None``."""

        specifier = specifier.strip()
        if not specifier:
            return None
        importer = posixpath.normpath(importer_path.replace("\\", "/"))
        if specifier.startswith(("./", "../")) or specifier in {".", ".."}:
            base = posixpath.join(posixpath.dirname(importer), specifier)
            return self._try_path(base)
        if specifier.startswith("/"):
            return None

        config = self.config_for(importer)
        if config is None:
            return None
        for target in self._alias_targets(config, specifier):
            found = self._try_path(target)
            if found is not None:
                return found
        if config.base_url is not None:
            return self._try_path(posixpath.join(config.base_url, specifier))
        return None

    def is_external(self, importer_path: str, specifier: str) -> bool:
        """Return whether the import is outside the repository (package/unresolved)."""

        return self.resolve(importer_path, specifier) is None

    def config_for(self, file_path: str) -> TsConfig | None:
        """Return the nearest tsconfig governing ``file_path``."""

        directory = posixpath.dirname(posixpath.normpath(file_path))
        walked: list[str] = []
        result: TsConfig | None = None
        while True:
            if directory in self._cache:
                result = self._cache[directory]
                break
            walked.append(directory)
            if directory in self._configs:
                result = self._configs[directory]
                break
            if directory in {"", "."}:
                break
            directory = posixpath.dirname(directory)
        for item in walked:
            self._cache[item] = result
        return result

    # resolution -----------------------------------------------------------

    @staticmethod
    def _alias_targets(config: TsConfig, specifier: str) -> list[str]:
        if not config.paths:
            return []
        base = config.base_url if config.base_url is not None else config.paths_origin
        ordered = sorted(
            config.paths.items(),
            key=lambda item: ("*" in item[0], -len(item[0].split("*", 1)[0])),
        )
        targets: list[str] = []
        for pattern, replacements in ordered:
            if "*" not in pattern:
                if specifier == pattern:
                    targets.extend(posixpath.join(base, item) for item in replacements)
                continue
            prefix, suffix = pattern.split("*", 1)
            if (
                specifier.startswith(prefix)
                and specifier.endswith(suffix)
                and len(specifier) >= len(prefix) + len(suffix)
            ):
                matched = specifier[
                    len(prefix) : len(specifier) - len(suffix) if suffix else None
                ]
                targets.extend(
                    posixpath.join(base, item.replace("*", matched, 1))
                    for item in replacements
                )
                # TypeScript uses only the longest matching wildcard pattern.
                break
        return targets

    def _try_path(self, path: str) -> str | None:
        normalized = posixpath.normpath(path.replace("\\", "/"))
        if normalized.startswith("..") or normalized.startswith("/"):
            return None
        if normalized == ".":
            normalized = ""

        candidates: list[str] = []
        suffix = posixpath.splitext(normalized)[1].lower()
        if normalized:
            candidates.append(normalized)
            if suffix in _EMITTED_TO_SOURCE:
                stem = normalized[: -len(suffix)]
                candidates.extend(f"{stem}{ext}" for ext in _EMITTED_TO_SOURCE[suffix])
            candidates.extend(f"{normalized}{ext}" for ext in _TRY_EXTENSIONS)
        prefix = f"{normalized}/" if normalized else ""
        candidates.extend(f"{prefix}index{ext}" for ext in _TRY_EXTENSIONS)
        for candidate in candidates:
            if candidate in self._files:
                return candidate
        return None

    # tsconfig loading -----------------------------------------------------

    def _load_configs(self) -> None:
        assert self._root is not None  # noqa: S101
        directories = {posixpath.dirname(item) for item in self._files}
        # Every ancestor directory of a source file may hold a tsconfig.
        all_directories: set[str] = set()
        for directory in directories:
            current = directory
            while True:
                all_directories.add(current)
                if current in {"", "."}:
                    break
                current = posixpath.dirname(current)
        for directory in sorted(all_directories):
            for name in _CONFIG_NAMES:
                relative = posixpath.join(directory, name) if directory else name
                config_path = self._root / relative
                if not config_path.is_file():
                    continue
                config = self._build_config(relative, set())
                if config is not None:
                    self._configs[directory or ""] = config
                    break

    def _build_config(self, relative: str, seen: set[str]) -> TsConfig | None:
        """Flatten ``extends`` for the config at repository-relative ``relative``."""

        if relative in seen or len(seen) > _MAX_EXTENDS_DEPTH:
            return None
        data = self._read_json(relative)
        if data is None:
            return None
        directory = posixpath.dirname(relative)
        seen = seen | {relative}

        base_url: str | None = None
        paths: dict[str, tuple[str, ...]] = {}
        paths_origin = directory
        extends = data.get("extends")
        parents = [extends] if isinstance(extends, str) else extends
        if isinstance(parents, list):
            for item in parents:
                if not isinstance(item, str) or not item.startswith("."):
                    continue  # package-based extends live in node_modules
                target = posixpath.normpath(posixpath.join(directory, item))
                if not target.endswith(".json"):
                    target += ".json"
                candidate = self._build_config(target, seen)
                if candidate is None:
                    continue
                if candidate.base_url is not None:
                    base_url = candidate.base_url
                if candidate.paths:
                    paths = dict(candidate.paths)
                    paths_origin = candidate.paths_origin

        options = data.get("compilerOptions")
        options = options if isinstance(options, dict) else {}
        raw_base = options.get("baseUrl")
        if isinstance(raw_base, str):
            base_url = self._join(directory, raw_base)
        raw_paths = options.get("paths")
        if isinstance(raw_paths, dict):
            # A child ``paths`` replaces the parent's entirely (TypeScript).
            paths = {
                pattern: tuple(t for t in targets if isinstance(t, str))
                for pattern, targets in raw_paths.items()
                if isinstance(pattern, str) and isinstance(targets, list)
            }
            paths_origin = directory
        return TsConfig(
            directory=directory,
            base_url=base_url,
            paths=paths,
            paths_origin=paths_origin,
        )

    @staticmethod
    def _join(base: str, target: str) -> str | None:
        joined = posixpath.normpath(posixpath.join(base, target.replace("\\", "/")))
        if joined.startswith("..") or joined.startswith("/"):
            return None
        return "" if joined == "." else joined

    def _read_json(self, relative: str) -> dict | None:
        assert self._root is not None  # noqa: S101
        path = self._root / relative
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(self._root):
                return None
            if not path.is_file() or path.stat().st_size > _MAX_TSCONFIG_BYTES:
                return None
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            return None
        text = _JSONC_COMMENTS.sub(lambda m: m.group(1) or "", text)
        text = _TRAILING_COMMAS.sub(r"\1", text)
        try:
            data = json.loads(text)
        except ValueError:
            return None
        return data if isinstance(data, dict) else None
