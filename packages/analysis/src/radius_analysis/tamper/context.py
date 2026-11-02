"""Analysis context handed to every rule (built once, from LK-01 output).

Rules never re-parse diffs: the context holds, per changed file, the base and head
text, the added/removed line numbers with their text, the file roles and lazily
parsed Python trees. Failures to read or parse are recorded as ``unanalyzable``
instead of raising.
"""

from __future__ import annotations

import difflib
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from radius_analysis.symbol_changes.diff_files import FileDiff, parse_unified_diff
from radius_analysis.symbol_changes.model import (
    ChangedSymbol,
    FileChange,
    FileLevel,
    FileStatus,
    LineRange,
    SymbolChangeSet,
)
from radius_analysis.symbol_changes.snapshots import SnapshotReader
from radius_analysis.tamper import pyast
from radius_analysis.tamper.classify import Role, classify_path
from radius_analysis.tamper.config import TamperConfig
from radius_analysis.tamper.model import (
    CATALOG_VERSION,
    Finding,
    Severity,
    Unanalyzable,
    clip,
    make_finding_id,
)

if TYPE_CHECKING:
    from radius_analysis.tamper.rules.base import BaseRule

MAX_DIFFLIB_LINES = 20_000


class PackageRegistry(Protocol):
    """Injectable registry port (T012). ``None`` means unknown (network error, off)."""

    def exists(self, name: str) -> bool | None: ...


@dataclass(slots=True)
class FileView:
    path: str
    old_path: str | None
    status: FileStatus
    language: str
    level: FileLevel
    roles: frozenset[Role]
    base_text: str | None = None
    head_text: str | None = None
    added: dict[int, str] = field(default_factory=dict)  # head line number -> text
    removed: dict[int, str] = field(default_factory=dict)  # base line number -> text
    skipped: str | None = None  # why the content was not loaded

    @property
    def is_python(self) -> bool:
        return self.path.endswith((".py", ".pyi"))

    @property
    def is_test(self) -> bool:
        return Role.TEST in self.roles

    def has(self, *roles: Role) -> bool:
        return bool(self.roles & set(roles))

    def head_lines(self) -> list[str]:
        return (self.head_text or "").splitlines()

    def base_lines(self) -> list[str]:
        return (self.base_text or "").splitlines()


def _decode(data: bytes | None) -> str | None:
    if data is None:
        return None
    return data.decode("utf-8", errors="replace").replace("\r\n", "\n")


def _lines_of(text: str | None, ranges: list[LineRange] | tuple[LineRange, ...]) -> dict[int, str]:
    if text is None:
        return {}
    lines = text.split("\n")
    out: dict[int, str] = {}
    for r in ranges:
        for n in range(max(r.start, 1), min(r.end, len(lines)) + 1):
            out[n] = lines[n - 1]
    return out


