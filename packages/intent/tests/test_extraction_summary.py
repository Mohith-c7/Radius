"""Opt-in summary extraction mode: what it takes, what it refuses, how it is labelled."""

from __future__ import annotations

import pytest
from extraction_helpers import src
from radius_intent.domain import CriterionState, IntentSourceKind
from radius_intent.infrastructure import default_extractors
from radius_intent.infrastructure.extraction import (
    SUMMARY_EXTRACTOR_VERSION,
    DeterministicCriterionExtractor,
    ExtractionConfig,
    normalize_mode,
)

WORDS = [
    "alpha",
    "bravo",
    "charlie",
    "delta",
    "echo",
    "foxtrot",
    "golf",
    "hotel",
    "india",
    "juliet",
    "kilo",
    "lima",
    "mike",
    "november",
    "oscar",
    "papa",
    "quebec",
    "romeo",
]
SUMMARY = DeterministicCriterionExtractor(ExtractionConfig(mode="summary"))
SECTIONS = DeterministicCriterionExtractor()

BODY = """## Summary
- Rejects uploads larger than 5 MB with a 413
- The login form must show an error for a wrong password
- Users no longer see the draft banner after publishing
- Storage layer rewrite
- [ ] I have read the contributing guide
- https://example.com/some/long/path
- Generated with a tool, adds nothing here today
- Co-Authored-By: Someone <a@b.c>

## Test plan
- Ran the unit tests locally and they passed
- The cache should be cleared when a user logs out

## Notes
- Adds an unrelated line under an unknown heading
"""


def _report(text, kind=IntentSourceKind.PR_BODY, extractor=SUMMARY):
    return extractor.extract_report(src(text, kind))


def test_default_mode_is_sections_and_finds_nothing_in_ordinary_text() -> None:
    assert ExtractionConfig().mode == "sections"
    # sections mode already reads sentences with "must"/"should"; nothing else
    assert [c.text for c in SECTIONS.extract(src(BODY))] == [
        "The login form must show an error for a wrong password",
    ]
    assert (
        SECTIONS.extract(src("## Summary\n- Rejects uploads larger than 5 MB\n")) == ()
    )
    assert default_extractors()[1].config.mode == "sections"


def test_summary_mode_keeps_behavioural_bullets_and_records_the_rule() -> None:
    rep = _report(BODY)
    texts = [c.text for c in rep.criteria]
    assert texts == [
        "Rejects uploads larger than 5 MB with a 413",
        "The login form must show an error for a wrong password",
        "Users no longer see the draft banner after publishing",
        "The cache should be cleared when a user logs out",
    ]
    rules = {t.criterion_id: t.rule for t in rep.traces}
    got = [rules[c.id] for c in rep.criteria]
    assert got[0] == "summary_lead_verb"
    assert got[2] == "summary_marker"
    assert all(r for r in got)


def test_boilerplate_links_testplan_and_unknown_sections_are_skipped() -> None:
    rep = _report(BODY)
    texts = " ".join(c.text for c in rep.criteria)
    for bad in (
        "contributing",
        "example.com",
        "Generated",
        "Co-Authored",
        "Ran the unit",
        "unrelated",
    ):
        assert bad not in texts
    codes = {d.code for d in rep.diagnostics}
    assert {"summary_skip_boilerplate", "summary_skip_not_behavioural"} <= codes


def test_criteria_are_proposed_low_weight_unhinted_and_versioned() -> None:
    crits = [
        c
        for c in _report(BODY).criteria
        if "must" not in c.text and "should" not in c.text
    ]
    assert len(crits) == 2
    for c in crits:
        assert c.state is CriterionState.PROPOSED
        assert c.weight == 0.5
        assert c.hints.is_empty
        assert c.origin.extractor_version == SUMMARY_EXTRACTOR_VERSION
        assert c.origin.source.kind is IntentSourceKind.PR_BODY


def test_conventional_title_becomes_a_criterion_and_other_types_do_not() -> None:
    rep = _report("fix(api): reject empty bearer tokens", IntentSourceKind.PR_TITLE)
    assert [c.text for c in rep.criteria] == ["reject empty bearer tokens"]
    assert rep.traces[0].rule == "summary_title"
    assert _report("chore: bump deps", IntentSourceKind.PR_TITLE).criteria == ()
    assert _report("Update things", IntentSourceKind.PR_TITLE).criteria == ()


def test_other_source_kinds_are_untouched() -> None:
    text = "## Summary\n- Adds a retry to the client\n"
    assert _report(text, IntentSourceKind.COMMENT).criteria == ()
    assert _report(text, IntentSourceKind.ISSUE).criteria == ()


def test_cap_dedupe_length_and_code_fences() -> None:
    many = "## Changes\n" + "".join(f"- Adds support for {w} handling\n" for w in WORDS)
    rep = _report(many)
    assert len(rep.criteria) == 12
    assert "summary_max_criteria" in {d.code for d in rep.diagnostics}
    dup = "## Changes\n- Adds a retry to the client\n- adds a retry to the client.\n"
    assert len(_report(dup).criteria) == 1
    long = "## Changes\n- Adds " + "very " * 80 + "long thing\n"
    assert _report(long).criteria == ()
    fenced = "## Changes\n```\n- Adds a retry to the client\n```\n"
    assert _report(fenced).criteria == ()


def test_checked_items_under_summary_are_read_but_templates_are_not() -> None:
    text = (
        "## Summary\n- [x] Adds a retry to the client\n- [ ] Tests added and passing\n"
    )
    assert [c.text for c in _report(text).criteria] == ["Adds a retry to the client"]


def test_output_is_deterministic_and_ids_are_stable() -> None:
    a, b = _report(BODY), _report(BODY)
    assert [c.id for c in a.criteria] == [c.id for c in b.criteria]
    assert a.traces == b.traces


def test_the_same_text_in_two_places_is_one_criterion() -> None:
    text = (
        "## Acceptance criteria\n- Rejects uploads larger than 5 MB\n\n"
        "## Summary\n- Rejects uploads larger than 5 MB\n"
    )
    assert len(_report(text).criteria) == 1


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "sections"),
        ("", "sections"),
        ("summary", "summary"),
        (" SUMMARY ", "summary"),
        ("bullets", "sections"),
    ],
)
def test_normalize_mode_fails_closed(value, expected) -> None:
    assert normalize_mode(value) == expected


def test_default_extractors_take_the_mode() -> None:
    assert default_extractors("summary")[1].config.mode == "summary"
    assert default_extractors("nonsense")[1].config.mode == "sections"
    with pytest.raises(ValueError, match="mode"):
        ExtractionConfig(mode="nonsense")
