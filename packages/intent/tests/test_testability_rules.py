"""Rule-by-rule unit tests: each rule fires on a positive and not on a negative."""

from __future__ import annotations

import pytest
from radius_intent.domain import IntentSourceKind, Testability
from radius_intent.infrastructure.testability import (
    MAX_ANALYSED_CHARS,
    RULES,
    TESTABILITY_RULES_VERSION,
    Confidence,
    DeterministicTestabilityRater,
    Group,
)

RATER = DeterministicTestabilityRater()

#: rule id -> (text that fires it, text that must not fire it)
RULE_CASES: dict[str, tuple[str, str]] = {
    "http_status": ("returns 404 for unknown ids", "returns 404 users"),
    "observable_verb": ("the form redirects to login", "make it so"),
    "error_wording": ("shows an error banner", "shows a banner"),
    "quantity_threshold": ("waits 30 seconds", "waits a while"),
    "code_reference": ("call `parse()` in src/app/main.py", "call the parser"),
    "condition_clause": ("when the user logs in", "the user logs in"),
    "result_clause": ("then they see a banner", "they see a banner"),
    "modal_verb": ("the tool must exit", "the tool exits"),
    "passive_requirement": ("tokens must be revoked", "tokens are revoked"),
    "comparator": ("at least five", "five"),
    "negation": ("never log secrets", "log secrets"),
    "literal_value": ('prints "hello world"', "prints hello world"),
    "structural_verb": ("rename the module", "use the module"),
    "docs_config_edit": ("Update the README", "The README is updated by CI"),
    "structural_noun": ("the changelog lists it", "the list shows it"),
    "nfr_term": ("lower latency overall", "lower overall"),
    "time_budget": ("finishes within 200 ms", "finishes within reason"),
    "measure_tool": ("no findings in bandit", "no findings"),
    "placeholder": ("TBD", "to be tested"),
    "vague_adjective": ("keep it clean", "keep it tidy"),
    "weasel_word": ("support formats etc", "support csv and json"),
    "external_judgment": ("legal must approve", "the plain path"),
    "live_system": ("works in production", "works locally"),
    "too_short": ("works", "the thing works fine"),
    "non_english_fallback": ("Le système doit être rapide", "The system is fast"),
}


@pytest.mark.parametrize("rule_id", sorted(RULE_CASES))
def test_rule_fires_and_does_not_fire(rule_id):
    positive, negative = RULE_CASES[rule_id]
    assert rule_id in RATER.rate_text(positive).rule_ids
    assert rule_id not in RATER.rate_text(negative).rule_ids


def test_hint_and_origin_rules():
    plain = RATER.rate_text("it works")
    hinted = RATER.rate_text(
        "it works",
        tests=("tests/t.py::t",),
        paths=("src/**",),
        source_kind=IntentSourceKind.SPEC_FILE,
    )
    assert {"explicit_test_hint", "path_hint", "spec_file_origin"} <= set(
        hinted.rule_ids
    )
    assert "explicit_test_hint" not in plain.rule_ids
    assert hinted.rating is Testability.BEHAVIORAL_TESTABLE
    assert plain.rating is Testability.SUBJECTIVE_OR_VAGUE


def test_gherkin_and_version_rules():
    g = RATER.rate_text("Scenario Outline: x: Given a; When b; Then c")
    assert "gherkin_scenario" in g.rule_ids
    assert g.rating is Testability.BEHAVIORAL_TESTABLE
    assert "version_number" in RATER.rate_text("Bump foo to 1.2.3").rule_ids
    assert "version_number" not in RATER.rate_text("Wait 1.5 s").rule_ids


def test_docs_edit_dropped_under_condition():
    r = RATER.rate_text("Update the config when the user logs in")
    assert "docs_config_edit" not in r.rule_ids


def test_every_rule_has_a_case_or_dedicated_test():
    dedicated = {
        "explicit_test_hint",
        "path_hint",
        "spec_file_origin",
        "gherkin_scenario",
        "version_number",
        "text_truncated",
        "no_testable_signal",
        "nfr_without_threshold",
    }
    assert set(RULES) == set(RULE_CASES) | dedicated
    assert all(spec.rule_id == key for key, spec in RULES.items())


def test_meta_reasons():
    assert "no_testable_signal" in RATER.rate_text("Fix the bug").rule_ids
    nfr = RATER.rate_text("Improve security overall")
    assert "nfr_without_threshold" in nfr.rule_ids
    long = RATER.rate_text("it must return 404 " + "x" * (MAX_ANALYSED_CHARS + 10))
    assert "text_truncated" in long.rule_ids


def test_spans_point_into_the_text():
    text = "The API returns 404 when the `user_id` is unknown."
    result = RATER.rate_text(text)
    for reason in result.reasons:
        for span in reason.spans:
            assert text[span.start : span.end].startswith(span.text[:5].rstrip("~"))
    http = next(r for r in result.reasons if r.rule_id == "http_status")
    assert http.spans[0].text == "returns 404"


