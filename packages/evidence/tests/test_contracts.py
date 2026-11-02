"""Every contract dataclass round-trips through stable JSON; defaults are pinned."""

from __future__ import annotations

import json

import pytest
from radius_evidence.domain.config import (
    DEFAULT_ASSERTION_SCORES,
    QualityConfig,
    VerdictV2Config,
)
from radius_evidence.domain.enums import (
    AssertKind,
    AuthoredBy,
    EdgeKind,
    EvidenceKind,
    EvidenceSource,
    IndependenceBasis,
    NodeKind,
    Outcome,
    SupportState,
)
from radius_evidence.domain.ieg import Ieg, IegEdge, IegNode
from radius_evidence.domain.inputs import (
    CaseOutcomeInput,
    CriterionInput,
    CriterionSymbolEdgeInput,
    CriterionTestEdgeInput,
    StageAInput,
    StageBInput,
    SymbolInput,
    SymbolTestEdgeInput,
    TamperFindingInput,
)
from radius_evidence.domain.model import (
    AssertionFact,
    AssertionFeatures,
    EvidenceItem,
    FlakyInfo,
    FreshnessBinding,
    FreshnessInfo,
    IndependenceInfo,
    Reason,
)
from radius_evidence.domain.quality import ChainRef, EvidenceQuality, QualityBreakdown
from radius_evidence.domain.serialization import canonical_json
from radius_evidence.domain.states import CriterionStateResult, UimResult
from radius_evidence.domain.support import SupportResult
from radius_evidence.domain.versions import ALGO_VERSION, DEFAULT_COMPONENT_VERSIONS

SHA = "4f2a9d1c0b7e6a53f8c1d2e3b4a59687c0d1e2f3"


def _features() -> AssertionFeatures:
    return AssertionFeatures(
        test_id="tests/test_v.py::test_a",
        path="tests/test_v.py",
        line_start=14,
        line_end=17,
        assertions=(
            AssertionFact(
                kind=AssertKind.VALUE_EQUALITY,
                line=16,
                compares_computed_value=True,
            ),
        ),
        n_assertions=1,
        expects_exception=False,
        is_parametrized=False,
        n_param_cases=None,
        has_skip_marker=False,
        name_terms=("reject", "digit"),
        literal_terms=("abcdefgh",),
        called_symbol_refs=("src/v.py::validate",),
    )


def _item() -> EvidenceItem:
    return EvidenceItem(
        evidence_id="ev_7c1e90ab53d2f1a44b0e",
        kind=EvidenceKind.TEST_OUTCOME,
        source=EvidenceSource.CI_UPLOAD,
        analysis_id="a-1",
        repository_id="r-1",
        head_sha=SHA,
        subject_id="tests/test_v.py::test_a",
        path="tests/test_v.py",
        symbol_ids=("python:src/v.py::validate#function@1",),
        criterion_ids=("c_1",),
        outcome=Outcome.PASSED,
        duration_ms=3,
        features=_features(),
        severity=None,
        rule_id=None,
        independence=IndependenceInfo(
            authored_by=AuthoredBy.UNKNOWN,
            basis=IndependenceBasis.CHANGED_IN_PR,
            factor=0.8,
            reasons=(Reason("test_added_in_pr", "test function is new in this PR"),),
        ),
        flaky=FlakyInfo(flagged=False),
        freshness=FreshnessInfo(SHA, SHA, 1.0, "current_head"),
        reasons=(),
        collected_at="2026-11-02T10:15:00Z",
        algo_versions={"assertions": "test-assertions-v1"},
    )


def _quality() -> EvidenceQuality:
    return EvidenceQuality(
        evidence_id="ev_1",
        criterion_id="c_1",
        a_static=1.0,
        d_eff=0.6,
        cap_static=0.6,
        i=0.8,
        f=1.0,
        flaky_f=1.0,
        tamper_penalty=0.0,
        q=0.48,
        l_cs=1.0,
        l_st=0.9,
        r_ct=1.0,
        l=0.9,
        term=0.432,
        status="counted",
        group_symbol="sym",
        rank_in_group=0,
        discount=1.0,
        contribution=0.432,
        path=ChainRef("sym", "tst", 1.0, 0.9, 1.0),
    )


