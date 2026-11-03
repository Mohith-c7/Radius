"""scripts/mutation_sandbox_compare.py: pure helpers (no docker, no fixture execution)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
FIXTURE = (
    Path(__file__).resolve().parents[3] / "benchmarks" / "fixtures" / "intent"
    / "01_correct_strong_tests"
)

pytestmark = pytest.mark.skipif(not FIXTURE.is_dir(), reason="intent fixtures not present")


@pytest.fixture(scope="module")
def cmp():
    spec = importlib.util.spec_from_file_location(
        "mutation_sandbox_compare_mod", SCRIPTS / "mutation_sandbox_compare.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _measurement(*rows, status="measured"):
    mutants = tuple(
        NS(mutant_id=i, operator="ROR", path="src/a.py", line=3, status=s, killed_by=kb)
        for i, s, kb in rows
    )
    return NS(
        status=status, reason="", baseline_failed=(), baseline_flaky=(), mutants=mutants
    )


def test_identical_matrices_have_no_differences(cmp) -> None:
    a = cmp.matrix(_measurement(("m1", "killed", ("t2", "t1")), ("m2", "survived", ())))
    b = cmp.matrix(_measurement(("m2", "survived", ()), ("m1", "killed", ("t1", "t2"))))
    assert cmp.diff(a, b) == []  # order of rows and of killers does not matter


def test_a_flipped_status_and_a_missing_mutant_are_reported(cmp) -> None:
    a = cmp.matrix(_measurement(("m1", "killed", ("t1",)), ("m2", "survived", ())))
    b = cmp.matrix(_measurement(("m1", "survived", ())))
    out = cmp.diff(a, b)
    assert len(out) == 2 and all(line.startswith("mutant ") for line in out)


def test_memory_units(cmp) -> None:
    assert cmp._mib("512KiB") == 0.5
    assert cmp._mib("1.5GiB") == 1536.0
    assert cmp._mib("12MiB ") == 12.0
    assert cmp._mib("nonsense") == 0.0
