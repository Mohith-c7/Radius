"""Debug CLI: ``python -m radius_analysis.tamper rules|catalog-md|analyze``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from radius_analysis.symbol_changes import (
    DirectorySnapshot,
    ExtractionOptions,
    extract_symbol_changes,
)
from radius_analysis.tamper.config import TamperConfig
from radius_analysis.tamper.registry import catalog_markdown, default_registry
from radius_analysis.tamper.service import analyze_tampering


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m radius_analysis.tamper")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("rules", help="list rules and checks as JSON")
    sub.add_parser("catalog-md", help="print the markdown catalog table")
    an = sub.add_parser("analyze", help="analyze base/head directories with a diff file")
    an.add_argument("base", type=Path)
    an.add_argument("head", type=Path)
    an.add_argument("diff", type=Path)
    an.add_argument("--config", type=Path)
    args = parser.parse_args(argv)

    if args.cmd == "rules":
        data = [
            {"id": r.id, "family": str(r.family), "title": r.doc.title,
             "checks": {k: {"severity": v.severity.label, "description": v.description}
                        for k, v in r.checks.items()}}
            for r in default_registry().all()
        ]
        print(json.dumps(data, indent=2))
    elif args.cmd == "catalog-md":
        sys.stdout.write(catalog_markdown())
    else:
        diff = args.diff.read_text(encoding="utf-8")
        base, head = DirectorySnapshot(args.base), DirectorySnapshot(args.head)
        changes = extract_symbol_changes(base, head, diff, ExtractionOptions())
        cfg = TamperConfig.from_json_file(args.config) if args.config else TamperConfig()
        print(analyze_tampering(changes, base, head, cfg, diff_text=diff).to_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
