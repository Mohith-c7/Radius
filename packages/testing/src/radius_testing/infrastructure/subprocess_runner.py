"""Subprocess-backed test runner."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from radius_testing.domain.entities import TestRunPlan, TestRunResult
from radius_testing.domain.enums import TestRunStatus


class SubprocessTestRunner:
    """Execute planned test commands with timeout and output capture."""

    SAFE_ENV_VARS = {
        "PATH", "SYSTEMROOT", "SYSTEMDRIVE", "LANG", "TEMP", "TMP", 
        "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PYTHONPATH"
    }
    MAX_OUTPUT_SIZE = 500 * 1024  # 500KB

    def __init__(self, timeout_seconds: int = 300) -> None:
        self._timeout_seconds = timeout_seconds

    def _get_sanitized_env(self) -> dict[str, str]:
        """Strip sensitive secrets from the environment."""
        env = {}
        for k, v in os.environ.items():
            if k.upper() in self.SAFE_ENV_VARS:
                env[k] = v
        return env

    def run(self, plan: TestRunPlan, repository_path: Path) -> TestRunResult:
        """Execute all commands in a test run plan."""

        started = time.monotonic()
        outputs: list[str] = []
        failed_commands = 0
        
        env = self._get_sanitized_env()

        for command, args in plan.command_plan:
            with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as out_f, \
                 tempfile.TemporaryFile(mode="w+", encoding="utf-8") as err_f:
                try:
                    completed = subprocess.run(
                        (command, *args),
                        cwd=repository_path,
                        stdout=out_f,
                        stderr=err_f,
                        timeout=self._timeout_seconds,
                        env=env,
                        check=False,
                    )
                    returncode = completed.returncode
                except subprocess.TimeoutExpired:
                    returncode = 1
                    outputs.append(f"Command timed out after {self._timeout_seconds} seconds")

                out_f.seek(0)
                err_f.seek(0)
                stdout = out_f.read(self.MAX_OUTPUT_SIZE)
                stderr = err_f.read(self.MAX_OUTPUT_SIZE)

                if stdout:
                    outputs.append(stdout)
                if stderr:
                    outputs.append(stderr)
                if returncode != 0:
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

