"""Subprocess-backed test runner."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from uuid import uuid4

from radius_testing.domain.entities import TestRunPlan, TestRunResult
from radius_testing.domain.enums import TestRunStatus


class SubprocessTestRunner:
    """Execute planned test commands with timeout and output capture."""

    def __init__(self, timeout_seconds: int = 300) -> None:
        self._timeout_seconds = timeout_seconds

    def run(self, plan: TestRunPlan, repository_path: Path) -> TestRunResult:
        """Execute all commands in a test run plan."""

        started = time.monotonic()
        outputs: list[str] = []
        failed_commands = 0
        for command, args in plan.command_plan:
            completed = subprocess.run(
                (command, *args),
                cwd=repository_path,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                check=False,
            )
            outputs.append(completed.stdout)
            outputs.append(completed.stderr)
            if completed.returncode != 0:
                failed_commands += 1
        total = len(plan.selected_tests)
        failed = total if failed_commands else 0
        passed = total - failed
        return TestRunResult(
            id=uuid4(),
            analysis_id=plan.analysis_id,
            status=TestRunStatus.FAILED if failed else TestRunStatus.PASSED,
            total_tests=total,
            passed=passed,
            failed=failed,
            skipped=0,
            duration_ms=int((time.monotonic() - started) * 1000),
            output="\n".join(item for item in outputs if item),
        )
