"""Batch normalization of Stage B inputs into evidence items (EV-01 + EV-03-lite + EV-07).

Pure and deterministic: equal inputs give an identical, sorted tuple of items.
Inputs are the plain DTOs of design 3.7; this module never reads files or clocks.
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from dataclasses import dataclass

from radius_evidence.domain.config import QualityConfig
from radius_evidence.domain.enums import Outcome
from radius_evidence.domain.factories import (
    EvidenceInputError,
    case_to_test_id,
    from_case,
    from_finding,
    from_test,
    merge_outcomes,
    normalize_test_id,
)
from radius_evidence.domain.freshness import bind_freshness
from radius_evidence.domain.independence import classify_independence
from radius_evidence.domain.inputs import CaseOutcomeInput, StageBInput
from radius_evidence.domain.model import (
    AssertionFeatures,
    EvidenceItem,
    FlakyInfo,
    Reason,
)
from radius_evidence.domain.versions import (
    ASSERTIONS_VERSION,
    FRESHNESS_VERSION,
    INDEPENDENCE_VERSION,
)

MAX_CASES = 50_000

_ALGOS = {
    "assertions": ASSERTIONS_VERSION,
    "independence": INDEPENDENCE_VERSION,
    "freshness": FRESHNESS_VERSION,
}


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    items: tuple[EvidenceItem, ...]
    rejected: tuple[Reason, ...] = ()


def normalize_evidence(
    stage_b: StageBInput,
    *,
    collected_at: str,
    config: QualityConfig | None = None,
    current_sha: str | None = None,
    human_attested_tests: frozenset[str] = frozenset(),
) -> NormalizationResult:
    """Turn test outcomes, tamper findings, assertion features and link chains into items.

    * one ``TEST_OUTCOME`` item per distinct test (cases of a parametrized test merge);
    * a linked test without any reported case becomes ``NOT_RUN`` (only once CI results
      exist; before that no test items are produced);
    * cases that match no known test become unmatched items with no links;
    * flaky ids from reruns turn the outcome into ``FLAKY`` (source ``rerun``); a history
      score alone flags without changing the outcome (source ``history``);
    * every tamper finding becomes a ``TAMPER_FINDING`` item;
    * malformed individual inputs are rejected and reported, the rest is kept.
    """

    sa = stage_b.stage_a
    cfg = config or QualityConfig()
    if len(stage_b.cases) > MAX_CASES:
        msg = f"more than {MAX_CASES} cases"
        raise EvidenceInputError(msg)
    head = sa.head_sha
    cur = current_sha or head
    # Validates the SHA binding once, up front (raises ValueError when unbound).
    if bind_freshness(head, head).f != 1.0:
        msg = "head_sha must be 40 lowercase hex characters"
        raise EvidenceInputError(msg)

    features: dict[str, AssertionFeatures] = {f.test_id: f for f in sa.assertions}
    symbols_by_test: dict[str, set[str]] = defaultdict(set)
    for edge in sa.symbol_test:
        symbols_by_test[normalize_test_id(edge.test_id)].add(edge.symbol_id)
    criteria_by_test: dict[str, set[str]] = defaultdict(set)
    for cedge in sa.criterion_test:
        criteria_by_test[normalize_test_id(cedge.test_id)].add(cedge.criterion_id)
    symbol_paths = {s.symbol_id: s.path for s in sa.symbols}

    known = (
        set(features)
        | set(symbols_by_test)
        | set(criteria_by_test)
        | {normalize_test_id(t) for t in sa.changed_test_ids}
    )

    rejected: list[Reason] = []
    outcomes: dict[str, list[Outcome]] = defaultdict(list)
    unmatched: list[CaseOutcomeInput] = []
    for case in stage_b.cases:
        if not isinstance(case, CaseOutcomeInput):
            rejected.append(Reason("malformed_case", "not a CaseOutcomeInput"))
            continue
        test_id = case.test_id and normalize_test_id(case.test_id)
        if not test_id:
            test_id = case_to_test_id(
                case.raw_file, case.raw_classname, case.raw_name, known
            )
        if test_id is None:
            unmatched.append(case)
        else:
            outcomes[test_id].append(case.outcome)

    items: list[EvidenceItem] = []
    test_ids = set(outcomes)
    if stage_b.results_received:
        test_ids |= set(symbols_by_test) | set(criteria_by_test)
    for test_id in sorted(test_ids):
        outcome = (
            merge_outcomes(outcomes[test_id])
            if test_id in outcomes
            else Outcome.NOT_RUN
        )
        flaky = FlakyInfo(False)
        if test_id in stage_b.flaky_test_ids:
            flaky = FlakyInfo(True, "rerun", stage_b.flaky_scores.get(test_id))
            if outcome in (Outcome.PASSED, Outcome.FAILED, Outcome.ERROR):
                outcome = Outcome.FLAKY
        elif stage_b.flaky_scores.get(test_id, 0.0) > 0.0:
            flaky = FlakyInfo(False, "history", stage_b.flaky_scores[test_id])
        feat = features.get(test_id)
        syms = symbols_by_test.get(test_id, set())
        impl_changed = any(
            s in symbol_paths for s in syms
        )  # symbols are the PR changed set
        independence = classify_independence(
            test_id,
            changed_test_ids={normalize_test_id(t) for t in sa.changed_test_ids},
            implementation_changed=impl_changed,
            agent_signal=sa.agent_signal,
            human_attested=test_id in human_attested_tests,
            config=cfg,
        )
        reasons = (
            [Reason("no_reported_case", "linked test has no CI case", test_id)]
            if (outcome is Outcome.NOT_RUN)
            else []
        )
        if feat is not None and feat.has_skip_marker and outcome is Outcome.PASSED:
            reasons.append(
                Reason("skip_marker_but_passed", "skip marker present", test_id)
            )
        try:
            items.append(
                from_test(
                    analysis_id=sa.analysis_id,
                    repository_id=sa.repository_id,
                    head_sha=head,
                    test_id=test_id,
                    outcome=outcome,
                    collected_at=collected_at,
                    independence=independence,
                    features=feat,
                    symbol_ids=syms,
                    criterion_ids=criteria_by_test.get(test_id, ()),
                    flaky=flaky,
                    reasons=reasons,
                    current_sha=cur,
                    path=feat.path if feat else None,
                    algo_versions=dict(_ALGOS),
                )
            )
        except EvidenceInputError as exc:
            rejected.append(Reason("rejected_test", str(exc), test_id))

    for case in unmatched:
        try:
            item = from_case(
                case,
                analysis_id=sa.analysis_id,
                repository_id=sa.repository_id,
                head_sha=head,
                collected_at=collected_at,
                independence=classify_independence("unmatched", config=cfg),
                known_test_ids=(),
                current_sha=cur,
                algo_versions=dict(_ALGOS),
            )
            items.append(item)
        except EvidenceInputError as exc:
            rejected.append(Reason("rejected_case", str(exc)))

    for finding in sa.tamper:
        try:
            items.append(
                from_finding(
                    finding,
                    analysis_id=sa.analysis_id,
                    repository_id=sa.repository_id,
                    head_sha=head,
                    collected_at=collected_at,
                    current_sha=cur,
                )
            )
        except EvidenceInputError as exc:
            rejected.append(Reason("rejected_finding", str(exc), finding.finding_id))

    unique: dict[str, EvidenceItem] = {}
    for item in items:
        merged = unique.get(item.evidence_id)
        if merged is None:
            unique[item.evidence_id] = item
        else:  # duplicate unmatched cases with the same label: keep the worse outcome
            worse = merge_outcomes(
                [merged.outcome or Outcome.NOT_RUN, item.outcome or Outcome.NOT_RUN]
            )
            unique[item.evidence_id] = dataclasses.replace(merged, outcome=worse)
    ordered = tuple(sorted(unique.values(), key=lambda i: (i.kind.value, i.subject_id)))
    return NormalizationResult(ordered, tuple(rejected))
