"""Stage B pipeline and the best-effort entry point (VS-03 composition + VS-06 hook).

``compute_pipeline`` is a pure function: a :class:`StageBInput` goes through

    normalize evidence -> IEG -> q(e, c) -> S(c) -> states / UIM -> rules R1..R4
    -> justification tree -> bundle JSON (``verdict_v2.schema.json``).

It lives in the worker (not in ``radius_evidence.application``) because the rules
are in ``radius_confidence.verdict_v2`` and the dependency direction is
``confidence -> evidence`` (design 2.2): the pure evidence package cannot import
the rules, so the composition root does.

``run_verdict_v2_best_effort`` is the flag-gated hook: it never raises, never
touches v1 tables, and with the flag ``off`` does nothing at all (design 5.4).
Logging carries ids and counts only (no criterion text, no code).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from radius_confidence.verdict_v2.application.service import (
    build_criterion_verdict,
    compute_verdict_v2,
)
from radius_confidence.verdict_v2.domain.model import CriterionVerdict, VerdictV2
from radius_confidence.verdict_v2.domain.rules import AnalysisFacts
from radius_evidence.application.ieg_builder import (
    build_ieg_with_report,
)
from radius_evidence.application.normalize import normalize_evidence
from radius_evidence.domain.config import VerdictV2Config
from radius_evidence.domain.enums import EdgeKind, EvidenceKind, NodeKind, Outcome
from radius_evidence.domain.ieg import Ieg, IegIndex, node_id
from radius_evidence.domain.inputs import (
    CaseOutcomeInput,
    CriterionInput,
    StageAInput,
    StageBInput,
)
from radius_evidence.domain.model import EvidenceItem
from radius_evidence.domain.quality import (
    EvidenceQuality,
    evidence_quality_row,
    link_strength,
)
from radius_evidence.domain.serialization import canonical_json, sha256_hex
from radius_evidence.domain.states import (
    CriterionStateResult,
    compute_uim,
    evaluate_criterion,
)
from radius_evidence.domain.strength import a_static
from radius_evidence.domain.support import (
    SupportResult,
    compute_support,
    support_reasons,
)
from radius_evidence.domain.versions import (
    ALGO_VERSION,
    BUNDLE_SCHEMA,
    DEFAULT_COMPONENT_VERSIONS,
)
from radius_shared.logging import get_logger
from radius_shared.verdict_v2_flag import VerdictV2Mode

from radius_worker.verdict_v2.adapters import behavioral_symbols, failed_case_count

LOGGER = get_logger(__name__)

STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_SKIPPED = "skipped"
_R = 6


def _r(value: float | None) -> float | None:
    return None if value is None else round(float(value), _R)


# ------------------------------------------------------------------ Stage B input


def build_stage_b(
    stage_a: StageAInput,
    *,
    cases: tuple[CaseOutcomeInput, ...] = (),
    uploads: int = 0,
    flaky_test_ids: frozenset[str] = frozenset(),
    flaky_scores: Mapping[str, float] | None = None,
) -> StageBInput:
    """Assemble a :class:`StageBInput`; ``results_received`` follows ``uploads``."""

    return StageBInput(
        stage_a=stage_a,
        cases=cases,
        uploads=uploads,
        flaky_test_ids=flaky_test_ids,
        flaky_scores=dict(flaky_scores or {}),
        results_received=uploads > 0,
        ci_failed_cases=failed_case_count(cases),
    )


# ------------------------------------------------------------------ pipeline


@dataclass(frozen=True, slots=True)
class PipelineResult:
    verdict: VerdictV2
    items: tuple[EvidenceItem, ...]
    ieg: Ieg
    rejected: tuple[str, ...] = ()
    unlinked_symbols: tuple[str, ...] = ()


def _best_rows(
    criterion: CriterionInput,
    index: IegIndex,
    items_by_test: Mapping[str, EvidenceItem],
    severity_by_finding: Mapping[str, str],
    cfg: VerdictV2Config,
) -> tuple[list[EvidenceQuality], bool]:
    """One quality row per (test, criterion) along the best path; tampered flag."""

    cid = criterion.criterion_id
    best: dict[str, tuple[float, str, Any]] = {}
    tampered = False
    for path in index.paths(cid):
        link = link_strength(path.w_cs, path.w_st, path.r_ct, cfg.link)
        cur = best.get(path.test_id)
        # highest l wins; ties: lexicographically smallest symbol id
        if cur is None or (-link.l, path.symbol_id) < (-cur[0], cur[1]):
            best[path.test_id] = (link.l, path.symbol_id, path)
        if link.l > 0.0 and index.findings_for_symbol(path.symbol_id):
            tampered = True
    rows: list[EvidenceQuality] = []
    for test_id in sorted(best):
        item = items_by_test.get(test_id)
        if item is None:
            continue
        path = best[test_id][2]
        sev = [
            severity_by_finding[f]
            for f in index.findings_for_test(test_id)
            if f in severity_by_finding
        ]
        rows.append(
            evidence_quality_row(
                item,
                cid,
                a_static=a_static(item.features, cfg.quality) if item.features else 0.0,
                w_cs=path.w_cs,
                w_st=path.w_st,
                r_ct=path.r_ct,
                symbol_id=path.symbol_id,
                tamper_severities=sev,
                quality=cfg.quality,
                mapping=cfg.link,
            )
        )
    # tests addressed by the criterion but with no symbol path: audit rows, gated
    for test_id in index.addressed_tests(cid):
        if test_id in best or test_id not in items_by_test:
            continue
        item = items_by_test[test_id]
        edge = next(
            e
            for e in index.out_edges(node_id(NodeKind.CRITERION, cid), EdgeKind.ADDRESSED_BY)
            if e.dst == node_id(NodeKind.TEST, test_id)
        )
        rows.append(
            evidence_quality_row(
                item,
                cid,
                a_static=a_static(item.features, cfg.quality) if item.features else 0.0,
                w_cs=0.0,
                w_st=0.0,
                r_ct=edge.weight,
                symbol_id="",
                quality=cfg.quality,
                mapping=cfg.link,
            )
        )
    return rows, tampered


def _covered_symbols(
    stage_a: StageAInput, active: set[str], link_min_cs: float
) -> set[str]:
    linked = {
        e.symbol_id
        for e in stage_a.criterion_symbol
        if e.criterion_id in active and e.score >= link_min_cs - 1e-12
    }
    files = {s.path for s in stage_a.symbols if s.symbol_id in linked and not s.is_pseudo}
    return {
        s.symbol_id
        for s in behavioral_symbols(stage_a.symbols)
        if s.symbol_id in linked or s.path in files
    }


def compute_pipeline(
    stage_b: StageBInput,
    *,
    config: VerdictV2Config | None = None,
    revision: int = 1,
    collected_at: str = "1970-01-01T00:00:00Z",
) -> PipelineResult:
    """Pure Stage B: deterministic for equal inputs (``collected_at`` is not scored)."""

    cfg = config or VerdictV2Config()
    sa = stage_b.stage_a
    norm = normalize_evidence(stage_b, collected_at=collected_at, config=cfg.quality)
    ieg, _report = build_ieg_with_report(
        analysis_id=sa.analysis_id,
        head_sha=sa.head_sha,
        criteria=sa.criteria,
        symbols=sa.symbols,
        criterion_symbol=sa.criterion_symbol,
        symbol_test=sa.symbol_test,
        criterion_test=sa.criterion_test,
        assertions=sa.assertions,
        tamper=sa.tamper,
        changed_test_ids=sa.changed_test_ids,
        cases=stage_b.cases,
        evidence=norm.items,
    )
    index = IegIndex(ieg)
    items_by_test = {
        i.subject_id: i for i in norm.items if i.kind is EvidenceKind.TEST_OUTCOME
    }
    severity = {t.finding_id: t.severity for t in sa.tamper}

    supports: dict[str, SupportResult] = {}
    states: dict[str, CriterionStateResult] = {}
    for c in sa.criteria:
        rows, tampered = _best_rows(c, index, items_by_test, severity, cfg)
        sup = compute_support(c.criterion_id, rows, cfg.support)
        supports[c.criterion_id] = sup
        states[c.criterion_id] = evaluate_criterion(
            c,
            sup,
            cfg,
            tampered=tampered,
            results_received=stage_b.results_received,
            n_addressed_tests=len(index.addressed_tests(c.criterion_id)),
        )
    active = {
        c.criterion_id
        for c in sa.criteria
        if states[c.criterion_id].state.value != "excluded"
    }
    b_symbols = behavioral_symbols(sa.symbols)
    covered = _covered_symbols(sa, active, cfg.link.link_min_cs)
    coverage = len(covered) / len(b_symbols) if b_symbols else 1.0
    uim = compute_uim(sa.criteria, states, coverage, cfg)

    verdicts: list[CriterionVerdict] = []
    for c in sa.criteria:
        sup = supports[c.criterion_id]
        st = states[c.criterion_id]
        verdicts.append(
            build_criterion_verdict(
                c,
                sup,
                CriterionStateResult(
                    st.criterion_id,
                    st.state,
                    st.reasons + support_reasons(sup, cfg.support)
                    if st.state.value != "excluded"
                    else st.reasons,
                    st.flags,
                ),
            )
        )
    unlinked = tuple(sorted(s.symbol_id for s in b_symbols if s.symbol_id not in covered))
    failed = max(stage_b.ci_failed_cases, failed_case_count(stage_b.cases))
    facts = AnalysisFacts(
        results_received=stage_b.results_received,
        ci_failed_cases=failed,
        tamper=sa.tamper,
        degraded=sa.degraded,
        behavioral_symbols=len(b_symbols),
        flaky_test_ids=stage_b.flaky_test_ids,
    )
    digest = "sha256:" + sha256_hex(
        canonical_json(
            {
                "stage_b": stage_b,
                "config": cfg.digest(),
                "versions": DEFAULT_COMPONENT_VERSIONS,
            }
        )
    )
    verdict = compute_verdict_v2(
        analysis_id=sa.analysis_id,
        head_sha=sa.head_sha,
        revision=revision,
        criteria=verdicts,
        uim=uim,
        facts=facts,
        config=cfg,
        unlinked_symbols=unlinked,
        inputs_digest=digest,
        versions=_versions(sa),
    )
    return PipelineResult(
        verdict=verdict,
        items=norm.items,
        ieg=ieg,
        rejected=tuple(f"{r.code}:{r.ref or ''}" for r in norm.rejected),
        unlinked_symbols=unlinked,
    )


def _versions(sa: StageAInput) -> dict[str, str]:
    out = dict(DEFAULT_COMPONENT_VERSIONS)
    for key in ("symbol_changes", "criterion_symbol_links", "symbol_test_links", "tamper"):
        if sa.algo_versions.get(key):
            out[key] = sa.algo_versions[key]
    return out


# ------------------------------------------------------------------ outputs

_ACTION_TEXT = {
    "no_linked_test": (
        "No test is linked to this criterion. Add a test that checks it, or add a "
        "tests hint in .radius/intent.yml."
    ),
    "weak_assertion": (
        "The linked tests assert too little. Assert the exact expected value."
    ),
    "single_test": (
        "Support is below the threshold. Add another independent case or a "
        "boundary case."
    ),
    "failing_test": "A linked test fails. Fix the code or the test.",
    "needs_typed_evidence": (
        "This criterion needs non-functional evidence that alpha does not collect."
    ),
}


def next_actions(criteria: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fixed-text actions per criterion (same rules as the stored-bundle reader)."""

    out: list[dict[str, Any]] = []
    for c in criteria:
        state, flags = c.get("state"), set(c.get("flags") or [])
        if state in ("proven", "excluded"):
            continue
        if state == "contradicted":
            code = "failing_test"
        elif "needs_typed_evidence" in flags:
            code = "needs_typed_evidence"
        elif "no_linked_test" in flags:
            code = "no_linked_test"
        elif "no_strong_assertion" in flags:
            code = "weak_assertion"
        else:
            code = "single_test"
        out.append(
            {
                "criterion_id": c.get("criterion_id"),
                "code": code,
                "text": _ACTION_TEXT[code],
            }
        )
    return out


