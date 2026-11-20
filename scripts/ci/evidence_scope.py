"""Decide which Radius evidence test jobs a pull request needs (radius-evidence.yml).

Reads the changed paths (``git diff --name-only --no-renames BASE HEAD``) on stdin
and writes GitHub Actions outputs to stdout:

    python-matrix=[{"shard": "api", "paths": "apps/api/tests"}, ...]   (JSON, may be [])
    dashboard=true|false

Radius needs a result for every selected test, so a suite is skipped only when the
pull request cannot change anything its tests read. The rules are conservative:

* Ignored (no suite runs): ``changelog.d/**``, and prose or images under ``docs/``
  (``.md``, ``.png`` ...) outside ``docs/research/`` whose file name no source,
  script or test in the repository mentions. Tests read several docs files
  (TAMPER_RULES.md, the Verdict v2 design fixtures, openapi.json), so anything
  named in code counts as a change to the code.
* ``apps/dashboard/**``: the dashboard tests, plus the Python shard that holds the
  root ``tests/`` directory (scripts/gen_config_reference.py scans the dashboard
  sources for environment variables, and tests/test_config_reference.py runs it).
* Anything else, including an unreadable diff: every suite.

The shards are listed here so the split can be tested to cover every test directory.

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Iterable
from functools import cache
from pathlib import Path, PurePosixPath

# Balanced on measured per-directory test time (pytest JUnit times, full suite):
# apps/api ~32%, tests ~21%, apps/worker ~17%, packages/testing + repository ~17%,
# all other packages ~12%. "rest" stands for every packages/*/tests directory not
# named by another shard, so a new package is picked up without editing this list.
# "testing" needs the sandbox image (packages/testing/tests/test_sandbox_runner.py).
SHARDS: tuple[dict[str, str], ...] = (
    {"shard": "api", "paths": "apps/api/tests"},
    {"shard": "root", "paths": "tests"},
    {"shard": "worker", "paths": "apps/worker/tests"},
    {"shard": "testing", "paths": "packages/testing/tests packages/repository/tests"},
    {"shard": "rest", "paths": "rest"},
)
# Shards whose tests read apps/dashboard (tests/test_config_reference.py).
DASHBOARD_COUPLED = frozenset({"root"})

DOC_SUFFIXES = frozenset({".md", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"})
SOURCE_SUFFIXES = frozenset(
    {".py", ".mjs", ".js", ".ts", ".tsx", ".json", ".yml", ".yaml", ".toml", ".cfg", ".ini", ".sh"}
)
SKIP_DIRS = frozenset({".git", "node_modules", ".next", ".turbo", "__pycache__", ".venv"})


def named_packages(shards: Iterable[dict[str, str]] = SHARDS) -> set[str]:
    """Package directories (``packages/<name>``) given to a shard explicitly."""
    named = set()
    for shard in shards:
        for path in shard["paths"].split():
            parts = PurePosixPath(path).parts
            if len(parts) >= 2 and parts[0] == "packages":
                named.add(parts[1])
    return named


def rest_paths(root: Path, shards: Iterable[dict[str, str]] = SHARDS) -> list[str]:
    """``packages/*/tests`` directories that no other shard names."""
    named = named_packages(shards)
    return sorted(
        f"packages/{tests.parent.name}/tests"
        for tests in (root / "packages").glob("*/tests")
        if tests.is_dir() and tests.parent.name not in named
    )


def _referenced_names(root: Path) -> str:
    """Concatenated text of every source, script and test file outside docs/."""
    chunks: list[str] = []
    for current, dirs, files in os.walk(root):
        top = Path(current) == root
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not (top and d == "docs")]
        for name in files:
            if Path(name).suffix in SOURCE_SUFFIXES:
                try:
                    chunks.append((Path(current) / name).read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    continue
    return "\n".join(chunks)


def classify(path: str, is_referenced: Callable[[str], bool]) -> str:
    """``ignore``, ``dashboard`` or ``all`` for one changed path."""
    p = PurePosixPath(path.strip().replace("\\", "/"))
    parts = p.parts
    if not parts:
        return "ignore"
    if parts[0] == "changelog.d":
        return "ignore"
    if (
        parts[0] == "docs"
        and (len(parts) < 2 or parts[1] != "research")
        and p.suffix.lower() in DOC_SUFFIXES
        and not is_referenced(p.name)
    ):
        return "ignore"
    if parts[:2] == ("apps", "dashboard"):
        return "dashboard"
    return "all"


def decide(
    paths: Iterable[str], is_referenced: Callable[[str], bool]
) -> tuple[list[dict[str, str]], bool]:
    """The Python shards to run and whether to run the dashboard tests."""
    kinds = {classify(path, is_referenced) for path in paths if path.strip()}
    if "all" in kinds:
        return list(SHARDS), True
    if "dashboard" in kinds:
        return [s for s in SHARDS if s["shard"] in DASHBOARD_COUPLED], True
    return [], False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("."), help="Checked-out repository root.")
    parser.add_argument(
        "--all", action="store_true", help="Run every suite (the diff could not be computed)."
    )
    parser.add_argument(
        "--rest", action="store_true", help="Print the directories of the 'rest' shard and exit."
    )
    args = parser.parse_args(argv)
    if args.rest:
        print(" ".join(rest_paths(args.root)))
        return 0
    if args.all:
        matrix, dashboard = list(SHARDS), True
    else:
        root = args.root

        @cache
        def text() -> str:  # read once, and only when a docs file needs the check
            return _referenced_names(root)

        matrix, dashboard = decide(sys.stdin.read().splitlines(), lambda name: name in text())
    print(f"python-matrix={json.dumps(matrix, separators=(',', ':'))}")
    print(f"dashboard={'true' if dashboard else 'false'}")
    print(
        f"evidence-scope: {len(matrix)} Python shard(s), dashboard={dashboard}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
