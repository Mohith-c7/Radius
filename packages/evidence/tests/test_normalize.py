"""EV-01 batch normalizer: cases, links, flaky, tamper, determinism, fuzz."""

from __future__ import annotations

import random

import pytest
from radius_evidence.application.normalize import MAX_CASES, normalize_evidence
from radius_evidence.domain.enums import EvidenceKind, Outcome
from radius_evidence.domain.factories import EvidenceInputError
from radius_evidence.domain.inputs import (
    CaseOutcomeInput,
    CriterionTestEdgeInput,
    StageAInput,
    StageBInput,
    SymbolInput,
    SymbolTestEdgeInput,
    TamperFindingInput,
)
from radius_evidence.domain.model import AssertionFeatures

SHA = "4f2a9d1c0b7e6a53f8c1d2e3b4a59687c0d1e2f3"
WHEN = "2026-11-02T10:15:00Z"
T1 = "tests/test_v.py::test_a"
T2 = "tests/test_v.py::test_b"
SYM = "python:src/v.py::f#function@1"


def feats(test_id: str, skip: bool = False) -> AssertionFeatures:
    return AssertionFeatures(
        test_id, test_id.split("::")[0], 1, 3, (), 0, False, False, None, skip, (), ()
    )


def stage(**over: object) -> StageBInput:
    a = dict(
        analysis_id="an1",
        repository_id="rp1",
        head_sha=SHA,
        changeset_ref="c",
        criteria=(),
        symbols=(
            SymbolInput(
                SYM,
                "src/v.py",
                "f",
                "function",
                "python",
                "modified",
                True,
                False,
                False,
            ),
        ),
        criterion_symbol=(),
        symbol_test=(
            SymbolTestEdgeInput(SYM, T1, 0.9, "direct_call"),
            SymbolTestEdgeInput(SYM, T2, 0.9, "direct_call"),
        ),
        criterion_test=(CriterionTestEdgeInput("c1", T1, 1.0, "intent_yml_hint"),),
        assertions=(feats(T1), feats(T2)),
        tamper=(),
        changed_test_ids=frozenset({T1}),
        agent_signal=False,
    )
    a_over = {k: over.pop(k) for k in list(over) if k in a}
    a.update(a_over)
    b = dict(stage_a=StageAInput(**a), results_received=True)  # type: ignore[arg-type]
    b.update(over)
    return StageBInput(**b)  # type: ignore[arg-type]


def run(sb: StageBInput, **kw: object):
    return normalize_evidence(sb, collected_at=WHEN, **kw)  # type: ignore[arg-type]


def by_subject(result) -> dict:
    return {i.subject_id: i for i in result.items}


def case(name: str, outcome: Outcome = Outcome.PASSED) -> CaseOutcomeInput:
    return CaseOutcomeInput(None, "tests/test_v.py", "tests.test_v", name, outcome)


def test_basic_join_links_independence_and_features() -> None:
    res = run(stage(cases=(case("test_a"), case("test_b"))))
    items = by_subject(res)
    a, b = items[T1], items[T2]
    assert res.rejected == ()
    assert a.symbol_ids == (SYM,) and a.criterion_ids == ("c1",)
    assert b.criterion_ids == ()
    assert a.independence.factor == 0.8 and b.independence.factor == 1.0
    assert "implementation_changed_in_pr" in {r.code for r in a.independence.reasons}
    assert a.features is not None and a.freshness.f == 1.0
    assert a.algo_versions["freshness"] == "fresh-1"


def test_agent_signal_lowers_changed_test_only() -> None:
    items = by_subject(
        run(stage(cases=(case("test_a"), case("test_b")), agent_signal=True))
    )
    assert items[T1].independence.factor == 0.6
    assert items[T2].independence.factor == 1.0


def test_parametrized_cases_merge_and_failure_wins() -> None:
    cases = (case("test_a[1]"), case("test_a[2]", Outcome.FAILED), case("test_a[3]"))
    items = by_subject(run(stage(cases=cases)))
    assert items[T1].outcome is Outcome.FAILED
    assert len([i for i in items if i == T1]) == 1


def test_linked_test_without_case_is_not_run_once_results_exist() -> None:
    items = by_subject(run(stage(cases=(case("test_a"),))))
    assert items[T2].outcome is Outcome.NOT_RUN
    assert "no_reported_case" in {r.code for r in items[T2].reasons}


def test_no_test_items_before_results_arrive() -> None:
    res = run(stage(cases=(), results_received=False))
    assert res.items == ()


def test_unmatched_case_kept_without_links() -> None:
    bad = CaseOutcomeInput(
        None, "tests/other.py", "tests.other", "test_zz", Outcome.FAILED
    )
    items = run(stage(cases=(case("test_a"), bad))).items
    unmatched = [i for i in items if i.subject_id.startswith("unmatched::")]
    assert len(unmatched) == 1
    assert unmatched[0].outcome is Outcome.FAILED and unmatched[0].symbol_ids == ()


