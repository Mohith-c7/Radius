"""Bounded mutation measurement of changed symbols against their linked tests (EV-04/05/09/10).

This is the orchestration the Verdict v2 Stage A ``mutation`` producer calls. It is a
pure library over a :class:`~radius_testing.mutation.runner.MutantRunner`: the caller
chooses the backend (the worker only ever passes the sandbox adapter; the dev-only
local runner needs the explicit ``allow_local_runner=True`` that the worker never sets).

Flow (see ``docs/research/design/MUTATION_EVIDENCE.md`` and ``docs/verdict-v2.md``):

1. mutate the ``new_range`` of each changed symbol that has linked tests (generator is
   pure ``ast``, nothing of the repository is imported or executed here);
2. drop equivalent suspects (listed, never run), then take a seeded stratified sample;
3. baseline run of the linked tests, repeated ``baseline_runs`` times; failing, missing
   and flaky tests are excluded (F-11) and listed;
4. one *control* run per mutated file (the unparsed but unmutated module): if it breaks a
   baseline-passing test the file's mutants are unreliable and are excluded;
5. each mutant runs only the baseline-stable tests linked to its own symbol (no early
   exit: per-test attribution needs every failing test); timeouts are rerun once;
   survivors are rerun ``survivor_reruns`` times and a rerun kill makes them ``flaky``;
6. a result cache keyed by (mutant hash, tests, image digest, repository context hash)
   short-circuits final statuses (``killed`` / ``survived``) only;
7. optional **stage 2** (``MeasureConfig.stage2``, default off; design 5.1, DEC-036): each
   surviving non-equivalent mutant is run against a wider, bounded, deterministic set
   of the repository's other tests that import the mutated module, with early exit at the
   first failing test. A confirmed kill is recorded as ``killed_outside_linked`` (the
   mutant stays ``survived`` for the linked tests; the killers are NOT evidence for any
   criterion). Same runner (so sandbox-only in the worker), separate cache keys, own
   budget; any problem leaves the stage-1 result untouched.

Degradation ladder (each step recorded in ``Measurement.ladder``)::

    full set -> sampled (max_mutants) -> tier_a_only -> budget_cut (fits the wall clock)
    -> unmeasured (static cap): reason code says why

Mutants not started when the wall clock expires are ``skipped_for_budget``. Nothing here
ever raises for a runner or repository problem: it returns ``status="unmeasured"``.
"""

from __future__ import annotations

import ast
import hashlib
import statistics
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Protocol

from radius_testing.domain.entities import CaseOutcome
from radius_testing.mutation.budget import MutationBudget, cache_key, sample_mutants
from radius_testing.mutation.equivalence import detect_equivalent
from radius_testing.mutation.operators import OPERATOR_IDS, Mutant, generate_mutants
from radius_testing.mutation.runner import (
    LocalRunnerRefusedError,
    MutantOutcome,
    MutantRunner,
    RunOutcome,
    SubprocessLocalRunner,
    validate_test_ids,
)

ENGINE_VERSION = "mutation-ast-1"
#: Sampling priority tiers (design 3): A first, then B, then C.
TIER_A = ("ROR", "AOR", "BOOL", "CRM", "EXC", "RET", "NEG")
TIER_B = ("CON", "CALL")

_MAX_SOURCE_BYTES = 512 * 1024
_CONTEXT_FILE_LIMIT = 4000
_CONTEXT_BYTES_LIMIT = 40 * 1024 * 1024
_CONTEXT_SUFFIXES = (".py", ".toml", ".ini", ".cfg", ".txt", ".yml", ".yaml", ".json")

KILLED = "killed"
SURVIVED = "survived"
EQUIVALENT = "equivalent_suspect"
SKIPPED_BUDGET = "skipped_for_budget"


class MutantCache(Protocol):
    """Minimal mapping used for cached final results (a ``dict`` satisfies it)."""

    def __contains__(self, key: object, /) -> bool: ...

    def __getitem__(self, key: str, /) -> MutantOutcome: ...

    def __setitem__(self, key: str, value: MutantOutcome, /) -> None: ...


