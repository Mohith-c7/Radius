"""Unified git diff hunk parser for extracting modified line numbers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


def _normalize_path(path: str) -> str:
    """Normalize file path from git diff headers by stripping prefixes and whitespace."""
    value = path.strip().replace("\\", "/")
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        value = value[1:-1]
    if value in ("/dev/null", "dev/null"):
        return ""
    if value.startswith("a/") or value.startswith("b/"):
        return value[2:]
    return value.lstrip("/")


_HUNK_RE = re.compile(r"^@@\s+-[0-9]+(?:,[0-9]+)?\s+\+([0-9]+)(?:,[0-9]+)?\s+@@")


@dataclass(slots=True)
class FileLineChanges:
    """Line-level changes of one file in the new-file coordinate system."""

    added: set[int] = field(default_factory=set)
    # New-file line number that follows each deletion point.
    deleted_at: set[int] = field(default_factory=set)
    # Text of every deleted line (without the leading '-').
    deleted_text: list[str] = field(default_factory=list)

    @property
    def modified(self) -> set[int]:
        return self.added | self.deleted_at


def parse_diff_modified_lines(diff_text: str) -> dict[str, set[int]]:
    """Parse a unified git diff and return modified 1-indexed line numbers per file.

    Tracks 1-indexed line numbers of the new file:
      - Context lines (' '): increment current line.
      - Added/modified lines ('+'): add current line to modified set, increment current line.
      - Deleted lines ('-'): add current line to modified set (the point of deletion affects this location in the file), do NOT increment current line.

    Returns:
        Dictionary mapping normalized file path (forward slashes, stripped 'a/' and 'b/')
        to a set of 1-indexed line numbers modified in the new file.
    """
    return {
        path: changes.modified
        for path, changes in parse_diff_line_changes(diff_text).items()
    }


def parse_diff_line_changes(diff_text: str) -> dict[str, FileLineChanges]:
    """Parse a unified git diff into added lines, deletion points and deleted text.

    Same traversal as :func:`parse_diff_modified_lines`, but keeps added lines
    and deletions apart so callers can tell that a symbol definition was removed.
    """
    if not diff_text or not isinstance(diff_text, str) or not diff_text.strip():
        return {}

    modified_lines: dict[str, FileLineChanges] = {}
    current_file: str | None = None
    old_file: str | None = None
    current_line = 1
    in_hunk = False

    for raw_line in diff_text.splitlines():
        line = raw_line.rstrip("\r\n")

        # Check diff --git header
        if line.startswith("diff --git "):
            in_hunk = False
            parts = line[len("diff --git ") :].strip()
            # Try matching quoted or unquoted a/... and b/...
            m = re.match(r'^["\']?a/(.+?)["\']?\s+["\']?b/(.+)["\']?$', parts)
            if m:
                old_raw = m.group(1).strip()
                new_raw = m.group(2).strip()
                old_file = (
                    _normalize_path(old_raw)
                    if old_raw not in ("/dev/null", "dev/null")
                    else None
                )
                new_p = _normalize_path(new_raw)
                current_file = new_p if new_p else old_file
            else:
                tokens = parts.split()
                if len(tokens) >= 2:
                    old_file = _normalize_path(tokens[0])
                    new_p = _normalize_path(tokens[1])
                    current_file = new_p if new_p else old_file
                elif len(tokens) == 1:
                    current_file = _normalize_path(tokens[0])
            if current_file:
                modified_lines.setdefault(current_file, FileLineChanges())
            continue

        # Check --- header
        if line.startswith("--- "):
            in_hunk = False
            raw = line.removeprefix("--- ").strip().split("\t")[0]
            old_p = _normalize_path(raw)
            old_file = old_p if old_p else None
            continue

        # Check +++ header
        if line.startswith("+++ "):
            in_hunk = False
            raw = line.removeprefix("+++ ").strip().split("\t")[0]
            new_p = _normalize_path(raw)
            if new_p:
                current_file = new_p
            elif old_file:
                current_file = old_file
            if current_file:
                modified_lines.setdefault(current_file, FileLineChanges())
            continue

        # Check hunk header: @@ -old_start,old_count +new_start,new_count @@
        hunk_match = _HUNK_RE.match(line)
        if hunk_match:
            in_hunk = True
            new_start = int(hunk_match.group(1))
            current_line = max(1, new_start)
            continue

        if not in_hunk or current_file is None:
            continue

        # Within a hunk:
        if line.startswith("+"):
            modified_lines[current_file].added.add(current_line)
            current_line += 1
        elif line.startswith("-"):
            modified_lines[current_file].deleted_at.add(current_line)
            modified_lines[current_file].deleted_text.append(line[1:])
            # do NOT increment current_line
        elif line.startswith(" "):
            current_line += 1
        elif line.startswith("\\"):
            # e.g. \ No newline at end of file
            continue
        elif line == "":
            # blank context line
            current_line += 1

    return modified_lines