def _item_rows(
    verdict: VerdictV2, items: Mapping[str, EvidenceItem]
) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for c in verdict.criteria:
        rows = []
        for q in c.items:
            item = items.get(q.evidence_id)
            outcome = (
                item.outcome.value if item and item.outcome else Outcome.NOT_RUN.value
            )
            rows.append(
                {
                    "evidence_id": q.evidence_id,
                    "test_id": q.path.test_id
                    if q.path
                    else (item.subject_id if item else ""),
                    "outcome": outcome,
                    "a_static": _r(q.a_static),
                    "d_eff": _r(q.d_eff),
                    "i": _r(q.i),
                    "f": _r(q.f),
                    "flaky_f": _r(q.flaky_f),
                    "tamper_penalty": _r(q.tamper_penalty),
                    "q": _r(q.q),
                    "l_cs": _r(q.l_cs),
                    "l_st": _r(q.l_st),
                    "r_ct": _r(q.r_ct),
                    "l": _r(q.l),
                    "term": _r(q.term),
                    "group_symbol": q.group_symbol or None,
                    "rank_in_group": q.rank_in_group,
                    "discount": _r(q.discount),
                    "contribution": _r(q.contribution),
                    "status": q.status,
                }
            )
        out[c.criterion_id] = rows
    return out