def test_duplicate_unmatched_cases_collapse_to_worst() -> None:
    def mk(o: Outcome) -> CaseOutcomeInput:
        return CaseOutcomeInput(None, "x.py", "x", "test_q", o)

    items = run(stage(cases=(mk(Outcome.PASSED), mk(Outcome.FAILED)))).items
    unmatched = [i for i in items if i.subject_id.startswith("unmatched::")]
    assert len(unmatched) == 1 and unmatched[0].outcome is Outcome.FAILED


def test_rerun_flaky_turns_pass_into_flaky_and_flags() -> None:
    items = by_subject(
        run(
            stage(
                cases=(case("test_a"),),
                flaky_test_ids=frozenset({T1}),
                flaky_scores={T1: 0.3},
            )
        )
    )
    assert items[T1].outcome is Outcome.FLAKY
    assert (items[T1].flaky.flagged, items[T1].flaky.source, items[T1].flaky.score) == (
        True,
        "rerun",
        0.3,
    )


def test_history_flakiness_discounts_without_changing_outcome() -> None:
    items = by_subject(run(stage(cases=(case("test_a"),), flaky_scores={T1: 0.4})))
    assert items[T1].outcome is Outcome.PASSED
    assert items[T1].flaky.source == "history" and not items[T1].flaky.flagged


def test_skipped_case_stays_skipped_and_marker_noted() -> None:
    sb = stage(
        cases=(case("test_a", Outcome.SKIPPED),),
        assertions=(feats(T1, skip=True), feats(T2)),
    )
    assert by_subject(run(sb))[T1].outcome is Outcome.SKIPPED


def test_tamper_findings_become_items() -> None:
    f = TamperFindingInput(
        "tf_1",
        "T001",
        "assertion_removed",
        "high",
        0.9,
        "tests/test_v.py",
        SYM,
        T1,
        "r",
    )
    bad = TamperFindingInput("tf_2", "T002", "x", "bogus", 0.9, "tests/test_v.py")
    res = run(stage(cases=(case("test_a"),), tamper=(f, bad)))
    tamper = [i for i in res.items if i.kind is EvidenceKind.TAMPER_FINDING]
    assert [i.subject_id for i in tamper] == ["tf_1"]
    assert [r.code for r in res.rejected] == ["rejected_finding"]


def test_human_attested_test() -> None:
    items = by_subject(
        run(stage(cases=(case("test_a"),)), human_attested_tests=frozenset({T1}))
    )
    assert items[T1].independence.factor == 1.0


def test_stale_current_sha_zeroes_freshness() -> None:
    items = run(stage(cases=(case("test_a"),)), current_sha="b" * 40).items
    assert all(i.freshness.f == 0.0 for i in items)


def test_rejects_unbound_sha_and_oversized() -> None:
    with pytest.raises(EvidenceInputError):
        run(stage(head_sha="nothex"))
    with pytest.raises(EvidenceInputError):
        run(stage(cases=tuple(case("test_a") for _ in range(MAX_CASES + 1))))


def test_malformed_case_object_is_reported() -> None:
    res = run(stage(cases=("garbage", case("test_a"))))  # type: ignore[arg-type]
    assert [r.code for r in res.rejected] == ["malformed_case"]
    assert T1 in by_subject(res)


def test_overlong_case_fields_are_rejected_not_fatal() -> None:
    bad = CaseOutcomeInput(None, "f.py", "c", "n" * 5000, Outcome.PASSED)
    res = run(stage(cases=(bad, case("test_a"))))
    assert "rejected_case" in {r.code for r in res.rejected}
    assert T1 in by_subject(res)


def test_deterministic_and_order_independent() -> None:
    cases = [case("test_a"), case("test_b", Outcome.FAILED), case("test_a[2]")]
    base = run(stage(cases=tuple(cases)))
    rng = random.Random(1)
    for _ in range(5):
        rng.shuffle(cases)
        assert run(stage(cases=tuple(cases))) == base
    assert [i.to_json() for i in base.items] == [
        i.to_json() for i in run(stage(cases=tuple(cases))).items
    ]


def test_fuzz_never_crashes_on_random_cases() -> None:
    rng = random.Random(42)
    chars = "abc/._:[]|\\ \x00é"

    def junk() -> str | None:
        return "".join(rng.choice(chars) for _ in range(rng.randint(0, 30))) or None

    for _ in range(100):
        cases = tuple(
            CaseOutcomeInput(junk(), junk(), junk(), junk(), rng.choice(list(Outcome)))
            for _ in range(rng.randint(0, 5))
        )
        res = run(stage(cases=cases))
        assert all(len(i.head_sha) == 40 for i in res.items)
