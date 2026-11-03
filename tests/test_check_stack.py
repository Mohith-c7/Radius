"""Unit tests for the pure parts of scripts/ci/check_stack.py (no Docker needed)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ci" / "check_stack.py"
_spec = importlib.util.spec_from_file_location("check_stack", _SCRIPT)
check_stack = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = check_stack
_spec.loader.exec_module(check_stack)


def _rows(**overrides: dict) -> list[dict]:
    rows = {
        "postgres": {"State": "running", "Health": "healthy", "ExitCode": 0},
        "api": {"State": "running", "Health": "healthy", "ExitCode": 0},
        "worker": {"State": "running", "Health": "", "ExitCode": 0},
        "dashboard": {"State": "running", "Health": "healthy", "ExitCode": 0},
        "migrations": {"State": "exited", "Health": "", "ExitCode": 0},
    }
    rows.update(overrides)
    return [{"Service": name, **row} for name, row in rows.items()]


def test_healthy_stack_has_no_problems() -> None:
    assert check_stack.evaluate_services(_rows()) == []


def test_crashed_worker_is_reported() -> None:
    problems = check_stack.evaluate_services(
        _rows(worker={"State": "exited", "Health": "", "ExitCode": 1})
    )
    assert len(problems) == 1
    assert "worker" in problems[0]
    assert "exit code 1" in problems[0]


def test_unhealthy_and_missing_services_are_reported() -> None:
    rows = [
        row
        for row in _rows(api={"State": "running", "Health": "unhealthy", "ExitCode": 0})
        if row["Service"] != "dashboard"
    ]
    problems = check_stack.evaluate_services(rows)
    assert any("api: health" in problem for problem in problems)
    assert any("dashboard: no container" in problem for problem in problems)


def test_failed_migrations_are_reported() -> None:
    problems = check_stack.evaluate_services(
        _rows(migrations={"State": "exited", "Health": "", "ExitCode": 3})
    )
    assert any("migrations" in problem for problem in problems)


def test_parse_ps_accepts_array_and_json_lines() -> None:
    rows = _rows()
    assert check_stack.parse_ps(json.dumps(rows)) == rows
    assert check_stack.parse_ps("\n".join(json.dumps(row) for row in rows)) == rows
    assert check_stack.parse_ps("") == []


def test_worker_ready_line() -> None:
    assert check_stack.worker_is_ready("worker-1  | Radius worker ready\n")
    assert not check_stack.worker_is_ready(
        "ModuleNotFoundError: No module named 'radius_evidence'"
    )