def build_payload(
    result: PipelineResult,
    stage_b: StageBInput,
    *,
    mode: str,
    computed_at: str,
    v1: Mapping[str, Any] | None = None,
    dashboard_url: str | None = None,
) -> dict[str, Any]:
    """The served payload (``verdict_v2.schema.json``), as the API and renderer see it."""

    v = result.verdict
    sev: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for t in v.tamper:
        if t.severity in sev:
            sev[t.severity] += 1
    counts = dict.fromkeys(
        ("proven", "weak", "unevidenced", "contradicted", "excluded"), 0
    )
    for c in v.criteria:
        counts[c.state.value] += 1
    rows = _item_rows(v, {i.evidence_id: i for i in result.items})
    criteria = [
        {
            "criterion_id": c.criterion_id,
            "text": c.text,
            "state": c.state.value,
            "S": _r(c.S),
            "S_raw": _r(c.S_raw),
            "weight": c.weight,
            "testability": c.testability,
            "lifecycle": c.lifecycle,
            "flags": [f.value for f in c.flags],
            "reasons": [
                {"code": r.code, "detail": r.detail, "ref": r.ref} for r in c.reasons
            ],
            "best_link": dict(c.best_link) or None,
            "items": rows[c.criterion_id],
        }
        for c in v.criteria
    ]
    reasons = [
        {"code": r.code, "detail": r.detail, "rule_id": r.ref, "ref": r.ref}
        for r in v.reasons
    ]
    return {
        "verdict_version": 2,
        "algo_version": v.algo_version,
        "profile": v.profile,
        "mode": mode,
        "status": STATUS_OK,
        "analysis_id": v.analysis_id,
        "head_sha": v.head_sha,
        "revision": v.revision,
        "computed_at": computed_at,
        "verdict": v.verdict.value,
        "pending": v.pending,
        "reasons": reasons,
        "score": None,
        "score_kind": "none",
        "trust_probability": None,
        "summary": {
            "criteria_total": len(v.criteria),
            **counts,
            "uim": _r(v.uim),
            "intent_coverage": _r(v.intent_coverage),
            "tamper": sev,
            "evidence_basis": v.evidence_basis,
        },
        "criteria": criteria,
        "tamper_findings": [t.to_dict() for t in v.tamper],
        "unlinked_symbols": list(v.unlinked_symbols),
        "next_actions": next_actions(criteria),
        "justification": v.justification,
        "v1": dict(v1) if v1 is not None else None,
        "dashboard_url": dashboard_url,
        "error": None,
        "degraded": list(stage_b.stage_a.degraded),
    }