def _stage_a() -> StageAInput:
    return StageAInput(
        analysis_id="a-1",
        repository_id="r-1",
        head_sha=SHA,
        changeset_ref="base..head",
        criteria=(CriterionInput("c_1", "text", 1.0, "behavioral_testable", "confirmed"),),
        symbols=(
            SymbolInput("s1", "src/v.py", "validate", "function", "python",
                        "modified_body", True, False, False),
        ),
        criterion_symbol=(
            CriterionSymbolEdgeInput("c_1", "s1", 0.5, 1, {"lexical": 0.31},
                                     (Reason("lexical", "bm25"),)),
        ),
        symbol_test=(SymbolTestEdgeInput("s1", "tst", 0.9, "direct_call", 1),),
        criterion_test=(CriterionTestEdgeInput("c_1", "tst", 1.0, "intent_yml_hint"),),
        assertions=(_features(),),
        tamper=(TamperFindingInput("tf_1", "T001", "assert_removed", "high", 0.9, "t.py"),),
        changed_test_ids=frozenset({"b", "a"}),
        degraded=("truncated",),
        algo_versions={"tamper": "tamper-rules-v1"},
    )


def _stage_b() -> StageBInput:
    return StageBInput(
        stage_a=_stage_a(),
        cases=(CaseOutcomeInput("tst", "t.py", "C", "n", Outcome.PASSED),),
        uploads=1,
        flaky_test_ids=frozenset({"z", "y"}),
        flaky_scores={"y": 0.25},
        results_received=True,
    )


