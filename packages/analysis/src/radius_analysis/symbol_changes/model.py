"""Pure domain model of symbol-level change extraction (LK-01).

Everything here is a frozen dataclass with a deterministic ``to_dict`` /
``from_dict`` pair so the output can be stored (LK-05), hashed and compared
across runs. No parsing, I/O or logging lives in this module.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

ALGO_VERSION = "symbol-changes-v1"
MODULE_SYMBOL = "<module>"
FILE_SYMBOL = "<file>"


class ChangeKind(StrEnum):
    """What happened to a symbol. See the README for exact semantics."""

    ADDED = "added"
    REMOVED = "removed"
    MODIFIED_BODY = "modified_body"
    MODIFIED_SIGNATURE = "modified_signature"
    RENAMED = "renamed"
    MOVED = "moved"
    DECORATOR_OR_ANNOTATION_CHANGED = "decorator_or_annotation_changed"
    DOCSTRING_OR_COMMENT_ONLY = "docstring_or_comment_only"
    FORMATTING_ONLY = "formatting_only"
    MOVED_BETWEEN_FILES = "moved_between_files"

    @property
    def is_behavioral(self) -> bool:
        """False for kinds that cannot change runtime behaviour."""

        return self not in _NON_BEHAVIORAL


_NON_BEHAVIORAL = frozenset({ChangeKind.DOCSTRING_OR_COMMENT_ONLY, ChangeKind.FORMATTING_ONLY})


class FileStatus(StrEnum):
    ADDED = "added"
    DELETED = "deleted"
    MODIFIED = "modified"
    RENAMED = "renamed"
    COPIED = "copied"


class FileLevel(StrEnum):
    """Granularity at which a file was analysed."""

    SYMBOL = "symbol"
    FILE = "file"  # degraded: one file-level unit, reason in notes
    IGNORED = "ignored"  # generated / vendored / configured away
    NONE = "none"  # nothing to report (e.g. mode-only change)


@dataclass(frozen=True, slots=True, order=True)
class LineRange:
    """Inclusive 1-based line range."""

    start: int
    end: int

    def to_dict(self) -> list[int]:
        return [self.start, self.end]

    @classmethod
    def from_list(cls, value: list[int] | None) -> LineRange | None:
        return None if value is None else cls(int(value[0]), int(value[1]))


def compress_lines(lines: list[int] | set[int] | tuple[int, ...]) -> tuple[LineRange, ...]:
    """Collapse line numbers into sorted, maximal inclusive ranges."""

    out: list[LineRange] = []
    for line in sorted(set(lines)):
        if out and out[-1].end + 1 == line:
            out[-1] = LineRange(out[-1].start, line)
        else:
            out.append(LineRange(line, line))
    return tuple(out)


def expand_ranges(ranges: tuple[LineRange, ...]) -> set[int]:
    return {n for r in ranges for n in range(r.start, r.end + 1)}


@dataclass(frozen=True, slots=True)
class SymbolHunk:
    """One diff hunk's contribution to a symbol (or to unattributed code).

    ``old_lines`` are deleted lines (base coordinates); ``new_lines`` are added
    lines (head coordinates). The ``*_start``/``*_count`` fields are the hunk
    header values.
    """

    hunk_index: int
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    old_lines: tuple[LineRange, ...] = ()
    new_lines: tuple[LineRange, ...] = ()
    path: str = ""  # file the hunk belongs to (differs per side for cross-file moves)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "hunk_index": self.hunk_index,
            "old_start": self.old_start,
            "old_count": self.old_count,
            "new_start": self.new_start,
            "new_count": self.new_count,
            "old_lines": [r.to_dict() for r in self.old_lines],
            "new_lines": [r.to_dict() for r in self.new_lines],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SymbolHunk:
        return cls(
            path=data.get("path", ""),
            hunk_index=int(data["hunk_index"]),
            old_start=int(data["old_start"]),
            old_count=int(data["old_count"]),
            new_start=int(data["new_start"]),
            new_count=int(data["new_count"]),
            old_lines=tuple(LineRange(*map(int, r)) for r in data["old_lines"]),
            new_lines=tuple(LineRange(*map(int, r)) for r in data["new_lines"]),
        )


@dataclass(frozen=True, slots=True)
class ChangedSymbol:
    """One symbol that changed between base and head.

    ``symbol_id`` is the head-side id when the symbol exists at head, else the
    base-side id. Ids are ``language:path::qualified_name#kind@signature_hash``;
    ``key`` is the same without the signature hash (stable across signature
    changes). ``old_*`` fields are ``None`` for added symbols, ``new_*`` fields
    are ``None`` for removed ones.
    """

    symbol_id: str
    key: str
    language: str
    path: str
    qualified_name: str
    kind: str
    change_kind: ChangeKind
    old_symbol_id: str | None = None
    new_symbol_id: str | None = None
    old_path: str | None = None
    old_qualified_name: str | None = None
    old_range: LineRange | None = None
    new_range: LineRange | None = None
    old_signature: str | None = None
    new_signature: str | None = None
    old_body_hash: str | None = None
    new_body_hash: str | None = None
    secondary_kinds: tuple[ChangeKind, ...] = ()
    hunks: tuple[SymbolHunk, ...] = ()
    confidence: float = 1.0
    notes: tuple[str, ...] = ()

    @property
    def is_behavioral(self) -> bool:
        return self.change_kind.is_behavioral

    def sort_key(self) -> tuple[Any, ...]:
        rng = self.new_range or self.old_range
        return (
            self.path,
            rng.start if rng else 0,
            rng.end if rng else 0,
            self.qualified_name,
            self.kind,
            self.change_kind.value,
            self.old_path or "",
            self.old_qualified_name or "",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol_id": self.symbol_id,
            "key": self.key,
            "language": self.language,
            "path": self.path,
            "qualified_name": self.qualified_name,
            "kind": self.kind,
            "change_kind": self.change_kind.value,
            "secondary_kinds": [k.value for k in self.secondary_kinds],
            "is_behavioral": self.is_behavioral,
            "old_symbol_id": self.old_symbol_id,
            "new_symbol_id": self.new_symbol_id,
            "old_path": self.old_path,
            "old_qualified_name": self.old_qualified_name,
            "old_range": self.old_range.to_dict() if self.old_range else None,
            "new_range": self.new_range.to_dict() if self.new_range else None,
            "old_signature": self.old_signature,
            "new_signature": self.new_signature,
            "old_body_hash": self.old_body_hash,
            "new_body_hash": self.new_body_hash,
            "hunks": [h.to_dict() for h in self.hunks],
            "confidence": self.confidence,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChangedSymbol:
        return cls(
            symbol_id=data["symbol_id"],
            key=data["key"],
            language=data["language"],
            path=data["path"],
            qualified_name=data["qualified_name"],
            kind=data["kind"],
            change_kind=ChangeKind(data["change_kind"]),
            old_symbol_id=data.get("old_symbol_id"),
            new_symbol_id=data.get("new_symbol_id"),
            old_path=data.get("old_path"),
            old_qualified_name=data.get("old_qualified_name"),
            old_range=LineRange.from_list(data.get("old_range")),
            new_range=LineRange.from_list(data.get("new_range")),
            old_signature=data.get("old_signature"),
            new_signature=data.get("new_signature"),
            old_body_hash=data.get("old_body_hash"),
            new_body_hash=data.get("new_body_hash"),
            secondary_kinds=tuple(ChangeKind(k) for k in data.get("secondary_kinds", [])),
            hunks=tuple(SymbolHunk.from_dict(h) for h in data.get("hunks", [])),
            confidence=float(data.get("confidence", 1.0)),
            notes=tuple(data.get("notes", [])),
        )


@dataclass(frozen=True, slots=True)
class UnattributedHunk:
    """Changed lines that belong to no symbol (imports, comments, config...)."""

    language: str
    reason: str  # import | blank_or_comment | blank_between_members | module_level | out_of_range
    hunk: SymbolHunk

    @property
    def path(self) -> str:
        return self.hunk.path

    def sort_key(self) -> tuple[Any, ...]:
        return (self.hunk.path, self.hunk.hunk_index, self.reason)

    def to_dict(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "reason": self.reason,
            **self.hunk.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UnattributedHunk:
        return cls(
            language=data["language"],
            reason=data["reason"],
            hunk=SymbolHunk.from_dict(data),
        )


@dataclass(frozen=True, slots=True)
class FileChange:
    """Per-file outcome: how it changed and at what granularity it was analysed."""

    path: str
    status: FileStatus
    language: str
    level: FileLevel
    old_path: str | None = None
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "old_path": self.old_path,
            "status": self.status.value,
            "language": self.language,
            "level": self.level.value,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileChange:
        return cls(
            path=data["path"],
            old_path=data.get("old_path"),
            status=FileStatus(data["status"]),
            language=data["language"],
            level=FileLevel(data["level"]),
            notes=tuple(data.get("notes", [])),
        )


@dataclass(frozen=True, slots=True)
class SymbolChangeSet:
    """All changed symbols of one analysis, deterministically ordered."""

    symbols: tuple[ChangedSymbol, ...] = ()
    unattributed_hunks: tuple[UnattributedHunk, ...] = ()
    files: tuple[FileChange, ...] = ()
    truncated: bool = False
    notes: tuple[str, ...] = ()
    config: dict[str, Any] = field(default_factory=dict)
    algo_version: str = ALGO_VERSION

    @property
    def counts(self) -> dict[str, Any]:
        by_kind = Counter(s.change_kind.value for s in self.symbols)
        by_lang = Counter(s.language for s in self.symbols)
        by_level = Counter(f.level.value for f in self.files)
        return {
            "symbols": len(self.symbols),
            "behavioral_symbols": sum(1 for s in self.symbols if s.is_behavioral),
            "by_change_kind": dict(sorted(by_kind.items())),
            "by_language": dict(sorted(by_lang.items())),
            "files": len(self.files),
            "files_by_level": dict(sorted(by_level.items())),
            "unattributed_hunks": len(self.unattributed_hunks),
        }

    def for_path(self, path: str) -> tuple[ChangedSymbol, ...]:
        return tuple(s for s in self.symbols if s.path == path or s.old_path == path)

    def to_dict(self) -> dict[str, Any]:
        return {
            "algo_version": self.algo_version,
            "config": self.config,
            "truncated": self.truncated,
            "notes": list(self.notes),
            "counts": self.counts,
            "files": [f.to_dict() for f in self.files],
            "symbols": [s.to_dict() for s in self.symbols],
            "unattributed_hunks": [u.to_dict() for u in self.unattributed_hunks],
        }

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SymbolChangeSet:
        return cls(
            algo_version=data.get("algo_version", ALGO_VERSION),
            config=dict(data.get("config", {})),
            truncated=bool(data.get("truncated", False)),
            notes=tuple(data.get("notes", [])),
            files=tuple(FileChange.from_dict(f) for f in data.get("files", [])),
            symbols=tuple(ChangedSymbol.from_dict(s) for s in data.get("symbols", [])),
            unattributed_hunks=tuple(
                UnattributedHunk.from_dict(u) for u in data.get("unattributed_hunks", [])
            ),
        )

    @classmethod
    def from_json(cls, text: str) -> SymbolChangeSet:
        return cls.from_dict(json.loads(text))