@dataclass
class TamperContext:
    changeset: SymbolChangeSet
    config: TamperConfig
    base: SnapshotReader | None
    head: SnapshotReader
    files: dict[str, FileView] = field(default_factory=dict)
    unanalyzable: list[Unanalyzable] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    registry: PackageRegistry | None = None
    _trees: dict[tuple[str, str], pyast.TestModule | None] = field(default_factory=dict)
    _parsed: dict[tuple[str, str], object] = field(default_factory=dict)
    _unanalyzable_seen: set[tuple[str, str, str]] = field(default_factory=set)
    _probe_cache: dict[tuple[str, str], str | bool | None] = field(default_factory=dict)
    source_roots: list[str] | None = None  # cache for T012 first-party detection

    # ------------------------------------------------------------------ building

    @classmethod
    def build(
        cls,
        changeset: SymbolChangeSet,
        base: SnapshotReader | None,
        head: SnapshotReader,
        config: TamperConfig,
        *,
        diff_text: str | None = None,
        registry: PackageRegistry | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> TamperContext:
        ctx = cls(changeset=changeset, config=config, base=base, head=head, registry=registry)
        if base is None:
            ctx.notes.append("base_snapshot_unavailable")
        diff_lines = _lines_from_diff(diff_text) if diff_text else {}
        hunk_ranges = _hunk_ranges(changeset)
        started = clock()
        params = config.params
        for position, fc in enumerate(sorted(changeset.files, key=lambda f: (f.path, f.old_path or ""))):
            if fc.level is FileLevel.NONE:
                continue
            if position >= params.max_files:
                ctx.notes.append("max_files_exceeded")
                break
            if clock() - started > params.time_budget_seconds:
                ctx.notes.append("context_time_budget_exceeded")
                break
            ctx.files[fc.path] = ctx._load(fc, diff_lines, hunk_ranges)
        return ctx

    def _read(self, reader: SnapshotReader | None, path: str, side: str, view_path: str) -> str | None:
        if reader is None:
            return None
        try:
            data = reader.read(path)
        except Exception as exc:  # reader errors must not abort the analysis
            self.mark_unanalyzable(view_path, side, f"read_error:{type(exc).__name__}")
            return None
        if data is None:
            return None
        if len(data) > self.config.params.max_file_bytes:
            self.mark_unanalyzable(view_path, side, "file_too_large")
            return None
        if b"\x00" in data[:8192]:
            self.mark_unanalyzable(view_path, side, "binary_file")
            return None
        return _decode(data)

    def _load(
        self,
        fc: FileChange,
        diff_lines: Mapping[str, tuple[dict[int, str], dict[int, str]]],
        hunk_ranges: Mapping[str, tuple[list[LineRange], list[LineRange]]],
    ) -> FileView:
        view = FileView(
            path=fc.path, old_path=fc.old_path, status=fc.status, language=fc.language,
            level=fc.level, roles=classify_path(fc.path),
        )
        if fc.status is not FileStatus.DELETED:
            view.head_text = self._read(self.head, fc.path, "head", fc.path)
        if fc.status is not FileStatus.ADDED:
            view.base_text = self._read(self.base, fc.old_path or fc.path, "base", fc.path)
        view.added, view.removed = self._changed_lines(view, diff_lines, hunk_ranges)
        return view

    def _changed_lines(
        self,
        view: FileView,
        diff_lines: Mapping[str, tuple[dict[int, str], dict[int, str]]],
        hunk_ranges: Mapping[str, tuple[list[LineRange], list[LineRange]]],
    ) -> tuple[dict[int, str], dict[int, str]]:
        if view.status is FileStatus.ADDED and view.head_text is not None:
            return dict(enumerate(view.head_text.split("\n"), 1)), {}
        if view.status is FileStatus.DELETED and view.base_text is not None:
            return {}, dict(enumerate(view.base_text.split("\n"), 1))
        if view.path in diff_lines:
            return diff_lines[view.path]
        new_r = hunk_ranges.get(view.path, ([], []))[0]
        old_r: list[LineRange] = []
        for p in {view.path, view.old_path or view.path}:
            old_r.extend(hunk_ranges.get(p, ([], []))[1])
        if new_r or old_r:
            return _lines_of(view.head_text, new_r), _lines_of(view.base_text, old_r)
        if view.head_text is not None and view.base_text is not None:
            return _difflib_lines(view.base_text, view.head_text)
        return {}, {}

    # ------------------------------------------------------------------ accessors

    def mark_unanalyzable(self, path: str, side: str, reason: str) -> None:
        key = (path, side, reason)
        if key not in self._unanalyzable_seen:
            self._unanalyzable_seen.add(key)
            self.unanalyzable.append(Unanalyzable(path, side, reason))

    def views(self, *roles: Role, python_only: bool = False) -> list[FileView]:
        out = [v for v in self.files.values() if not roles or v.has(*roles)]
        if python_only:
            out = [v for v in out if v.is_python]
        return sorted(out, key=lambda v: v.path)

    def tests_of(self, view: FileView, side: str) -> pyast.TestModule | None:
        """Parsed test functions of one side (``base``/``head``); ``None`` if unavailable."""
        key = (view.path, side)
        if key in self._trees:
            return self._trees[key]
        text = view.head_text if side == "head" else view.base_text
        module: pyast.TestModule | None = None
        if text is not None and view.is_python:
            try:
                module = pyast.collect_tests(pyast.parse_python(text))
            except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
                self.mark_unanalyzable(view.path, side, f"parse_error:{type(exc).__name__}")
        self._trees[key] = module
        return module

    def tree_of(self, view: FileView, side: str):  # noqa: ANN201 - ast.Module | None
        module = self.tests_of(view, side)
        return None if module is None else module.tree

    def read_head(self, path: str) -> str | None:
        key = ("text", path)
        if key not in self._probe_cache:
            self._probe_cache[key] = self._read(self.head, path, "head", path)
        return self._probe_cache[key]  # str | None for "text" keys

    def read_base(self, path: str) -> str | None:
        return self._read(self.base, path, "base", path)

    def head_exists(self, path: str) -> bool:
        key = ("exists", path)
        if key not in self._probe_cache:
            try:
                self._probe_cache[key] = self.head.read(path) is not None
            except Exception:
                self._probe_cache[key] = False
        return bool(self._probe_cache[key])

    def behavioral_source_symbols(self) -> list[ChangedSymbol]:
        out = []
        for s in self.changeset.symbols:
            view = self.files.get(s.path)
            if view is None or not view.has(Role.SOURCE):
                continue
            if s.is_behavioral and s.kind != "module" and s.change_kind.value != "added":
                out.append(s)
        return out

    def removed_symbol_names(self) -> frozenset[str]:
        names = set()
        for s in self.changeset.symbols:
            if s.change_kind.value in ("removed",):
                names.add(s.qualified_name.rsplit(".", 1)[-1])
        return frozenset(names)

    # ------------------------------------------------------------------ findings

    def finding(
        self,
        rule: BaseRule,
        check: str,
        path: str,
        reason: str,
        *,
        symbol: str | None = None,
        test_id: str | None = None,
        old_range: tuple[int, int] | None = None,
        new_range: tuple[int, int] | None = None,
        old: str | None = None,
        new: str | None = None,
        confidence: float = 0.8,
        evidence: tuple[str, ...] = (),
    ) -> Finding:
        spec = rule.checks[check]
        severity: Severity = self.config.severity_for(rule.id, check, spec.severity)
        return Finding(
            finding_id=make_finding_id(rule.id, check, path, symbol or test_id, old, new),
            rule_id=rule.id,
            check=check,
            family=str(rule.family),
            severity=severity,
            confidence=round(max(0.0, min(1.0, confidence)), 2),
            path=path,
            symbol=symbol,
            test_id=test_id,
            old_range=LineRange(*old_range) if old_range else None,
            new_range=LineRange(*new_range) if new_range else None,
            old_snippet=clip(old),
            new_snippet=clip(new),
            reason=reason,
            evidence=evidence,
            catalog_version=CATALOG_VERSION,
        )


# ---------------------------------------------------------------------- helpers


def _lines_from_diff(diff_text: str) -> dict[str, tuple[dict[int, str], dict[int, str]]]:
    out: dict[str, tuple[dict[int, str], dict[int, str]]] = {}
    for fd in parse_unified_diff(diff_text):
        out[fd.path] = _diff_lines(fd)
    return out


def _diff_lines(fd: FileDiff) -> tuple[dict[int, str], dict[int, str]]:
    added: dict[int, str] = {}
    removed: dict[int, str] = {}
    for hunk in fd.hunks:
        for line in hunk.lines:
            if line.tag == "+" and line.new_no is not None:
                added[line.new_no] = line.text
            elif line.tag == "-" and line.old_no is not None:
                removed[line.old_no] = line.text
    return added, removed


def _hunk_ranges(changeset: SymbolChangeSet) -> dict[str, tuple[list[LineRange], list[LineRange]]]:
    out: dict[str, tuple[list[LineRange], list[LineRange]]] = {}

    def add(path: str, hunk) -> None:  # noqa: ANN001
        new_r, old_r = out.setdefault(path, ([], []))
        new_r.extend(hunk.new_lines)
        old_r.extend(hunk.old_lines)

    for sym in changeset.symbols:
        for h in sym.hunks:
            add(h.path or sym.path, h)
    for un in changeset.unattributed_hunks:
        add(un.hunk.path, un.hunk)
    return out


def _difflib_lines(base: str, head: str) -> tuple[dict[int, str], dict[int, str]]:
    a, b = base.split("\n"), head.split("\n")
    if len(a) > MAX_DIFFLIB_LINES or len(b) > MAX_DIFFLIB_LINES:
        return {}, {}
    added: dict[int, str] = {}
    removed: dict[int, str] = {}
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if tag in ("replace", "delete"):
            removed.update({n + 1: a[n] for n in range(i1, i2)})
        if tag in ("replace", "insert"):
            added.update({n + 1: b[n] for n in range(j1, j2)})
    return added, removed
