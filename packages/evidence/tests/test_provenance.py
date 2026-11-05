"""Contract 3: provenance tags, the author hint cap setting and the new flag."""

from __future__ import annotations

from radius_evidence.domain.config import LinkMapping, VerdictV2Config
from radius_evidence.domain.enums import (
    ALL_PROVENANCE,
    TRUSTED_HINT_PROVENANCE,
    Flag,
    Provenance,
)
from radius_evidence.domain.inputs import CriterionInput, CriterionTestEdgeInput


def test_provenance_values_are_the_documented_five() -> None:
    assert {p.value for p in Provenance} == ALL_PROVENANCE == {
        "author_pr_body",
        "author_head_spec",
        "base_spec",
        "human_confirmed",
        "llm_proposed",
    }
    assert TRUSTED_HINT_PROVENANCE < ALL_PROVENANCE
    assert TRUSTED_HINT_PROVENANCE == {"base_spec", "human_confirmed"}


def test_new_fields_are_optional_and_default_to_author_controlled() -> None:
    c = CriterionInput("c", "t", 1.0, "behavioral_testable", "proposed")
    assert (c.provenance, c.hints_provenance) == ("author_pr_body", "author_pr_body")
    e = CriterionTestEdgeInput("c", "t.py::t", 1.0, "intent_yml_hint")
    assert e.provenance == ""


def test_inputs_round_trip_with_and_without_the_tags() -> None:
    c = CriterionInput(
        "c", "t", 1.0, "behavioral_testable", "confirmed",
        hints_tests=("t.py",), provenance="human_confirmed", hints_provenance="base_spec",
    )
    assert CriterionInput.from_dict(c.to_dict()) == c
    legacy = {k: v for k, v in c.to_dict().items() if "provenance" not in k}
    assert CriterionInput.from_dict(legacy).hints_provenance == "author_pr_body"


def test_flag_and_cap_defaults() -> None:
    assert Flag.AUTHOR_SUPPLIED_HINT.value == "author_supplied_hint"
    assert VerdictV2Config().link.author_hint_cap == 0.7
    assert 0.0 < LinkMapping().author_hint_cap < LinkMapping().hint_test_weight
