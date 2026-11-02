"""Corpus-driven checks of the sanitiser, prompt builder and full guarded flow."""

from __future__ import annotations

import collections

import pytest
from pi_harness import (
    TEST_NONCE,
    GuardedCriteriaFeature,
    NaiveCompliantModel,
    WellBehavedModel,
    check_outcome,
    inputs_for,
    load_cases,
    sanitize_inputs,
)
from radius_shared.llm_guard import sanitize_untrusted

CASES = load_cases()
IDS = [c.id for c in CASES]


def _secrets():
    from pi_harness import PLANTED_ENV

    return list(PLANTED_ENV.values())


def test_corpus_shape():
    assert len(CASES) >= 60
    assert len(set(IDS)) == len(IDS)
    cats = collections.Counter(c.category for c in CASES)
    assert len(cats) >= 14
    required = {
        "direct_override", "role_spoofing", "delimiter_breakout", "hidden_unicode",
        "markup_smuggling", "location_specific", "multilingual", "encoded",
        "exfiltration", "verdict_manipulation", "tool_url_lure", "oversize", "benign_control",
    }  # fmt: skip
    assert required <= set(cats)
    assert cats["benign_control"] >= 10


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_sanitizer_findings(case):
    got = sanitize_untrusted(case.payload, source_id="s", kind=case.where, secrets=_secrets())
    codes = got.finding_codes()
    assert set(case.findings) <= codes, (case.id, sorted(codes))
    assert not (set(case.forbid_findings) & codes), (case.id, sorted(codes))
    if case.guard == "pass_through":
        assert got.text == case.payload
        if case.category == "benign_control":
            assert not got.findings


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_sanitizer_deterministic(case):
    a = sanitize_untrusted(case.payload, source_id="s", kind=case.where, secrets=_secrets())
    b = sanitize_untrusted(case.payload, source_id="s", kind=case.where, secrets=_secrets())
    assert a == b
    # idempotent on strip findings: sanitised text sanitises to itself
    again = sanitize_untrusted(a.text, source_id="s", kind=case.where, secrets=_secrets())
    if "truncated" not in a.finding_codes():
        assert again.text == a.text


@pytest.mark.parametrize("case", CASES, ids=IDS)
@pytest.mark.parametrize("model_cls", [NaiveCompliantModel, WellBehavedModel])
def test_guarded_flow_is_safe(case, model_cls):
    secrets = _secrets()
    model = model_cls(secrets) if model_cls is NaiveCompliantModel else model_cls()
    inputs = inputs_for(case)
    out = GuardedCriteriaFeature().run(inputs, model=model, nonce=TEST_NONCE, secrets=secrets)
    assert check_outcome(out, inputs=inputs, secrets=secrets) == []
    assert out.verdict_inputs == {}
    if case.guard == "nonce_collision":
        assert out.rejection_code == "nonce_collision" and not out.prompts
        return
    assert out.prompts
    if model_cls is NaiveCompliantModel:
        if case.guard == "rejected_output":
            assert out.rejection_code == case.rejection_code, case.id
            assert out.fell_back
    elif case.guard == "pass_through" and case.category == "benign_control":
        assert out.rejection_code is None


@pytest.mark.parametrize("case", [c for c in CASES if c.guard == "sanitized"], ids=lambda c: c.id)
def test_sanitized_cases_never_reach_the_prompt_unsanitised(case):
    secrets = _secrets()
    inputs = inputs_for(case)
    out = GuardedCriteriaFeature().run(inputs, model=WellBehavedModel(), nonce=TEST_NONCE, secrets=secrets)
    prompt_text = "\n".join(p.user for p in out.prompts)
    for ch in ("​", "‮", "\x00", "\x1b", "<!--"):
        assert ch not in prompt_text
    for s in secrets:
        assert s not in prompt_text


def test_benign_controls_yield_criteria_with_well_behaved_model():
    secrets = _secrets()
    ok = 0
    for case in (c for c in CASES if c.category == "benign_control"):
        inputs = inputs_for(case)
        out = GuardedCriteriaFeature().run(inputs, model=WellBehavedModel(), nonce=TEST_NONCE, secrets=secrets)
        assert out.rejection_code is None, case.id
        assert '"quote"' in out.emitted
        ok += 1
    assert ok >= 10


def test_suite_is_deterministic_across_runs():
    secrets = _secrets()

    def run_all():
        res = []
        for case in CASES:
            inputs = inputs_for(case)
            o = GuardedCriteriaFeature().run(
                inputs, model=NaiveCompliantModel(secrets), nonce=TEST_NONCE, secrets=secrets
            )
            res.append((case.id, o.prompts, o.emitted, o.rejection_code, sorted(map(sorted, o.findings.values()))))
        return res

    assert run_all() == run_all()


def test_sanitize_inputs_helper_matches_guard():
    case = CASES[0]
    srcs = sanitize_inputs(inputs_for(case), _secrets())
    assert [s.source_id for s in srcs][:2] == ["pr_title", "pr_body"]
