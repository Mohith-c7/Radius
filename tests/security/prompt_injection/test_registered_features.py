"""Contract tests every registered LLM feature must pass, plus proof the suite bites.

TEMPLATE for a new feature: add an adapter + factory to ``pi_registry.py``; it is then
run here against the whole corpus with the worst-case naive model automatically.
"""

from __future__ import annotations

import pytest
from pi_harness import (
    PLANTED_ENV,
    TEST_NONCE,
    NaiveCompliantModel,
    WellBehavedModel,
    check_outcome,
    inputs_for,
    load_cases,
)
from pi_registry import KNOWN_BAD_FEATURES, REGISTERED_FEATURES

CASES = load_cases()
SECRETS = list(PLANTED_ENV.values())


@pytest.mark.parametrize("feature_name", sorted(REGISTERED_FEATURES))
@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
@pytest.mark.parametrize("model_name", ["naive_compliant", "well_behaved"])
def test_registered_feature_contract(feature_name, case, model_name):
    model = NaiveCompliantModel(SECRETS) if model_name == "naive_compliant" else WellBehavedModel()
    inputs = inputs_for(case)
    out = REGISTERED_FEATURES[feature_name]().run(
        inputs, model=model, nonce=TEST_NONCE, secrets=SECRETS
    )
    assert check_outcome(out, inputs=inputs, secrets=SECRETS) == []
    assert not out.verdict_inputs, "LLM output must never reach verdict logic"


@pytest.mark.parametrize("feature_name", sorted(KNOWN_BAD_FEATURES))
def test_suite_catches_naive_implementation(feature_name):
    """The harness must flag the anti-pattern on every case the stub obeys."""

    obeyed = [c for c in CASES if c.naive_obeys]
    assert len(obeyed) >= 50
    missed = []
    for case in obeyed:
        inputs = inputs_for(case)
        out = KNOWN_BAD_FEATURES[feature_name]().run(
            inputs, model=NaiveCompliantModel(SECRETS), nonce=TEST_NONCE, secrets=SECRETS
        )
        real = [
            v
            for v in check_outcome(out, inputs=inputs, secrets=SECRETS)
            if v != "prompt_without_delimiters"
        ]
        if not real:
            missed.append(case.id)
    assert missed == [], "obeyed attacks with no concrete violation"


def test_naive_feature_leaks_secret_and_sets_verdict():
    by_id = {c.id: c for c in CASES}
    naive = KNOWN_BAD_FEATURES["reference-naive"]
    leak_inputs = inputs_for(by_id["PI-EX-01"])
    out = naive().run(
        leak_inputs, model=NaiveCompliantModel(SECRETS), nonce=TEST_NONCE, secrets=SECRETS
    )
    assert "emitted_secret" in check_outcome(out, inputs=leak_inputs, secrets=SECRETS)
    vm_inputs = inputs_for(by_id["PI-VM-03"])
    out = naive().run(
        vm_inputs, model=NaiveCompliantModel(SECRETS), nonce=TEST_NONCE, secrets=SECRETS
    )
    assert out.verdict_inputs == {"verdict": "verified"}
    assert "verdict_influenced" in check_outcome(out, inputs=vm_inputs, secrets=SECRETS)


def test_naive_feature_flagged_structurally_even_with_polite_model():
    case = next(c for c in CASES if c.category == "benign_control")
    inputs = inputs_for(case)
    out = KNOWN_BAD_FEATURES["reference-naive"]().run(
        inputs, model=WellBehavedModel(), nonce=TEST_NONCE, secrets=SECRETS
    )
    assert "prompt_without_delimiters" in check_outcome(out, inputs=inputs, secrets=SECRETS)
