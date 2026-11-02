"""Stage A: collect the plain-data facts of one analysis from the checkout (VS-05).

Producers (LK-01 symbol changes, EV-02 tamper, LK-02 criterion->symbol, LK-03
symbol->test, LK-04 assertions, optional VS-04 relevance) are re-run from the
checkout (the orchestrator is not edited, design 2.3). Each producer is guarded
with a timeout and isolated:

* ``symbol_changes``, ``tamper`` and the intent load are *critical*: without them
  the verdict could be falsely clean, so their failure raises :class:`StageAError`
  and the caller keeps v1 published.
* every other producer degrades the analysis (``producer_failed:<name>``, or
  ``producer_timeout:<name>`` plus the blocking marker ``truncated``) and the
  evidence it would have supplied is simply absent, which only lowers support.

Nothing here logs criterion text or code; failures carry the exception class only.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from uuid import UUID

from radius_evidence.domain.inputs import CriterionInput, StageAInput
from radius_evidence.domain.versions import (
    CRITERION_SYMBOL_LINKS_VERSION,
    SYMBOL_CHANGES_VERSION,
    SYMBOL_TEST_LINKS_VERSION,
    TAMPER_VERSION,
)
from radius_shared.logging import get_logger

from radius_worker.verdict_v2 import adapters
from radius_worker.verdict_v2.sources import (
    HeadShaPort,
    IntentFacts,
    IntentPort,
    read_python_sources,
    resolve_head_sha,
)

LOGGER = get_logger(__name__)

TRUNCATED = "truncated"


class StageAError(Exception):
    """A critical Stage A producer failed; v1 stays the published verdict."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class ProducerTimeoutError(Exception):
    """A guarded producer exceeded its time budget."""


@dataclass(frozen=True, slots=True)
class CollectLimits:
    """Soft budgets (design 3.8); hitting one yields the ``truncated`` marker."""

    max_criteria: int = 50
    max_symbols: int = 5000
    max_tests: int = 3000
    timeout_s: float = 120.0
    step_timeout_s: float = 60.0


def guarded[T](fn: Callable[[], T], timeout_s: float) -> T:
    """Run ``fn`` with a timeout in a worker thread.

    A timed-out call is abandoned (Python threads cannot be killed); its result is
    discarded. Exceptions propagate unchanged.
    """

    if timeout_s <= 0:
        raise ProducerTimeoutError
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="verdict-v2")
    future = pool.submit(fn)
    try:
        return future.result(timeout=timeout_s)
    except FutureTimeout as exc:
        future.cancel()
        raise ProducerTimeoutError from exc
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


# ------------------------------------------------------------------ producers


def _snapshots(command: Any) -> tuple[Any, Any, Any]:
    """``(base, head, diff source)`` as the orchestrator builds them."""

    from radius_analysis.symbol_changes import DirectorySnapshot, GitSnapshot, RefRange

    base = GitSnapshot(command.repository_path, command.base_ref) if command.base_ref else None
    head = (
        GitSnapshot(command.repository_path, command.head_ref)
        if command.head_ref
        else DirectorySnapshot(command.repository_path)
    )
    if command.diff_text:
        source: Any = command.diff_text
    elif command.base_ref and command.head_ref:
        source = RefRange(command.repository_path, command.base_ref, command.head_ref)
    else:
        raise StageAError("no_diff_source")
    return base, head, source


def default_symbol_changes(command: Any) -> Any:
    from radius_analysis.symbol_changes import extract_symbol_changes

    base, head, source = _snapshots(command)
    return extract_symbol_changes(base, head, source)


def default_tamper(changeset: Any, command: Any) -> Any:
    from radius_analysis.tamper import analyze_tampering

    base, head, _ = _snapshots(command)
    return analyze_tampering(changeset, base, head, diff_text=command.diff_text or None)


def default_link_criteria(
    criteria: Sequence[CriterionInput],
    changeset: Any,
    command: Any,
    sources: dict[str, str],
) -> Any:
    from radius_linking.domain.model import CriterionInput as LinkCriterion
    from radius_linking.infrastructure.pipeline import link_changeset

    base, head, _ = _snapshots(command)
    inputs = [
        LinkCriterion(
            criterion_id=c.criterion_id,
            text=c.text,
            paths=c.hints_paths,
            tests=c.hints_tests,
            weight=c.weight,
            state=c.lifecycle,
        )
        for c in criteria
    ]
    linkset, _docs = link_changeset(inputs, changeset, head, base, python_sources=sources)
    return linkset


