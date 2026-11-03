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
   short-circuits final statuses (``killed`` / ``survived``) only.

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

    def __post_init__(self) -> None:
        if self.baseline_runs < 1 or self.survivor_reruns < 0 or self.min_decided < 1:
            raise ValueError("invalid mutation measurement configuration")


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
    return Measurement(
        "measured", "", tuple(records), sym_tests, tuple(failed), tuple(flaky), generated,
        len(runnable), skipped, hits, budget.seed, cfg.min_decided, tuple(ladder),
        ENGINE_VERSION, cfg.operators, image_digest,
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
