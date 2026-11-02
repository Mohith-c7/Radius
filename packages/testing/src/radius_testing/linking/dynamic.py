"""Dynamic coverage-context symbol-to-test linker (LK-03, part 3).

Runs the selected test files inside the hardened F-07 sandbox
(``ContainerSandboxRunner``: no network, read-only root, dropped capabilities,
resource limits, wall-clock timeout) under coverage.py with one *dynamic context
per test* (the pytest ``nodeid``; the same contexts ``pytest-cov
--cov-context=test`` records), retrieves the resulting ``.coverage`` SQLite file
from the sandbox's results directory, parses it offline (``coveragedb``) and
maps the executed lines of every test onto the changed symbols' line ranges.

Safety invariants (tests enforce each):

* never executes on the host: the constructor requires a
  ``ContainerSandboxRunner`` instance and there is no subprocess fallback;
* flag-gated: ``RADIUS_FEATURE_COVERAGE_CONTEXTS`` (default OFF);
* test file arguments are repo-relative ``.py`` paths confined to the checkout
  (no absolute paths, ``..``, option-like names, symlink escapes);
* the driver script is a constant; user data only ever arrives as argv;
* a missing/corrupt coverage file, a timeout, a sandbox error or a failing test
  never raises: they produce notes (and, for failures, annotated evidence).

The sandbox image must contain ``pytest`` and ``coverage`` (see the README).
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from uuid import uuid4

from radius_testing.domain.entities import CaseOutcome, TestRunPlan, TestRunStatus
from radius_testing.infrastructure.result_matching import report_cases
from radius_testing.infrastructure.sandbox_runner import (
    CONTAINER_RESULTS,
    ContainerSandboxRunner,
)
from radius_testing.linking.coveragedb import (
    CoverageData,
    CoverageDataError,
    read_coverage_bytes,
)
from radius_testing.linking.model import (
    DYNAMIC_ALGO_VERSION,
    LinkKind,
    LinkSet,
    LinkTarget,
    SymbolTestLink,
    clamp01,
    normalize_test_id,
)

FEATURE_FLAG = "RADIUS_FEATURE_COVERAGE_CONTEXTS"
LINKER = "dynamic"
COVERAGE_ARTIFACT = ".coverage"
JUNIT_ARTIFACT = "junit.xml"
DEFAULT_BATCH_SIZE = 25
DEFAULT_MAX_BATCHES = 20
FAILED_FACTOR = 0.85
FLAKY_FACTOR = 0.7
_TRUE = frozenset({"1", "true", "yes", "on"})
_SAFE_PATH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./\-]*\.py$")

# Constant, reviewed driver. argv: <coverage data file> <junit file> <test files...>
# One coverage context per test item (setup + call + teardown), like pytest-cov.
DRIVER_SCRIPT = """
import sys
data_file, junit_file, *files = sys.argv[1:]
import coverage
import pytest
cov = coverage.Coverage(data_file=data_file, config_file=False, source=["."])
cov.set_option("run:relative_files", True)
class _Contexts:
    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(self, item, nextitem):
        cov.switch_context(item.nodeid)
        yield
cov.start()
try:
    code = pytest.main(["-q", "-p", "no:cacheprovider", "--junitxml=" + junit_file, *files],
                       plugins=[_Contexts()])
finally:
    cov.stop()
    cov.save()
