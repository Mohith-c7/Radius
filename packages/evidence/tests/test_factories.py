"""EV-01: factories, stable ids, test-id joiner, malformed input rejection."""

from __future__ import annotations

import json

import pytest
from radius_evidence.domain.enums import (
    AuthoredBy,
    EvidenceKind,
    EvidenceSource,
    IndependenceBasis,
    Outcome,
)
from radius_evidence.domain.factories import (
    EvidenceInputError,
    case_to_test_id,
    finding_input_from_dict,
    from_aggregate,
    from_case,
    from_finding,
    from_test,
    make_evidence_id,
    merge_outcomes,
    normalize_test_id,
)
from radius_evidence.domain.independence import classify_independence
from radius_evidence.domain.inputs import CaseOutcomeInput, TamperFindingInput
from radius_evidence.domain.model import EvidenceItem, FlakyInfo, Reason

SHA = "4f2a9d1c0b7e6a53f8c1d2e3b4a59687c0d1e2f3"
WHEN = "2026-11-02T10:15:00Z"
KW = {
    "analysis_id": "an1",
    "repository_id": "rp1",
    "head_sha": SHA,
    "collected_at": WHEN,
}


def make_item(
    test_id: str = "tests/t.py::test_a",
    *,
    head: str = SHA,
    outcome: Outcome = Outcome.PASSED,
    current: str | None = None,
) -> EvidenceItem:
    return from_test(
        analysis_id="an1",
        repository_id="rp1",
        head_sha=head,
        test_id=test_id,
        outcome=outcome,
        collected_at=WHEN,
        independence=classify_independence(test_id),
        current_sha=current,
    )


def finding(**over: object) -> TamperFindingInput:
    base = {
        "finding_id": "tf_1",
        "rule_id": "T001",
        "check": "assertion_removed",
        "severity": "high",
        "confidence": 0.9,
        "path": "tests/t.py",
        "symbol": "python:src/a.py::f#function@abc",
        "test_id": "tests/t.py::test_a",
        "reason": "assertion removed",
    }
    base.update(over)
    return TamperFindingInput(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("tests/a.py::T::f[1-2]", "tests/a.py::T::f"),
        ("tests/a.py::f", "tests/a.py::f"),
        ("  tests\\a.py::f  ", "tests/a.py::f"),
        ("tests/a.py::f|run", "tests/a.py::f"),
        ("tests/a.py::f|setup", "tests/a.py::f"),
        ("tests/a.py::f|other", "tests/a.py::f|other"),
        ("tests/a.py::f[a[b]]", "tests/a.py::f"),
    ],
)
def test_normalize_test_id(raw: str, expected: str) -> None:
    assert normalize_test_id(raw) == expected


KNOWN = {
    "tests/test_validators.py::test_a",
    "tests/test_validators.py::TestV::test_b",
    "src/pkg/tests/test_deep.py::test_c",
}


@pytest.mark.parametrize(
    ("file", "classname", "name", "expected"),
    [
        (None, "tests.test_validators", "test_a", "tests/test_validators.py::test_a"),
        (
            None,
            "tests.test_validators.TestV",
            "test_b",
            "tests/test_validators.py::TestV::test_b",
        ),
        (
            "tests/test_validators.py",
            "tests.test_validators",
            "test_a[1-2]",
            "tests/test_validators.py::test_a",
        ),
        (
            "tests/test_validators.py",
            "tests.test_validators.TestV",
            "test_b",
            "tests/test_validators.py::TestV::test_b",
        ),
        (
            "tests\\test_validators.py",
            None,
            "test_a",
            "tests/test_validators.py::test_a",
        ),
        (
            "./tests/test_validators.py",
            "",
            "test_a",
            "tests/test_validators.py::test_a",
        ),
        (
            None,
            None,
            "tests/test_validators.py::test_a[x]",
            "tests/test_validators.py::test_a",
        ),
        (
            None,
            "pkg.tests.test_deep",
            "test_c",
            "src/pkg/tests/test_deep.py::test_c",
        ),  # suffix match
        (None, "tests.test_other", "test_a", None),
        (None, None, None, None),
        (None, None, "", None),
        (None, "nonsense", "test_zzz", None),
    ],
)
def test_case_to_test_id(
    file: str | None, classname: str | None, name: str | None, expected: str | None
) -> None:
    assert case_to_test_id(file, classname, name, KNOWN) == expected