SAMPLES = [
    Reason("code", "detail", "ref"),
    _features(),
    _item(),
    _quality(),
    ChainRef("s", "t"),
    SupportResult("c_1", 0.432, 0.432, (_quality(),), 1, True),
    CriterionStateResult("c_1", SupportState.PROVEN),
    UimResult(0.75, 3.0, 4.0, 1.0, ("c_2",)),
    IegNode("crit:c_1", NodeKind.CRITERION, "c_1", {"k": 1}),
    IegEdge("e_1", EdgeKind.IMPLEMENTED_BY, "crit:c_1", "sym:s1", 0.5, "combined",
            (Reason("r", "d"),), {"rank": 1}),
    Ieg("a-1", SHA, (IegNode("crit:c_1", NodeKind.CRITERION, "c_1"),), (), "d"),
    _stage_a(),
    _stage_b(),
    VerdictV2Config(),
    QualityConfig(),
]


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda s: type(s).__name__)
def test_round_trip_through_dict_and_json(sample) -> None:
    cls = type(sample)
    assert cls.from_dict(sample.to_dict()) == sample
    assert cls.from_json(sample.to_json()) == sample
    assert json.loads(sample.to_json()) == sample.to_dict()


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda s: type(s).__name__)
def test_json_is_stable_and_sorted(sample) -> None:
    text = sample.to_json()
    assert text == canonical_json(sample)
    assert text == json.dumps(
        json.loads(text), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def test_sets_serialize_sorted_and_floats_round() -> None:
    data = _stage_a().to_dict()
    assert data["changed_test_ids"] == ["a", "b"]
    assert UimResult(0.1234567891, 0.0, 0.0, 1.0).to_dict()["uim"] == 0.123457


def test_unknown_keys_are_ignored_on_read() -> None:
    data = {**Reason("c", "d").to_dict(), "future_field": 1}
    assert Reason.from_dict(data) == Reason("c", "d")


@pytest.mark.parametrize(
    "sha", ["", "abc", "G" * 40, SHA.upper(), SHA + "0", SHA[:-1]]
)
def test_evidence_item_rejects_unbound_or_malformed_sha(sha: str) -> None:
    data = {**_item().to_dict(), "head_sha": sha}
    with pytest.raises(ValueError, match="head_sha"):
        EvidenceItem.from_dict(data)


def test_aliases_point_at_the_contract_classes() -> None:
    assert QualityBreakdown is EvidenceQuality
    assert FreshnessBinding is FreshnessInfo


def test_support_state_is_not_the_intent_lifecycle_state() -> None:
    assert {s.value for s in SupportState} == {
        "proven", "weak", "unevidenced", "contradicted", "excluded",
    }


def test_alpha_static_defaults_are_pinned() -> None:
    cfg = VerdictV2Config()
    assert cfg.profile == "alpha-static"
    assert (cfg.quality.cap_static, cfg.support.tau_support) == (0.60, 0.50)
    assert (cfg.quality.iota_agent, cfg.quality.iota_unknown) == (0.6, 0.8)
    assert (cfg.support.tau_weak, cfg.support.rho, cfg.support.s_cap) == (0.2, 0.7, 0.9)
    assert cfg.support.strong_min == 0.50
    assert (cfg.link.link_min_cs, cfg.link.link_sat_cs, cfg.link.min_test_link) == (
        0.20, 0.40, 0.50,
    )
    assert (cfg.link.relevance_gate, cfg.link.relevance_sat) == (0.5, 1.5)
    assert (cfg.rules.uim_max, cfg.rules.min_intent_coverage) == (0.20, 0.50)
    assert cfg.rules.fail_on_tamper_at_least == "high"
    assert cfg.rules.review_on_tamper_at_least == "medium"
    assert cfg.rules.max_bundle_bytes == 2 * 1024 * 1024
    assert cfg.quality.tamper_penalty["medium"] == 0.5
    assert set(DEFAULT_ASSERTION_SCORES) == {k.value for k in AssertKind}


def test_config_digest_is_deterministic_and_sensitive() -> None:
    a, b = VerdictV2Config(), VerdictV2Config()
    assert a.digest() == b.digest()
    assert len(a.digest()) == 64
    changed = VerdictV2Config(support=type(a.support)(tau_support=0.6))
    assert changed.digest() != a.digest()


def test_component_versions_cover_the_justification_keys() -> None:
    assert DEFAULT_COMPONENT_VERSIONS["verdict"] == ALGO_VERSION == "verdict-v2-alpha-1"
    assert len(DEFAULT_COMPONENT_VERSIONS) == 12


# ----------------------------------------------------------------- contract 2


def test_contract_two_fields_default_to_the_old_behaviour() -> None:
    from radius_evidence.domain.versions import CONTRACT_VERSION

    assert CONTRACT_VERSION == "verdict-v2-contract-4"
    fact = AssertionFact(AssertKind.VALUE_EQUALITY, 3)
    assert not any(
        (fact.mock_only, fact.circular, fact.dead, fact.swallowed, fact.in_loop, fact.property_based)
    )
    assert Reason("c", "d").rule_id is None
    sa = _stage_a()
    assert sa.added_test_ids == frozenset() and sa.agent_signal_by_test == {}


def test_contract_one_payloads_still_load() -> None:
    old_fact = {"kind": "value_equality", "line": 4, "note": "mock_only in_loop"}
    fact = AssertionFact.from_dict(old_fact)
    assert fact.note == "mock_only in_loop" and fact.mock_only is False
    data = _stage_a().to_dict()
    for key in ("added_test_ids", "agent_signal_by_test"):
        data.pop(key, None)
    assert StageAInput.from_dict(data).added_test_ids == frozenset()
    assert Reason.from_dict({"code": "c", "detail": "d", "ref": "R2b"}).rule_id is None


def test_contract_two_fields_round_trip() -> None:
    fact = AssertionFact(
        AssertKind.TAUTOLOGY, 9, circular=True, dead=True, swallowed=True,
        mock_only=True, in_loop=True, property_based=True,
    )
    assert AssertionFact.from_json(fact.to_json()) == fact
    reason = Reason("tamper_high", "d", ref="tf_1", rule_id="R1c")
    assert Reason.from_dict(reason.to_dict()) == reason
    sa = StageAInput.from_dict(
        {**_stage_a().to_dict(), "added_test_ids": ["b"], "agent_signal_by_test": {"a": True}}
    )
    assert sa.added_test_ids == frozenset({"b"}) and sa.agent_signal_by_test == {"a": True}
    assert StageAInput.from_json(sa.to_json()) == sa


def test_freshness_reasons_allow_the_decay_value() -> None:
    from radius_evidence.domain import freshness
    from radius_evidence.domain.model import FRESHNESS_REASONS

    assert freshness.REASON_STALE_UNCHANGED in FRESHNESS_REASONS
    assert {freshness.REASON_CURRENT, freshness.REASON_STALE} <= set(FRESHNESS_REASONS)
