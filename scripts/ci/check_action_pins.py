"""Assert every `uses:` in .github/workflows is pinned to a full commit SHA.

Regression guard for the OpenSSF Scorecard Pinned-Dependencies check.
Local actions (`./...`) and `docker://...@sha256:` references are allowed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(?P<ref>[^\s#]+)(?P<rest>.*)$")
SHA = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
DIGEST = re.compile(r"^docker://[^@\s]+@sha256:[0-9a-f]{64}$")
VERSION_COMMENT = re.compile(r"#\s*v?\d")


def find_violations(workflow_dir: Path) -> list[str]:
    problems: list[str] = []
    for path in sorted([*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")]):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = USES.match(line)
            if not match:
                continue
            ref = match["ref"].strip("\"'")
            where = f"{path.name}:{number}"
            if ref.startswith("./") or DIGEST.match(ref):
                continue
            if not SHA.match(ref):
                problems.append(f"{where}: not pinned to a full SHA: {ref}")
            elif not VERSION_COMMENT.search(match["rest"]):
                problems.append(f"{where}: missing '# vX.Y.Z' comment: {ref}")
    return problems


def main() -> int:
    root = Path(__file__).resolve().parents[2] / ".github" / "workflows"
    problems = find_violations(root)
    for problem in problems:
        print(f"FAIL: {problem}")
    print("action pin check:", "FAILED" if problems else "ok")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