def is_test_path(path: str) -> bool:
    """Test files, ``conftest.py`` and test directories are never mutated."""

    p = PurePosixPath(path.replace("\\", "/"))
    name = p.name
    return (
        name == "conftest.py"
        or name.startswith("test_")
        or name.endswith(("_test.py", "_tests.py"))
        or any(part in {"tests", "test"} for part in p.parts[:-1])
    )


@dataclass(frozen=True, slots=True)
class SymbolTarget:
    """A changed behavioural symbol with the tests linked to it."""

    symbol_id: str
    path: str  # repo-relative, posix
    ranges: tuple[tuple[int, int], ...]  # inclusive 1-based line ranges (LK-01 new_range)
    tests: tuple[str, ...]  # pytest node ids as they appear in symbol_test edges


@dataclass(frozen=True, slots=True)
class MeasureConfig:
    budget: MutationBudget = field(default_factory=MutationBudget)
    baseline_runs: int = 2
    survivor_reruns: int = 1
    min_decided: int = 5
    operators: tuple[str, ...] = OPERATOR_IDS
    #: Estimated share of mutants that are survivors and rerun (cost model, design 7).
    survivor_share: float = 0.3
    #: Stage 2 (wider test set for survivors); off by default.
    stage2: bool = False
    #: Max wider tests passed to one stage-2 run (command length, container time).
    stage2_max_tests: int = 60
    #: Wall clock of the whole stage 2 (separate from the stage-1 budget).
    stage2_wall_clock_seconds: float = 300.0
    #: Max test files taken per mutated module from the static import scan.
    stage2_max_files: int = 40
    #: Killing tests kept per mutant in the result.
    stage2_max_killers: int = 5

    def __post_init__(self) -> None:
        if self.baseline_runs < 1 or self.survivor_reruns < 0 or self.min_decided < 1:
            raise ValueError("invalid mutation measurement configuration")
        if (
            self.stage2_max_tests < 1
            or self.stage2_max_files < 1
            or self.stage2_max_killers < 1
            or self.stage2_wall_clock_seconds <= 0
        ):
            raise ValueError("invalid stage 2 configuration")


@dataclass(frozen=True, slots=True)
class MeasuredMutant:
    mutant_id: str
    symbol_id: str
    path: str
    line: int
    operator: str
    status: str  # killed | survived | timeout | error | flaky | equivalent_suspect | skipped_for_budget
    killed_by: tuple[str, ...] = ()
    equivalent_suspect: bool = False
    cached: bool = False
    #: Stage 2: tests outside the linked set that kill this stage-1 survivor (sorted,
    #: capped, confirmed by a repeat run). ``None`` = stage 2 did not run for this mutant;
    #: ``()`` = it ran and nothing killed it.
    killed_outside_linked: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class Stage2Summary:
    """What stage 2 did (all counts are over stage-1 survivors)."""

    survivors: int = 0
    run: int = 0  # mutants actually run against a wider set (incl. cache hits)
    killed: int = 0  # confirmed killed_outside_linked
    unconfirmed: int = 0  # killed once, not on the confirmation run: stays a survivor
    no_wider_tests: int = 0
    skipped_for_budget: int = 0
    errors: int = 0  # timeout / sandbox error: no stage-2 statement
    cache_hits: int = 0
    tests_considered: int = 0  # distinct baseline-stable wider tests
    ladder: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Measurement:
    status: str  # "measured" | "unmeasured"
    reason: str = ""
    mutants: tuple[MeasuredMutant, ...] = ()
    symbol_tests: dict[str, tuple[str, ...]] = field(default_factory=dict)
    baseline_failed: tuple[str, ...] = ()
    baseline_flaky: tuple[str, ...] = ()
    generated: int = 0
    sampled: int = 0
    skipped_for_budget: int = 0
    cache_hits: int = 0
    seed: int = 0
    min_decided: int = 5
    ladder: tuple[str, ...] = ()
    engine: str = ENGINE_VERSION
    operators: tuple[str, ...] = ()
    image: str = ""
    #: ``None`` when stage 2 was not enabled.
    stage2: Stage2Summary | None = None


