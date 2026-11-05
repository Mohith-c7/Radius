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


def find_violations(workflow_dir: Path, *extra_files: Path) -> list[str]:
    problems: list[str] = []
    paths = {*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml"), *extra_files}
    for path in sorted(paths):
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


def action_files(repo: Path) -> list[Path]:
    """Composite actions shipped from this repo (actions/**/action.yml)."""

    return sorted((repo / "actions").glob("**/action.y*ml"))


def main() -> int:
    repo = Path(__file__).resolve().parents[2]
    problems = find_violations(repo / ".github" / "workflows", *action_files(repo))
    for problem in problems:
        print(f"FAIL: {problem}")
    print("action pin check:", "FAILED" if problems else "ok")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