def build_bundle(
    result: PipelineResult, stage_b: StageBInput, *, max_bytes: int
) -> dict[str, Any]:
    """The stored bundle (``verdict-v2-bundle-1``, written verbatim by the store).

    Holds the whole computation (design 4.1): ``verdict`` is ``VerdictV2.to_dict()``,
    ``stage_a`` lets Stage B re-run after CI without the checkout.
    """

    v = result.verdict
    bundle: dict[str, Any] = {
        "schema": BUNDLE_SCHEMA,
        "analysis_id": v.analysis_id,
        "head_sha": v.head_sha,
        "status": STATUS_OK,
        "inputs_digest": v.inputs_digest,
        "config_digest": v.config_digest,
        "algo_version": v.algo_version,
        "profile": v.profile,
        "verdict": v.to_dict(),
        "evidence_items": [i.to_dict() for i in result.items],
        "stage_a": stage_b.stage_a.to_dict(),
        "stage_b": {
            "uploads": stage_b.uploads,
            "results_received": stage_b.results_received,
            "ci_failed_cases": stage_b.ci_failed_cases,
            "cases": [c.to_dict() for c in stage_b.cases],
            "flaky_test_ids": sorted(stage_b.flaky_test_ids),
        },
        "degraded": list(stage_b.stage_a.degraded),
        "reason_code": v.reasons[0].code if v.reasons else None,
        "error_detail": None,
        "fallback": None,
        "truncated": False,
    }
    return cap_bundle(bundle, max_bytes)