def unmeasured(reason: str, config: MeasureConfig, ladder: Sequence[str] = ()) -> Measurement:
    return Measurement(
        "unmeasured",
        reason,
        seed=config.budget.seed,
        min_decided=config.min_decided,
        ladder=tuple(ladder),
        operators=config.operators,
    )


# ------------------------------------------------------------------ helpers


def collapse_results(results: dict[str, str], tests: Sequence[str]) -> dict[str, str | None]:
    """Reduce JUnit rows to one outcome per linked test id.

    A linked id ``path::f`` matches the row ``path::f`` and parametrised rows
    ``path::f[...]``. Outcome precedence: failed, then skipped, then passed; ``None``
    when no row matched (not collected / not reported).
    """

    out: dict[str, str | None] = {}
    for t in tests:
        rows = [o for k, o in results.items() if k == t or k.startswith(t + "[")]
        if not rows:
            out[t] = None
        elif any(o == CaseOutcome.FAILED for o in rows):
            out[t] = CaseOutcome.FAILED
        elif any(o != CaseOutcome.PASSED for o in rows):
            out[t] = CaseOutcome.SKIPPED
        else:
            out[t] = CaseOutcome.PASSED
    return out


def context_hash(root: Path) -> str | None:
    """Hash of the repository's Python and configuration files (conservative cache scope).

    ``None`` when the tree is too large to hash cheaply: the cache is then disabled.
    Any edit to any covered file changes the hash, so a cached result can never outlive
    a change to a test body, a helper, ``conftest.py`` or the pytest configuration.
    """

    entries: list[tuple[str, str]] = []
    total = 0
    skip = {".git", "__pycache__", "node_modules", ".venv", ".mypy_cache", ".pytest_cache"}
    stack = [root]
    while stack:
        cur = stack.pop()
        try:
            children = sorted(cur.iterdir())
        except OSError:
            return None
        for child in children:
            if child.name in skip or child.is_symlink():
                continue
            if child.is_dir():
                stack.append(child)
            elif child.suffix in _CONTEXT_SUFFIXES:
                try:
                    data = child.read_bytes()
                except OSError:
                    return None
                total += len(data)
                if len(entries) >= _CONTEXT_FILE_LIMIT or total > _CONTEXT_BYTES_LIMIT:
                    return None
                entries.append(
                    (child.relative_to(root).as_posix(), hashlib.sha256(data).hexdigest())
                )
    digest = hashlib.sha256()
    for rel, h in sorted(entries):
        digest.update(f"{rel}\0{h}\n".encode())
    return digest.hexdigest()


def _read_source(root: Path, rel: str) -> str | None:
    try:
        target = (root / rel).resolve()
        target.relative_to(root.resolve())
        if target.suffix != ".py" or not target.is_file() or target.stat().st_size > _MAX_SOURCE_BYTES:
            return None
        return target.read_text(encoding="utf-8")
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _control_mutant(path: str, source: str) -> Mutant | None:
    try:
        text = ast.unparse(ast.parse(source))
    except (SyntaxError, ValueError, RecursionError):
        return None
    return Mutant(
        id="control", path=path, operator="CONTROL", lineno=0, col=0, end_lineno=0, end_col=0,
        original="", replacement="", symbol="", mutated_source=text,
        mutant_hash=hashlib.sha256(text.encode()).hexdigest(), description="control",
    )


def _timeout_for(baseline_durations: Sequence[float], cap: float) -> float:
    median = statistics.median(baseline_durations) if baseline_durations else 1.0
    return max(1.0, min(cap, max(5.0, min(120.0, 3 * median + 2.0))))