def default_link_tests(sources: dict[str, str], targets: Sequence[Any]) -> Any:
    from radius_testing.linking import NamingLinker, StaticLinker, combine_links

    static = StaticLinker().link(sources, targets)
    naming = NamingLinker().link(sources, targets)
    return combine_links(static, naming)


def default_assertions(
    test_files: Sequence[str], sources: dict[str, str], links: Any, targets: Sequence[Any]
) -> Any:
    from radius_testing.assertions import LinkTargetResolver, extract_assertions

    return extract_assertions(
        test_files, sources, links, resolver=LinkTargetResolver(list(targets))
    )


def default_relevance(
    criteria: Sequence[CriterionInput],
    criterion_linkset: Any,
    test_linkset: Any,
    sources: dict[str, str],
    assertion_set: Any,
) -> list[dict[str, Any]]:
    """VS-04 ``r_ct`` for the criteria x tests connected through a changed symbol."""

    from radius_linking.application.relevance import relevance_from_links
    from radius_linking.domain.chain import SymbolTestEdge
    from radius_linking.domain.model import CriterionInput as LinkCriterion

    inputs = [
        LinkCriterion(
            criterion_id=c.criterion_id,
            text=c.text,
            paths=c.hints_paths,
            tests=c.hints_tests,
            weight=c.weight,
            state=c.lifecycle,
        )
        for c in criteria
    ]
    c2s = [
        replace(lk, symbol_id=adapters.short_symbol_id(lk.symbol_id))
        for lk in getattr(criterion_linkset, "links", ())
    ]
    s2t = [
        SymbolTestEdge(
            symbol_id=adapters.short_symbol_id(lk.symbol_id),
            test_id=lk.test_id,
            score=lk.score,
            kind=getattr(lk.kind, "value", str(lk.kind)),
            linker="combined",
        )
        for lk in getattr(test_linkset, "links", ())
    ]
    docs = adapters.build_test_docs(
        sources,
        {e.test_id for e in s2t},
        assertion_set.to_dict() if assertion_set is not None else None,
    )
    rel = relevance_from_links(inputs, docs, c2s, s2t)
    return [
        {
            "criterion_id": i.criterion_id,
            "test_id": i.test_id,
            "weight": i.r_ct,
            "method": "criterion_test_relevance",
        }
        for i in rel.items
        if i.r_ct > 0.0
    ]


@dataclass(slots=True)
class Producers:
    """Injectable producer callables (tests substitute fakes)."""

    symbol_changes: Callable[[Any], Any] = default_symbol_changes
    tamper: Callable[[Any, Any], Any] = default_tamper
    link_criteria: Callable[..., Any] = default_link_criteria
    link_tests: Callable[..., Any] = default_link_tests
    assertions: Callable[..., Any] = default_assertions
    #: VS-04 relevance: ``(criteria, criterion_linkset, symbol_test_linkset, sources,
    #: assertion_set) -> edges``. ``None`` means unavailable (hints only, marker
    #: ``relevance_unavailable``).
    relevance: Callable[..., Any] | None = default_relevance
    #: LK-03 dynamic-coverage links (flag-gated); ``None`` = not produced.
    dynamic_links: Callable[..., Any] | None = None
    read_sources: Callable[[Path], tuple[dict[str, str], bool]] = read_python_sources


# ------------------------------------------------------------------ collector


@dataclass(slots=True)
class _Run:
    """Per-collect mutable state: degraded markers and the time budget."""

    limits: CollectLimits
    degraded: list[str] = field(default_factory=list)
    algo: dict[str, str] = field(default_factory=dict)
    started: float = field(default_factory=time.monotonic)

    def remaining(self) -> float:
        return self.limits.timeout_s - (time.monotonic() - self.started)

    def mark(self, *markers: str) -> None:
        for m in markers:
            if m not in self.degraded:
                self.degraded.append(m)

    def step[T](self, name: str, fn: Callable[[], T], default: T) -> T:
        """Run a non-critical producer; degrade (never raise) on failure or timeout."""

        try:
            return guarded(fn, min(self.limits.step_timeout_s, self.remaining()))
        except ProducerTimeoutError:
            self.mark(f"producer_timeout:{name}", TRUNCATED)
        except Exception as exc:  # noqa: BLE001 - isolation by contract
            self.mark(f"producer_failed:{name}")
            LOGGER.warning(
                "Verdict v2 producer failed",
                extra={"producer": name, "reason_code": type(exc).__name__},
            )
        return default

    def critical[T](self, name: str, fn: Callable[[], T]) -> T:
        try:
            return guarded(fn, min(self.limits.step_timeout_s, self.remaining()))
        except StageAError:
            raise
        except ProducerTimeoutError as exc:
            raise StageAError(f"{name}_timeout") from exc
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(
                "Verdict v2 critical producer failed",
                extra={"producer": name, "reason_code": type(exc).__name__},
            )
            raise StageAError(f"{name}_failed") from exc


