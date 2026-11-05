"""Support ``S(c)`` (design 3.9): contract and the VD-01 aggregation.

Formulas (verbatim, design 3.9):

    term(e)    = lambda_kind(e) * q(e, c) * l(c, e)
    group(e)   = the symbol id on the best path of e
    sorted within a group by term desc (ties: evidence_id); k = 0-based rank
    contrib(e) = term(e) * rho^k
    S_raw(c)   = 1 - PROD_{e in E(c)} (1 - contrib(e))
    S(c)       = min(S_raw(c), s_cap)

``term`` is computed by ``quality.evidence_quality_row`` (EV-08); this module
groups, discounts and combines the counted rows. Pure and order-independent.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace

from radius_evidence.domain.config import SupportConfig
from radius_evidence.domain.model import Reason
from radius_evidence.domain.quality import STATUS_COUNTED, EvidenceQuality
from radius_evidence.domain.serialization import Serializable
from radius_evidence.domain.versions import SUPPORT_VERSION

#: Group key for counted rows that carry no symbol (treated as one correlated group).
UNKNOWN_GROUP = "<unknown>"


@dataclass(frozen=True, slots=True)
class SupportResult(Serializable):
    """Result of ``S(c)`` with every intermediate value kept for audit."""

    criterion_id: str
    S: float  # min(S_raw, s_cap)
    S_raw: float
    items: tuple[EvidenceQuality, ...]  # every item considered
    n_counted: int
    has_strong_item: bool
    algo_version: str = SUPPORT_VERSION


def _group_key(row: EvidenceQuality) -> str:
    if row.group_symbol:
        return row.group_symbol
    if row.path is not None and row.path.symbol_id:
        return row.path.symbol_id
    return UNKNOWN_GROUP


def compute_support(
    criterion_id: str,
    items: Iterable[EvidenceQuality],
    config: SupportConfig | None = None,
) -> SupportResult:
    """Aggregate the rows of ``criterion_id`` into ``S(c)``.

    Only rows with status ``counted`` and a positive term contribute; rows of
    other criteria are ignored. Returned ``items`` are sorted by
    (evidence_id, status) and counted rows carry ``group_symbol``,
    ``rank_in_group``, ``discount`` and ``contribution``.
    """

    cfg = config if config is not None else SupportConfig()
    rows = [r for r in items if r.criterion_id == criterion_id]
    counted = [r for r in rows if r.status == STATUS_COUNTED and r.term > 0.0]
    groups: dict[str, list[EvidenceQuality]] = {}
    for row in counted:
        groups.setdefault(_group_key(row), []).append(row)

    annotated: dict[int, EvidenceQuality] = {}
    keep = 1.0
    for key in sorted(groups):
        ordered = sorted(groups[key], key=lambda r: (-r.term, r.evidence_id))
        for k, row in enumerate(ordered):
            discount = cfg.rho**k
            contribution = row.term * discount
            keep *= 1.0 - contribution
            annotated[id(row)] = replace(
                row,
                group_symbol=key,
                rank_in_group=k,
                discount=discount,
                contribution=contribution,
            )
    s_raw = 1.0 - keep if counted else 0.0
    out = tuple(
        annotated.get(id(r), r)
        for r in sorted(rows, key=lambda r: (r.evidence_id, r.status))
    )
    return SupportResult(
        criterion_id=criterion_id,
        S=min(s_raw, cfg.s_cap),
        S_raw=s_raw,
        items=out,
        n_counted=len(counted),
        has_strong_item=any(r.a_static >= cfg.strong_min for r in counted),
    )


def support_reasons(
    result: SupportResult, config: SupportConfig | None = None
) -> tuple[Reason, ...]:
    """Reason codes explaining ``S``: ``no_counted_evidence``, ``correlated_discount``,
    ``capped_at_s_cap``, ``no_strong_assertion``."""

    cfg = config if config is not None else SupportConfig()
    reasons: list[Reason] = []
    if result.n_counted == 0:
        reasons.append(Reason("no_counted_evidence", "no usable passing evidence"))
        return tuple(reasons)
    if any((r.rank_in_group or 0) > 0 for r in result.items):
        reasons.append(
            Reason(
                "correlated_discount",
                f"same-symbol tests discounted by rho={cfg.rho:g}^k",
            )
        )
    if result.S_raw > cfg.s_cap:
        reasons.append(
            Reason(
                "capped_at_s_cap", f"S_raw {result.S_raw:.3f} capped at {cfg.s_cap:g}"
            )
        )
    if not result.has_strong_item:
        reasons.append(
            Reason(
                "no_strong_assertion",
                f"no counted item with a_static >= {cfg.strong_min:g}",
            )
        )
    return tuple(reasons)