# ------------------------------------------------------------------ main


def measure_mutation(
    runner: MutantRunner,
    repo_root: Path,
    targets: Sequence[SymbolTarget],
    config: MeasureConfig | None = None,
    *,
    cache: MutantCache | None = None,
    image_digest: str = "",
    allow_local_runner: bool = False,
    clock: Callable[[], float] = time.monotonic,
) -> Measurement:
    """Measure; see the module docstring. Never raises for runner/repository problems."""

    cfg = config or MeasureConfig()
    if isinstance(runner, SubprocessLocalRunner) and not allow_local_runner:
        raise LocalRunnerRefusedError(
            "the local runner executes code on this host; production callers must pass "
            "the sandbox runner (allow_local_runner is for development fixtures only)"
        )
    try:
        return _measure(runner, Path(repo_root), targets, cfg, cache, image_digest, clock)
    except LocalRunnerRefusedError:
        raise
    except Exception as exc:  # noqa: BLE001 - degrade to the static cap, never crash the pipeline
        return unmeasured(f"measurement_failed:{type(exc).__name__}", cfg)


def _measure(
    runner: MutantRunner,
    root: Path,
    targets: Sequence[SymbolTarget],
    cfg: MeasureConfig,
    cache: MutantCache | None,
    image_digest: str,
    clock: Callable[[], float],
) -> Measurement:
    budget = cfg.budget
    deadline = clock() + budget.wall_clock_seconds
    ladder: list[str] = []

    # 1. targets: valid tests, real source files, never test files
    usable: list[tuple[SymbolTarget, tuple[str, ...], str]] = []
    dropped_ids = 0
    for t in targets:
        if is_test_path(t.path):
            continue
        source = _read_source(root, t.path)
        if source is None:
            continue
        ok_tests: list[str] = []
        for tid in dict.fromkeys(t.tests):
            try:
                ok_tests.extend(validate_test_ids([tid]))
            except ValueError:
                dropped_ids += 1
        if ok_tests:
            usable.append((t, tuple(ok_tests), source))
    if dropped_ids:
        ladder.append(f"unsafe_test_ids_dropped:{dropped_ids}")
    if not usable:
        return unmeasured("no_mutable_symbols_with_tests", cfg, ladder)

    # 2. generate (innermost symbol owns a mutant), drop suspects
    usable.sort(key=lambda u: (sum(b - a + 1 for a, b in u[0].ranges), u[0].symbol_id))
    owner: dict[str, SymbolTarget] = {}
    by_id: dict[str, Mutant] = {}
    sources: dict[str, str] = {}
    suspects: list[tuple[Mutant, SymbolTarget]] = []
    for target, _tests, source in usable:
        sources[target.path] = source
        for m in generate_mutants(source, target.path, target.ranges, cfg.operators):
            if m.id in owner:
                continue
            owner[m.id] = target
            if detect_equivalent(source, m).suspect:
                suspects.append((m, target))
            else:
                by_id[m.id] = m
    generated = len(by_id) + len(suspects)
    if not by_id:
        return unmeasured("no_mutants_generated", cfg, ladder)
    candidates = sorted(by_id.values(), key=lambda m: (m.path, m.lineno, m.col, m.operator, m.id))

    # 3. sample (seeded, stratified); then ladder by budget after the baseline
    sampled = sample_mutants(candidates, budget.max_mutants, budget.seed)
    if len(sampled) < len(candidates):
        ladder.append(f"sampled:{len(sampled)}of{len(candidates)}")

    # 4. baseline over the union of linked tests of the symbols that have mutants
    sym_tests_all: dict[str, tuple[str, ...]] = {}
    for target, tests, _ in usable:
        sym_tests_all[target.symbol_id] = tests
    live_symbols = {owner[m.id].symbol_id for m in sampled}
    union = sorted({t for s in live_symbols for t in sym_tests_all[s]})
    base_timeout = max(1.0, min(budget.per_mutant_timeout_seconds, budget.wall_clock_seconds))
    base_runs: list[RunOutcome] = []
    for _ in range(cfg.baseline_runs):
        if clock() >= deadline:
            return unmeasured("budget_exhausted_before_baseline", cfg, ladder)
        base_runs.append(runner.run(None, union, base_timeout))
    bad = [b for b in base_runs if b.status != "ok" or not b.results]
    if bad:
        return unmeasured("baseline_failed_to_run", cfg, ladder)
    collapsed = [collapse_results(b.results, union) for b in base_runs]
    stable: set[str] = set()
    flaky: list[str] = []
    failed: list[str] = []
    for t in union:
        outs = [c[t] for c in collapsed]
        if all(o == CaseOutcome.PASSED for o in outs):
            stable.add(t)
        elif len(set(outs)) > 1:
            flaky.append(t)
        else:
            failed.append(t)
    sym_tests = {
        s: tuple(t for t in sym_tests_all[s] if t in stable) for s in sorted(live_symbols)
    }
    sym_tests = {s: ts for s, ts in sym_tests.items() if ts}
    if not sym_tests:
        return replace(
            unmeasured("no_stable_linked_tests", cfg, ladder),
            baseline_failed=tuple(failed),
            baseline_flaky=tuple(flaky),
            generated=generated,
        )
    runnable = [m for m in sampled if owner[m.id].symbol_id in sym_tests]
    if len(runnable) < len(sampled):
        ladder.append(f"symbols_without_stable_tests:{len(sampled) - len(runnable)}mutants")
    durations = [b.duration for b in base_runs]
    timeout = _timeout_for(durations, budget.per_mutant_timeout_seconds)
    per_run = max(statistics.median(durations), 0.05)
    def affordable() -> int:
        """Largest mutant count whose estimated cost (incl. reruns, controls) fits the clock."""

        remaining = max(0.0, deadline - clock())
        n_files = len({m.path for m in runnable})
        return max(0, int((remaining / per_run - n_files) / (1 + cfg.survivor_share)))

    if len(runnable) > affordable():
        tier = [m for m in runnable if m.operator in TIER_A]
        if tier and len(tier) < len(runnable):
            runnable = tier
            ladder.append("tier_a_only")
        fit = affordable()
        if len(runnable) > fit:
            runnable = sample_mutants(runnable, fit, budget.seed)
            ladder.append(f"budget_cut:{len(runnable)}")
        if len(runnable) < cfg.min_decided:
            return replace(
                unmeasured("budget_insufficient", cfg, ladder),
                baseline_failed=tuple(failed),
                baseline_flaky=tuple(flaky),
                generated=generated,
            )
    files = sorted({m.path for m in runnable})

    # 5. control runs, one per mutated file
    control_bad: set[str] = set()
    for path in files:
        control = _control_mutant(path, sources[path])
        if control is None:
            control_bad.add(path)
            continue
        file_tests = sorted(
            {t for m in runnable if m.path == path for t in sym_tests[owner[m.id].symbol_id]}
        )
        out = runner.run(control, file_tests, timeout)
        res = collapse_results(out.results, file_tests) if out.status == "ok" else {}
        if out.status != "ok" or any(res.get(t) != CaseOutcome.PASSED for t in file_tests):
            control_bad.add(path)
    if control_bad:
        ladder.append(f"control_failed:{','.join(sorted(control_bad))}")
    runnable = [m for m in runnable if m.path not in control_bad]

    # 6. mutants
    ctx = context_hash(root) if cache is not None else None
    use_cache = cache is not None and ctx is not None and bool(image_digest)
    records: list[MeasuredMutant] = []
    hits = 0
    skipped = 0
    for m in runnable:
        target = owner[m.id]
        tests = sym_tests[target.symbol_id]
        key = cache_key(m.mutant_hash, tests, image_digest, ctx or "") if use_cache else ""
        if use_cache and cache is not None and key in cache:
            hit = cache[key]
            if hit.status in {KILLED, SURVIVED}:
                hits += 1
                records.append(_record(m, target, hit.status, tuple(sorted(hit.killed_by)), cached=True))
                continue
        if clock() >= deadline:
            skipped += 1
            records.append(_record(m, target, SKIPPED_BUDGET, ()))
            continue
        outcome = _run_one(runner, m, tests, timeout, cfg.survivor_reruns)
        records.append(
            _record(m, target, outcome.status, tuple(sorted(outcome.killed_by)))
        )
        if use_cache and cache is not None and outcome.status in {KILLED, SURVIVED}:
            cache[key] = outcome
    for m, target in suspects:
        records.append(_record(m, target, EQUIVALENT, (), suspect=True))
    if skipped:
        ladder.append(f"wall_clock_expired:{skipped}skipped")
    if hits:
        ladder.append(f"cache_hits:{hits}")
    records.sort(key=lambda r: (r.path, r.line, r.operator, r.mutant_id))
    decided = sum(1 for r in records if r.status in {KILLED, SURVIVED} and not r.equivalent_suspect)
    if decided < cfg.min_decided:
        return Measurement(
            "unmeasured", "too_few_decided_mutants", tuple(records), sym_tests, tuple(failed),
            tuple(flaky), generated, len(runnable), skipped, hits, budget.seed, cfg.min_decided,
            tuple(ladder), ENGINE_VERSION, cfg.operators, image_digest,
        )
    summary: Stage2Summary | None = None
    if cfg.stage2:
        by_mutant = {m.id: m for m in runnable}
        records, summary = _stage2(
            runner, root, cfg, records, by_mutant, sym_tests, timeout,
            cache if use_cache else None, image_digest, ctx or "", clock,
        )
    return Measurement(
        "measured", "", tuple(records), sym_tests, tuple(failed), tuple(flaky), generated,
        len(runnable), skipped, hits, budget.seed, cfg.min_decided, tuple(ladder),
        ENGINE_VERSION, cfg.operators, image_digest, summary,
    )


