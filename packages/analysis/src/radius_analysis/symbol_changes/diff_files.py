"""Full unified-diff parser for symbol-change extraction (LK-01).

Unlike :mod:`radius_analysis.diff_hunks` (F-08, new-file lines only) this keeps
both coordinate systems, every hunk's header and the line text, and understands
renames/copies, new/deleted files, binary patches, mode-only changes,
``\\ No newline at end of file`` markers, CRLF content and quoted paths.

Hunks are consumed by their header counts, so a deleted line such as
``-- comment`` (rendered ``--- comment``) is never mistaken for a file header.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from radius_analysis.symbol_changes.model import FileStatus

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_NULL = "/dev/null"


@dataclass(slots=True)
class DiffLine:
    tag: str  # '+', '-' or ' '
    text: str
    old_no: int | None
    new_no: int | None


@dataclass(slots=True)
class Hunk:
    index: int
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[DiffLine] = field(default_factory=list)

    @property
    def deleted(self) -> list[int]:
        return [ln.old_no for ln in self.lines if ln.tag == "-" and ln.old_no is not None]

    @property
    def added(self) -> list[int]:
        return [ln.new_no for ln in self.lines if ln.tag == "+" and ln.new_no is not None]


@dataclass(slots=True)
class FileDiff:
    old_path: str | None = None
    new_path: str | None = None
    status: FileStatus = FileStatus.MODIFIED
    similarity: int | None = None
    binary: bool = False
    mode_only: bool = False
    hunks: list[Hunk] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def path(self) -> str:
        return self.new_path or self.old_path or ""


@dataclass(slots=True)
class _Builder:
    """Mutable state while a file's header block is being read."""

    diff: FileDiff = field(default_factory=FileDiff)
    header_old: str | None = None
    header_new: str | None = None
    saw_minus: bool = False
    saw_plus: bool = False
    rename_from: str | None = None
    rename_to: str | None = None
    copy_from: str | None = None
    copy_to: str | None = None
    new_file: bool = False
    deleted_file: bool = False
    old_mode: str | None = None
    new_mode: str | None = None
    git_header: bool = False
    skip_body: bool = False

    def finish(self) -> FileDiff:
        d = self.diff
        old = self.rename_from or self.copy_from or self.header_old
        new = self.rename_to or self.copy_to or self.header_new
        if self.new_file:
            old = None
        if self.deleted_file:
            new = None
        d.old_path, d.new_path = old, new
        if self.rename_from or self.rename_to:
            d.status = FileStatus.RENAMED
        elif self.copy_from or self.copy_to:
            d.status = FileStatus.COPIED
        elif old is None and new is not None:
            d.status = FileStatus.ADDED
        elif new is None and old is not None:
            d.status = FileStatus.DELETED
        elif old is not None and new is not None and old != new:
            d.status = FileStatus.RENAMED
        else:
            d.status = FileStatus.MODIFIED
        if (
            d.status is FileStatus.MODIFIED
            and not d.hunks
            and not d.binary
            and self.old_mode != self.new_mode
        ):
            d.mode_only = True
            d.notes.append("mode_only_change")
        return d


def _unquote(raw: str) -> str:
    """Decode a git C-style quoted path (``"caf\\303\\251.py"``)."""

    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        body = raw[1:-1]
        out = bytearray()
        i = 0
        simple = {"n": 10, "t": 9, "r": 13, "\\": 92, '"': 34, "a": 7, "b": 8, "f": 12, "v": 11}
        while i < len(body):
            ch = body[i]
            if ch == "\\" and i + 1 < len(body):
                nxt = body[i + 1]
                if nxt in "01234567":
                    j = i + 1
                    digits = ""
                    while j < len(body) and len(digits) < 3 and body[j] in "01234567":
                        digits += body[j]
                        j += 1
                    out.append(int(digits, 8) & 0xFF)
                    i = j
                    continue
                if nxt in simple:
                    out.append(simple[nxt])
                    i += 2
                    continue
            out.extend(ch.encode("utf-8"))
            i += 1
        return out.decode("utf-8", errors="replace")
    return raw


def _clean_path(raw: str, *, strip_prefix: bool) -> str | None:
    value = raw.split("\t")[0].rstrip("\r")
    value = _unquote(value.strip() if value.startswith('"') else value.rstrip())
    if value == _NULL:
        return None
    value = value.replace("\\", "/")
    if strip_prefix and (value.startswith("a/") or value.startswith("b/")):
        value = value[2:]
    while value.startswith("./"):
        value = value[2:]
    return value


def _split_git_header(rest: str) -> tuple[str | None, str | None]:
    """Split the tail of ``diff --git a/x b/y`` into (old, new) best-effort."""

    rest = rest.rstrip("\r")
    if rest.startswith('"'):
        end = _closing_quote(rest)
        if end is not None:
            left, right = rest[: end + 1], rest[end + 1 :].strip()
            return _clean_path(left, strip_prefix=True), _clean_path(right, strip_prefix=True)
    candidates = [m.start() for m in re.finditer(r" (?=\"?b/)", rest)]
    best: tuple[str, str] | None = None
    for pos in candidates:
        left, right = rest[:pos], rest[pos + 1 :]
        left_c = _clean_path(left, strip_prefix=True)
        right_c = _clean_path(right, strip_prefix=True)
        if left_c is None or right_c is None:
            continue
        if best is None:
            best = (left_c, right_c)
        if left_c == right_c:
            best = (left_c, right_c)
            break
    if best is not None:
        return best
    parts = rest.split(" ")
    if len(parts) == 2:
        return _clean_path(parts[0], strip_prefix=True), _clean_path(parts[1], strip_prefix=True)
    return None, None


