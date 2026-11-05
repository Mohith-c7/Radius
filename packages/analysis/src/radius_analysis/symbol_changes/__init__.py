"""Symbol-level change extraction (LK-01).

Public surface: :func:`extract_symbol_changes`, :class:`ExtractionOptions`,
:class:`RefRange`, the snapshot adapters and the pure result model.
"""

from radius_analysis.symbol_changes.diff_files import FileDiff, Hunk, parse_unified_diff
from radius_analysis.symbol_changes.model import (
    ALGO_VERSION,
    ChangedSymbol,
    ChangeKind,
    FileChange,
    FileLevel,
    FileStatus,
    LineRange,
    SymbolChangeSet,
    SymbolHunk,
    UnattributedHunk,
)
from radius_analysis.symbol_changes.service import (
    DEFAULT_IGNORE_GLOBS,
    ExtractionOptions,
    RefRange,
    extract_symbol_changes,
)
from radius_analysis.symbol_changes.snapshots import (
    DictSnapshot,
    DiffReversedSnapshot,
    DirectorySnapshot,
    GitSnapshot,
    SnapshotReader,
)

__all__ = [
    "ALGO_VERSION",
    "DEFAULT_IGNORE_GLOBS",
    "ChangeKind",
    "ChangedSymbol",
    "DictSnapshot",
    "DiffReversedSnapshot",
    "DirectorySnapshot",
    "ExtractionOptions",
    "FileChange",
    "FileDiff",
    "FileLevel",
    "FileStatus",
    "GitSnapshot",
    "Hunk",
    "LineRange",
    "RefRange",
    "SnapshotReader",
    "SymbolChangeSet",
    "SymbolHunk",
    "UnattributedHunk",
    "extract_symbol_changes",
    "parse_unified_diff",
]
