#!/usr/bin/env python3
"""Print the extracted test assertions (LK-04) as JSON, for debugging.

Usage::

    python scripts/assertion_dump.py [--root DIR] [--summary] [--test-id ID] FILE_OR_DIR...

Paths are made relative to ``--root`` (default: the current directory) so test
ids match the ones LK-03 produces. Python and (partial) TS/JS test files are read;
nothing is executed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for pkg in ("testing", "graph", "analysis", "parser", "shared"):
    sys.path.insert(0, str(ROOT / "packages" / pkg / "src"))

from radius_testing.assertions import extract_assertions  # noqa: E402
from radius_testing.linking.model import is_test_path  # noqa: E402

_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".tox"}


def collect(root: Path, targets: list[str]) -> dict[str, str]:
    files: dict[str, str] = {}
    for t in targets:
        p = (root / t) if not Path(t).is_absolute() else Path(t)
        candidates = [p] if p.is_file() else sorted(q for q in p.rglob("*") if q.is_file())
        for q in candidates:
            if any(part in _SKIP_DIRS for part in q.parts):
                continue
            rel = q.resolve().relative_to(root.resolve()).as_posix()
            if p.is_file() or is_test_path(rel) or q.name == "conftest.py":
                files[rel] = q.read_text(encoding="utf-8", errors="replace")
    return files


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--root", default=".")
    ap.add_argument("--summary", action="store_true", help="print counts only")
    ap.add_argument("--test-id", help="only assertions of this test id")
    args = ap.parse_args(argv)
    root = Path(args.root)
    files = collect(root, args.paths)
    tests = [p for p in files if p.endswith(".py") and p.rsplit("/", 1)[-1] == "conftest.py"]
    test_files = [p for p in files if p not in tests]
    result = extract_assertions(test_files, files)
    data = result.to_dict()
    if args.test_id:
        data["assertions"] = [a for a in data["assertions"] if a["test_id"] == args.test_id]
        data["tests"] = [t for t in data["tests"] if t["test_id"] == args.test_id]
    if args.summary:
        data = {"counts": data["counts"], "notes": data["notes"]}
    json.dump(data, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
