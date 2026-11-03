"""Stage A ``mutation`` producer (contract 5; flag ``RADIUS_FEATURE_MUTATION``, default OFF).

Mutants are generated code derived from an untrusted pull request. They run ONLY through
:class:`radius_testing.mutation.SandboxMutantRunner` (the F-07 hardened container: no
network, read-only root, dropped capabilities, resource limits, one throw-away container
per run, a fresh copy of the checkout with the mutated file written into the copy). This
module never constructs the dev-only ``SubprocessLocalRunner``, and
:func:`radius_testing.mutation.measure_mutation` refuses it unless a caller passes
``allow_local_runner=True`` (only the fixture scripts do).

With the flag off, :func:`create_mutation_producer` returns ``None`` and nothing in this
module is imported by the pipeline. Every failure degrades to "unmeasured, static cap"
(a :class:`MutationInput` with ``status="unmeasured"``); nothing here raises into Stage A.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from radius_evidence.domain.inputs import (
    CriterionSymbolEdgeInput,
    MutantInput,
    MutationInput,
    SymbolInput,
    SymbolTestEdgeInput,
)
from radius_evidence.domain.versions import MUTATION_VERSION
from radius_shared.logging import get_logger

LOGGER = get_logger(__name__)

#: Tests run per mutant of one symbol are bounded (command length, container time).
MAX_TESTS_PER_SYMBOL = 12
#: Link thresholds used to select targets (the same defaults Stage B applies).
MIN_CRITERION_LINK = 0.20
MIN_TEST_LINK = 0.50
CACHE_RETENTION = timedelta(days=30)
CACHE_ALGO = MUTATION_VERSION


@dataclass(frozen=True, slots=True)
class MutationRequest:
    """What the producer may read: the head checkout and the plain Stage A facts."""

    repository_path: Path
    changeset: Any
    symbols: tuple[SymbolInput, ...]
    criterion_symbol: tuple[CriterionSymbolEdgeInput, ...]
    symbol_test: tuple[SymbolTestEdgeInput, ...]


def unmeasured_input(reason: str, *, seed: int = 0, min_decided: int = 5) -> MutationInput:
    return MutationInput(
        status="unmeasured", reason=reason, seed=seed, min_decided=min_decided,
        engine="mutation-ast-1",
    )


def select_targets(req: MutationRequest) -> list[Any]:
    """Changed Python behavioural symbols linked to a criterion AND to at least one test.

    Test files, pseudo symbols (``<module>`` / ``<file>``), removed symbols and symbols
    without a ``new_range`` are never mutated. Tests are the symbol's ``symbol_test``
    edges at or above the link minimum, best first, bounded per symbol.
    """

    from radius_testing.mutation import SymbolTarget, is_test_path

    inputs = {s.symbol_id: s for s in req.symbols}
    linked_to_criterion = {
        e.symbol_id for e in req.criterion_symbol if e.score >= MIN_CRITERION_LINK - 1e-12
    }
    tests_by_symbol: dict[str, list[tuple[float, str]]] = {}
    for e in req.symbol_test:
        if e.score >= MIN_TEST_LINK - 1e-12:
            tests_by_symbol.setdefault(e.symbol_id, []).append((e.score, e.test_id))
    targets = []
    for cs in getattr(req.changeset, "symbols", ()) or ():
        sid = getattr(cs, "symbol_id", None)
        info = inputs.get(sid)
        if info is None or sid not in linked_to_criterion or sid not in tests_by_symbol:
            continue
        rng = getattr(cs, "new_range", None)
        if (
            info.language != "python"
            or not info.is_behavioral
            or info.is_test
            or info.is_pseudo
            or info.change_kind == "removed"
            or rng is None
            or is_test_path(info.path)
        ):
            continue
        ranked = sorted(tests_by_symbol[sid], key=lambda t: (-t[0], t[1]))
        tests = tuple(dict.fromkeys(t for _, t in ranked))[:MAX_TESTS_PER_SYMBOL]
        targets.append(
            SymbolTarget(sid, info.path, ((int(rng.start), int(rng.end)),), tests)
        )
    return sorted(targets, key=lambda t: (t.path, t.symbol_id))


def to_input(m: Any, *, image: str = "") -> MutationInput:
    """``radius_testing.mutation.Measurement`` -> the persisted :class:`MutationInput`."""

    return MutationInput(
        status=m.status,
        reason=m.reason,
        mutants=tuple(
            MutantInput(
                mutant_id=r.mutant_id,
                symbol_id=r.symbol_id,
                path=r.path,
                line=r.line,
                operator=r.operator,
                status=r.status,
                killed_by=tuple(r.killed_by),
                equivalent_suspect=r.equivalent_suspect,
                killed_outside_linked=(
                    None if r.killed_outside_linked is None else tuple(r.killed_outside_linked)
                ),
            )
            for r in m.mutants
        ),
        symbol_tests={k: tuple(v) for k, v in sorted(m.symbol_tests.items())},
        baseline_failed=tuple(m.baseline_failed),
        baseline_flaky=tuple(m.baseline_flaky),
        generated=m.generated,
        sampled=m.sampled,
        skipped_for_budget=m.skipped_for_budget,
        cache_hits=m.cache_hits,
        seed=m.seed,
        min_decided=m.min_decided,
        ladder=tuple(m.ladder),
        engine=m.engine,
        operators=tuple(m.operators),
        image=image or m.image,
        stage2=stage2_block(getattr(m, "stage2", None)),
    )


def stage2_block(s: Any) -> dict[str, Any] | None:
    """Plain-data stage 2 summary for ``MutationInput.stage2``; ``None`` when not enabled."""

    if s is None:
        return None
    return {
        "enabled": True,
        "survivors": s.survivors,
        "run": s.run,
        "killed_outside_linked": s.killed,
        "unconfirmed": s.unconfirmed,
        "no_wider_tests": s.no_wider_tests,
        "skipped_for_budget": s.skipped_for_budget,
        "errors": s.errors,
        "cache_hits": s.cache_hits,
        "tests_considered": s.tests_considered,
        "ladder": list(s.ladder),
    }


# ------------------------------------------------------------------ image identity


def resolve_image_digest(sandbox: Any) -> str:
    """Identity of the sandbox image for cache keys; ``""`` when unknown (cache off).

    A reference pinned by digest is used as is; otherwise the local image id is read
    with ``docker image inspect``. Any failure yields ``""``: no cache, never a guess.
    """

    image = sandbox.config.image
    if "@sha256:" in image:
        return image
    runtime = shutil.which(sandbox.config.runtime)
    if runtime is None:
        return ""
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, image reference validated by SandboxConfig
            [runtime, "image", "inspect", "--format", "{{.Id}}", image],
            capture_output=True, text=True, timeout=20, check=False, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    ident = (done.stdout or "").strip()
    return ident if done.returncode == 0 and ident.startswith("sha256:") else ""


# ------------------------------------------------------------------ SQL cache


class SqlMutationCache:
    """Per-(organization, repository) cache of final mutant results (EV-09).

    A performance optimisation only: every database error acts as a miss / skipped store,
    so a broken cache can never change a result or fail the analysis.
    """

    def __init__(
        self,
        session_factory: Callable[[], Any],
        organization_id: UUID,
        repository_id: UUID,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sf = session_factory
        self._org = organization_id
        self._repo = repository_id
        self._clock = clock
        self._pruned = False

    def _row(self, session: Any, key: str) -> Any:
        from radius_shared.database.verdict_v2 import MutationResultCacheRow
        from sqlalchemy import select

        return session.execute(
            select(MutationResultCacheRow).where(
                MutationResultCacheRow.organization_id == self._org,
                MutationResultCacheRow.repository_id == self._repo,
                MutationResultCacheRow.cache_key == key,
            )
        ).scalar_one_or_none()

    def _get(self, key: str) -> Any | None:
        from radius_testing.mutation import MutantOutcome

        try:
            with self._sf() as session:
                row = self._row(session, key)
                if row is None or row.status not in {"killed", "survived"}:
                    return None
                return MutantOutcome("", row.status, frozenset(row.killed_by or ()), cached=True)
        except Exception as exc:  # noqa: BLE001 - cache is best effort
            LOGGER.warning("Mutation cache read failed", extra={"reason_code": type(exc).__name__})
            return None

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and self._get(key) is not None

    def __getitem__(self, key: str) -> Any:
        hit = self._get(key)
        if hit is None:
            raise KeyError(key)
        return hit

    def __setitem__(self, key: str, value: Any) -> None:
        if value.status not in {"killed", "survived"}:
            return
        try:
            from radius_shared.database.verdict_v2 import MutationResultCacheRow
            from sqlalchemy import delete

            now = self._clock()
            with self._sf() as session:
                if not self._pruned:
                    session.execute(
                        delete(MutationResultCacheRow).where(
                            MutationResultCacheRow.created_at < now - CACHE_RETENTION
                        )
                    )
                    self._pruned = True
                if self._row(session, key) is None:
                    session.add(
                        MutationResultCacheRow(
                            organization_id=self._org,
                            repository_id=self._repo,
                            cache_key=key,
                            status=value.status,
                            killed_by=sorted(value.killed_by),
                            algo_version=CACHE_ALGO,
                            created_at=now,
                        )
                    )
                session.commit()
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Mutation cache write failed", extra={"reason_code": type(exc).__name__})


# ------------------------------------------------------------------ producer


class SandboxMutationProducer:
    """``Producers.mutation`` implementation: sandbox backend only."""

    def __init__(
        self,
        settings: Any,
        sandbox: Any,
        *,
        cache: Any | None = None,
        image_digest: Callable[[Any], str] = resolve_image_digest,
    ) -> None:
        self._settings = settings
        self._sandbox = sandbox
        self._cache = cache
        self._image_digest = image_digest

    def __call__(self, req: MutationRequest) -> MutationInput:
        from radius_testing.mutation import (
            MeasureConfig,
            MutationBudget,
            SandboxMutantRunner,
            measure_mutation,
        )

        s = self._settings
        cfg = MeasureConfig(
            budget=MutationBudget(
                max_mutants=int(s.mutation_max_mutants),
                wall_clock_seconds=float(s.mutation_wall_clock_seconds),
                per_mutant_timeout_seconds=float(s.mutation_mutant_timeout_seconds),
            ),
            stage2=bool(getattr(s, "mutation_stage2_enabled", False)),
            stage2_max_tests=int(getattr(s, "mutation_stage2_max_tests", 60)),
            stage2_wall_clock_seconds=float(
                getattr(s, "mutation_stage2_wall_clock_seconds", 300.0)
            ),
        )
        targets = select_targets(req)
        if not targets:
            return unmeasured_input("no_linked_changed_symbols", seed=cfg.budget.seed)
        try:
            self._sandbox.check_ready()
        except Exception as exc:  # noqa: BLE001 - SandboxUnavailableError and friends
            LOGGER.warning(
                "Mutation sandbox not ready", extra={"reason_code": type(exc).__name__}
            )
            return unmeasured_input("sandbox_not_ready", seed=cfg.budget.seed)
        runner = SandboxMutantRunner(req.repository_path, self._sandbox)
        digest = self._image_digest(self._sandbox)
        m = measure_mutation(
            runner, req.repository_path, targets, cfg, cache=self._cache, image_digest=digest
        )
        return to_input(m, image=digest)


def create_mutation_producer(
    settings: Any,
    *,
    session_factory: Callable[[], Any] | None = None,
    organization_id: UUID | None = None,
    repository_id: UUID | None = None,
) -> Callable[[MutationRequest], MutationInput] | None:
    """The producer for the runtime, or ``None`` when the flag is off.

    With the flag on but the sandbox not selected (``WORKER_TEST_EXECUTION_MODE`` is not
    ``sandbox``), the producer is a stub returning ``unmeasured/sandbox_disabled``: mutants
    are never executed anywhere else.
    """

    if not getattr(settings, "mutation_enabled", False):
        return None
    from radius_worker.execution_mode import (
        TestExecutionMode,
        build_test_runner,
        resolve_test_execution_mode,
    )

    try:
        mode = resolve_test_execution_mode(settings)
    except Exception:  # noqa: BLE001 - misconfigured isolation: do not run anything
        mode = TestExecutionMode.DISABLED
    if mode is not TestExecutionMode.SANDBOX:
        return lambda _req: unmeasured_input("sandbox_disabled")
    from radius_testing.infrastructure import ContainerSandboxRunner

    # A fresh runner on the same hardened config: no F-11 failure reruns (a failing
    # mutant is a kill, not a flake to repeat; the producer reruns survivors itself).
    sandbox = ContainerSandboxRunner(build_test_runner(mode, settings).config)
    cache = None
    if session_factory is not None and organization_id is not None and repository_id is not None:
        cache = SqlMutationCache(session_factory, organization_id, repository_id)
    return SandboxMutationProducer(settings, sandbox, cache=cache)


def request_from_stage_a(
    repository_path: Path,
    changeset: Any,
    symbols: Sequence[SymbolInput],
    criterion_symbol: Sequence[CriterionSymbolEdgeInput],
    symbol_test: Sequence[SymbolTestEdgeInput],
) -> MutationRequest:
    return MutationRequest(
        Path(repository_path), changeset, tuple(symbols), tuple(criterion_symbol),
        tuple(symbol_test),
    )
