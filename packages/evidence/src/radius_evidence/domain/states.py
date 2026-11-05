"""Per-criterion states, flags, UIM and intent coverage (design 3.9), VD-02.

State table (first match wins), thresholds from ``VerdictV2Config``:

    1  lifecycle rejected/orphaned, or testability subjective_or_vague /
       untestable_external                                     -> excluded
    2  an attached item has outcome FAILED or ERROR            -> contradicted
    3  testability non_functional_measurable                   -> unevidenced (needs_typed_evidence)
    4  S >= tau_support and a strong item exists               -> proven
    5  S >= tau_support and no strong item                     -> weak (no_strong_assertion)
    6  tau_weak <= S < tau_support                              -> weak
    7  otherwise                                                -> unevidenced (no_linked_test if E(c) empty
                                                                  and no ADDRESSED_BY edge exists)

UIM (design 3.9; the alpha counts a non-excluded criterion as unproven when
its state is not ``proven``, which equals ``S(c) < tau`` except when
``S >= tau`` without a strong item or when the criterion is contradicted):

    C*  = criteria whose state is not "excluded"
    UIM = SUM_{c in C*} w_c * [c unproven] / SUM_{c in C*} w_c      (0.0 when C* is empty)

Intent coverage:

    B = changed symbols with is_behavioral and not is_test and not (is_pseudo and kind == "file")
    covered(s) = exists a non-excluded criterion with an IMPLEMENTED_BY edge to s with weight >= link_min_cs
                 OR s is in the same file as a covered non-pseudo symbol
    intent_coverage = |{s in B : covered(s)}| / |B|        (1.0 when B is empty)
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from radius_evidence.domain.config import VerdictV2Config
from radius_evidence.domain.enums import Flag, SupportState
from radius_evidence.domain.inputs import (
    CriterionInput,
    CriterionSymbolEdgeInput,
    SymbolInput,
)
from radius_evidence.domain.model import Reason
from radius_evidence.domain.quality import (
    FAILING_STATUSES,
    GATE_OUTCOME_PREFIX,
    STATUS_COUNTED,
    EvidenceQuality,
    gated,
)
from radius_evidence.domain.serialization import Serializable
from radius_evidence.domain.support import SupportResult
from radius_evidence.domain.versions import PROFILE_ALPHA_STATIC

#: Testability values (current and legacy spellings) that exclude a criterion.
EXCLUDING_TESTABILITY: frozenset[str] = frozenset(
    {"subjective_or_vague", "vague", "untestable_external"}
)
NON_FUNCTIONAL_TESTABILITY: frozenset[str] = frozenset(
    {"non_functional_measurable", "non_functional"}
)
EXCLUDING_LIFECYCLE: frozenset[str] = frozenset({"rejected", "orphaned"})

_FLAKY_STATUS = gated(GATE_OUTCOME_PREFIX + "flaky")
_EPS = 1e-12


@dataclass(frozen=True, slots=True)
class CriterionStateResult(Serializable):
    criterion_id: str
    state: SupportState
    reasons: tuple[Reason, ...] = ()
    flags: tuple[Flag, ...] = ()


@dataclass(frozen=True, slots=True)
class UimResult(Serializable):
    """UIM = sum(w_c * [S(c) < tau]) / sum(w_c) over non-excluded criteria."""

    uim: float
    numerator: float
    denominator: float
    intent_coverage: float
    unproven_criterion_ids: tuple[str, ...] = ()
    excluded_criterion_ids: tuple[str, ...] = ()
    profile: str = PROFILE_ALPHA_STATIC


def _ge(value: float, bound: float) -> bool:
    """``value >= bound`` tolerant to float noise (1e-12)."""

    return value >= bound - _EPS


def _is_attached(row: EvidenceQuality) -> bool:
    return row.r_ct > 0.0 and row.l_st > 0.0 and row.l_cs > 0.0


def evaluate_criterion(
    criterion: CriterionInput,
    support: SupportResult,
    config: VerdictV2Config | None = None,
    *,
    tampered: bool = False,
    results_received: bool = True,
    n_addressed_tests: int | None = None,
) -> CriterionStateResult:
    """State, reason codes and flags of one criterion.

    ``tampered`` is OR-ed with the tamper penalty of attached rows (use it for
    findings attached to a linked symbol). ``n_addressed_tests`` is the number
    of ADDRESSED_BY edges of the criterion; when ``None`` it is the number of
    rows with ``r_ct > 0``.
    """

    cfg = config if config is not None else VerdictV2Config()
    sup = cfg.support
    cid = criterion.criterion_id
    if criterion.lifecycle in EXCLUDING_LIFECYCLE:
        return CriterionStateResult(
            cid,
            SupportState.EXCLUDED,
            (Reason("rejected", f"criterion lifecycle is {criterion.lifecycle}"),),
        )
    if criterion.testability in EXCLUDING_TESTABILITY:
        return CriterionStateResult(
            cid,
            SupportState.EXCLUDED,
            (Reason("not_testable", f"testability is {criterion.testability}"),),
        )

    rows = [r for r in support.items if r.criterion_id == cid]
    attached = [r for r in rows if _is_attached(r)]
    flags: set[Flag] = {Flag.STATIC_ONLY}
    if tampered or any(r.tamper_penalty > 0.0 for r in attached):
        flags.add(Flag.TAMPERED)
    if any(r.flaky_f < 1.0 or r.status == _FLAKY_STATUS for r in attached):
        flags.add(Flag.FLAKY_EVIDENCE)
    if any(r.f <= 0.0 for r in attached):
        flags.add(Flag.STALE_EVIDENCE)
    if criterion.lifecycle == "proposed":
        flags.add(Flag.UNCONFIRMED)
    if not results_received:
        flags.add(Flag.PENDING_RESULTS)

    failing = sorted(r.evidence_id for r in attached if r.status in FAILING_STATUSES)
    reasons: list[Reason] = []
    if failing:
        state = SupportState.CONTRADICTED
        reasons.append(
            Reason(
                "failing_linked_test",
                f"{len(failing)} linked test(s) failed",
                failing[0],
                refs=tuple(failing) if len(failing) > 1 else None,
            )
        )
    elif criterion.testability in NON_FUNCTIONAL_TESTABILITY:
        state = SupportState.UNEVIDENCED
        flags.add(Flag.NEEDS_TYPED_EVIDENCE)
        reasons.append(
            Reason(
                "needs_typed_evidence", "non-functional criteria need typed evidence"
            )
        )
    elif _ge(support.S, cfg.support.tau_support) and support.has_strong_item:
        state = SupportState.PROVEN
        reasons.append(
            Reason(
                "strong_support",
                f"S={support.S:.3f} >= tau_support={sup.tau_support:g}",
            )
        )
        best_l_cs = max(
            (r.l_cs for r in support.items if r.status == STATUS_COUNTED), default=0.0
        )
        if best_l_cs < cfg.rules.link_review_min:
            flags.add(Flag.LOW_LINK_CONFIDENCE)
    elif _ge(support.S, sup.tau_support):
        state = SupportState.WEAK
        flags.add(Flag.NO_STRONG_ASSERTION)
        reasons.append(
            Reason(
                "no_strong_assertion",
                f"S={support.S:.3f} reaches tau_support but no item has a_static >= {sup.strong_min:g}",
            )
        )
    elif _ge(support.S, sup.tau_weak):
        state = SupportState.WEAK
        reasons.append(
            Reason(
                "partial_support",
                f"{sup.tau_weak:g} <= S={support.S:.3f} < tau_support={sup.tau_support:g}",
            )
        )
    else:
        state = SupportState.UNEVIDENCED
        reasons.append(
            Reason(
                "insufficient_support", f"S={support.S:.3f} < tau_weak={sup.tau_weak:g}"
            )
        )
        n_edges = (
            n_addressed_tests
            if n_addressed_tests is not None
            else sum(1 for r in rows if r.r_ct > 0.0)
        )
        if support.n_counted == 0 and n_edges == 0:
            flags.add(Flag.NO_LINKED_TEST)
            reasons.append(
                Reason("no_linked_test", "no test is linked to this criterion")
            )
    return CriterionStateResult(cid, state, tuple(reasons), tuple(sorted(flags)))


def intent_coverage(
    symbols: Iterable[SymbolInput],
    edges: Iterable[CriterionSymbolEdgeInput],
    covering_criterion_ids: Iterable[str],
    link_min_cs: float,
) -> float:
    """Share of behavioral changed symbols accounted for by a non-excluded criterion."""

    syms = list(symbols)
    active = set(covering_criterion_ids)
    linked = {
        e.symbol_id
        for e in edges
        if e.criterion_id in active and _ge(e.score, link_min_cs)
    }
    behavioral = [
        s
        for s in syms
        if s.is_behavioral and not s.is_test and not (s.is_pseudo and s.kind == "file")
    ]
    if not behavioral:
        return 1.0
    covered_files = {s.path for s in syms if s.symbol_id in linked and not s.is_pseudo}
    covered = sum(
        1 for s in behavioral if s.symbol_id in linked or s.path in covered_files
    )
    return covered / len(behavioral)


def compute_uim(
    criteria: Iterable[CriterionInput],
    results: Mapping[str, CriterionStateResult],
    coverage: float,
    config: VerdictV2Config | None = None,
) -> UimResult:
    """Unproven intent mass over non-excluded criteria (see module docstring)."""

    cfg = config if config is not None else VerdictV2Config()
    numerator = 0.0
    denominator = 0.0
    unproven: list[str] = []
    excluded: list[str] = []
    for c in sorted(criteria, key=lambda c: c.criterion_id):
        state = results[c.criterion_id].state
        if state is SupportState.EXCLUDED:
            excluded.append(c.criterion_id)
            continue
        denominator += c.weight
        if state is not SupportState.PROVEN:
            numerator += c.weight
            unproven.append(c.criterion_id)
    return UimResult(
        uim=numerator / denominator if denominator > 0.0 else 0.0,
        numerator=numerator,
        denominator=denominator,
        intent_coverage=coverage,
        unproven_criterion_ids=tuple(unproven),
        excluded_criterion_ids=tuple(excluded),
        profile=cfg.profile,
    )