def test_case_to_test_id_ambiguous_suffix_is_none() -> None:
    known = {"a/tests/test_x.py::test_a", "b/tests/test_x.py::test_a"}
    assert case_to_test_id(None, "tests.test_x", "test_a", known) is None


def test_case_to_test_id_empty_known() -> None:
    assert case_to_test_id(None, "tests.t", "test_a", ()) is None


def test_evidence_id_stable_and_sensitive() -> None:
    a = make_evidence_id("an1", EvidenceKind.TEST_OUTCOME, "t", SHA)
    assert a == make_evidence_id("an1", "test_outcome", "t", SHA)
    assert a.startswith("ev_") and len(a) == 23
    for other in (
        make_evidence_id("an2", EvidenceKind.TEST_OUTCOME, "t", SHA),
        make_evidence_id("an1", EvidenceKind.TAMPER_FINDING, "t", SHA),
        make_evidence_id("an1", EvidenceKind.TEST_OUTCOME, "u", SHA),
        make_evidence_id("an1", EvidenceKind.TEST_OUTCOME, "t", "b" * 40),
        make_evidence_id("an1", EvidenceKind.TEST_OUTCOME, "t", SHA, "other-algo"),
    ):
        assert other != a


@pytest.mark.parametrize(
    ("outcomes", "expected"),
    [
        ([Outcome.PASSED, Outcome.FAILED], Outcome.FAILED),
        ([Outcome.PASSED, Outcome.ERROR], Outcome.ERROR),
        ([Outcome.PASSED, Outcome.SKIPPED], Outcome.PASSED),
        ([Outcome.SKIPPED, Outcome.SKIPPED], Outcome.SKIPPED),
        ([Outcome.PASSED, Outcome.FLAKY], Outcome.FLAKY),
        ([Outcome.FAILED, Outcome.ERROR], Outcome.FAILED),
        ([Outcome.NOT_RUN, Outcome.SKIPPED], Outcome.SKIPPED),
        ([], Outcome.NOT_RUN),
    ],
)
def test_merge_outcomes(outcomes: list[Outcome], expected: Outcome) -> None:
    assert merge_outcomes(outcomes) is expected


def test_from_test_builds_a_bound_item() -> None:
    item = make_item("tests/t.py::test_a")
    assert item.kind is EvidenceKind.TEST_OUTCOME
    assert item.source is EvidenceSource.CI_UPLOAD
    assert item.path == "tests/t.py"
    assert item.freshness.f == 1.0 and item.freshness.bound_sha == SHA
    assert item.independence.basis is IndependenceBasis.PRE_EXISTING_UNCHANGED
    assert EvidenceItem.from_dict(item.to_dict()) == item
    json.dumps(item.to_dict())


@pytest.mark.parametrize("bad", ["", "abc", "A" * 40, "g" * 40, "a" * 41, "a" * 39])
def test_unbound_or_malformed_sha_is_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        make_item(head=bad)
    with pytest.raises(ValueError):
        from_finding(finding(), **{**KW, "head_sha": bad})


def test_sorted_symbols_and_criteria_deduplicated() -> None:
    item = from_test(
        **{**KW, "test_id": "t.py::t", "outcome": Outcome.PASSED},
        independence=classify_independence("t.py::t"),
        symbol_ids=["b", "a", "b"],
        criterion_ids=["c2", "c1"],
    )
    assert item.symbol_ids == ("a", "b")
    assert item.criterion_ids == ("c1", "c2")


def test_flaky_outcome_flags_rerun() -> None:
    item = make_item(outcome=Outcome.FLAKY)
    assert item.flaky == FlakyInfo(True, "rerun", None)


def test_negative_duration_and_long_ids_rejected() -> None:
    ind = classify_independence("t")
    base = {**KW, "outcome": Outcome.PASSED, "independence": ind}
    with pytest.raises(EvidenceInputError):
        from_test(**base, test_id="t", duration_ms=-1)
    with pytest.raises(EvidenceInputError):
        from_test(**base, test_id="x" * 5000)


