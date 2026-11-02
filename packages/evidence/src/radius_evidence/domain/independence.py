"""Authorship and independence, lite version (EV-03-lite, ``indep-lite-1``).

Factor table (design 3.5 / 3.8, D13):

* test pre-existing and unchanged in the PR          -> 1.0  (pre_existing_unchanged_factor)
* changed in the PR, author attested human           -> 1.0  (iota_human)
* changed in the PR, PR carries an agent trailer     -> 0.6  (iota_agent)
* changed in the PR, authorship unknown (default)    -> 0.8  (iota_unknown)

Whether the covered implementation changed in the same PR is reported as a reason
(``implementation_changed_in_pr``) but does not change the factor in the lite
version. A *failing* test is never discounted by independence (callers' rule).
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass

from radius_evidence.domain.config import QualityConfig
from radius_evidence.domain.enums import AuthoredBy, IndependenceBasis
from radius_evidence.domain.model import IndependenceInfo, Reason


@dataclass(frozen=True, slots=True)
class AgentSignal:
    detected: bool
    matches: tuple[str, ...] = ()  # the patterns that matched, sorted


def detect_agent_trailers(
    messages: Iterable[str], patterns: Iterable[str] | None = None
) -> AgentSignal:
    """Case-insensitive substring match of ``patterns`` over commit messages.

    Pure and total: non-string items and empty patterns are ignored. Whitespace runs
    are collapsed so ``Co-Authored-By:   Claude`` matches ``co-authored-by: claude``.
    """

    pats = (
        QualityConfig().agent_trailer_patterns if patterns is None else tuple(patterns)
    )
    norm_patterns = sorted(
        {" ".join(p.lower().split()) for p in pats if p and p.strip()}
    )
    found: set[str] = set()
    for msg in messages:
        if not isinstance(msg, str):
            continue
        text = " ".join(msg.lower().split())
        for pat in norm_patterns:
            if pat in text:
                found.add(pat)
    return AgentSignal(bool(found), tuple(sorted(found)))


def classify_independence(
    test_id: str,
    *,
    changed_test_ids: Collection[str] = frozenset(),
    added_test_ids: Collection[str] = frozenset(),
    implementation_changed: bool = False,
    agent_signal: bool = False,
    human_attested: bool = False,
    config: QualityConfig | None = None,
) -> IndependenceInfo:
    """Independence factor of one test with reasons."""

    cfg = config or QualityConfig()
    if test_id not in changed_test_ids and test_id not in added_test_ids:
        return IndependenceInfo(
            AuthoredBy.HUMAN if human_attested else AuthoredBy.UNKNOWN,
            IndependenceBasis.PRE_EXISTING_UNCHANGED,
            cfg.pre_existing_unchanged_factor,
            (
                Reason(
                    "pre_existing_unchanged",
                    "test exists unchanged at the PR base",
                    test_id,
                ),
            ),
        )

    reasons: list[Reason] = []
    if test_id in added_test_ids:
        reasons.append(
            Reason("test_added_in_pr", "test function is new in this PR", test_id)
        )
    else:
        reasons.append(
            Reason(
                "test_modified_in_pr", "test function was changed in this PR", test_id
            )
        )
    if implementation_changed:
        reasons.append(
            Reason(
                "implementation_changed_in_pr",
                "code under test changed in the same PR (no factor change in the lite version)",
                test_id,
            )
        )

    if agent_signal:
        authored, factor = AuthoredBy.AGENT, cfg.iota_agent
        reasons.append(Reason("agent_trailer", "PR carries an agent trailer", None))
    elif human_attested:
        authored, factor = AuthoredBy.HUMAN, cfg.iota_human
        reasons.append(Reason("human_attested", "author attested as human", None))
    else:
        authored, factor = AuthoredBy.UNKNOWN, cfg.iota_unknown
        reasons.append(
            Reason("author_unknown", "no authorship signal; default factor", None)
        )

    return IndependenceInfo(
        authored, IndependenceBasis.CHANGED_IN_PR, factor, tuple(reasons)
    )
