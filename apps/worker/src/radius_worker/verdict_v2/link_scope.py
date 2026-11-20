"""Scope LK-03 symbol->test linking to the test files that can reach a changed file.

The static and naming linkers parse every Python file they are given. On a slow host
(0.1 CPU) parsing the whole repository can use up the Stage A step budget, and a timed
out step yields no links at all. Only test files are dropped here, and only those that
cannot link to a changed symbol:

* every non-test file is kept (imports, re-exports, base classes and conftest fixtures
  still resolve);
* a test file is kept when it mentions, as a word, the module stem of a file in the
  reverse-import closure of the changed files (a text over-approximation of "imports
  it", so relative imports, ``from pkg import mod`` and re-exports through
  ``__init__.py`` are covered), when it sits under a ``conftest.py`` of that closure
  (fixture links), when it contains a changed symbol's name (naming links), when its
  file name follows the naming convention for a changed file, or when a ``tests:``
  hint names it.

If the closure does not settle within ``max_rounds`` the sources are returned
unchanged: scoping must never cost recall.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from posixpath import basename, dirname
from typing import Any

#: Rounds of the reverse-import closure before giving up and linking everything.
MAX_ROUNDS = 12
_NORM = re.compile(r"[^a-z0-9]")


def _stem(path: str) -> str:
    base = basename(path)
    if base == "__init__.py":
        return basename(dirname(path)) or base
    return base.removesuffix(".py")


def _words(stems: Iterable[str]) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(re.escape(s) for s in sorted(stems)) + r")\b")


def scope_link_sources(
    sources: Mapping[str, str],
    targets: Sequence[Any],
    keep: Iterable[str] = (),
    *,
    max_rounds: int = MAX_ROUNDS,
) -> dict[str, str]:
    """``sources`` without the Python test files that cannot link to ``targets``."""

    from radius_testing.linking.model import is_test_path

    py = {p: s for p, s in sources.items() if p.endswith(".py")}
    target_paths = {t.path for t in targets if t.path in py}
    if not target_paths:
        return dict(sources)
    reached = set(target_paths)
    stems: set[str] = set()
    new = {_stem(p) for p in reached}
    for _ in range(max_rounds):
        new -= stems
        if not new:
            break
        stems |= new
        pattern = _words(new)
        found = {p for p, s in py.items() if p not in reached and pattern.search(s)}
        reached |= found
        new = {_stem(p) for p in found}
    else:
        if new - stems:
            return dict(sources)  # not settled: link everything (no recall loss)

    conftest_dirs = {dirname(p) for p in reached if basename(p) == "conftest.py"}
    names = {
        _NORM.sub("", str(getattr(t, "qualified_name", "")).rsplit(".", 1)[-1].lower())
        for t in targets
    }
    names = {n for n in names if len(n) >= 3}
    target_stems = {_stem(p) for p in target_paths}
    kept = set(keep)

    def relevant(path: str, text: str) -> bool:
        if path in reached or path in kept:
            return True
        if any(d == "" or path.startswith(d + "/") for d in conftest_dirs):
            return True
        base = basename(path)
        if any(s in base for s in target_stems):
            return True
        flat = _NORM.sub("", text.lower())
        return any(n in flat for n in names)

    return {
        p: s
        for p, s in sources.items()
        if not (p.endswith(".py") and is_test_path(p)) or relevant(p, s)
    }
