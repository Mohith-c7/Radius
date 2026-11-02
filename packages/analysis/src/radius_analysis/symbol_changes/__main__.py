"""Debug CLI: ``python -m radius_analysis.symbol_changes`` prints a SymbolChangeSet as JSON.

Examples::

    # refs of a local repository (diff and both snapshots come from git)
    python -m radius_analysis.symbol_changes --repo . --base origin/develop --head HEAD

    # a patch file plus a checkout of the head (base is rebuilt from the patch)
    python -m radius_analysis.symbol_changes --diff pr.patch --head-dir ./checkout
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from radius_analysis.symbol_changes.service import (
    ExtractionOptions,
    RefRange,
    extract_symbol_changes,
)
from radius_analysis.symbol_changes.snapshots import DirectorySnapshot, GitSnapshot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m radius_analysis.symbol_changes")
    parser.add_argument("--repo", type=Path, help="local git repository")
    parser.add_argument("--base", help="base git ref (with --repo)")
    parser.add_argument("--head", help="head git ref (with --repo)")
    parser.add_argument("--diff", help="unified diff file, or '-' for stdin")
    parser.add_argument("--head-dir", type=Path, help="checkout of the head state (with --diff)")
    parser.add_argument("--base-dir", type=Path, help="checkout of the base state (optional)")
    parser.add_argument("--ignore", action="append", default=[], help="extra ignore glob")
    parser.add_argument("--indent", type=int, default=2)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    extra = tuple(args.ignore)
    defaults = ExtractionOptions()
    options = ExtractionOptions(ignore_globs=defaults.ignore_globs + extra)
    if args.diff:
        diff = sys.stdin.read() if args.diff == "-" else Path(args.diff).read_text(encoding="utf-8")
        if args.head_dir is None:
            print("--head-dir is required with --diff", file=sys.stderr)
            return 2
        base = DirectorySnapshot(args.base_dir) if args.base_dir else None
        result = extract_symbol_changes(base, DirectorySnapshot(args.head_dir), diff, options)
    elif args.repo and args.base and args.head:
        refs = RefRange(args.repo, args.base, args.head)
        result = extract_symbol_changes(
            GitSnapshot(args.repo, args.base), GitSnapshot(args.repo, args.head), refs, options
        )
    else:
        print("provide either --diff/--head-dir or --repo/--base/--head", file=sys.stderr)
        return 2
    print(result.to_json(indent=args.indent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