def test_decision_precedence():
    assert RATER.rate_text("TBD").rating is Testability.SUBJECTIVE_OR_VAGUE
    # a linked test does not turn an undefined criterion into a defined one
    assert (
        RATER.rate_text("TBD", tests=("a::b",)).rating
        is Testability.SUBJECTIVE_OR_VAGUE
    )
    # external judgment beats behavioral wording
    assert (
        RATER.rate_text("Legal must approve the wording").rating
        is Testability.UNTESTABLE_EXTERNAL
    )
    # a status code makes a rate-limit rule behavioral, not non-functional
    assert (
        RATER.rate_text("Rate limit returns 429 after 100 requests").rating
        is Testability.BEHAVIORAL_TESTABLE
    )
    # threshold present -> non-functional measurable; absent -> vague
    assert (
        RATER.rate_text("Latency is under 200 ms").rating
        is Testability.NON_FUNCTIONAL_MEASURABLE
    )
    assert (
        RATER.rate_text("Latency should be low").rating
        is Testability.SUBJECTIVE_OR_VAGUE
    )
    # vague wording outweighs one weak behavioral cue
    assert (
        RATER.rate_text("Error handling should be robust").rating
        is Testability.SUBJECTIVE_OR_VAGUE
    )
    # a behavioral frame keeps ambiguous verbs from being structural
    assert (
        RATER.rate_text(
            "Given a user, when they open the page, then they see the upgrade prompt"
        ).rating
        is Testability.BEHAVIORAL_TESTABLE
    )


def test_nfr_with_strong_behavior_is_behavioral_low():
    r = RATER.rate_text(
        "Security: the endpoint must reject, redact and log invalid tokens"
    )
    assert r.rating is Testability.BEHAVIORAL_TESTABLE
    assert r.confidence is Confidence.LOW


def test_confidence_bands():
    high = RATER.rate_text("Bump requests to 2.32.0 in pyproject.toml")
    assert (high.rating, high.confidence) == (
        Testability.STRUCTURAL_CHECKABLE,
        Confidence.HIGH,
    )
    strong = RATER.rate_text(
        "POST /api/orders must reject an invalid body with status 400 when empty"
    )
    assert strong.confidence is Confidence.HIGH
    assert RATER.rate_text("Fix the bug").confidence is Confidence.LOW
    assert RATER.rate_text("It should be clean and robust").confidence is (
        Confidence.HIGH
    )
    cut = RATER.rate_text("TBD " + "x" * (MAX_ANALYSED_CHARS + 1))
    assert cut.confidence is Confidence.MEDIUM


def test_rewrite_hints_for_vague_and_external():
    vague = RATER.rate_text("Make it clean etc")
    joined = " ".join(vague.rewrite_hints)
    assert "clean" in joined and "etc" in joined
    assert "Try:" in vague.rationale()
    assert RATER.rate_text("TBD").rewrite_hints[0].startswith("Replace the placeholder")
    nfr = RATER.rate_text("Latency should be low")
    assert "measurable threshold" in nfr.rewrite_hints[0]
    short = RATER.rate_text("works")
    assert any("who does what" in h for h in short.rewrite_hints)
    ext = RATER.rate_text("Legal must approve it")
    assert any("approval" in h for h in ext.rewrite_hints)
    foreign = RATER.rate_text("Le système doit être rapide")
    assert any("English summary" in h for h in foreign.rewrite_hints)
    assert RATER.rate_text("Rename Foo to Bar").rewrite_hints == ()


def test_reason_order_and_rationale_shape():
    r = RATER.rate_text("The API returns 404 when the user is missing")
    assert r.reasons[0].group is Group.BEHAVIORAL
    weights = [x.weight for x in r.reasons if x.group is Group.BEHAVIORAL]
    assert weights == sorted(weights, reverse=True)
    rationale = r.rationale()
    assert TESTABILITY_RULES_VERSION in rationale
    assert "confidence=" in rationale and "rules=http_status" in rationale
    assert "\n" not in rationale
    data = r.to_dict()
    assert data["rules_version"] == TESTABILITY_RULES_VERSION
    assert data["reasons"][0]["spans"][0][2] == "returns 404"


def test_rationale_never_contains_control_characters():
    r = RATER.rate_text("`bad\x00name\x07` must return 404")
    assert "\x00" not in r.rationale() and "\x07" not in r.rationale()
    assert r.to_assessment().rationale == r.rationale()


def test_readme_documents_every_rule():
    from pathlib import Path

    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")
    missing = [rule_id for rule_id in RULES if f"`{rule_id}`" not in readme]
    assert missing == []
    assert TESTABILITY_RULES_VERSION in readme
