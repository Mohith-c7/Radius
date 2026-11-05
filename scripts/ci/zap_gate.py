"""Gate a ZAP JSON report (used by dast.yml): fail only on HIGH alerts.

Usage: python scripts/ci/zap_gate.py REPORT.json [--rules .zap/rules.tsv]

ZAP ``riskcode`` 3 is High. A High alert whose plugin id is listed as IGNORE in the
rules file (documented false positive) is not counted. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def ignored_rules(text: str) -> set[str]:
    ids: set[str] = set()
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1].strip().upper() == "IGNORE":
            ids.add(parts[0].strip())
    return ids


def high_alerts(report: dict, ignored: set[str]) -> list[str]:
    found: list[str] = []
    for site in report.get("site", []):
        for alert in site.get("alerts", []):
            if str(alert.get("riskcode")) == "3" and str(alert.get("pluginid")) not in ignored:
                found.append(f"{alert.get('pluginid')}: {alert.get('name')} ({site.get('@name')})")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("report", type=Path)
    parser.add_argument("--rules", type=Path, default=Path(".zap/rules.tsv"))
    args = parser.parse_args(argv)
    rules = args.rules.read_text(encoding="utf-8") if args.rules.exists() else ""
    report = json.loads(args.report.read_text(encoding="utf-8"))
    problems = high_alerts(report, ignored_rules(rules))
    for problem in problems:
        print(f"HIGH: {problem}", file=sys.stderr)
    print("zap gate:", "FAILED" if problems else "ok (no unignored High alerts)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