def test_from_case_matched_unmatched_and_empty() -> None:
    ind = classify_independence("x")
    matched = from_case(
        CaseOutcomeInput(
            None,
            "tests/test_validators.py",
            "tests.test_validators",
            "test_a[1]",
            Outcome.PASSED,
        ),
        independence=ind,
        known_test_ids=KNOWN,
        symbol_ids=["s1"],
        **KW,
    )
    assert matched.subject_id == "tests/test_validators.py::test_a"
    assert matched.symbol_ids == ("s1",)

    unmatched = from_case(
        CaseOutcomeInput(None, "tests/zzz.py", "tests.zzz", "test_q", Outcome.FAILED),
        independence=ind,
        known_test_ids=KNOWN,
        symbol_ids=["s1"],
        **KW,
    )
    assert unmatched.subject_id.startswith("unmatched::")
    assert unmatched.symbol_ids == () and unmatched.features is None
    assert "unmatched_case" in {r.code for r in unmatched.reasons}
    assert unmatched.outcome is Outcome.FAILED

    with pytest.raises(EvidenceInputError):
        from_case(
            CaseOutcomeInput(None, None, None, None, Outcome.PASSED),
            independence=ind,
            **KW,
        )
    with pytest.raises(EvidenceInputError):
        from_case(
            CaseOutcomeInput(None, None, "n" * 3000, "x", Outcome.PASSED),
            independence=ind,
            **KW,
        )


def test_from_case_uses_given_test_id() -> None:
    item = from_case(
        CaseOutcomeInput("tests/a.py::t[3]", None, None, None, Outcome.PASSED),
        independence=classify_independence("x"),
        **KW,
    )
    assert item.subject_id == "tests/a.py::t[3]"  # caller-joined ids are kept verbatim


@pytest.mark.parametrize(
    ("counts", "expected"),
    [
        ({"passed": 5, "failed": 0}, Outcome.PASSED),
        ({"passed": 5, "failed": 1}, Outcome.FAILED),
        ({"passed": 5, "failed": 0, "errors": 2}, Outcome.ERROR),
        ({"passed": 0, "failed": 0, "skipped": 3}, Outcome.SKIPPED),
        ({"passed": 0, "failed": 0}, Outcome.NOT_RUN),
    ],
)
def test_from_aggregate(counts: dict[str, int], expected: Outcome) -> None:
    item = from_aggregate(**KW, **counts)
    assert item.outcome is expected
    assert item.source is EvidenceSource.WORKER_RUN
    assert item.symbol_ids == ()
    assert "aggregate_only" in {r.code for r in item.reasons}


@pytest.mark.parametrize(
    "bad",
    [
        {"passed": -1, "failed": 0},
        {"passed": 1.5, "failed": 0},
        {"passed": True, "failed": 0},
    ],
)
def test_from_aggregate_rejects_bad_counts(bad: dict) -> None:
    with pytest.raises(EvidenceInputError):
        from_aggregate(**KW, **bad)


def test_from_finding() -> None:
    item = from_finding(finding(severity="HIGH"), **KW)
    assert item.kind is EvidenceKind.TAMPER_FINDING
    assert item.severity == "high" and item.rule_id == "T001"
    assert item.outcome is None and item.features is None
    assert item.symbol_ids == ("python:src/a.py::f#function@abc",)
    assert item.independence.authored_by is AuthoredBy.UNKNOWN
    assert item.independence.factor == 1.0
    assert (
        Reason("affects_test", "finding attached to a test", "tests/t.py::test_a")
        in item.reasons
    )


@pytest.mark.parametrize(
    "over",
    [
        {"severity": "catastrophic"},
        {"severity": ""},
        {"severity": None},
        {"finding_id": ""},
        {"rule_id": ""},
        {"path": ""},
        {"finding_id": "f" * 3000},
    ],
)
def test_from_finding_rejects_malformed(over: dict) -> None:
    with pytest.raises(EvidenceInputError):
        from_finding(finding(**over), **KW)


def test_finding_without_symbol_or_test() -> None:
    item = from_finding(finding(symbol=None, test_id=None), **KW)
    assert item.symbol_ids == ()
    assert [r.code for r in item.reasons] == ["T001"]


def test_finding_input_from_dict_roundtrip_and_errors() -> None:
    data = {
        "finding_id": "tf_9",
        "rule_id": "T004",
        "check": "x",
        "severity": "medium",
        "confidence": 0.5,
        "path": "p.py",
        "extra": 1,
    }
    assert finding_input_from_dict(data).rule_id == "T004"
    for bad in ({}, {"finding_id": "x"}, {**data, "confidence": "high"}):
        with pytest.raises(EvidenceInputError):
            finding_input_from_dict(bad)
    with pytest.raises(EvidenceInputError):
        finding_input_from_dict(None)  # type: ignore[arg-type]


def test_ids_are_deterministic_across_builds() -> None:
    assert make_item().evidence_id == make_item().evidence_id
    assert make_item("t.py::a").evidence_id != make_item("t.py::b").evidence_id
