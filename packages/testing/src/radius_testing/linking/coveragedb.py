"""Offline reader for coverage.py data files with per-test contexts (LK-03).

``.coverage`` is an SQLite database (coverage.py 5+): ``file(id, path)``,
``context(id, context)`` and ``line_bits(file_id, context_id, numbits)`` where
``numbits`` is a little-endian bitmap (bit ``n % 8`` of byte ``n // 8`` set when
line ``n`` ran). This module reads it with the standard library only -- no
``coverage`` import, no execution, no network -- so the data produced inside the
sandbox can be parsed on the host without trusting the sandbox image's
coverage version. The database is untrusted input: it is opened from an
in-memory copy (``sqlite3.Connection.deserialize``), size-capped, and every
count is bounded.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

MAX_DB_BYTES = 64 * 1024 * 1024
MAX_CONTEXTS = 50_000
MAX_ROWS = 2_000_000
MAX_NUMBITS_BYTES = 1 << 20  # lines up to 8M; anything larger is corrupt
CONTAINER_PREFIXES = ("/workspace/",)


class CoverageDataError(ValueError):
    """The coverage database is missing, corrupt or exceeds the safety limits."""


@dataclass(frozen=True, slots=True)
class CoverageData:
    """Executed lines per context label and file (``""`` is the no-context bucket)."""

    contexts: Mapping[str, Mapping[str, frozenset[int]]] = field(default_factory=dict)
    truncated: bool = False

    def lines(self, context: str, path: str) -> frozenset[int]:
        return self.contexts.get(context, {}).get(path, frozenset())

    def merged(self, other: CoverageData) -> CoverageData:
        out: dict[str, dict[str, frozenset[int]]] = {c: dict(f) for c, f in self.contexts.items()}
        for ctx, files in other.contexts.items():
            tgt = out.setdefault(ctx, {})
            for path, lines in files.items():
                tgt[path] = tgt.get(path, frozenset()) | lines
        return CoverageData(out, self.truncated or other.truncated)


def numbits_to_nums(numbits: bytes) -> list[int]:
    """Decode coverage.py's ``numbits`` blob into sorted line numbers."""

    if len(numbits) > MAX_NUMBITS_BYTES:
        raise CoverageDataError("numbits blob too large")
    nums: list[int] = []
    for byte_i, byte in enumerate(numbits):
        if byte:
            for bit_i in range(8):
                if byte & (1 << bit_i):
                    nums.append(byte_i * 8 + bit_i)
    return nums


def nums_to_numbits(nums: list[int]) -> bytes:
    """Inverse of :func:`numbits_to_nums` (used by tests and fixtures)."""

    if not nums:
        return b""
    out = bytearray(max(nums) // 8 + 1)
    for n in nums:
        out[n // 8] |= 1 << (n % 8)
    return bytes(out)


def normalize_path(path: str, roots: tuple[str, ...] = CONTAINER_PREFIXES) -> str:
    """Repo-relative posix path for a measured file (strips the sandbox workspace prefix)."""

    cleaned = path.replace("\\", "/")
    for root in roots:
        if cleaned.startswith(root):
            cleaned = cleaned[len(root) :]
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned


def read_coverage_bytes(
    data: bytes,
    *,
    max_contexts: int = MAX_CONTEXTS,
    max_rows: int = MAX_ROWS,
    roots: tuple[str, ...] = CONTAINER_PREFIXES,
) -> CoverageData:
    """Parse the bytes of a ``.coverage`` file."""

    if not data:
        raise CoverageDataError("empty coverage data")
    if len(data) > MAX_DB_BYTES:
        raise CoverageDataError("coverage data exceeds the size limit")
    if not data.startswith(b"SQLite format 3\x00"):
        raise CoverageDataError("not an SQLite database")
    conn = sqlite3.connect(":memory:")
    try:
        try:
            conn.deserialize(data)
            tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
            if not {"file", "context"} <= tables:
                raise CoverageDataError("coverage database lacks file/context tables")
            files = dict(conn.execute("select id, path from file"))
            contexts = dict(conn.execute("select id, context from context limit ?", (max_contexts + 1,)))
            truncated = len(contexts) > max_contexts
            out: dict[str, dict[str, set[int]]] = {}
            rows = 0
            if "line_bits" in tables:
                for file_id, ctx_id, numbits in conn.execute(
                    "select file_id, context_id, numbits from line_bits order by file_id, context_id"
                ):
                    rows += 1
                    if rows > max_rows:
                        truncated = True
                        break
                    if ctx_id not in contexts or file_id not in files:
                        continue
                    lines = numbits_to_nums(bytes(numbits))
                    path = normalize_path(files[file_id], roots)
                    out.setdefault(contexts[ctx_id] or "", {}).setdefault(path, set()).update(lines)
            if "arc" in tables and not out:  # branch-measurement databases
                for file_id, ctx_id, a, b in conn.execute("select file_id, context_id, fromno, tono from arc"):
                    rows += 1
                    if rows > max_rows:
                        truncated = True
                        break
                    if ctx_id not in contexts or file_id not in files:
                        continue
                    path = normalize_path(files[file_id], roots)
                    bucket = out.setdefault(contexts[ctx_id] or "", {}).setdefault(path, set())
                    bucket.update(n for n in (a, b) if n > 0)
        except sqlite3.Error as exc:
            raise CoverageDataError(f"unreadable coverage database ({exc.__class__.__name__})") from exc
    finally:
        conn.close()
    frozen = {c: {p: frozenset(ls) for p, ls in files_.items()} for c, files_ in out.items()}
    return CoverageData(frozen, truncated)


def read_coverage_file(path: Path, **kwargs) -> CoverageData:  # noqa: ANN003
    try:
        if path.is_symlink() or not path.is_file():
            raise CoverageDataError("coverage file is missing or not a regular file")
        if path.stat().st_size > MAX_DB_BYTES:
            raise CoverageDataError("coverage data exceeds the size limit")
        return read_coverage_bytes(path.read_bytes(), **kwargs)
    except OSError as exc:
        raise CoverageDataError(f"cannot read coverage file ({exc.__class__.__name__})") from exc
