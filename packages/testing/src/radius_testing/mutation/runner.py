"""Mutant runners: dev-only local subprocess backend and the F-07 sandbox adapter.

SAFETY MODEL
------------
Mutants are generated code derived from untrusted repositories.

* Production execution MUST use :class:`SandboxMutantRunner`, which delegates every
  run to the F-07 :class:`ContainerSandboxRunner` (no network, read-only root,
  dropped capabilities, resource limits, throw-away container, fresh snapshot of the
  repository with the mutated file written into the *snapshot*).
* :class:`SubprocessLocalRunner` runs pytest as a plain child process of the caller
  with the caller's privileges. It exists for development and for the F-14 fixtures
  (code written by us). It is **unsafe for untrusted code** and refuses to
  construct unless ``RADIUS_MUTATION_ALLOW_LOCAL=1`` is set.
* Neither backend ever writes into the original checkout: both operate on a copy.
"""

from __future__ import annotations

import dataclasses
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from radius_testing.domain.entities import CaseOutcome, ReportedTestCase, TestRunPlan
from radius_testing.domain.enums import TestRunStatus
from radius_testing.infrastructure.result_matching import report_cases
from radius_testing.infrastructure.sandbox_runner import (
    ContainerSandboxRunner,
    SandboxConfig,
)
from radius_testing.mutation.budget import MutationBudget, cache_key
from radius_testing.mutation.equivalence import detect_equivalent
from radius_testing.mutation.matrix import KillMatrix, MutantRecord
from radius_testing.mutation.operators import Mutant

ALLOW_LOCAL_ENV = "RADIUS_MUTATION_ALLOW_LOCAL"
_TEST_ID_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./\\\[\]:\-\(\)=, +]*$")
_COPY_IGNORE = shutil.ignore_patterns(
    ".git", "__pycache__", ".pytest_cache", "*.pyc", "node_modules", ".venv", ".mypy_cache"
)


class LocalRunnerRefusedError(RuntimeError):
    """The unsafe local runner was constructed without explicit opt-in."""


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """Raw result of one pytest invocation. ``mutant_id`` None means the baseline."""

    status: str  # "ok" | "timeout" | "error"
    results: Mapping[str, str] = field(default_factory=dict)  # test id -> passed|failed|skipped
    duration: float = 0.0
    detail: str = ""


@dataclass(frozen=True, slots=True)
class MutantOutcome:
    mutant_id: str
    status: str  # killed | survived | timeout | error | flaky
    killed_by: frozenset[str] = frozenset()
    duration: float = 0.0
    cached: bool = False
    detail: str = ""


class MutantRunner(Protocol):
    def run(
        self,
        mutant: Mutant | None,
        tests: Sequence[str],
        timeout: float,
        *,
        stop_on_first_failure: bool = False,
    ) -> RunOutcome: ...


def validate_test_ids(tests: Sequence[str]) -> list[str]:
    """Reject anything that could be parsed as a pytest option or escape the repo."""

    ids = []
    for t in tests:
        if (
            not _TEST_ID_RE.match(t)
            or ".." in t.replace("\\", "/").split("::")[0].split("/")
            or t.startswith(("/", "\\"))
            or re.match(r"^[A-Za-z]:", t)
        ):
            raise ValueError(f"unsafe test id {t!r}")
        ids.append(t)
    return ids


def case_to_test_id(case: ReportedTestCase, workspace: Path) -> str:
    """Map a JUnit case (classname ``tests.test_x.Class`` + name) to a pytest node id."""

    parts = [p for p in (case.classname or "").split(".") if p]
    for end in range(len(parts), 0, -1):
        rel = "/".join(parts[:end]) + ".py"
        if (workspace / rel).is_file():
            return "::".join([rel, *parts[end:], case.name or ""])
    return f"{case.classname or ''}::{case.name or ''}"


