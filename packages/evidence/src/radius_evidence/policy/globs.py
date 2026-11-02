"""Path globs for policy and waiver scopes (``*``, ``**``, ``?``; ``/`` separators).

``*`` and ``?`` never cross a ``/``; ``**`` crosses any number of directories
(``src/auth/**`` matches ``src/auth/a.py`` and ``src/auth/x/y.py``; ``**/x.py``
matches ``x.py`` at any depth). The translation is to an anchored regex built
from a closed alphabet and at most ``MAX_WILDCARDS`` wildcards per glob, so
matching is cheap and cannot backtrack catastrophically.
"""

from __future__ import annotations

import re
from functools import lru_cache

MAX_GLOB_LENGTH = 200
MAX_PATH_LENGTH = 1024
MAX_WILDCARDS = 6


def normalize_path(path: str) -> str:
    out = path.replace("\\", "/")
    while out.startswith("./"):
        out = out[2:]
    return out.lstrip("/")


def glob_problem(glob: str) -> str | None:
    """Why ``glob`` is not acceptable, or ``None``."""

    if not isinstance(glob, str) or not glob.strip():
        return "empty glob"
    if len(glob) > MAX_GLOB_LENGTH:
        return f"glob longer than {MAX_GLOB_LENGTH} characters"
    if glob.startswith("/") or re.match(r"^[A-Za-z]:", glob):
        return "absolute paths are not allowed; use a repository-relative glob"
    if ".." in glob.replace("\\", "/").split("/"):
        return "'..' is not allowed in a glob"
    if "\x00" in glob:
        return "NUL in glob"
    if glob.count("*") + glob.count("?") > MAX_WILDCARDS * 2:
        return "too many wildcards"
    if re.search(r"\*\*[^/]", glob) or re.search(r"[^/]\*\*", glob):
        return "'**' must be a whole path segment"
    return None


@lru_cache(maxsize=512)
def _compile(glob: str) -> re.Pattern[str]:
    glob = normalize_path(glob)
    out: list[str] = []
    i, n = 0, len(glob)
    while i < n:
        c = glob[i]
        if glob.startswith("**/", i):
            out.append("(?:[^/]+/)*")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("".join(out) + r"\Z")


def path_matches(glob: str, path: str) -> bool:
    """True when ``path`` (repo-relative) matches ``glob``; invalid globs never match."""

    if glob_problem(glob) is not None:
        return False
    norm = normalize_path(path)
    if not norm or norm.endswith("/") or len(norm) > MAX_PATH_LENGTH:
        return False
    return _compile(glob).match(norm) is not None


def any_match(globs: tuple[str, ...] | list[str], path: str) -> bool:
    return any(path_matches(g, path) for g in globs)
