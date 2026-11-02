"""Chain and per-criterion link confidence (LK-06, ``link-chain-v1``).

Inputs are plain data: the combined criterion -> symbol links (LK-02
``LinkSet.links``), symbol -> test edges (LK-03, adapted with
``SymbolTestEdge.from_object``), optional symbol facts, test outcomes and
author test hints. Pure, deterministic, offline, bounded.

Chain score for ``criterion c -> symbol s -> test t`` (all numbers in [0, 1])::

    a   = c2s score (LK-02 combined)          e = max explicit-linker reason score
    b   = s2t score (LK-03 combined)
    h1  = max(a, EXPLICIT_DOMINANCE * e)                 explicit hints dominate hop 1
    h2  = max(b, DYNAMIC_FLOOR)            if dynamic coverage evidence   (dominates hop 2)
        = b * LOW_CONFIDENCE_FACTOR        if the link is flagged low confidence
        = b                                otherwise
    base  = h1 * h2                                      noisy-AND: both hops must be strong
    agree = min(1, (L1 - 1 + L2 - 1) / AGREE_FULL)       L1/L2 = independent linkers per hop
    chain = 1 - (1 - base) * (1 - AGREE_WEIGHT * agree)  only if min(h1, h2) >= AGREE_MIN
    chain = min(chain, CAP_STRONG if explicit(e >= 0.5) and dynamic else CAP_OTHER)
    chain = chain * status_factor(test)                  failed/flaky/skipped discounted
    chains with min(h1, h2) < HOP_FLOOR or chain < MIN_CHAIN do not exist

Per criterion, ``specificity(t) = 1 / (1 + LAMBDA * max(0, n_t - N_FREE))`` (floored)
where ``n_t`` counts criteria with a chain through test ``t`` scoring >=
``SPEC_MIN``; ``support = chain * specificity``. The best support per test
(a test counted once however many symbols it reaches) is sorted descending and::

    confidence = min(cap, 1 - prod_i (1 - DECAY**i * support_i))   i = 0.. (top AGG_TOP_N tests)

Monotone: raising any input score, adding a chain or a linker never lowers a chain
or the criterion confidence (the descending sort plus decaying weights keep the
terms pointwise larger). The only non-monotone input is specificity, a cross-
criterion effect that is part of the corpus, not of one criterion's evidence.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, NamedTuple

from radius_linking.domain import (
    COMBINED,
    LINKER_CHANGE_PRIOR,
    LINKER_EXPLICIT,
    LINKER_RERANK,
    Link,
    Reason,
    SymbolDoc,
    clamp01,
)
from radius_linking.domain.calibration import (
    TARGET_CHAIN,
    TARGET_CRITERION,
    CalibrationArtifact,
    CalibrationError,
)
from radius_linking.domain.chain import (
    CHAIN_ALGO_VERSION,
    LINKER_CHAIN,
    SCORE_KIND_CALIBRATED,
    SCORE_KIND_UNCALIBRATED,
    STATUS_FAILED,
    STATUS_FLAKY,
    STATUS_PASSED,
    STATUS_SKIPPED,
    STATUS_UNKNOWN,
    UNLINKED_NO_SYMBOL,
    UNLINKED_NON_BEHAVIORAL,
    UNLINKED_TESTS_WITHOUT_SYMBOL,
    UNLINKED_UNTESTED,
    UNLINKED_WEAK,
    ChainLink,
    CriterionSupportLinks,
    SupportLinkSet,
    SymbolTestEdge,
)

# Reason codes (``Reason.kind``; ``Reason.linker`` is always "chain").
R_HOP1 = "hop1_criterion_symbol"
R_HOP1_EXPLICIT = "hop1_explicit_dominance"
R_HOP2 = "hop2_symbol_test"
R_HOP2_DYNAMIC = "hop2_dynamic_dominance"
R_HOP2_LOW_CONF = "hop2_low_confidence"
R_AND = "chain_noisy_and"
R_AGREEMENT = "agreement_bonus"
R_CAP = "chain_cap"
R_STATUS = "test_status_discount"
R_SPECIFICITY = "specificity_penalty"
R_AGG_TERM = "aggregate_term"
R_AGG_CAP = "aggregate_cap"
R_EXCLUDED = "excluded_non_behavioral"
R_UNLINKED = "unlinked"
R_UNTESTED_SYMBOL = "untested_symbol"
R_HINTED_TEST = "hinted_test_without_symbol"
R_CALIBRATED = "calibrated"
R_NOT_CALIBRATED = "unlinked_not_calibrated"

NON_BEHAVIORAL_CHANGE_KINDS = frozenset(
    {"formatting_only", "docstring_or_comment_only", "docstring_only", "comment_only"}
)
_IGNORED_FOR_AGREEMENT = frozenset(
    {LINKER_CHANGE_PRIOR, LINKER_RERANK, LINKER_CHAIN, COMBINED}
)
EXPLICIT_STRONG = 0.5


@dataclass(frozen=True)
class ChainConfig:
    explicit_dominance: float = 0.95
    dynamic_floor: float = 0.92
    low_confidence_factor: float = 0.85
    agree_weight: float = 0.3
    agree_full: float = 3.0
    agree_min: float = 0.5
    cap_other: float = 0.95
    cap_strong: float = 0.99
    hop_floor: float = 0.05
    min_chain: float = 0.01
    status_factors: Mapping[str, float] = field(
        default_factory=lambda: {
            STATUS_PASSED: 1.0,
            STATUS_UNKNOWN: 1.0,
            STATUS_FLAKY: 0.5,
            STATUS_FAILED: 0.4,
            STATUS_SKIPPED: 0.1,
        }
    )
    spec_min: float = 0.3
    spec_free: int = 2
    spec_lambda: float = 0.15
    spec_floor: float = 0.5
    decay: float = 0.7
    agg_top_n: int = 5
    max_symbols_per_criterion: int = 10
    max_tests_per_symbol: int = 10
    max_chains_kept: int = 10

    def __post_init__(self) -> None:
        unit = {
            "explicit_dominance": self.explicit_dominance,
            "dynamic_floor": self.dynamic_floor,
            "low_confidence_factor": self.low_confidence_factor,
            "agree_weight": self.agree_weight,
            "agree_min": self.agree_min,
            "cap_other": self.cap_other,
            "cap_strong": self.cap_strong,
            "hop_floor": self.hop_floor,
            "min_chain": self.min_chain,
            "spec_min": self.spec_min,
            "spec_floor": self.spec_floor,
            "decay": self.decay,
        }
        for name, value in unit.items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        if self.cap_other > self.cap_strong:
            raise ValueError("require cap_other <= cap_strong")
        if self.spec_floor <= 0.0:
            raise ValueError("spec_floor must be > 0")
        if self.agree_full <= 0 or self.spec_lambda < 0 or self.spec_free < 0:
            raise ValueError(
                "agree_full > 0, spec_lambda >= 0, spec_free >= 0 required"
            )
        for name in ("agg_top_n", "max_symbols_per_criterion", "max_tests_per_symbol"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be >= 1")
        if self.max_chains_kept < 1:
            raise ValueError("max_chains_kept must be >= 1")
        for status, factor in self.status_factors.items():
            if not 0.0 <= factor <= 1.0:
                raise ValueError(f"status factor for {status!r} must be in [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            k: getattr(self, k)
            for k in (
                "explicit_dominance dynamic_floor low_confidence_factor agree_weight "
                "agree_full agree_min cap_other cap_strong hop_floor min_chain spec_min "
                "spec_free spec_lambda spec_floor decay agg_top_n "
                "max_symbols_per_criterion max_tests_per_symbol max_chains_kept"
            ).split()
        }
        out["status_factors"] = dict(sorted(self.status_factors.items()))
        out["combiner"] = CHAIN_ALGO_VERSION
        return out


def _reason(kind: str, detail: str, score: float) -> Reason:
    return Reason(LINKER_CHAIN, kind, detail, clamp01(score))


class _Parts(NamedTuple):
    score: float
    h1: float
    h2: float
    explicit: float
    dynamic: bool
    low_conf: bool
    agree: float
    bonus: bool
    capped: bool
    cap: float
    status: str
    factor: float
    pre_cap: float


def _explicit_score(link: Link) -> float:
    best = link.score if link.linker == LINKER_EXPLICIT else 0.0
    for r in link.evidence:
        if r.linker == LINKER_EXPLICIT and r.score > best:
            best = r.score
    return best


def _linker_count(link: Link) -> int:
    names = {
        r.linker
        for r in link.evidence
        if r.score > 0 and r.linker not in _IGNORED_FOR_AGREEMENT
    }
    return max(1, len(names))


def score_chain(
    c2s: Link, s2t: SymbolTestEdge, status: str, cfg: ChainConfig
) -> _Parts:
    """Pure chain rule (see module docs). ``score == 0`` means no chain."""

    a, b = c2s.score, s2t.score
    e = _explicit_score(c2s)
    h1 = max(a, cfg.explicit_dominance * e)
    dynamic = s2t.is_dynamic
    low = s2t.low_confidence and not dynamic
    if dynamic:
        h2 = max(b, cfg.dynamic_floor)
    elif low:
        h2 = b * cfg.low_confidence_factor
    else:
        h2 = b
    factor = cfg.status_factors.get(status, 1.0)
    if min(h1, h2) < cfg.hop_floor:
        return _Parts(
            0.0, h1, h2, e, dynamic, low, 0.0, False, False, 0.0, status, factor, 0.0
        )
    base = h1 * h2
    l1 = _linker_count(c2s)
    l2 = max(1, len({n for n, _ in s2t.components}))
    agree = min(1.0, ((l1 - 1) + (l2 - 1)) / cfg.agree_full)
    bonus = min(h1, h2) >= cfg.agree_min and agree > 0
    chain = 1.0 - (1.0 - base) * (1.0 - cfg.agree_weight * agree) if bonus else base
    strong = e >= EXPLICIT_STRONG and dynamic
    cap = cfg.cap_strong if strong else cfg.cap_other
    capped = chain > cap
    pre_cap = chain
    chain = min(chain, cap) * factor
    if chain < cfg.min_chain:
        chain = 0.0
    return _Parts(
        chain,
        h1,
        h2,
        e,
        dynamic,
        low,
        agree,
        bonus,
        capped,
        cap,
        status,
        factor,
        pre_cap,
    )


def _chain_reasons(
    c2s: Link, s2t: SymbolTestEdge, p: _Parts, cfg: ChainConfig
) -> list[Reason]:
    out = [
        _reason(R_HOP1, f"criterion->symbol combined score {c2s.score:.3f}", c2s.score)
    ]
    if p.h1 > c2s.score:
        out.append(
            _reason(
                R_HOP1_EXPLICIT,
                f"explicit hint {p.explicit:.3f} x {cfg.explicit_dominance} lifts hop 1 to {p.h1:.3f}",
                p.h1,
            )
        )
    out.append(
        _reason(R_HOP2, f"symbol->test {s2t.kind} score {s2t.score:.3f}", s2t.score)
    )
    if p.dynamic and p.h2 > s2t.score:
        out.append(
            _reason(
                R_HOP2_DYNAMIC,
                f"dynamic coverage floor {cfg.dynamic_floor} lifts hop 2 to {p.h2:.3f}",
                p.h2,
            )
        )
    if p.low_conf:
        out.append(
            _reason(
                R_HOP2_LOW_CONF,
                f"low-confidence test link x {cfg.low_confidence_factor}",
                p.h2,
            )
        )
    out.append(_reason(R_AND, f"h1 {p.h1:.3f} x h2 {p.h2:.3f}", p.h1 * p.h2))
    if p.bonus:
        out.append(
            _reason(
                R_AGREEMENT,
                f"independent linkers agree ({p.agree:.2f}), weight {cfg.agree_weight}",
                p.agree,
            )
        )
    if p.capped:
        out.append(_reason(R_CAP, f"{p.pre_cap:.3f} capped at {p.cap}", p.cap))
    if p.status in cfg.status_factors and p.factor < 1.0:
        out.append(_reason(R_STATUS, f"test status {p.status} x {p.factor}", p.factor))
    return out


def _specificity(n_criteria: int, cfg: ChainConfig) -> float:
    extra = max(0, n_criteria - cfg.spec_free)
    return max(cfg.spec_floor, 1.0 / (1.0 + cfg.spec_lambda * extra))


def aggregate_support(
    supports: Sequence[float], cfg: ChainConfig, *, strong: bool = False
) -> float:
    """Per-criterion noisy-OR with diminishing returns over per-test supports."""

    ordered = sorted((clamp01(s) for s in supports), reverse=True)[: cfg.agg_top_n]
    miss = 1.0
    weight = 1.0
    for s in ordered:
        miss *= 1.0 - weight * s
        weight *= cfg.decay
    cap = cfg.cap_strong if strong else cfg.cap_other
    return min(cap, 1.0 - miss)


class _Cand(NamedTuple):
    link: Link
    edge: SymbolTestEdge
    parts: _Parts


def _group_edges(
    edges: Iterable[SymbolTestEdge],
) -> dict[str, list[SymbolTestEdge]]:
    best: dict[tuple[str, str], SymbolTestEdge] = {}
    for e in edges:
        old = best.get((e.symbol_id, e.test_id))
        if old is None or (e.score, e.test_id) > (old.score, old.test_id):
            best[(e.symbol_id, e.test_id)] = e
    out: dict[str, list[SymbolTestEdge]] = {}
    for (sid, _), e in best.items():
        out.setdefault(sid, []).append(e)
    for lst in out.values():
        lst.sort(key=lambda x: (-x.score, x.test_id))
    return out


def _group_links(
    links: Iterable[Link], criterion_ids: set[str]
) -> dict[str, list[Link]]:
    best: dict[tuple[str, str], Link] = {}
    for link in links:
        if link.linker != COMBINED or link.criterion_id not in criterion_ids:
            continue
        key = (link.criterion_id, link.symbol_id)
        old = best.get(key)
        if old is None or link.score > old.score:
            best[key] = link
    out: dict[str, list[Link]] = {}
    for (cid, _), link in best.items():
        out.setdefault(cid, []).append(link)
    for lst in out.values():
        lst.sort(key=lambda x: (-x.score, x.symbol_id))
    return out


def _unlinked(
    cid: str,
    reason: str,
    detail: str,
    *,
    suspicious: bool = False,
    extra: Sequence[Reason] = (),
) -> CriterionSupportLinks:
    return CriterionSupportLinks(
        criterion_id=cid,
        link_confidence=0.0,
        unlinked_reason=reason,
        reasons=(*extra, _reason(R_UNLINKED, f"{reason}: {detail}", 0.0)),
        suspicious=suspicious,
    )


def build_support_links(
    criterion_ids: Sequence[str],
    c2s_links: Iterable[Link],
    s2t_edges: Iterable[SymbolTestEdge],
    *,
    symbols: Mapping[str, SymbolDoc] | None = None,
    test_status: Mapping[str, str] | None = None,
    hinted_tests: Mapping[str, Sequence[str]] | None = None,
    config: ChainConfig | None = None,
    criterion_calibration: CalibrationArtifact | None = None,
    chain_calibration: CalibrationArtifact | None = None,
) -> SupportLinkSet:
    """Chains and link confidence for every criterion in ``criterion_ids``.

    ``symbols`` (by ``symbol_id``) enables the formatting/docstring-only
    exclusion; ``test_status`` maps test ids to ``passed|failed|flaky|skipped|
    unknown``; ``hinted_tests`` maps criterion ids to author-hinted test ids
    (used only to flag "tests but no symbol"). Calibration artifacts are applied
    only when given; without them every value is ``link_confidence_uncalibrated``.
    """

    cfg = config or ChainConfig()
    _check_target(criterion_calibration, TARGET_CRITERION)
    _check_target(chain_calibration, TARGET_CHAIN)
    status_of = test_status or {}
    hints = hinted_tests or {}
    syms = symbols or {}
    cids = sorted(set(criterion_ids))
    by_crit = _group_links(c2s_links, set(cids))
    by_sym = _group_edges(s2t_edges)

    # Pass 1: candidate chains and the per-test criterion counts (specificity).
    cands: dict[str, list[_Cand]] = {}
    pre: dict[str, CriterionSupportLinks] = {}
    untested: dict[str, list[Link]] = {}
    excluded: dict[str, list[Reason]] = {}
    test_criteria: dict[str, set[str]] = {}
    for cid in cids:
        links = by_crit.get(cid, [])
        kept: list[Link] = []
        ex: list[Reason] = []
        for link in links:
            doc = syms.get(link.symbol_id)
            if doc is not None and (
                not doc.is_behavioral or doc.change_kind in NON_BEHAVIORAL_CHANGE_KINDS
            ):
                ex.append(
                    _reason(
                        R_EXCLUDED,
                        f"{link.symbol_id} excluded ({doc.change_kind}, behavioral={doc.is_behavioral})",
                        link.score,
                    )
                )
            else:
                kept.append(link)
        excluded[cid] = ex
        if not links:
            hinted = tuple(hints.get(cid, ()))
            if hinted:
                pre[cid] = _unlinked(
                    cid,
                    UNLINKED_TESTS_WITHOUT_SYMBOL,
                    f"{len(hinted)} hinted test(s) but no linked symbol",
                    suspicious=True,
                    extra=[_reason(R_HINTED_TEST, t, 0.0) for t in sorted(hinted)[:5]],
                )
            else:
                pre[cid] = _unlinked(cid, UNLINKED_NO_SYMBOL, "no symbol candidate")
            continue
        if not kept:
            pre[cid] = _unlinked(
                cid,
                UNLINKED_NON_BEHAVIORAL,
                "all candidates are non-behavioral",
                extra=ex,
            )
            continue
        found: list[_Cand] = []
        unt: list[Link] = []
        for link in kept[: cfg.max_symbols_per_criterion]:
            tests = by_sym.get(link.symbol_id, [])
            if not tests:
                unt.append(link)
                continue
            for edge in tests[: cfg.max_tests_per_symbol]:
                st = status_of.get(edge.test_id, STATUS_UNKNOWN)
                parts = score_chain(link, edge, st, cfg)
                if parts.score > 0:
                    found.append(_Cand(link, edge, parts))
        untested[cid] = unt
        if not found:
            if len(unt) == len(kept[: cfg.max_symbols_per_criterion]):
                pre[cid] = _unlinked(
                    cid,
                    UNLINKED_UNTESTED,
                    "linked symbols have no test link",
                    extra=[
                        *ex,
                        *(
                            _reason(R_UNTESTED_SYMBOL, k.symbol_id, k.score)
                            for k in unt[:5]
                        ),
                    ],
                )
            else:
                pre[cid] = _unlinked(
                    cid, UNLINKED_WEAK, "every chain is below the floor", extra=ex
                )
            continue
        cands[cid] = found
        for c in found:
            if c.parts.score >= cfg.spec_min:
                test_criteria.setdefault(c.edge.test_id, set()).add(cid)

    # Pass 2: specificity, selection, aggregation.
    out: dict[str, CriterionSupportLinks] = dict(pre)
    for cid, found in cands.items():
        chains_all: list[ChainLink] = []
        for c in found:
            n = len(test_criteria.get(c.edge.test_id, ()))
            chains_all.append(_build_chain(cid, c, _specificity(n, cfg), n, cfg))
        chains = sorted(chains_all, key=ChainLink.sort_key)
        # the best chain per test is what the aggregation counts
        per_test: dict[str, ChainLink] = {}
        for ch in chains:
            per_test.setdefault(ch.test_id, ch)
        counted = list(per_test.values())[: cfg.agg_top_n]
        strong = any(
            _explicit_score(ch.c2s) >= EXPLICIT_STRONG and ch.s2t.is_dynamic
            for ch in counted
        )
        conf = aggregate_support(
            [ch.support_score for ch in counted], cfg, strong=strong
        )
        reasons = list(excluded[cid])
        weight = 1.0
        raw_total = 1.0
        for i, ch in enumerate(counted):
            term = weight * ch.support_score
            raw_total *= 1.0 - term
            reasons.append(
                _reason(
                    R_AGG_TERM,
                    f"#{i + 1} test {ch.test_id} via {ch.symbol_id}: support {ch.support_score:.3f} x weight {weight:.3f}",
                    term,
                )
            )
            weight *= cfg.decay
        cap = cfg.cap_strong if strong else cfg.cap_other
        if 1.0 - raw_total > cap:
            reasons.append(
                _reason(R_AGG_CAP, f"{1.0 - raw_total:.3f} capped at {cap}", cap)
            )
        reasons.extend(
            _reason(R_UNTESTED_SYMBOL, k.symbol_id, k.score) for k in untested[cid][:5]
        )
        out[cid] = CriterionSupportLinks(
            criterion_id=cid,
            chains=tuple(chains[: cfg.max_chains_kept]),
            link_confidence=conf,
            reasons=tuple(reasons),
        )

    result = tuple(out[cid] for cid in cids)
    return _apply_calibration(
        SupportLinkSet(criteria=result, config=cfg.to_dict()),
        criterion_calibration,
        chain_calibration,
    )


def _build_chain(
    cid: str, c: _Cand, spec: float, n: int, cfg: ChainConfig
) -> ChainLink:
    reasons = _chain_reasons(c.link, c.edge, c.parts, cfg)
    if spec < 1.0:
        reasons.append(
            _reason(
                R_SPECIFICITY,
                f"test covers {n} criteria (free {cfg.spec_free}): x {spec:.3f}",
                spec,
            )
        )
    return ChainLink(
        criterion_id=cid,
        symbol_id=c.link.symbol_id,
        test_id=c.edge.test_id,
        c2s=c.link,
        s2t=c.edge,
        chain_score=c.parts.score,
        reasons=tuple(reasons),
        specificity=spec,
        test_status=c.parts.status,
    )


def _check_target(art: CalibrationArtifact | None, target: str) -> None:
    if art is not None and art.target != target:
        raise CalibrationError(
            f"calibration artifact targets {art.target!r}, expected {target!r}"
        )


def _apply_calibration(
    ls: SupportLinkSet,
    criterion_art: CalibrationArtifact | None,
    chain_art: CalibrationArtifact | None,
) -> SupportLinkSet:
    if criterion_art is None and chain_art is None:
        return ls
    ccal = criterion_art.calibrator() if criterion_art else None
    kcal = chain_art.calibrator() if chain_art else None
    items: list[CriterionSupportLinks] = []
    for cs in ls.criteria:
        chains = cs.chains
        if kcal is not None and chain_art is not None:
            chains = tuple(
                replace(
                    ch,
                    chain_score=kcal.transform(ch.raw_chain_score or 0.0),
                    score_kind=SCORE_KIND_CALIBRATED,
                    reasons=(
                        *ch.reasons,
                        _reason(
                            R_CALIBRATED,
                            f"{chain_art.method} {chain_art.artifact_id}: raw {ch.raw_chain_score:.3f}",
                            kcal.transform(ch.raw_chain_score or 0.0),
                        ),
                    ),
                )
                for ch in cs.chains
            )
        conf = cs.link_confidence
        kind = cs.score_kind
        reasons = cs.reasons
        if ccal is not None and criterion_art is not None:
            if cs.unlinked_reason is None:
                conf = ccal.transform(cs.raw_link_confidence or 0.0)
                reasons = (
                    *reasons,
                    _reason(
                        R_CALIBRATED,
                        f"{criterion_art.method} {criterion_art.artifact_id}: raw {cs.raw_link_confidence:.3f}",
                        conf,
                    ),
                )
                kind = SCORE_KIND_CALIBRATED
            else:
                reasons = (
                    *reasons,
                    _reason(R_NOT_CALIBRATED, "no chain, confidence stays 0", 0.0),
                )
        items.append(
            replace(
                cs,
                chains=chains,
                link_confidence=conf,
                reasons=reasons,
                score_kind=kind,
            )
        )
    meta: dict[str, Any] = {}
    for label, art in (("criterion", criterion_art), ("chain", chain_art)):
        if art is not None:
            meta[label] = {
                "artifact_id": art.artifact_id,
                "method": art.method,
                "version": art.version,
                "fit": dict(art.fit),
            }
    return replace(
        ls,
        criteria=tuple(items),
        score_kind=SCORE_KIND_CALIBRATED if criterion_art else SCORE_KIND_UNCALIBRATED,
        calibration=meta,
    )


def explain(cs: CriterionSupportLinks, *, max_chains: int = 3) -> list[str]:
    """Human-readable lines for one criterion (numbers come from ``reasons``)."""

    head = (
        f"{cs.criterion_id}: link_confidence {cs.link_confidence:.3f} ({cs.score_kind})"
    )
    if cs.unlinked_reason:
        head += f", unlinked: {cs.unlinked_reason}"
    lines = [head]
    lines.extend(f"  - {r.kind}: {r.detail}" for r in cs.reasons)
    for ch in cs.chains[:max_chains]:
        lines.append(
            f"  chain {ch.symbol_id} -> {ch.test_id}: {ch.chain_score:.3f} (support {ch.support_score:.3f})"
        )
        lines.extend(f"    . {r.kind}: {r.detail}" for r in ch.reasons)
    return lines
