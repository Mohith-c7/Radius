#!/usr/bin/env python
"""Run the tamper rule engine (EV-02) over a directory of labelled fixtures.

FIXTURE SANITY CHECK, NOT A RESEARCH RESULT. The F-14 fixtures were written together
with the rules' expectations, eight cases are far too few for any recall or precision
claim, and nothing here measures hit rates on real agent or human PRs (that is EP-07/RQ2).
The script is the hook for that later evaluation: point ``fixtures_dir`` at any directory
whose sub-directories have ``base/``, ``head/``, ``pr.patch`` and (optionally)
``expected.json`` with a ``tamper_findings`` list.

Usage::

    python scripts/tamper_eval.py [FIXTURES_DIR] [--config rules.json] [--json] [--check]

``--check`` exits 1 when a fixture's findings differ from ``expected.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for src in sorted((ROOT / "packages").glob("*/src")):
    sys.path.insert(0, str(src))

from radius_analysis.symbol_changes import (  # noqa: E402
    DirectorySnapshot,
    ExtractionOptions,
    extract_symbol_changes,
)
from radius_analysis.tamper import TamperConfig, analyze_tampering, default_registry  # noqa: E402

DEFAULT_DIR = ROOT / "benchmarks" / "fixtures" / "intent"
BANNER = "FIXTURE SANITY CHECK - not a research result (8 hand-written fixtures; no recall/precision claim)"


def evaluate_fixture(path: Path, config: TamperConfig) -> dict:
    diff = (path / "pr.patch").read_text(encoding="utf-8")
    base, head = DirectorySnapshot(path / "base"), DirectorySnapshot(path / "head")
    changes = extract_symbol_changes(base, head, diff, ExtractionOptions())
    report = analyze_tampering(changes, base, head, config, diff_text=diff)
    actual = [
        {"rule": f.rule_id, "check": f.check, "file": f.path, "test": f.test_id,
         "severity": f.severity.label, "id": f.finding_id}
        for f in report.findings
    ]
    expected_file = path / "expected.json"
    expected = None
    if expected_file.exists():
        expected = json.loads(expected_file.read_text(encoding="utf-8")).get("tamper_findings")
    missing: list[dict] = []
    unexpected = list(actual)
    if expected is not None:
        for exp in expected:
            hit = next(
                (a for a in unexpected if a["rule"] == exp["rule"] and a["file"] == exp["file"]
                 and (exp.get("test") is None or a["test"] == exp["test"])),
                None,
            )
            if hit is None:
                missing.append(exp)
            else:
                unexpected.remove(hit)
    return {
        "fixture": path.name, "findings": actual, "expected": expected,
        "missing": missing, "unexpected": unexpected if expected is not None else [],
        "unanalyzable": [u.to_dict() for u in report.unanalyzable],
        "rule_errors": list(report.rule_errors),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("fixtures_dir", nargs="?", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--config", type=Path)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--check", action="store_true", help="exit 1 on any expectation mismatch")
    args = ap.parse_args(argv)

    known = default_registry().ids()
    config = TamperConfig.from_json_file(args.config, known_rules=known) if args.config \
        else TamperConfig()
    fixtures = sorted(
        p for p in args.fixtures_dir.iterdir()
        if p.is_dir() and (p / "base").is_dir() and (p / "head").is_dir() and (p / "pr.patch").exists()
    )
    results = [evaluate_fixture(p, config) for p in fixtures]
    per_rule: Counter[str] = Counter()
    for r in results:
        per_rule.update(f["rule"] for f in r["findings"])
    bad = [r for r in results if r["missing"] or r["unexpected"] or r["rule_errors"]]

    if args.json:
        print(json.dumps({"label": BANNER, "per_rule_hits": dict(sorted(per_rule.items())),
                          "fixtures": results}, indent=2, sort_keys=True))
    else:
        print(BANNER)
        print(f"fixtures: {len(results)}  directory: {args.fixtures_dir}")
        for r in results:
            status = "n/a" if r["expected"] is None else ("MISMATCH" if r in bad else "ok")
            print(f"\n{r['fixture']}: {len(r['findings'])} finding(s) [{status}]")
            for f in r["findings"]:
                print(f"  {f['rule']}:{f['check']:<24} {f['severity']:<6} {f['file']}"
                      f"{'  ' + f['test'] if f['test'] else ''}")
            for m in r["missing"]:
                print(f"  MISSING    {m['rule']} {m['file']} {m.get('test') or ''}")
            for u in r["unexpected"]:
                print(f"  UNEXPECTED {u['rule']}:{u['check']} {u['file']} {u['test'] or ''}")
            for e in r["rule_errors"]:
                print(f"  RULE ERROR {e}")
        print("\nper-rule hits (all fixtures):")
        for rule in sorted(known):
            print(f"  {rule}: {per_rule.get(rule, 0)}")
    return 1 if (args.check and bad) else 0


if __name__ == "__main__":
    raise SystemExit(main())