class VerdictStageACollector:
    """``StageACollector`` implementation (see ``ports.py``)."""

    def __init__(
        self,
        intent: IntentPort,
        *,
        head_sha_port: HeadShaPort | None = None,
        producers: Producers | None = None,
        limits: CollectLimits | None = None,
    ) -> None:
        self._intent = intent
        self._head_port = head_sha_port or (intent if hasattr(intent, "head_sha") else None)
        self._producers = producers or Producers()
        self._limits = limits or CollectLimits()

    # -- helpers ----------------------------------------------------------

    def _head_sha(self, analysis_id: UUID, command: Any) -> str:
        sha = None
        if self._head_port is not None:
            sha = self._head_port.head_sha(analysis_id, command)
        sha = sha or resolve_head_sha(command)
        if not sha:
            raise StageAError("head_sha_unresolved")
        return sha

    # -- API --------------------------------------------------------------

    def resolve_head(self, analysis_id: UUID, command: Any) -> str | None:
        """The head sha, or ``None`` when it cannot be resolved (never raises)."""

        try:
            return self._head_sha(analysis_id, command)
        except Exception:  # noqa: BLE001 - used on the error path only
            return None

    def collect(self, analysis_id: UUID, command: Any) -> StageAInput:
        """Build the :class:`StageAInput`; raises :class:`StageAError` on critical failure."""

        run = _Run(self._limits)
        prod = self._producers
        head_sha = self._head_sha(analysis_id, command)

        try:
            facts: IntentFacts = guarded(
                lambda: self._intent.load(analysis_id), self._limits.step_timeout_s
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(
                "Verdict v2 intent load failed",
                extra={"analysis_id": str(analysis_id), "reason_code": type(exc).__name__},
            )
            raise StageAError("intent_load_failed") from exc

        criteria = adapters.criterion_inputs(facts.criteria, limit=self._limits.max_criteria)
        if criteria.dropped.get("criteria_over_limit"):
            run.mark(TRUNCATED)
        run.mark(*criteria.notes)

        changeset = run.critical("symbol_changes", lambda: prod.symbol_changes(command))
        run.algo["symbol_changes"] = getattr(changeset, "algo_version", SYMBOL_CHANGES_VERSION)
        if getattr(changeset, "truncated", False):
            run.mark(TRUNCATED)
        symbols = adapters.symbol_inputs(changeset)
        run.mark(*symbols.notes)
        sym_items = symbols.items
        if len(sym_items) > self._limits.max_symbols:
            sym_items = sym_items[: self._limits.max_symbols]
            run.mark(TRUNCATED)
        run.mark(*adapters.unsupported_languages(sym_items))

        report = run.critical("tamper", lambda: prod.tamper(changeset, command))
        tamper = adapters.tamper_inputs(report)
        if tamper.truncated:
            run.mark(TRUNCATED)
        if tamper.rule_errors:
            raise StageAError("tamper_incomplete")
        run.mark(*(f"adapter_dropped:{k}" for k in sorted(tamper.dropped)))
        run.algo["tamper"] = getattr(report, "catalog_version", TAMPER_VERSION)

        root = Path(command.repository_path)
        sources, src_truncated = run.step(
            "read_sources", lambda: prod.read_sources(root), ({}, False)
        )
        if src_truncated:
            run.mark(TRUNCATED)

        link_targets = self._link_targets(changeset, sym_items)
        crit_sym = adapters.Adapted((), {})
        crit_linkset = None
        if criteria.items and sym_items:
            linkset = run.step(
                "criterion_symbol_links",
                lambda: prod.link_criteria(criteria.items, changeset, command, sources),
                None,
            )
            crit_linkset = linkset
            if linkset is not None:
                crit_sym = adapters.criterion_symbol_edges(
                    linkset,
                    known_criteria=[c.criterion_id for c in criteria.items],
                )
                run.algo["criterion_symbol_links"] = getattr(
                    linkset, "algo_version", CRITERION_SYMBOL_LINKS_VERSION
                )
        run.mark(*crit_sym.notes)

        sym_test = adapters.Adapted((), {})
        test_links = None
        if link_targets:
            test_links = run.step(
                "symbol_test_links", lambda: prod.link_tests(sources, link_targets), None
            )
            if prod.dynamic_links is not None and test_links is not None:
                test_links = run.step(
                    "dynamic_links",
                    lambda: prod.dynamic_links(sources, link_targets, test_links),
                    test_links,
                )
            if test_links is not None:
                sym_test = adapters.symbol_test_edges(test_links)
                run.algo["symbol_test_links"] = (
                    getattr(test_links, "algo_version", "") or SYMBOL_TEST_LINKS_VERSION
                )
        run.mark(*sym_test.notes)
        edges_st = sym_test.items
        tests_in_links = sorted({e.test_id for e in edges_st})
        if len(tests_in_links) > self._limits.max_tests:
            keep = set(tests_in_links[: self._limits.max_tests])
            edges_st = tuple(e for e in edges_st if e.test_id in keep)
            run.mark(TRUNCATED)

        changed_tests = adapters.changed_test_ids(sym_items)
        test_files = sorted(
            {t.split("::", 1)[0] for t in {*(e.test_id for e in edges_st), *changed_tests}}
        )
        features = adapters.Adapted((), {})
        aset = None
        if test_files:
            aset = run.step(
                "assertions",
                lambda: prod.assertions(test_files, sources, test_links, link_targets),
                None,
            )
            if aset is not None:
                features = adapters.assertion_features(aset)
                run.algo["assertion_extract"] = getattr(aset, "algo_version", "")
        run.mark(*features.notes)

        known_tests = {a.test_id for a in features.items} | {e.test_id for e in edges_st}
        known_tests |= set(changed_tests)
        hints = adapters.hint_test_edges(criteria.items, known_tests)
        run.mark(*hints.notes)
        relevance_edges: tuple[Any, ...] = ()
        if prod.relevance is not None and criteria.items and known_tests:
            raw = run.step(
                "relevance",
                lambda: prod.relevance(
                    criteria.items, crit_linkset, test_links, sources, aset
                ),
                None,
            )
            if raw is not None:
                rel = adapters.relevance_edges(
                    raw, known_criteria=[c.criterion_id for c in criteria.items]
                )
                relevance_edges = rel.items
                run.mark(*rel.notes)
        elif prod.relevance is None:
            run.mark("relevance_unavailable")
        crit_test = adapters.merge_criterion_test_edges(hints.items, relevance_edges)

        return StageAInput(
            analysis_id=str(analysis_id),
            repository_id=str(getattr(command, "repository_id", "")),
            head_sha=head_sha,
            changeset_ref=_changeset_ref(changeset),
            criteria=criteria.items,
            symbols=sym_items,
            criterion_symbol=crit_sym.items,
            symbol_test=edges_st,
            criterion_test=crit_test,
            assertions=features.items,
            tamper=tamper.findings,
            tamper_waived=tamper.waived,
            tamper_unanalyzable=tamper.unanalyzable,
            changed_test_ids=changed_tests,
            added_test_ids=adapters.changed_test_ids(sym_items, added_only=True),
            agent_signal=adapters.agent_signal(facts.commit_messages),
            degraded=tuple(run.degraded),
            algo_versions=dict(sorted(run.algo.items())),
        )

    @staticmethod
    def _link_targets(changeset: Any, symbols: Sequence[Any]) -> list[Any]:
        """LK-03 targets: behavioral, non-test, non-pseudo-file changed symbols."""

        from radius_testing.linking import LinkTarget

        keep = {s.symbol_id for s in symbols if not s.is_test and s.kind != "file"}
        out = []
        for s in getattr(changeset, "symbols", ()) or ():
            if s.symbol_id in keep and s.is_behavioral:
                try:
                    out.append(LinkTarget.from_changed_symbol(s))
                except (AttributeError, TypeError, ValueError):
                    continue
        return out


def _changeset_ref(changeset: Any) -> str:
    try:
        from radius_linking.infrastructure.pipeline import changeset_ref

        return changeset_ref(changeset)
    except Exception:  # noqa: BLE001
        return str(getattr(changeset, "algo_version", SYMBOL_CHANGES_VERSION))