def _closing_quote(text: str) -> int | None:
    i = 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == '"':
            return i
        i += 1
    return None


def parse_unified_diff(text: str) -> list[FileDiff]:
    """Parse ``git diff`` / ``diff -u`` output into per-file diffs (input order)."""

    if not text or not text.strip():
        return []
    lines = text.split("\n")
    n = len(lines)
    results: list[FileDiff] = []
    cur: _Builder | None = None
    i = 0

    def close() -> None:
        nonlocal cur
        if cur is not None:
            results.append(cur.finish())
            cur = None

    while i < n:
        line = lines[i]
        if line.startswith("diff --git "):
            close()
            cur = _Builder(git_header=True)
            old, new = _split_git_header(line[len("diff --git ") :])
            cur.header_old, cur.header_new = old, new
            i += 1
            continue
        if line.startswith(("diff --cc ", "diff --combined ")):
            close()
            cur = _Builder(git_header=True, skip_body=True)
            path = _clean_path(line.split(" ", 2)[2], strip_prefix=False)
            cur.header_old = cur.header_new = path
            cur.diff.notes.append("combined_diff_unsupported")
            i += 1
            continue
        if line.startswith("--- ") and i + 1 < n and lines[i + 1].startswith("+++ "):
            if cur is None or cur.saw_plus:
                close()
                cur = _Builder()
            cur.saw_minus = cur.saw_plus = True
            old = _clean_path(line[4:], strip_prefix=True)
            new = _clean_path(lines[i + 1][4:], strip_prefix=True)
            cur.header_old = old
            cur.header_new = new
            if old is None:
                cur.new_file = True
            if new is None:
                cur.deleted_file = True
            i += 2
            continue
        if cur is None:
            i += 1  # leading junk (commit message of a format-patch, ...)
            continue
        match = _HUNK_RE.match(line)
        if match and not cur.skip_body:
            old_start = int(match.group(1))
            old_count = 1 if match.group(2) is None else int(match.group(2))
            new_start = int(match.group(3))
            new_count = 1 if match.group(4) is None else int(match.group(4))
            hunk = Hunk(len(cur.diff.hunks), old_start, old_count, new_start, new_count)
            i = _read_hunk(lines, i + 1, hunk, cur.diff)
            cur.diff.hunks.append(hunk)
            continue
        _header_line(cur, line)
        i += 1
    close()
    return results


def _header_line(cur: _Builder, line: str) -> None:
    if line.startswith("new file mode"):
        cur.new_file = True
        cur.new_mode = line.split()[-1]
    elif line.startswith("deleted file mode"):
        cur.deleted_file = True
        cur.old_mode = line.split()[-1]
    elif line.startswith("old mode "):
        cur.old_mode = line[len("old mode ") :].strip()
    elif line.startswith("new mode "):
        cur.new_mode = line[len("new mode ") :].strip()
    elif line.startswith("rename from "):
        cur.rename_from = _clean_path(line[len("rename from ") :], strip_prefix=False)
    elif line.startswith("rename to "):
        cur.rename_to = _clean_path(line[len("rename to ") :], strip_prefix=False)
    elif line.startswith("copy from "):
        cur.copy_from = _clean_path(line[len("copy from ") :], strip_prefix=False)
    elif line.startswith("copy to "):
        cur.copy_to = _clean_path(line[len("copy to ") :], strip_prefix=False)
    elif line.startswith("similarity index "):
        value = line[len("similarity index ") :].strip().rstrip("%")
        if value.isdigit():
            cur.diff.similarity = int(value)
    elif line.startswith("Binary files ") or line.startswith("GIT binary patch"):
        cur.diff.binary = True


def _read_hunk(lines: list[str], i: int, hunk: Hunk, diff: FileDiff) -> int:
    """Consume hunk body lines according to the header counts."""

    old_no = hunk.old_start
    new_no = hunk.new_start
    old_left = hunk.old_count
    new_left = hunk.new_count
    n = len(lines)
    while i < n and (old_left > 0 or new_left > 0):
        raw = lines[i]
        tag = raw[:1]
        if tag == "\\":
            i += 1
            continue
        if tag == "+" and new_left > 0:
            hunk.lines.append(DiffLine("+", raw[1:], None, new_no))
            new_no += 1
            new_left -= 1
        elif tag == "-" and old_left > 0:
            hunk.lines.append(DiffLine("-", raw[1:], old_no, None))
            old_no += 1
            old_left -= 1
        elif (tag == " " or raw in ("", "\r")) and old_left > 0 and new_left > 0:
            hunk.lines.append(DiffLine(" ", raw[1:], old_no, new_no))
            old_no += 1
            new_no += 1
            old_left -= 1
            new_left -= 1
        else:
            diff.notes.append(f"hunk_{hunk.index}_truncated")
            return i
        i += 1
    while i < n and lines[i].startswith("\\"):
        i += 1
    return i