def cap_bundle(bundle: dict[str, Any], max_bytes: int) -> dict[str, Any]:
    """Drop the bulkiest optional parts (evidence, cases) until under the cap."""

    def size() -> int:
        return len(canonical_json(bundle).encode("utf-8"))

    if size() <= max_bytes:
        return bundle
    bundle["truncated"] = True
    bundle["evidence_items"] = []
    if size() > max_bytes:
        bundle["stage_b"]["cases"] = []
    return bundle


def build_error_bundle(
    *,
    analysis_id: str,
    head_sha: str | None,
    code: str,
    status: str = STATUS_ERROR,
    config: VerdictV2Config | None = None,
) -> dict[str, Any] | None:
    """Bundle of a failed/skipped run (v1 stays published); ``None`` without a head sha.

    ``code`` is an exception class or reason code, never a message (no raw text).
    The digest is stable for equal (analysis, head, code), so a repeated failure is
    an idempotent no-op in the store.
    """

    cfg = config or VerdictV2Config()
    if head_sha is None:
        return None
    digest = "sha256:" + sha256_hex(
        canonical_json(
            {
                "analysis": analysis_id,
                "head": head_sha,
                "code": code,
                "algo": ALGO_VERSION,
            }
        )
    )
    return {
        "schema": BUNDLE_SCHEMA,
        "analysis_id": analysis_id,
        "head_sha": head_sha,
        "status": status,
        "inputs_digest": digest,
        "config_digest": cfg.digest(),
        "algo_version": ALGO_VERSION,
        "profile": cfg.profile,
        "verdict": None,
        "reason_code": code[:48],
        "error_detail": None,
        "fallback": "v1",
        "truncated": False,
    }


# ------------------------------------------------------------------ Stage B port


@dataclass(frozen=True, slots=True)
class Scored:
    result: PipelineResult
    bundle: dict[str, Any]
    payload: dict[str, Any]


