"""Gate `pnpm audit --json` output against an expiring baseline (F-13 / QS-05).

Exit 0 when every high/critical advisory is in the baseline and no baseline
entry is expired. Exit 1 otherwise. Moderate/low findings are reported only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

BLOCKING = {"high", "critical"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audit_json", type=Path)
    parser.add_argument("baseline_json", type=Path)
    parser.add_argument("--today", default=dt.date.today().isoformat())
    args = parser.parse_args()

    audit = json.loads(args.audit_json.read_text(encoding="utf-8"))
    baseline = json.loads(args.baseline_json.read_text(encoding="utf-8"))
    today = dt.date.fromisoformat(args.today)
    entries = {e["id"]: e for e in baseline["entries"]}

    found: dict[str, tuple[str, str]] = {}
    for adv in audit.get("advisories", {}).values():
        found[adv["github_advisory_id"]] = (adv["module_name"], adv["severity"])

    failures: list[str] = []
    for adv_id, (package, severity) in sorted(found.items()):
        entry = entries.get(adv_id)
        if severity not in BLOCKING:
            print(f"info  {severity:<8} {package} {adv_id}")
            continue
        if entry is None:
            failures.append(f"NEW {severity} advisory {adv_id} in {package}")
        elif dt.date.fromisoformat(entry["expires"]) < today:
            failures.append(
                f"EXPIRED baseline for {adv_id} ({package}) on {entry['expires']}"
            )
        else:
            print(f"known {severity:<8} {package} {adv_id} (expires {entry['expires']})")

    stale = sorted(set(entries) - set(found))
    if stale:
        print(f"note: baseline entries no longer reported (remove them): {stale}")

    for failure in failures:
        print(f"FAIL: {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
