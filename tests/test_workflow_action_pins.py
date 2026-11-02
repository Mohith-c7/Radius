"""Guard: GitHub Actions are SHA-pinned (Scorecard Pinned-Dependencies)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_action_pins", ROOT / "scripts" / "ci" / "check_action_pins.py"
)
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)


def test_all_workflow_actions_are_sha_pinned() -> None:
    assert module.find_violations(ROOT / ".github" / "workflows", *module.action_files(ROOT)) == []


def test_shipped_composite_actions_are_scanned(tmp_path: Path) -> None:
    action = tmp_path / "action.yml"
    action.write_text(
        "runs:\n  steps:\n    - uses: actions/checkout@v4\n",
        encoding="utf-8",
    )
    assert len(module.find_violations(tmp_path, action)) == 1


def test_detects_unpinned_actions(tmp_path: Path) -> None:
    sha = "11d5960a326750d5838078e36cf38b85af677262"
    (tmp_path / "bad.yml").write_text(
        "jobs:\n  a:\n    steps:\n"
        "      - uses: actions/checkout@v4\n"
        f"      - uses: actions/checkout@{sha}\n"
        "      - uses: ./local\n"
        f"      - uses: actions/checkout@{sha} # v4.4.0\n",
        encoding="utf-8",
    )
    assert len(module.find_violations(tmp_path)) == 2