@dataclass(slots=True)
class ScoringPipeline:
    """``StageBScorer`` implementation: ``score(stage_b) -> bundle dict``."""

    config: VerdictV2Config = field(default_factory=VerdictV2Config)
    mode: str = "shadow"
    revision: int = 1
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)  # noqa: E731
    v1: Mapping[str, Any] | None = None
    dashboard_url: str | None = None

    def score_full(self, stage_b: StageBInput) -> Scored:
        computed_at = self.clock().strftime("%Y-%m-%dT%H:%M:%SZ")
        result = compute_pipeline(
            stage_b,
            config=self.config,
            revision=self.revision,
            collected_at=computed_at,
        )
        return Scored(
            result,
            build_bundle(result, stage_b, max_bytes=self.config.rules.max_bundle_bytes),
            build_payload(
                result,
                stage_b,
                mode=self.mode,
                computed_at=computed_at,
                v1=self.v1,
                dashboard_url=self.dashboard_url,
            ),
        )

    def score(self, stage_b: StageBInput) -> dict[str, Any]:
        return self.score_full(stage_b).bundle


# ------------------------------------------------------------------ best-effort hook


@dataclass(frozen=True, slots=True)
class RunReport:
    """Outcome of one best-effort run; counts and ids only."""

    status: str
    reason_code: str | None = None
    verdict: str | None = None
    persisted: bool = False
    duration_ms: int = 0
    bundle: dict[str, Any] | None = None
    payload: dict[str, Any] | None = None


def run_verdict_v2_best_effort(
    *,
    mode: VerdictV2Mode,
    analysis_id: UUID,
    command: Any,
    collector: Any,
    outcomes: Any,
    store: Any | None = None,
    organization_id: UUID | None = None,
    config: VerdictV2Config | None = None,
    revision: int = 1,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    v1: Mapping[str, Any] | None = None,
) -> RunReport:
    """Collect (Stage A), score (Stage B) and persist; never raises.

    * ``mode == OFF``: returns ``skipped/flag_off`` immediately, touching nothing.
    * any failure: ``error`` with the exception class (or ``StageAError`` reason
      code) as ``reason_code``; no message and no text is kept. An error bundle is
      persisted when a store is available and the head sha is known; v1 stays the
      published verdict.
    """

    if mode is VerdictV2Mode.OFF:
        return RunReport(STATUS_SKIPPED, "flag_off")
    started = time.monotonic()
    cfg = config or VerdictV2Config()
    aid = str(analysis_id)
    head_sha: str | None = None
    scored: Scored | None = None
    try:
        stage_a = collector.collect(analysis_id, command)
        head_sha = stage_a.head_sha
        facts = outcomes.load(analysis_id, stage_a)
        stage_b = build_stage_b(
            stage_a,
            cases=facts.cases,
            uploads=facts.uploads,
            flaky_test_ids=facts.flaky_test_ids,
            flaky_scores=facts.flaky_scores,
        )
        scored = ScoringPipeline(
            config=cfg, mode=mode.value, revision=revision, clock=clock, v1=v1
        ).score_full(stage_b)
        status, code = STATUS_OK, None
        bundle: dict[str, Any] | None = scored.bundle
    except Exception as exc:  # noqa: BLE001 - v1 must stay unaffected
        code = str(getattr(exc, "reason_code", None) or type(exc).__name__)
        status = STATUS_ERROR
        bundle = build_error_bundle(
            analysis_id=aid, head_sha=head_sha, code=code, config=cfg
        )
    persisted = False
    if store is not None and organization_id is not None and bundle is not None:
        try:
            persisted = bool(store.save(organization_id, analysis_id, bundle))
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(
                "Verdict v2 persistence failed",
                extra={"analysis_id": aid, "reason_code": type(exc).__name__},
            )
            if status == STATUS_OK:
                status, code = STATUS_ERROR, "store_failed"
    duration_ms = int((time.monotonic() - started) * 1000)
    ok = scored is not None and status == STATUS_OK
    verdict = scored.payload["verdict"] if scored is not None and ok else None
    LOGGER.info(
        "Verdict v2 computed",
        extra={
            "analysis_id": aid,
            "mode": mode.value,
            "status": status,
            "reason_code": code,
            "verdict": verdict,
            "persisted": persisted,
            "duration_ms": duration_ms,
            "criteria": len(scored.payload["criteria"]) if scored is not None else 0,
        },
    )
    return RunReport(
        status=status,
        reason_code=code,
        verdict=verdict,
        persisted=persisted,
        duration_ms=duration_ms,
        bundle=bundle,
        payload=scored.payload if scored is not None and ok else None,
    )


