"""Helpers shared by the linkers: glob matching, test-path detection, reason building."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import PurePosixPath

from radius_linking.domain import Reason, SymbolDoc

_TEST_PARTS = frozenset({"tests", "test", "__tests__", "spec", "specs", "testing"})
_TEST_NAME = re.compile(
    r"(^test_.*\.py$|.*_test\.(py|go|rb)$|.*\.(test|spec)\.(js|jsx|ts|tsx|mjs|cjs)$|^conftest\.py$)"
)


def is_test_path(path: str) -> bool:
    parts = PurePosixPath(path.replace("\\", "/")).parts
    if any(p in _TEST_PARTS for p in parts[:-1]):
        return True
    return bool(_TEST_NAME.match(parts[-1])) if parts else False


@lru_cache(maxsize=512)
def _glob_regex(pattern: str) -> re.Pattern[str]:
    out: list[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif ch == "*":
            out.append("[^/]*")
            i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(ch))
            i += 1
    return re.compile("".join(out) + r"\Z")


def normalize_path(path: str) -> str:
    p = path.strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


def has_wildcard(pattern: str) -> bool:
    return any(c in pattern for c in "*?")


def glob_match(pattern: str, path: str) -> bool:
    """Repo-relative glob. ``**`` crosses directories; plain names match a file or a directory."""

    pat = normalize_path(pattern)
    path = normalize_path(path)
    if not pat:
        return False
    if pat.endswith("/"):
        return path.startswith(pat)
    if _glob_regex(pat).match(path):
        return True
    if not has_wildcard(pat):
        return path.startswith(pat + "/")
    return False


def pattern_specificity(pattern: str) -> float:
    """How narrowly a path hint points: exact file 0.85, wildcard file set 0.7, broad 0.5."""

    pat = normalize_path(pattern)
    if pat.endswith("/") or pat.endswith("**") or pat in {"*", ""}:
        return 0.5
    if has_wildcard(pat):
        return 0.7
    last = pat.rsplit("/", 1)[-1]
    return 0.85 if "." in last else 0.5  # a bare directory name is a broad hint


def reason(linker: str, kind: str, detail: str, score: float) -> Reason:
    return Reason(linker, kind, detail[:240], round(min(1.0, max(0.0, score)), 6))


def noisy_or(values: list[float]) -> float:
    p = 1.0
    for v in values:
        p *= 1.0 - min(1.0, max(0.0, v))
    return 1.0 - p


def sort_reasons(reasons: list[Reason]) -> tuple[Reason, ...]:
    return tuple(sorted(reasons, key=lambda r: (-r.score, r.linker, r.kind, r.detail)))


def symbol_dir(sym: SymbolDoc) -> str:
    return str(PurePosixPath(sym.path).parent)
