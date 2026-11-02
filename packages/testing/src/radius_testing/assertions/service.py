"""Entry point of assertion extraction (LK-04)."""

from __future__ import annotations

import ast
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from radius_testing.assertions.model import (
    ALGO_VERSION,
    AssertionRecord,
    AssertionSet,
    TestSummary,
    canonical,
)
from radius_testing.assertions.pyextract import Extractor, ModuleInfo, build_module
from radius_testing.assertions.resolve import SymbolResolver, linked_symbols_by_test

FEATURE_FLAG = "RADIUS_FEATURE_ASSERTION_EXTRACTION"
MAX_FILE_BYTES = 1_000_000
MAX_FILES = 5000
JS_PARTIAL_NOTE = "TS/JS extraction is partial: jest/vitest expect(), chai call matchers and node assert only"
_JS_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")


def assertion_extraction_enabled(environ: Mapping[str, str] | None = None) -> bool:
    value = (environ if environ is not None else os.environ).get(FEATURE_FLAG, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _read(snapshot: Any, path: str) -> str | None:
    if isinstance(snapshot, Mapping):
        raw = snapshot.get(path)
    else:
        try:
            raw = snapshot.read(path)
        except Exception:  # noqa: BLE001 - a broken adapter means "file not available"
            raw = None
    if raw is None:
        return None
    if isinstance(raw, bytes):
        if len(raw) > MAX_FILE_BYTES:
            return ""
        return raw.decode("utf-8", errors="replace")
    return raw if len(raw) <= MAX_FILE_BYTES else ""


def extract_assertions(
    test_files: Iterable[str],
    repo_snapshot: Any,
    links: Any = None,
    *,
    resolver: SymbolResolver | None = None,
) -> AssertionSet:
    """Extract the assertions of ``test_files``.

    ``repo_snapshot`` is a ``{path: text}`` mapping or any object with
    ``read(path) -> bytes | None`` (LK-01's snapshots qualify). ``links`` are the
    LK-03 ``SymbolTestLink``s (or a ``LinkSet``): with a ``resolver`` they make
    ``depends_on_changed`` yes/no instead of ``unknown``. Never raises on bad
    input; problems are reported in ``AssertionSet.notes``.
    """

    linked = linked_symbols_by_test(links)
    paths = sorted({p.replace("\\", "/") for p in test_files})
    notes: list[str] = []
    if len(paths) > MAX_FILES:
        notes.append(f"truncated: {len(paths)} test files given, only the first {MAX_FILES} analysed")
        paths = paths[:MAX_FILES]
    present = _Present(repo_snapshot, set(paths))
    records: list[AssertionRecord] = []
    summaries: list[TestSummary] = []
    conftests: dict[str, ModuleInfo | None] = {}

    def conftest(path: str) -> ModuleInfo | None:
        if path not in conftests:
            src = _read(repo_snapshot, path)
            conftests[path] = _parse_module(path, src) if src else None
        return conftests[path]

    for path in paths:
        source = _read(repo_snapshot, path)
        if source is None:
            notes.append(f"{path}: not found in snapshot")
            continue
        if source == "":
            notes.append(f"{path}: empty or larger than {MAX_FILE_BYTES} bytes; skipped")
            continue
        if path.endswith(".py"):
            try:
                tree = ast.parse(source, filename=path)
            except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
                notes.append(f"{path}: unparseable ({type(exc).__name__}); skipped")
                continue
            mod = build_module(path, tree)
            helpers = [m for p in _conftest_paths(path) if (m := conftest(p)) is not None]
            ex = Extractor(mod, helpers, resolver, linked)
            try:
                ex.run()
            except (RecursionError, MemoryError):
                notes.append(f"{path}: too deeply nested; partial result discarded")
                continue
            records.extend(ex.records)
            summaries.extend(ex.summaries)
            notes.extend(ex.notes)
        elif path.endswith(_JS_SUFFIXES):
            from radius_testing.assertions.jsextract import extract_js_file

            try:
                r, s, n = extract_js_file(path, source, present, resolver, linked)
            except Exception as exc:  # noqa: BLE001 - partial TS/JS support must never break the run
                notes.append(f"{path}: TS/JS extraction failed ({type(exc).__name__}); skipped")
                continue
            records.extend(r)
            summaries.extend(s)
            notes.extend(n)
            notes.append(JS_PARTIAL_NOTE)
        else:
            notes.append(f"{path}: unsupported language; skipped")

    return AssertionSet(
        assertions=canonical(records),
        tests=tuple(sorted({s.test_id: s for s in summaries}.values(), key=lambda s: s.test_id)),
        notes=tuple(sorted(set(notes))),
        algo_version=ALGO_VERSION,
    )


class _Present:
    """Set-like view of the snapshot's files, so relative imports resolve to non-test sources."""

    def __init__(self, snapshot: Any, known: set[str]) -> None:
        self._snapshot = snapshot
        self._known = known
        self._cache: dict[str, bool] = {}

    def __contains__(self, path: object) -> bool:
        if not isinstance(path, str):
            return False
        if path in self._known:
            return True
        if path not in self._cache:
            if isinstance(self._snapshot, Mapping):
                self._cache[path] = path in self._snapshot
            else:
                try:
                    self._cache[path] = self._snapshot.read(path) is not None
                except Exception:  # noqa: BLE001
                    self._cache[path] = False
        return self._cache[path]


def _parse_module(path: str, source: str) -> ModuleInfo | None:
    try:
        return build_module(path, ast.parse(source, filename=path))
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None


def _conftest_paths(path: str) -> list[str]:
    """``conftest.py`` candidates from the test's directory up to the root, nearest first."""

    parts = path.split("/")[:-1]
    out = []
    for i in range(len(parts), -1, -1):
        out.append("/".join([*parts[:i], "conftest.py"]))
    return [p for p in out if p != path]


def log_counts(result: AssertionSet) -> dict[str, Any]:
    """The summary logged by the (flag-gated) worker hook."""

    return {"algo_version": result.algo_version, **result.counts()}



_SKIP_DIRS = frozenset({".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".tox", ".next"})


def discover_test_files(root: Path | str, limit: int = MAX_FILES) -> list[str]:
    """Repo-relative paths of Python/TS/JS test files below ``root`` (sorted, bounded)."""

    from radius_testing.linking.model import is_test_path

    base = Path(root)
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            rel = (Path(dirpath) / name).relative_to(base).as_posix()
            if is_test_path(rel):
                found.append(rel)
                if len(found) >= limit:
                    return sorted(found)
    return sorted(found)