def run_verdict_v2_for_analysis(
    *,
    session_factory: Callable[[], Any],
    analysis_id: UUID,
    command: Any,
    settings: Any,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> RunReport:
    """Runner entry point: build the SQL-backed ports and run best-effort.

    Never raises. With the flag off nothing is imported or touched. The store is the
    VS-06/07 ``SqlVerdictStore`` when present in this checkout; otherwise the bundle
    is computed and logged but not persisted (``persisted=False``).
    """

    mode = getattr(settings, "verdict_v2_mode", VerdictV2Mode.OFF)
    if mode is VerdictV2Mode.OFF:
        return RunReport(STATUS_SKIPPED, "flag_off")
    try:
        from radius_worker.verdict_v2.collect import VerdictStageACollector
        from radius_worker.verdict_v2.sources import SqlIntentSource, SqlOutcomeSource

        intent = SqlIntentSource(session_factory)
        store = _sql_store(session_factory, mode)
        return run_verdict_v2_best_effort(
            mode=mode,
            analysis_id=analysis_id,
            command=command,
            collector=VerdictStageACollector(intent),
            outcomes=SqlOutcomeSource(session_factory),
            store=store,
            organization_id=intent.organization_id(analysis_id) if store else None,
            clock=clock,
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning(
            "Verdict v2 could not start",
            extra={"analysis_id": str(analysis_id), "reason_code": type(exc).__name__},
        )
        return RunReport(STATUS_ERROR, type(exc).__name__)


def _sql_store(session_factory: Callable[[], Any], mode: VerdictV2Mode) -> Any | None:
    try:
        from radius_worker.verdict_v2.store import SqlVerdictStore
    except ImportError:  # the store module is owned by another task
        return None
    return SqlVerdictStore(session_factory, mode)


@dataclass(slots=True)
class StageBRecomputer:
    """``requests.Recomputer``: re-run Stage B from the stored Stage A after CI results.

    No clone and no producers: ``store.latest_stage_a`` plus the CI uploads read with
    the caller's session. Returns True when the newest stored revision changed.
    """

    store: Any
    mode: VerdictV2Mode
    config: VerdictV2Config = field(default_factory=VerdictV2Config)
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)  # noqa: E731

    def recompute(
        self, session: Any, organization_id: UUID, analysis_id: UUID
    ) -> bool:
        from radius_testing.infrastructure.sqlalchemy_store import SqlAlchemyTestStore

        from radius_worker.verdict_v2.sources import outcomes_from_uploads

        stage_a = self.store.latest_stage_a(organization_id, analysis_id)
        if stage_a is None:
            return False
        facts = outcomes_from_uploads(
            SqlAlchemyTestStore(session).list_result_uploads(analysis_id), stage_a
        )
        stage_b = build_stage_b(
            stage_a,
            cases=facts.cases,
            uploads=facts.uploads,
            flaky_test_ids=facts.flaky_test_ids,
            flaky_scores=facts.flaky_scores,
        )
        bundle = ScoringPipeline(
            config=self.config, mode=self.mode.value, clock=self.clock
        ).score(stage_b)
        return bool(self.store.save(organization_id, analysis_id, bundle))
