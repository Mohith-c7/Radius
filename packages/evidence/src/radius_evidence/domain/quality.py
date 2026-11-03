"""Evidence quality: contract (design 3.5) and the EV-08 ``q(e, c)`` combiner.

Formulas (verbatim, design 3.5):

    l_cs   = 0 if w(IMPLEMENTED_BY) < link_min_cs else min(1, w / link_sat_cs)
    l_st   = w(EXERCISED_BY) if w >= min_test_link else 0
    r_ct   = w(ADDRESSED_BY)
    l      = l_cs * l_st * r_ct
    d_eff  = min(cap_static, a_static)            (unmeasured: the static cap)
    d_eff  = lcb_wilson(killed, n)                (measured by mutation, contract 5; see
                                                   ``MutationMeasure`` and ``combine_quality``)
    flaky_f = 0 if flagged by rerun; 1 - min(flaky_discount_max, score) if a score is known; else 1
    tamper_p = 1 - PROD_k (1 - penalty(severity_k))
    q(e,c) = d_eff * i * f * flaky_f * (1 - tamper_p)
    term   = lambda_kind * q * l           (0 unless the item is usable)

Everything here is a pure, deterministic function of already-computed factors.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from radius_evidence.domain.config import LinkMapping, QualityConfig
from radius_evidence.domain.enums import Outcome
from radius_evidence.domain.model import EvidenceItem, FlakyInfo, Reason
from radius_evidence.domain.serialization import Serializable
from radius_evidence.domain.versions import (
    EVIDENCE_QUALITY_MUTATION_VERSION,
    EVIDENCE_QUALITY_VERSION,
)


@dataclass(frozen=True, slots=True)
class ChainRef(Serializable):
    """The criterion -> symbol -> test path an item was credited through."""

    symbol_id: str
    test_id: str
    l_cs: float = 0.0
    l_st: float = 0.0
    r_ct: float = 0.0


@dataclass(frozen=True, slots=True)
class EvidenceQuality(Serializable):
    """One row per (evidence, criterion), including unusable ones (for ablations).

    ``status`` is ``counted`` or ``gated:<reason>``. ``l`` is the design symbol
    for link strength ``l_cs * l_st * r_ct``.
    """

    evidence_id: str
    criterion_id: str
    a_static: float
    d_eff: float
    cap_static: float
    i: float
    f: float
    flaky_f: float
    tamper_penalty: float
    q: float
    l_cs: float
    l_st: float
    r_ct: float
    l: float  # noqa: E741
    term: float
    status: str
    d_mut: float | None = None  # no mutation data in the alpha
    lambda_kind: float = 1.0
    group_symbol: str | None = None
    rank_in_group: int | None = None
    discount: float | None = None
    contribution: float | None = None
    path: ChainRef | None = None
    algo_version: str = EVIDENCE_QUALITY_VERSION
    #: Contract 5. ``d_mut`` above is the point estimate; ``d_eff`` used its Wilson lower
    #: bound when ``basis == "mutation"``.
    d_mut_lcb: float | None = None
    mutation_n: int | None = None
    mutation_killed: int | None = None
    #: ``static`` (assertion cap) or ``mutation`` (d_eff measured).
    basis: str = "static"


#: Alias used in the design discussion.
QualityBreakdown = EvidenceQuality


# --------------------------------------------------------------------------
# EV-08
# --------------------------------------------------------------------------

#: ``EvidenceQuality.status`` of an item that contributes to ``S(c)``.
STATUS_COUNTED = "counted"
_GATED_PREFIX = "gated:"
#: Gate reasons, in the order they are checked (first match wins).
GATE_NO_CRITERION_TEST_EDGE = "no_criterion_test_edge"  # r_ct == 0
GATE_TEST_LINK_BELOW_MIN = "test_link_below_min"  # w(EXERCISED_BY) < min_test_link
GATE_CRITERION_LINK_BELOW_MIN = (
    "criterion_link_below_min"  # w(IMPLEMENTED_BY) < link_min_cs
)
GATE_OUTCOME_PREFIX = "outcome_"  # outcome_failed, outcome_error, outcome_skipped, ...
GATE_ZERO_QUALITY = "zero_quality"  # q == 0 (tamper, stale, flaky rerun, a == 0)

#: Statuses meaning "the attached test ran and failed" (state ``contradicted``).
FAILING_STATUSES: frozenset[str] = frozenset(
    {
        _GATED_PREFIX + GATE_OUTCOME_PREFIX + Outcome.FAILED.value,
        _GATED_PREFIX + GATE_OUTCOME_PREFIX + Outcome.ERROR.value,
    }
)


def gated(reason: str) -> str:
    """Return the ``status`` string for an item gated for ``reason``."""

    return _GATED_PREFIX + reason


def _unit(value: float, name: str) -> float:
    if not 0.0 <= value <= 1.0:
        msg = f"{name} must be within [0, 1], got {value!r}"
        raise ValueError(msg)
    return value


@dataclass(frozen=True, slots=True)
class LinkStrength(Serializable):
    """Link strength of one path ``c -> s -> t`` (design 3.5)."""

    l_cs: float
    l_st: float
    r_ct: float
    l: float  # noqa: E741  (design symbol: l_cs * l_st * r_ct)


@dataclass(frozen=True, slots=True)
class MutationMeasure(Serializable):
    """Measured detection power of one test for one criterion (contract 5).

    ``n`` is the number of decided, non-equivalent mutants of the changed symbols linked
    to the test; ``d_mut = killed / n`` and ``lcb`` is the Wilson lower bound (95%).
    ``measured`` is False when ``n`` is below the minimum sample: the static cap applies.
    """

    killed: int
    n: int
    d_mut: float | None
    lcb: float | None
    measured: bool
    min_decided: int = 5


@dataclass(frozen=True, slots=True)
class QualityFactors(Serializable):
    """Every component of ``q(e, c)`` with reason codes (audit and ablations)."""

    a_static: float
    cap_static: float
    d_eff: float
    i: float
    f: float
    flaky_f: float
    tamper_penalty: float
    q: float
    reasons: tuple[Reason, ...] = ()
    basis: str = "static"


def criterion_link_strength(weight: float, mapping: LinkMapping) -> float:
    """``l_cs``: 0 below ``link_min_cs``, else ``min(1, w / link_sat_cs)``."""

    if weight < mapping.link_min_cs:
        return 0.0
    return min(1.0, weight / mapping.link_sat_cs)


def exercise_link_strength(weight: float, mapping: LinkMapping) -> float:
    """``l_st``: the raw weight when ``>= min_test_link``, else 0."""

    return weight if weight >= mapping.min_test_link else 0.0


def link_strength(
    w_cs: float, w_st: float, r_ct: float, mapping: LinkMapping
) -> LinkStrength:
    """``l(c, e) = l_cs * l_st * r_ct`` for the edge weights of one path."""

    l_cs = criterion_link_strength(w_cs, mapping)
    l_st = exercise_link_strength(w_st, mapping)
    r = _unit(r_ct, "r_ct")
    return LinkStrength(l_cs=l_cs, l_st=l_st, r_ct=r, l=l_cs * l_st * r)


def tamper_penalty(severities: Iterable[str], config: QualityConfig) -> float:
    """``1 - PROD_k (1 - penalty(severity_k))``; an unknown label raises."""

    keep = 1.0
    for label in severities:
        key = label.lower()
        if key not in config.tamper_penalty:
            msg = f"unknown tamper severity {label!r}"
            raise ValueError(msg)
        keep *= 1.0 - config.tamper_penalty[key]
    return 1.0 - keep


def flaky_factor(flaky: FlakyInfo, config: QualityConfig) -> float:
    """0 for a rerun-flagged flaky test; ``1 - min(max, score)`` with a score; else 1."""

    if flaky.flagged and flaky.source == "rerun":
        return 0.0
    if flaky.score is not None:
        return 1.0 - min(config.flaky_discount_max, max(0.0, flaky.score))
    return 1.0


def combine_quality(
    a_static: float,
    *,
    independence: float,
    freshness: float,
    flaky_f: float,
    tamper_p: float,
    config: QualityConfig,
    mutation: MutationMeasure | None = None,
) -> QualityFactors:
    """``q = d_eff * i * f * flaky_f * (1 - tamper_p)``.

    ``d_eff = min(cap_static, a_static)`` unless ``mutation`` is a measured
    :class:`MutationMeasure`, in which case ``d_eff`` is its Wilson lower bound (it may
    be above or below the static value; unmeasured never gets better than static). A
    test with ``a_static == 0`` stays at 0 even when measured: it has no assertion, so a
    "kill" can only be a crash (open decision D4, conservative guard).

    Reason codes: ``d_from_mutation``, ``mutation_insufficient_sample``, ``mutation_ignored_zero_a``, ``zero_a_static``, ``capped_static``, ``independence_discount``,
    ``stale_evidence``, ``flaky_rerun`` / ``flaky_history``, ``tamper_nullified``
    / ``tamper_penalty``.
    """

    a = _unit(a_static, "a_static")
    i = _unit(independence, "independence")
    f = _unit(freshness, "freshness")
    fl = _unit(flaky_f, "flaky_f")
    tp = _unit(tamper_p, "tamper_p")
    d_eff = min(config.cap_static, a)
    basis = "static"
    reasons: list[Reason] = []
    if mutation is not None:
        if not mutation.measured or mutation.lcb is None:
            reasons.append(
                Reason(
                    "mutation_insufficient_sample",
                    f"{mutation.n} decided mutant(s), fewer than {mutation.min_decided}: "
                    "static cap kept",
                )
            )
        elif a == 0.0:
            reasons.append(
                Reason(
                    "mutation_ignored_zero_a",
                    "no assertion: a kill could only be a crash, static value kept",
                )
            )
        else:
            d_eff = _unit(mutation.lcb, "mutation lcb")
            basis = "mutation"
            reasons.append(
                Reason(
                    "d_from_mutation",
                    f"{mutation.killed}/{mutation.n} mutants killed; Wilson lower bound "
                    f"{d_eff:.3f} replaces the static cap",
                )
            )
    q = d_eff * i * f * fl * (1.0 - tp)
    if a == 0.0:
        reasons.append(Reason("zero_a_static", "assertion strength is 0"))
    if basis == "static" and a > config.cap_static:
        reasons.append(
            Reason("capped_static", f"a_static {a:g} capped at {config.cap_static:g}")
        )
    if i < 1.0:
        reasons.append(Reason("independence_discount", f"independence factor {i:g}"))
    if f == 0.0:
        reasons.append(Reason("stale_evidence", "bound to another head SHA"))
    if fl == 0.0:
        reasons.append(Reason("flaky_rerun", "failed then passed on rerun"))
    elif fl < 1.0:
        reasons.append(Reason("flaky_history", f"flaky factor {fl:g}"))
    if tp >= 1.0:
        reasons.append(Reason("tamper_nullified", "tamper penalty 1.0"))
    elif tp > 0.0:
        reasons.append(Reason("tamper_penalty", f"tamper penalty {tp:g}"))
    return QualityFactors(
        a_static=a,
        cap_static=config.cap_static,
        d_eff=d_eff,
        i=i,
        f=f,
        flaky_f=fl,
        tamper_penalty=tp,
        q=q,
        reasons=tuple(reasons),
        basis=basis,
    )


def item_quality(
    item: EvidenceItem,
    a_static: float,
    tamper_severities: Iterable[str],
    config: QualityConfig,
    mutation: MutationMeasure | None = None,
) -> QualityFactors:
    """``q`` for an item, reading its independence, freshness and flaky info."""

    return combine_quality(
        a_static,
        independence=item.independence.factor,
        freshness=item.freshness.f,
        flaky_f=flaky_factor(item.flaky, config),
        tamper_p=tamper_penalty(tamper_severities, config),
        config=config,
        mutation=mutation,
    )


def evidence_quality_row(
    item: EvidenceItem,
    criterion_id: str,
    *,
    a_static: float,
    w_cs: float,
    w_st: float,
    r_ct: float,
    symbol_id: str,
    tamper_severities: Iterable[str] = (),
    quality: QualityConfig | None = None,
    mapping: LinkMapping | None = None,
    mutation: MutationMeasure | None = None,
) -> EvidenceQuality:
    """Build the ``EvidenceQuality`` row of (item, criterion) along its best path.

    Gates are checked in this order: no criterion-test edge, test link below
    minimum, criterion link below minimum, outcome other than PASSED, ``q == 0``
    (or a zero ``lambda_kind``). A FAILED/ERROR item that clears the link gates
    keeps status ``gated:outcome_failed`` / ``gated:outcome_error`` whatever its
    ``q`` (a failure contradicts the criterion regardless of authorship).
    ``term`` is 0 unless the status is ``counted``. ``group_symbol`` is the path
    symbol; rank, discount and contribution are filled by
    ``support.compute_support``.
    """

    qcfg = quality if quality is not None else QualityConfig()
    lmap = mapping if mapping is not None else LinkMapping()
    link = link_strength(w_cs, w_st, r_ct, lmap)
    factors = item_quality(item, a_static, tamper_severities, qcfg, mutation)
    lam = qcfg.lambda_kind.get(item.kind.value, 0.0)
    if link.r_ct <= 0.0:
        status = gated(GATE_NO_CRITERION_TEST_EDGE)
    elif link.l_st <= 0.0:
        status = gated(GATE_TEST_LINK_BELOW_MIN)
    elif link.l_cs <= 0.0:
        status = gated(GATE_CRITERION_LINK_BELOW_MIN)
    elif item.outcome != Outcome.PASSED:
        label = item.outcome.value if item.outcome is not None else "none"
        status = gated(GATE_OUTCOME_PREFIX + label)
    elif factors.q <= 0.0 or lam <= 0.0:
        status = gated(GATE_ZERO_QUALITY)
    else:
        status = STATUS_COUNTED
    term = lam * factors.q * link.l if status == STATUS_COUNTED else 0.0
    return EvidenceQuality(
        evidence_id=item.evidence_id,
        criterion_id=criterion_id,
        a_static=factors.a_static,
        d_eff=factors.d_eff,
        cap_static=factors.cap_static,
        i=factors.i,
        f=factors.f,
        flaky_f=factors.flaky_f,
        tamper_penalty=factors.tamper_penalty,
        q=factors.q,
        l_cs=link.l_cs,
        l_st=link.l_st,
        r_ct=link.r_ct,
        l=link.l,
        term=term,
        status=status,
        lambda_kind=lam,
        d_mut=mutation.d_mut if mutation is not None and mutation.measured else None,
        d_mut_lcb=mutation.lcb if mutation is not None and mutation.measured else None,
        mutation_n=mutation.n if mutation is not None else None,
        mutation_killed=mutation.killed if mutation is not None else None,
        basis=factors.basis,
        algo_version=(
            EVIDENCE_QUALITY_MUTATION_VERSION
            if factors.basis == "mutation"
            else EVIDENCE_QUALITY_VERSION
        ),
        group_symbol=symbol_id,
        path=ChainRef(
            symbol_id=symbol_id,
            test_id=item.subject_id,
            l_cs=link.l_cs,
            l_st=link.l_st,
            r_ct=link.r_ct,
        ),
    )