sys.exit(int(code))
""".strip()


class SandboxRequiredError(TypeError):
    """Dynamic linking was requested with something other than the sandbox runner."""


class UnsafeTestPathError(ValueError):
    """A test file argument escapes the checkout or is not a plain ``.py`` path."""


def coverage_contexts_enabled(environ: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return env.get(FEATURE_FLAG, "").strip().lower() in _TRUE


def validate_test_files(repository: Path, files: Sequence[str]) -> list[str]:
    """Return normalised, confined test paths or raise ``UnsafeTestPathError``."""

    root = repository.resolve()
    out: list[str] = []
    for raw in files:
        norm = raw.replace("\\", "/")
        if not _SAFE_PATH.match(norm) or ".." in PurePosixPath(norm).parts or norm.startswith("/"):
            raise UnsafeTestPathError(f"unsafe test path {raw!r}")
        resolved = (root / norm).resolve()
        if root not in resolved.parents:
            raise UnsafeTestPathError(f"test path {raw!r} escapes the repository")
        if not resolved.is_file():
            raise UnsafeTestPathError(f"test file {raw!r} does not exist in the checkout")
        out.append(norm)
    return sorted(set(out))


@dataclass(frozen=True, slots=True)
class DynamicResult:
    links: LinkSet
    status: str  # disabled | ok | partial | no_data
    notes: tuple[str, ...] = ()
    executed_tests: tuple[str, ...] = ()
    failed_tests: tuple[str, ...] = ()
    duration_ms: int = 0
    contexts: int = 0
    truncated: bool = False
    extra: dict[str, str] = field(default_factory=dict)


def coverage_strength(hit_lines: int) -> float:
    """Evidence strength of ``hit_lines`` executed lines inside the symbol (0.7 .. 1.0)."""

    return clamp01(0.6 + 0.1 * hit_lines) if hit_lines > 0 else 0.0


def links_from_coverage(
    data: CoverageData,
    targets: Sequence[LinkTarget],
    *,
    failed: Collection[str] = (),
    flaky: Collection[str] = (),
    known_tests: Collection[str] | None = None,
    use_old_ranges: bool = False,
) -> tuple[list[SymbolTestLink], list[str]]:
    """Map per-test executed lines onto symbol ranges. Pure and deterministic."""

    notes: list[str] = []
    dotted: dict[str, str] = {}
    for tid in known_tests or ():
        path, _, rest = tid.partition("::")
        dotted[(path[:-3].replace("/", ".") + "." + rest.replace("::", ".")).strip(".")] = tid
    failed_set, flaky_set = set(failed), set(flaky)
    links: list[SymbolTestLink] = []
    skipped_contexts = 0
    py_targets = [t for t in targets if t.language == "python"]
    if len(py_targets) != len(targets):
        notes.append("non-Python symbols are not covered by coverage.py contexts and were skipped")
    for ctx in sorted(data.contexts):
        if not ctx:
            continue  # collection/import-time code, not attributable to a test
        tid = normalize_test_id(ctx) if "::" in ctx else dotted.get(ctx)
        if tid is None:
            skipped_contexts += 1
            continue
        per_file = data.contexts[ctx]
        for tgt in py_targets:
            rng = (tgt.old_range if use_old_ranges else tgt.new_range)
            if rng is None:
                continue
            hits = sorted(n for n in per_file.get(tgt.path, ()) if rng[0] <= n <= rng[1])
            if not hits:
                continue
            strength = coverage_strength(len(hits))
            evidence = [
                f"{len(hits)} line(s) of {tgt.path}:{rng[0]}-{rng[1]} executed in context {ctx!r}: "
                + _fmt_lines(hits)
            ]
            if tid in failed_set:
                strength *= FAILED_FACTOR
                evidence.append("test failed in the coverage run; coverage is up to the failure")
            if tid in flaky_set:
                strength *= FLAKY_FACTOR
                evidence.append("test is flaky (F-11); coverage may differ between runs")
            links.append(
                SymbolTestLink(
                    symbol_id=tgt.symbol_id,
                    test_id=tid,
                    linker=LINKER,
                    score=clamp01(strength),
                    kind=LinkKind.DYNAMIC_COVERAGE,
                    evidence=tuple(evidence),
                    algo_version=DYNAMIC_ALGO_VERSION,
                )
            )
    if skipped_contexts:
        notes.append(f"{skipped_contexts} coverage context(s) were not recognisable test ids and were ignored")
    # parametrised cases merge into one function-level link: keep the strongest
    best: dict[tuple[str, str], SymbolTestLink] = {}
    for link in links:
        old = best.get(link.key)
        if old is None or link.score > old.score:
            best[link.key] = link
    return list(best.values()), notes


def _fmt_lines(lines: list[int], limit: int = 12) -> str:
    shown = ",".join(str(n) for n in lines[:limit])
    return shown + (f",...(+{len(lines) - limit})" if len(lines) > limit else "")


class DynamicCoverageLinker:
    """Collect and map per-test coverage in the sandbox; flag-gated, default OFF."""

    algo_version = DYNAMIC_ALGO_VERSION

    def __init__(
        self,
        runner: ContainerSandboxRunner,
        *,
        enabled: bool | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_batches: int = DEFAULT_MAX_BATCHES,
    ) -> None:
        if not isinstance(runner, ContainerSandboxRunner):
            raise SandboxRequiredError(
                "dynamic coverage linking only runs inside ContainerSandboxRunner (F-07); "
                "refusing to execute tests anywhere else"
            )
        if batch_size < 1 or max_batches < 1:
            raise ValueError("batch_size and max_batches must be positive")
        self._runner = runner
        self._enabled = coverage_contexts_enabled() if enabled is None else enabled
        self._batch_size = batch_size
        self._max_batches = max_batches

    @property
    def enabled(self) -> bool:
        return self._enabled

    def plan_for(self, files: Sequence[str]) -> TestRunPlan:
        args = (
            "-c",
            DRIVER_SCRIPT,
            f"{CONTAINER_RESULTS}/{COVERAGE_ARTIFACT}",
            f"{CONTAINER_RESULTS}/{JUNIT_ARTIFACT}",
            *files,
        )
        return TestRunPlan.pending(uuid4(), (), (("python", args),))

    def link(
        self,
        repository_path: Path,
        test_files: Sequence[str],
        targets: Sequence[LinkTarget],
        *,
        known_tests: Collection[str] | None = None,
        flaky_tests: Collection[str] = (),
    ) -> DynamicResult:
        if not self._enabled:
            return DynamicResult(
                LinkSet.of([], algo_version=self.algo_version),
                "disabled",
                (f"{FEATURE_FLAG} is off; dynamic coverage linking skipped",),
            )
        files = validate_test_files(repository_path, test_files)
        started = time.monotonic()
        notes: list[str] = []
        merged = CoverageData()
        failed: set[str] = set()
        executed: set[str] = set()
        good_batches = 0
        batches = [files[i : i + self._batch_size] for i in range(0, len(files), self._batch_size)]
        if len(batches) > self._max_batches:
            notes.append(
                f"{len(batches) - self._max_batches} batch(es) of test files skipped (max_batches={self._max_batches})"
            )
            batches = batches[: self._max_batches]
        for number, batch in enumerate(batches, start=1):
            result, artifacts = self._runner.run_collecting(
                self.plan_for(batch),
                repository_path,
                (COVERAGE_ARTIFACT, JUNIT_ARTIFACT),
            )
            if result.status == TestRunStatus.ERROR:
                notes.append(
                    f"batch {number}: sandbox run did not complete ({_first_line(result.output)}); "
                    "no coverage retained"
                )
            raw = artifacts.get(f"0/{COVERAGE_ARTIFACT}")
            if raw is None:
                if result.status != TestRunStatus.ERROR:
                    notes.append(
                        f"batch {number}: no coverage data produced "
                        "(is `coverage` installed in the sandbox image?)"
                    )
                continue
            try:
                data = read_coverage_bytes(raw)
            except CoverageDataError as exc:
                notes.append(f"batch {number}: coverage data unreadable ({exc})")
                continue
            if data.truncated:
                notes.append(f"batch {number}: coverage data truncated by safety limits")
            good_batches += 1
            merged = merged.merged(data)
            junit = artifacts.get(f"0/{JUNIT_ARTIFACT}")
            if junit:
                for case in report_cases(junit):
                    tid = _case_test_id(case, known_tests)
                    if tid is None:
                        continue
                    if case.outcome != CaseOutcome.SKIPPED:
                        executed.add(tid)
                    if case.outcome == CaseOutcome.FAILED:
                        failed.add(tid)
            if result.status == TestRunStatus.FAILED:
                notes.append(f"batch {number}: some tests failed; their coverage is partial")
        links, link_notes = links_from_coverage(
            merged, targets, failed=failed, flaky=_flaky_ids(flaky_tests, known_tests), known_tests=known_tests
        )
        notes.extend(link_notes)
        status = "no_data" if good_batches == 0 else ("ok" if good_batches == len(batches) else "partial")
        return DynamicResult(
            LinkSet.of(links, algo_version=self.algo_version, notes=notes, config={"batches": len(batches)}),
            status,
            tuple(notes),
            tuple(sorted(executed)),
            tuple(sorted(failed)),
            int((time.monotonic() - started) * 1000),
            len(merged.contexts),
            merged.truncated,
        )


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:200]
    return "no output"


def _case_test_id(case, known: Collection[str] | None) -> str | None:  # noqa: ANN001
    name = normalize_test_id(case.name or "")
    if not name:
        return None
    candidates: list[str] = []
    parts = (case.classname or "").split(".")
    for cut in range(len(parts), 0, -1):
        path = "/".join(parts[:cut]) + ".py"
        cls = ".".join(parts[cut:])
        candidates.append("::".join(p for p in (path, *([cls] if cls else []), name) if p))
    if case.file:
        candidates.insert(0, f"{case.file.replace(chr(92), '/')}::{name}")
    if known:
        for cand in candidates:
            if cand in known:
                return cand
        return None
    return candidates[0] if candidates else None


def _flaky_ids(flaky: Collection[str], known: Collection[str] | None) -> set[str]:
    out = {normalize_test_id(f) for f in flaky}
    for tid in known or ():  # F-11 identities are ``file::name``; accept class-qualified ids too
        for f in tuple(out):
            if tid.split("::")[0] == f.split("::")[0] and tid.split("::")[-1] == f.split("::")[-1]:
                out.add(tid)
    return out
