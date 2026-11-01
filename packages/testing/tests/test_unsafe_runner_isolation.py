"""Adversarial test: why in-process execution is not a security boundary.

``SubprocessTestRunner`` strips secrets from the child's environment, but the
child runs as the same uid as the worker and can simply read the worker's
original environment from ``/proc/<ppid>/environ``. This test proves the leak
so that the default (``WORKER_TEST_EXECUTION_MODE=disabled``) stays justified.
If this test ever starts failing, re-check the reasoning in
``docs/security/EXECUTION_ISOLATION.md`` rather than deleting it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SECRET = "postgresql://radius:LEAKED-VIA-PROC-1f2e3d@db/radius"
PACKAGES = Path(__file__).resolve().parents[2]
WORKER_PYTHONPATH = os.pathsep.join(
    str(PACKAGES / name / "src") for name in ("testing", "shared")
)

PROBE = textwrap.dedent(
    """
    import os
    print("ENV_HAS_SECRET=" + str("DATABASE_URL" in os.environ))
    try:
        data = open(f"/proc/{os.getppid()}/environ", "rb").read()
        print("PROC_HAS_SECRET=" + str(b"LEAKED-VIA-PROC" in data))
    except OSError as exc:
        print("PROC_HAS_SECRET=unreadable " + type(exc).__name__)
    """
)

# The "worker": a separate process whose real (exec-time) environment holds the
# secret, running the in-process runner exactly as the worker would.
WORKER = textwrap.dedent(
    """
    import sys
    from pathlib import Path
    from uuid import uuid4
    from radius_testing.domain import TestRunPlan
    from radius_testing.infrastructure import SubprocessTestRunner

    plan = TestRunPlan.pending(
        analysis_id=uuid4(),
        selected_tests=(),
        command_plan=(("python", ("probe.py",)),),
    )
    result = SubprocessTestRunner(timeout_seconds=30).run(plan, Path(sys.argv[1]))
    print(result.output)
    """
)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="/proc is Linux-only")
def test_unsafe_in_process_child_can_read_worker_secrets_via_proc(tmp_path: Path) -> None:
    if shutil.which("python") is None:
        pytest.skip("no `python` on PATH for the planned command")
    (tmp_path / "probe.py").write_text(PROBE, encoding="utf-8")
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": WORKER_PYTHONPATH,
        "DATABASE_URL": SECRET,
    }

    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", WORKER, str(tmp_path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    # The env allowlist does its job for the direct environment...
    assert "ENV_HAS_SECRET=False" in completed.stdout, completed.stdout
    # ...but same-uid execution still exposes the worker's secrets via /proc.
    if "PROC_HAS_SECRET=unreadable" in completed.stdout:
        pytest.skip("ptrace/proc hardening prevents the read on this host")
    assert "PROC_HAS_SECRET=True" in completed.stdout, completed.stdout
