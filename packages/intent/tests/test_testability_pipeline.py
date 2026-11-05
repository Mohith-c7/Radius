"""Pipeline integration, word-list schema and the accuracy helper."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from extraction_helpers import src
from radius_intent.domain import (
    CriterionState,
    IntentSourceKind,
    Testability,
    TestabilityAssessment,
)
from radius_intent.infrastructure.extraction import DeterministicCriterionExtractor
from radius_intent.infrastructure.testability import (
    REQUIRED_LISTS,
    WORDLIST_SCHEMA,
    DeterministicTestabilityRater,
    LabeledCaseError,
    WordListError,
    evaluate,
    load_labeled,
    load_wordlists,
    parse_labeled_line,
    rate_criteria,
    rate_criteria_report,
    validate_wordlists,
)
from radius_intent.interfaces import TestabilityRater

BODY = """## Acceptance criteria
- The API returns 404 when the user does not exist
- The UI should be intuitive and clean
- Rename `UserService` to `AccountService`
- Latency stays under 200 ms at p95
- Legal must approve the wording

```gherkin
Scenario: Login
  Given a registered user
  When they submit valid credentials
  Then they are redirected to the dashboard
```
"""

SPEC = (
    'version: 1\ncriteria:\n  - id: C1\n    text: "it works"\n'
    '    tests: ["tests/t.py::test_it"]\n  - id: C2\n    text: "make it nicer"\n'
)


def extract(text, kind=IntentSourceKind.PR_BODY):
    return DeterministicCriterionExtractor().extract(src(text, kind, "s-1"))


def test_rater_satisfies_the_port():
    rater: TestabilityRater = DeterministicTestabilityRater()
    criterion = extract(BODY)[0]
    assessment = rater.rate(criterion)
    assert isinstance(assessment, TestabilityAssessment)
    assert assessment.rating is Testability.BEHAVIORAL_TESTABLE
    assert assessment.rationale and "testability-rules-v1" in assessment.rationale


def test_rate_criteria_sets_rating_and_rationale_immutably():
    criteria = extract(BODY)
    assert all(c.testability is Testability.UNRATED for c in criteria)
    rated = rate_criteria(criteria)
    assert [c.testability for c in rated] == [
        Testability.BEHAVIORAL_TESTABLE,
        Testability.SUBJECTIVE_OR_VAGUE,
        Testability.STRUCTURAL_CHECKABLE,
        Testability.NON_FUNCTIONAL_MEASURABLE,
        Testability.UNTESTABLE_EXTERNAL,
        Testability.BEHAVIORAL_TESTABLE,
    ]
    # originals untouched; everything but the rating is preserved
    assert all(c.testability is Testability.UNRATED for c in criteria)
    for before, after in zip(criteria, rated, strict=True):
        assert (before.id, before.text, before.span, before.weight, before.state) == (
            after.id,
            after.text,
            after.span,
            after.weight,
            after.state,
        )
        assert after.testability_rationale


def test_rate_criteria_is_idempotent_and_ordered():
    criteria = extract(BODY)
    once = rate_criteria(criteria)
    assert rate_criteria(once) == once
    assert rate_criteria(reversed(criteria)) == tuple(reversed(once))
    assert rate_criteria(()) == ()


def test_rating_keeps_confirmation_state():
    confirmed = extract(BODY)[0].confirm()
    (rated,) = rate_criteria([confirmed])
    assert rated.state is CriterionState.CONFIRMED
    assert rated.testability is Testability.BEHAVIORAL_TESTABLE


def test_spec_file_hints_raise_the_rating():
    plain, hinted = extract(SPEC, IntentSourceKind.SPEC_FILE)
    assert hinted.hints.tests == ()
    assert plain.hints.tests == ("tests/t.py::test_it",)
    rated = rate_criteria([plain, hinted])
    assert rated[0].testability is Testability.BEHAVIORAL_TESTABLE
    assert rated[1].testability is Testability.SUBJECTIVE_OR_VAGUE
    assert "explicit_test_hint" in rated[0].testability_rationale


def test_report_counts_and_clarification_list():
    report = rate_criteria_report(extract(BODY))
    assert report.counts() == {
        "behavioral_testable": 2,
        "non_functional_measurable": 1,
        "structural_checkable": 1,
        "subjective_or_vague": 1,
        "untestable_external": 1,
    }
    assert [c.text for c in report.needs_clarification()] == [
        "The UI should be intuitive and clean",
        "Legal must approve the wording",
    ]
    assert len(report.results) == len(report.criteria) == 6


def test_custom_rater_is_used():
    words = json.loads(Path(load_path()).read_text(encoding="utf-8"))
    words["lists"]["vague_adjectives"].append("zesty")
    rater = DeterministicTestabilityRater(validate_wordlists(words))
    (c,) = extract("- The sauce must be zesty and zesty again\n")
    (rated,) = rate_criteria([c], rater)
    assert "vague_adjective" in rated.testability_rationale


def load_path() -> Path:
    import radius_intent.infrastructure.testability as pkg

    return Path(pkg.__file__).parent / "wordlists.json"


# -- word lists -----------------------------------------------------------


def good() -> dict:
    return json.loads(load_path().read_text(encoding="utf-8"))


def test_default_wordlists_load_and_are_normalized():
    lists = load_wordlists()
    assert set(lists.lists) == set(REQUIRED_LISTS)
    for name in REQUIRED_LISTS:
        entries = lists.get(name)
        assert entries == tuple(sorted(set(entries)))
        assert all(e == e.casefold() for e in entries)
    assert good()["schema"] == WORDLIST_SCHEMA


def test_load_from_explicit_path(tmp_path):
    path = tmp_path / "w.json"
    path.write_text(json.dumps(good()), encoding="utf-8")
    assert load_wordlists(path) == load_wordlists()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(schema="other"),
        lambda d: d.update(lists=[]),
        lambda d: d["lists"].pop("modal_verbs"),
        lambda d: d["lists"].update(extra=["x"]),
        lambda d: d["lists"].update(modal_verbs=[]),
        lambda d: d["lists"].update(modal_verbs="must"),
        lambda d: d["lists"].update(modal_verbs=["must", 3]),
        lambda d: d["lists"].update(modal_verbs=["  "]),
        lambda d: d["lists"].update(modal_verbs=["x" * 100]),
        lambda d: d["lists"].update(modal_verbs=["bad\x00word"]),
        lambda d: d["lists"].update(modal_verbs=["w"] * 2001),
    ],
)
def test_schema_violations_are_rejected(mutate):
    data = good()
    mutate(data)
    with pytest.raises(WordListError):
        validate_wordlists(data)


def test_non_object_and_unreadable_files(tmp_path):
    with pytest.raises(WordListError):
        validate_wordlists([])
    with pytest.raises(WordListError):
        load_wordlists(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(WordListError):
        load_wordlists(bad)


def test_wordlist_order_does_not_change_ratings():
    data = good()
    for name in data["lists"]:
        data["lists"][name] = list(reversed(data["lists"][name]))
    shuffled = DeterministicTestabilityRater(validate_wordlists(data))
    base = DeterministicTestabilityRater()
    for text in ("Users can log in", "Make it nicer", "Bump foo to 1.0.0"):
        assert shuffled.rate_text(text) == base.rate_text(text)


# -- accuracy helper ------------------------------------------------------


def test_parse_labeled_line():
    case = parse_labeled_line(
        '{"id":"a","text":"x y z","label":"testable","source":"spec_file",'
        '"tests":["t::t"],"lang":"en"}'
    )
    assert case.label is Testability.BEHAVIORAL_TESTABLE  # legacy value
    assert case.source_kind is IntentSourceKind.SPEC_FILE and case.tests == ("t::t",)
    for bad in (
        "{",
        '{"id":"a","text":"t","label":"nope"}',
        '{"id":"a","text":"t","label":"unrated"}',
        '{"text":"t","label":"vague"}',
        "[]",
        '{"id":"a","text":"t","label":"vague","source":"zzz"}',
    ):
        with pytest.raises(LabeledCaseError):
            parse_labeled_line(bad, 3)


def test_load_labeled_skips_blank_lines(tmp_path):
    path = tmp_path / "l.jsonl"
    path.write_text(
        '{"id":"a","text":"Fix the bug","label":"vague"}\n\n', encoding="utf-8"
    )
    (case,) = load_labeled(path)
    report = evaluate([case])
    assert report.accuracy == 1.0 and report.mistakes == ()
    assert evaluate([]).accuracy == 0.0


def test_evaluate_reports_mistakes_and_per_label():
    cases = [
        parse_labeled_line(
            '{"id":"ok","text":"Rename Foo to Bar","label":"structural_checkable"}'
        ),
        parse_labeled_line(
            '{"id":"bad","text":"Rename Foo to Bar","label":"untestable_external"}'
        ),
    ]
    report = evaluate(cases)
    assert (report.correct, report.total) == (1, 2)
    assert report.mistakes == (("bad", "untestable_external", "structural_checkable"),)
    stats = {s.label: s for s in report.per_label}
    assert stats["structural_checkable"].precision == 0.5
    assert stats["untestable_external"].recall == 0.0
    assert "bad: untestable_external -> structural_checkable" in report.format()