def results_from_junit(content: bytes, workspace: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for case in report_cases(content):
        tid = case_to_test_id(case, workspace)
        prev = out.get(tid)
        # failed beats passed beats skipped (setup errors report extra rows)
        if prev == CaseOutcome.FAILED:
            continue
        out[tid] = case.outcome
    return out


def _write_mutant(workspace: Path, mutant: Mutant) -> Path:
    target = (workspace / mutant.path).resolve()
    target.relative_to(workspace.resolve())  # raises ValueError on path escape
    return target


class SubprocessLocalRunner:
    """DEV/TEST ONLY. Runs pytest in a temp copy of the repo as a local child process.

    UNSAFE for untrusted code: no isolation of network, filesystem outside the copy,
    or privileges. Refused unless ``RADIUS_MUTATION_ALLOW_LOCAL=1``.
    """

    def __init__(
        self,
        repo_root: Path,
        *,
        python: str | None = None,
        environ: Mapping[str, str] | None = None,
        pytest_args: Sequence[str] = (),
    ) -> None:
        env = os.environ if environ is None else environ
        if env.get(ALLOW_LOCAL_ENV) != "1":
            raise LocalRunnerRefusedError(
                f"SubprocessLocalRunner executes code on this host; set {ALLOW_LOCAL_ENV}=1 "
                "only for trusted code (dev/tests). Use SandboxMutantRunner otherwise."
            )
        self._repo = Path(repo_root).resolve()
        self._python = python or sys.executable
        self._pytest_args = tuple(pytest_args)
        self._tmp: Path | None = None
        self._ws: Path | None = None

    def __enter__(self) -> SubprocessLocalRunner:
        self._tmp = Path(tempfile.mkdtemp(prefix="radius-mutation-local-"))
        self._ws = self._tmp / "ws"
        shutil.copytree(self._repo, self._ws, ignore=_COPY_IGNORE, symlinks=True)
        return self

    def __exit__(self, *exc: object) -> None:
        if self._tmp is not None:
            shutil.rmtree(self._tmp, ignore_errors=True)
        self._tmp = self._ws = None

    @staticmethod
    def _child_env() -> dict[str, str]:
        keep = ("PATH", "SYSTEMROOT", "TEMP", "TMP")
        env = {k: os.environ[k] for k in keep if k in os.environ}
        env.update(
            PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0", CI="true", NO_COLOR="1",
            # third-party pytest plugins are not loaded implicitly (faster, and no ambient plugin code)
            PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        )
        return env

    def run(
        self,
        mutant: Mutant | None,
        tests: Sequence[str],
        timeout: float,
        *,
        stop_on_first_failure: bool = False,
    ) -> RunOutcome:
        if self._ws is None or self._tmp is None:
            raise RuntimeError("use SubprocessLocalRunner as a context manager")
        ids = validate_test_ids(tests)
        original: bytes | None = None
        target: Path | None = None
        started = time.monotonic()
        try:
            if mutant is not None:
                target = _write_mutant(self._ws, mutant)
                original = target.read_bytes()
                target.write_text(mutant.mutated_source, encoding="utf-8")
            junit = self._tmp / f"junit-{uuid4().hex[:8]}.xml"
            cmd = [
                self._python, "-m", "pytest", "-p", "no:cacheprovider", "-q",
                f"--junitxml={junit}", *self._pytest_args,
            ]
            if stop_on_first_failure:
                cmd.append("-x")
            cmd.extend(ids)
            try:
                proc = subprocess.run(  # noqa: S603 - argv list, validated ids, dev-only runner
                    cmd, cwd=self._ws, env=self._child_env(), capture_output=True,
                    timeout=timeout, check=False, stdin=subprocess.DEVNULL,
                )
            except subprocess.TimeoutExpired:
                return RunOutcome("timeout", {}, time.monotonic() - started, "timeout")
            duration = time.monotonic() - started
            if not junit.is_file():
                tail = (proc.stdout or b"")[-300:].decode("utf-8", "replace")
                return RunOutcome("error", {}, duration, f"no report (rc={proc.returncode}) {tail}")
            results = results_from_junit(junit.read_bytes(), self._ws)
            return RunOutcome("ok", results, duration)
        finally:
            if target is not None and original is not None:
                target.write_bytes(original)


class SandboxMutantRunner:
    """Production backend: every run is one hardened F-07 container execution.

    For each run a fresh copy of the repository is made with the mutated file
    written *into the copy*; ``ContainerSandboxRunner`` snapshots that copy again,
    mounts it read-only with ``--network none`` and returns the JUnit report via its
    results directory. The user's checkout is never touched.
    """

    def __init__(
        self,
        repo_root: Path,
        sandbox: ContainerSandboxRunner,
        *,
        pytest_args: Sequence[str] = (),
    ) -> None:
        self._repo = Path(repo_root).resolve()
        self._sandbox = sandbox
        self._pytest_args = tuple(pytest_args)

    @property
    def image(self) -> str:
        return self._sandbox.config.image

    def build_plan(
        self, tests: Sequence[str], *, stop_on_first_failure: bool = False
    ) -> TestRunPlan:
        """Pure command construction (unit-tested with fakes)."""

        args = ["-m", "pytest", "-q", *self._pytest_args]
        if stop_on_first_failure:
            args.append("-x")
        args.extend(validate_test_ids(tests))
        return TestRunPlan(
            id=uuid4(), analysis_id=uuid4(), status=TestRunStatus.PENDING,
            selected_tests=(), command_plan=(("python", tuple(args)),),
        )

    def run(
        self,
        mutant: Mutant | None,
        tests: Sequence[str],
        timeout: float,
        *,
        stop_on_first_failure: bool = False,
    ) -> RunOutcome:
        plan = self.build_plan(tests, stop_on_first_failure=stop_on_first_failure)
        tmp = Path(tempfile.mkdtemp(prefix="radius-mutant-"))
        started = time.monotonic()
        try:
            ws = tmp / "repo"
            shutil.copytree(self._repo, ws, ignore=_COPY_IGNORE, symlinks=True)
            if mutant is not None:
                _write_mutant(ws, mutant).write_text(mutant.mutated_source, encoding="utf-8")
            sandbox = self._sandbox_with_timeout(timeout)
            result, files = sandbox.run_collecting(plan, ws, artifacts=("junit.xml",))
            duration = time.monotonic() - started
            junit = files.get("0/junit.xml")
            if junit:
                return RunOutcome("ok", results_from_junit(junit, ws), duration)
            if "timed out" in result.output:
                return RunOutcome("timeout", {}, duration, "timeout")
            return RunOutcome("error", {}, duration, result.output[-300:])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _sandbox_with_timeout(self, timeout: float) -> ContainerSandboxRunner:
        seconds = max(1, int(timeout))
        if seconds == self._sandbox.config.timeout_seconds:
            return self._sandbox
        cfg: SandboxConfig = dataclasses.replace(self._sandbox.config, timeout_seconds=seconds)
        return ContainerSandboxRunner(cfg)


@dataclass(frozen=True, slots=True)
class MutationRun:
    matrix: KillMatrix
    outcomes: tuple[MutantOutcome, ...]
    baseline_failed: tuple[str, ...]
    baseline_flaky: tuple[str, ...]
    skipped_for_budget: tuple[str, ...]
    cache_hits: int
    seed: int


def run_mutants(
    runner: MutantRunner,
    mutants: Sequence[Mutant],
    tests: Sequence[str],
    budget: MutationBudget | None = None,
    *,
    original_sources: Mapping[str, str] | None = None,
    cache: MutableMapping[str, MutantOutcome] | None = None,
    image_digest: str = "local",
    context_hash: str = "",
    baseline_runs: int = 2,
    survivor_reruns: int = 1,
    clock: Callable[[], float] = time.monotonic,
) -> MutationRun:
    """Baseline, then every mutant (sequentially), build the kill matrix.

    * Baseline is run ``baseline_runs`` times; tests that fail or change outcome are
      excluded (F-11 spirit: a failing/flaky baseline test cannot be attributed).
    * Survivors are rerun ``survivor_reruns`` times; a survivor that gets killed on
      rerun is ``flaky`` (excluded from the denominator and reported).
    * ``cache`` is keyed by (mutant hash, test set, image digest); hits are free.
    * Stops starting new mutants when the wall-clock budget is spent; the rest are
      reported in ``skipped_for_budget``.
    """

    budget = budget or MutationBudget()
    deadline = clock() + budget.wall_clock_seconds
    base_runs = [
        runner.run(None, tests, budget.per_mutant_timeout_seconds) for _ in range(max(1, baseline_runs))
    ]
    if any(b.status != "ok" for b in base_runs):
        raise RuntimeError(f"baseline run failed: {[b.detail for b in base_runs if b.status != 'ok']}")
    first = base_runs[0].results
    stable = {
        t for t, o in first.items()
        if o == CaseOutcome.PASSED and all(b.results.get(t) == CaseOutcome.PASSED for b in base_runs)
    }
    flaky = sorted(t for t in first if any(b.results.get(t) != first[t] for b in base_runs))
    failed = sorted(t for t, o in first.items() if o == CaseOutcome.FAILED and t not in flaky)

    outcomes: list[MutantOutcome] = []
    skipped: list[str] = []
    hits = 0
    for mutant in mutants:
        key = cache_key(mutant.mutant_hash, sorted(stable), image_digest, context_hash)
        if cache is not None and key in cache:
            outcomes.append(dataclasses.replace(cache[key], mutant_id=mutant.id, cached=True))
            hits += 1
            continue
        if clock() >= deadline:
            skipped.append(mutant.id)
            continue
        outcome = _run_one(runner, mutant, tests, stable, budget, survivor_reruns)
        outcomes.append(outcome)
        if cache is not None and outcome.status in {"killed", "survived"}:
            cache[key] = outcome

    by_id = {m.id: m for m in mutants}
    records = []
    for o in outcomes:
        m = by_id[o.mutant_id]
        suspect = detect_equivalent((original_sources or {}).get(m.path, ""), m).suspect \
            if original_sources and m.path in original_sources else False
        records.append(
            MutantRecord(
                id=m.id, symbol=m.symbol, operator=m.operator, status=o.status,
                killed_by=o.killed_by, equivalent_suspect=suspect,
                location=f"{m.path}:{m.lineno}",
            )
        )
    return MutationRun(
        KillMatrix(tuple(records), tuple(sorted(stable))), tuple(outcomes), tuple(failed),
        tuple(flaky), tuple(skipped), hits, budget.seed,
    )


def _run_one(
    runner: MutantRunner,
    mutant: Mutant,
    tests: Sequence[str],
    stable: set[str],
    budget: MutationBudget,
    survivor_reruns: int,
) -> MutantOutcome:
    out = runner.run(mutant, tests, budget.per_mutant_timeout_seconds)
    if out.status == "timeout":
        return MutantOutcome(mutant.id, "timeout", duration=out.duration, detail=out.detail)
    if out.status != "ok" or not out.results:
        return MutantOutcome(mutant.id, "error", duration=out.duration, detail=out.detail)
    killers = frozenset(t for t in stable if out.results.get(t) == CaseOutcome.FAILED)
    # A stable-passing test that did not report at all (collection crash) also counts as killed.
    killers |= frozenset(t for t in stable if t not in out.results)
    if killers:
        return MutantOutcome(mutant.id, "killed", killers, out.duration)
    for _ in range(survivor_reruns):
        again = runner.run(mutant, tests, budget.per_mutant_timeout_seconds)
        if again.status == "ok" and any(
            again.results.get(t) == CaseOutcome.FAILED for t in stable
        ):
            return MutantOutcome(mutant.id, "flaky", duration=out.duration, detail="killed on rerun")
    return MutantOutcome(mutant.id, "survived", duration=out.duration)
