"""Fail on strong-copyleft licenses in dependency license reports (F-13).

Inputs: `pip-licenses --format=json` output and optionally the JSON from
`pnpm licenses list --json` (a mapping of license -> packages).
Weak copyleft (LGPL/MPL) is reported but allowed; see docs/security/CI_CHECKS.md.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DENY = re.compile(r"\b(AGPL|SSPL|GPL)", re.IGNORECASE)
ALLOW_EXPRESSION = re.compile(r"LGPL", re.IGNORECASE)


def denied(license_name: str) -> bool:
    stripped = ALLOW_EXPRESSION.sub("", license_name)
    return bool(DENY.search(stripped))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pip", type=Path, required=True)
    parser.add_argument("--pnpm", type=Path)
    args = parser.parse_args()

    bad: list[str] = []
    for row in json.loads(args.pip.read_text(encoding="utf-8")):
        if denied(row["License"]):
            bad.append(f"python {row['Name']} {row['Version']}: {row['License']}")
    if args.pnpm:
        data = json.loads(args.pnpm.read_text(encoding="utf-8"))
        for license_name, packages in data.items():
            if denied(license_name):
                names = ", ".join(p["name"] for p in packages)
                bad.append(f"node {names}: {license_name}")

    for line in bad:
        print(f"FAIL: {line}")
    print("license check:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