# ------------------------------------------------------------------ stage 2

_TEST_FILE_BYTES = 512 * 1024
_SCAN_SKIP = {".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache", ".pytest_cache"}


def _module_candidates(path: str) -> frozenset[str]:
    """Dotted names a test may use to import ``path`` (every suffix; src layouts, packages)."""

    parts = [p for p in PurePosixPath(path.replace("\\", "/")).with_suffix("").parts if p]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return frozenset(".".join(parts[i:]) for i in range(len(parts)))


def _imported_names(tree: ast.AST) -> frozenset[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if base:
                names.add(base)
            names.update(f"{base}.{a.name}" if base else a.name for a in node.names)
    return frozenset(names)


def discover_wide_test_files(
    root: Path, module_paths: Sequence[str], *, max_files: int
) -> dict[str, tuple[str, ...]]:
    """Static scan (pure ``ast``, nothing is imported or run): test files of the repository
    that import each module. Sorted, bounded by ``max_files`` per module, test files only."""

    index: list[tuple[str, frozenset[str]]] = []
    stack = [root]
    while stack:
        cur = stack.pop()
        try:
            children = sorted(cur.iterdir())
        except OSError:
            continue
        for child in children:
            if child.name in _SCAN_SKIP or child.is_symlink():
                continue
            if child.is_dir():
                stack.append(child)
            elif child.suffix == ".py" and child.name != "conftest.py":
                rel = child.relative_to(root).as_posix()
                if not is_test_path(rel):
                    continue
                try:
                    if child.stat().st_size > _TEST_FILE_BYTES:
                        continue
                    tree = ast.parse(child.read_text(encoding="utf-8"))
                except (OSError, SyntaxError, ValueError, UnicodeDecodeError, RecursionError):
                    continue
                index.append((rel, _imported_names(tree)))
    index.sort()
    out: dict[str, tuple[str, ...]] = {}
    for mp in module_paths:
        cands = _module_candidates(mp)
        hits = [rel for rel, names in index if names & cands]
        out[mp] = tuple(hits[:max_files])
    return out


def _is_linked(test_id: str, linked: Sequence[str]) -> bool:
    return any(test_id == t or test_id.startswith(t + "[") for t in linked)


def _stage2(
    runner: MutantRunner,
    root: Path,
    cfg: MeasureConfig,
    records: list[MeasuredMutant],
    by_mutant: dict[str, Mutant],
    sym_tests: dict[str, tuple[str, ...]],
    timeout: float,
    cache: MutantCache | None,
    image_digest: str,
    ctx: str,
    clock: Callable[[], float],
) -> tuple[list[MeasuredMutant], Stage2Summary]:
    """Run the wider test set against every stage-1 survivor (see the module docstring).

    Stage-1 statuses are never changed here; only ``killed_outside_linked`` is filled.
    """

    deadline = clock() + cfg.stage2_wall_clock_seconds
    ladder: list[str] = []
    survivors = [
        r
        for r in records
        if r.status == SURVIVED and not r.equivalent_suspect and r.mutant_id in by_mutant
    ]
    if not survivors:
        return records, Stage2Summary(ladder=("stage2:no_survivors",))
    n = len(survivors)
    paths = sorted({r.path for r in survivors})
    files_by_path = discover_wide_test_files(root, paths, max_files=cfg.stage2_max_files)
    all_files: list[str] = []
    for f in sorted({f for fs in files_by_path.values() for f in fs}):
        try:
            validate_test_ids([f])
        except ValueError:
            continue
        all_files.append(f)
    if not all_files:
        return records, Stage2Summary(
            survivors=n, no_wider_tests=n, ladder=("stage2:no_test_files_found",)
        )

    # baseline of the wider files on the unmutated module: only tests that pass in every
    # run can attribute a kill to the mutant (failing and flaky tests are excluded, F-11)
    base_timeout = max(1.0, min(120.0, cfg.stage2_wall_clock_seconds))
    base: list[RunOutcome] = []
    for _ in range(cfg.baseline_runs):
        if clock() >= deadline:
            return records, Stage2Summary(
                survivors=n, skipped_for_budget=n,
                ladder=("stage2:budget_exhausted_before_baseline",),
            )
        base.append(runner.run(None, all_files, base_timeout))
    if any(b.status != "ok" or not b.results for b in base):
        return records, Stage2Summary(
            survivors=n, errors=n, ladder=("stage2:baseline_failed_to_run",)
        )
    stable: list[str] = []
    for tid in sorted(base[0].results):
        if all(b.results.get(tid) == CaseOutcome.PASSED for b in base):
            try:
                validate_test_ids([tid])
            except ValueError:
                continue
            stable.append(tid)
    if not stable:
        return records, Stage2Summary(
            survivors=n, no_wider_tests=n, ladder=("stage2:no_stable_wider_tests",)
        )
    stage2_timeout = _timeout_for([b.duration for b in base], cfg.budget.per_mutant_timeout_seconds)

    run = killed = unconfirmed = none_wider = skipped = errors = hits = 0
    updated: dict[str, tuple[str, ...]] = {}
    for r in survivors:  # canonical order: records are sorted
        m = by_mutant[r.mutant_id]
        own_files = set(files_by_path.get(r.path, ()))
        linked = sym_tests.get(r.symbol_id, ())
        wide = [
            t for t in stable if t.split("::", 1)[0] in own_files and not _is_linked(t, linked)
        ][: cfg.stage2_max_tests]
        if not wide:
            none_wider += 1
            continue
        key = (
            cache_key(m.mutant_hash, ["stage2", *wide], image_digest, ctx)
            if cache is not None
            else ""
        )
        if cache is not None and key in cache:
            hit = cache[key]
            if hit.status in {KILLED, SURVIVED}:
                hits += 1
                run += 1
                kills = tuple(sorted(hit.killed_by))[: cfg.stage2_max_killers]
                updated[r.mutant_id] = kills
                killed += 1 if kills else 0
                continue
        if clock() >= deadline:
            skipped += 1
            continue
        out = runner.run(m, wide, stage2_timeout, stop_on_first_failure=True)
        if out.status != "ok" or not out.results:
            errors += 1
            continue
        res = collapse_results(out.results, wide)
        killers = sorted(t for t in wide if res[t] == CaseOutcome.FAILED)
        if not killers:
            run += 1
            updated[r.mutant_id] = ()
            if cache is not None:
                cache[key] = MutantOutcome(m.id, SURVIVED, duration=out.duration)
            continue
        # confirm: a flaky test must not turn a survivor into a "link gap" (that can only
        # ever lower the penalty), so the kill has to repeat on a second run
        if clock() >= deadline:
            skipped += 1  # killed once but not confirmed in budget: no statement
            continue
        again = runner.run(m, killers, stage2_timeout)
        if again.status != "ok" or not again.results:
            errors += 1
            continue
        res2 = collapse_results(again.results, killers)
        confirmed = sorted(t for t in killers if res2[t] == CaseOutcome.FAILED)
        run += 1
        if not confirmed:
            unconfirmed += 1
            updated[r.mutant_id] = ()
            continue
        updated[r.mutant_id] = tuple(confirmed[: cfg.stage2_max_killers])
        killed += 1
        if cache is not None:
            cache[key] = MutantOutcome(m.id, KILLED, frozenset(confirmed), out.duration)
    if skipped:
        ladder.append(f"stage2:wall_clock_expired:{skipped}skipped")
    if hits:
        ladder.append(f"stage2:cache_hits:{hits}")
    if len(stable) > cfg.stage2_max_tests:
        ladder.append(f"stage2:tests_capped_at:{cfg.stage2_max_tests}")
    new_records = [
        replace(r, killed_outside_linked=updated[r.mutant_id]) if r.mutant_id in updated else r
        for r in records
    ]
    return new_records, Stage2Summary(
        survivors=n, run=run, killed=killed, unconfirmed=unconfirmed, no_wider_tests=none_wider,
        skipped_for_budget=skipped, errors=errors, cache_hits=hits, tests_considered=len(stable),
        ladder=tuple(ladder),
    )


def _record(
    m: Mutant, target: SymbolTarget, status: str, killed_by: tuple[str, ...],
    *, suspect: bool = False, cached: bool = False,
) -> MeasuredMutant:
    return MeasuredMutant(
        m.id, target.symbol_id, m.path, m.lineno, m.operator, status, killed_by,
        suspect, cached,
    )


def _run_one(
    runner: MutantRunner, mutant: Mutant, tests: Sequence[str], timeout: float, reruns: int
) -> MutantOutcome:
    out = runner.run(mutant, tests, timeout)
    if out.status == "timeout":
        out = runner.run(mutant, tests, timeout)  # timeouts rerun once (design 5.2)
        if out.status == "timeout":
            return MutantOutcome(mutant.id, "timeout", duration=out.duration, detail="timeout")
    if out.status != "ok" or not out.results:
        return MutantOutcome(mutant.id, "error", duration=out.duration, detail=out.detail)
    res = collapse_results(out.results, tests)
    killers = frozenset(t for t in tests if res[t] in {CaseOutcome.FAILED, None})
    if killers:
        return MutantOutcome(mutant.id, KILLED, killers, out.duration)
    for _ in range(reruns):
        again = runner.run(mutant, tests, timeout)
        if again.status == "ok":
            r2 = collapse_results(again.results, tests)
            if any(v in {CaseOutcome.FAILED, None} for v in r2.values()):
                return MutantOutcome(mutant.id, "flaky", duration=out.duration, detail="killed on rerun")
    return MutantOutcome(mutant.id, SURVIVED, duration=out.duration)
