"""IEG builder: invariants, determinism, policy for dirty input, queries, speed."""

from __future__ import annotations

import json
import random
import time
from dataclasses import replace
from typing import Any

import pytest
from radius_evidence.application.ieg_builder import (
    build_ieg,
    build_ieg_from_stage_a,
    build_ieg_with_report,
)
from radius_evidence.domain.enums import (
    AuthoredBy,
    EdgeKind,
    EvidenceKind,
    EvidenceSource,
    IndependenceBasis,
    NodeKind,
    Outcome,
)
from radius_evidence.domain.ieg import (
    ALLOWED_ENDPOINTS,
    Ieg,
    IegEdge,
    IegIndex,
    IegNode,
    edge_id,
    node_id,
    validate_ieg,
)
from radius_evidence.domain.inputs import (
    CaseOutcomeInput,
    CriterionInput,
    CriterionSymbolEdgeInput,
    CriterionTestEdgeInput,
    StageAInput,
    SymbolInput,
    SymbolTestEdgeInput,
    TamperFindingInput,
)
from radius_evidence.domain.model import (
    AssertionFeatures,
    EvidenceItem,
    FlakyInfo,
    FreshnessInfo,
    IndependenceInfo,
    Reason,
)

SHA = "a" * 40
AID = "analysis-1"


def crit(cid: str = "C1", **kw: Any) -> CriterionInput:
    base: dict[str, Any] = {
        "criterion_id": cid,
        "text": f"text {cid}",
        "weight": 1.0,
        "testability": "testable",
        "lifecycle": "confirmed",
    }
    base.update(kw)
    return CriterionInput(**base)


def sym(sid: str = "S1", **kw: Any) -> SymbolInput:
    base: dict[str, Any] = {
        "symbol_id": sid,
        "path": "src/a.py",
        "qualified_name": sid,
        "kind": "function",
        "language": "python",
        "change_kind": "modified",
        "is_behavioral": True,
        "is_test": False,
        "is_pseudo": False,
    }
    base.update(kw)
    return SymbolInput(**base)


def cs(c: str = "C1", s: str = "S1", score: float = 0.9, rank: int = 1) -> CriterionSymbolEdgeInput:
    return CriterionSymbolEdgeInput(c, s, score, rank, {"lexical": 0.3})


def st(s: str = "S1", t: str = "t.py::test_a", score: float = 0.8, kind: str = "direct_call"):
    return SymbolTestEdgeInput(s, t, score, kind, 1)


def ct(c: str = "C1", t: str = "t.py::test_a", w: float = 0.7, method: str = "lexical_test_relevance"):
    return CriterionTestEdgeInput(c, t, w, method, 1.2)


def finding(fid: str = "tf_1", **kw: Any) -> TamperFindingInput:
    base: dict[str, Any] = {
        "finding_id": fid,
        "rule_id": "T001",
        "check": "deleted",
        "severity": "high",
        "confidence": 0.9,
        "path": "t.py",
        "test_id": "t.py::test_a",
        "reason": "r",
    }
    base.update(kw)
    return TamperFindingInput(**base)


def feats(tid: str = "t.py::test_a") -> AssertionFeatures:
    return AssertionFeatures(
        test_id=tid, path=tid.split("::")[0], line_start=1, line_end=3, assertions=(),
        n_assertions=0, expects_exception=False, is_parametrized=False, n_param_cases=None,
        has_skip_marker=False, name_terms=(), literal_terms=(),
    )


def item(eid: str = "ev_1", subject: str = "t.py::test_a", **kw: Any) -> EvidenceItem:
    base: dict[str, Any] = {
        "evidence_id": eid,
        "kind": EvidenceKind.TEST_OUTCOME,
        "source": EvidenceSource.CI_UPLOAD,
        "analysis_id": AID,
        "repository_id": "repo",
        "head_sha": SHA,
        "subject_id": subject,
        "path": "t.py",
        "symbol_ids": (),
        "criterion_ids": (),
        "outcome": Outcome.PASSED,
        "duration_ms": 1,
        "features": None,
        "severity": None,
        "rule_id": None,
        "independence": IndependenceInfo(AuthoredBy.UNKNOWN, IndependenceBasis.CHANGED_IN_PR, 0.8),
        "flaky": FlakyInfo(False),
        "freshness": FreshnessInfo(SHA, SHA, 1.0, "current_head"),
        "reasons": (),
        "collected_at": "2026-11-02T10:00:00Z",
    }
    base.update(kw)
    return EvidenceItem(**base)


def build(**kw: Any) -> Ieg:
    return build_ieg(analysis_id=AID, head_sha=SHA, **kw)


def report(**kw: Any):
    return build_ieg_with_report(analysis_id=AID, head_sha=SHA, **kw)[1]


def full_inputs() -> dict[str, Any]:
    return {
        "criteria": [crit("C1"), crit("C2"), crit("C3")],
        "symbols": [sym("S1"), sym("S2")],
        "criterion_symbol": [cs("C1", "S1"), cs("C2", "S1", 0.5, 2), cs("C2", "S2", 0.6)],
        "symbol_test": [st("S1", "t.py::test_a"), st("S1", "t.py::test_b"), st("S2", "t.py::test_c")],
        "criterion_test": [ct("C1", "t.py::test_a"), ct("C2", "t.py::test_c", 1.0, "intent_yml_hint")],
        "assertions": [feats("t.py::test_a"), feats("t.py::test_b")],
        "tamper": [finding("tf_1"), finding("tf_2", test_id=None, symbol="S2")],
        "changed_test_ids": ["t.py::test_a"],
        "cases": [CaseOutcomeInput("t.py::test_a", None, None, None, Outcome.PASSED)],
        "evidence": [item("ev_1"), item("ev_2", "t.py::test_c")],
    }


# ---------------------------------------------------------------- structure


def test_empty_input_gives_empty_valid_graph() -> None:
    ieg = build()
    assert ieg.nodes == () and ieg.edges == ()
    assert validate_ieg(ieg) == ()
    assert ieg.analysis_id == AID and ieg.head_sha == SHA and ieg.algo_version == "ieg-1"


def test_full_graph_is_valid_and_complete() -> None:
    ieg = build(**full_inputs())
    assert validate_ieg(ieg) == ()
    kinds = {k: sum(1 for n in ieg.nodes if n.kind is k) for k in NodeKind}
    assert kinds == {
        NodeKind.CRITERION: 3, NodeKind.SYMBOL: 2, NodeKind.TEST: 3,
        NodeKind.EVIDENCE: 2, NodeKind.FINDING: 2,
    }
    ek = {k: sum(1 for e in ieg.edges if e.kind is k) for k in EdgeKind}
    assert ek[EdgeKind.IMPLEMENTED_BY] == 3
    assert ek[EdgeKind.EXERCISED_BY] == 3
    assert ek[EdgeKind.ADDRESSED_BY] == 2
    assert ek[EdgeKind.PRODUCED] == 2
    assert ek[EdgeKind.AFFECTS] == 2


@pytest.mark.parametrize(
    ("kind", "prefix"),
    [
        (NodeKind.CRITERION, "crit:"),
        (NodeKind.SYMBOL, "sym:"),
        (NodeKind.TEST, "tst:"),
        (NodeKind.EVIDENCE, "evd:"),
        (NodeKind.FINDING, "tfd:"),
    ],
)
def test_node_id_prefixes(kind: NodeKind, prefix: str) -> None:
    assert node_id(kind, "x") == prefix + "x"


def test_node_ids_match_design_forms() -> None:
    ieg = build(**full_inputs())
    ids = {n.node_id for n in ieg.nodes}
    assert {"crit:C1", "sym:S1", "tst:t.py::test_a", "evd:ev_1", "tfd:tf_1"} <= ids


def test_edge_id_formula() -> None:
    e = edge_id(EdgeKind.IMPLEMENTED_BY, "crit:C1", "sym:S1", "combined")
    assert e.startswith("e_") and len(e) == 18
    assert e != edge_id(EdgeKind.IMPLEMENTED_BY, "crit:C1", "sym:S1", "explicit")


def test_edge_attrs_carry_producer_detail() -> None:
    ieg = build(**full_inputs())
    e = next(e for e in ieg.edges if e.kind is EdgeKind.IMPLEMENTED_BY and e.dst == "sym:S1" and e.src == "crit:C2")
    assert e.attrs == {"rank": 2, "by_linker": {"lexical": 0.3}}
    assert e.method == "combined" and e.weight == 0.5
    a = next(e for e in ieg.edges if e.kind is EdgeKind.ADDRESSED_BY and e.method == "lexical_test_relevance")
    assert a.attrs == {"bm25_raw": 1.2}


@pytest.mark.parametrize(
    ("kind", "method"),
    [
        ("direct_call", "static"),
        ("indirect_call", "static"),
        ("import_reference", "static"),
        ("fixture_dependency", "static"),
        ("name_convention", "naming"),
        ("dynamic_coverage", "dynamic"),
        ("something_new", "combined"),
    ],
)
def test_symbol_test_method_from_link_kind(kind: str, method: str) -> None:
    ieg = build(symbols=[sym()], symbol_test=[st(kind=kind)])
    (edge,) = ieg.edges
    assert edge.method == method and edge.attrs["kind"] == kind


@pytest.mark.parametrize(
    ("src_kind", "dst_kind", "edge_kind", "ok"),
    [
        (NodeKind.CRITERION, NodeKind.SYMBOL, EdgeKind.IMPLEMENTED_BY, True),
        (NodeKind.SYMBOL, NodeKind.TEST, EdgeKind.EXERCISED_BY, True),
        (NodeKind.CRITERION, NodeKind.TEST, EdgeKind.ADDRESSED_BY, True),
        (NodeKind.TEST, NodeKind.EVIDENCE, EdgeKind.PRODUCED, True),
        (NodeKind.FINDING, NodeKind.EVIDENCE, EdgeKind.PRODUCED, True),
        (NodeKind.FINDING, NodeKind.TEST, EdgeKind.AFFECTS, True),
        (NodeKind.FINDING, NodeKind.SYMBOL, EdgeKind.AFFECTS, True),
        (NodeKind.SYMBOL, NodeKind.CRITERION, EdgeKind.IMPLEMENTED_BY, False),
        (NodeKind.TEST, NodeKind.SYMBOL, EdgeKind.EXERCISED_BY, False),
        (NodeKind.CRITERION, NodeKind.CRITERION, EdgeKind.ADDRESSED_BY, False),
        (NodeKind.EVIDENCE, NodeKind.TEST, EdgeKind.PRODUCED, False),
        (NodeKind.TEST, NodeKind.TEST, EdgeKind.AFFECTS, False),
    ],
)
def test_allowed_endpoint_table(src_kind, dst_kind, edge_kind, ok) -> None:
    assert ((src_kind, dst_kind) in ALLOWED_ENDPOINTS[edge_kind]) is ok


def _mini(edge: IegEdge, *nodes: IegNode) -> Ieg:
    return Ieg(AID, SHA, tuple(sorted(nodes, key=lambda n: n.node_id)), (edge,), "d")


def _n(kind: NodeKind, ref: str) -> IegNode:
    return IegNode(node_id(kind, ref), kind, ref, {})


def _e(kind: EdgeKind, src: str, dst: str, w: float = 0.5, method: str = "m") -> IegEdge:
    return IegEdge(edge_id(kind, src, dst, method), kind, src, dst, w, method)


@pytest.mark.parametrize(
    ("ieg", "needle"),
    [
        (_mini(_e(EdgeKind.IMPLEMENTED_BY, "crit:C", "sym:S"), _n(NodeKind.CRITERION, "C")), "missing endpoint"),
        (_mini(_e(EdgeKind.IMPLEMENTED_BY, "crit:C", "sym:S"), _n(NodeKind.SYMBOL, "S")), "missing endpoint"),
        (
            _mini(_e(EdgeKind.IMPLEMENTED_BY, "sym:S", "crit:C"), _n(NodeKind.CRITERION, "C"), _n(NodeKind.SYMBOL, "S")),
            "cannot connect",
        ),
        (
            _mini(_e(EdgeKind.IMPLEMENTED_BY, "crit:C", "sym:S", 1.5), _n(NodeKind.CRITERION, "C"), _n(NodeKind.SYMBOL, "S")),
            "outside",
        ),
        (
            _mini(_e(EdgeKind.IMPLEMENTED_BY, "crit:C", "sym:S", float("nan")), _n(NodeKind.CRITERION, "C"), _n(NodeKind.SYMBOL, "S")),
            "outside",
        ),
        (
            _mini(
                replace(_e(EdgeKind.IMPLEMENTED_BY, "crit:C", "sym:S"), edge_id="e_bad"),
                _n(NodeKind.CRITERION, "C"), _n(NodeKind.SYMBOL, "S"),
            ),
            "does not match its content",
        ),
        (
            Ieg(AID, SHA, (_n(NodeKind.CRITERION, "C"), _n(NodeKind.CRITERION, "C")), (), "d"),
            "duplicate node",
        ),
        (
            Ieg(AID, SHA, (IegNode("crit:X", NodeKind.CRITERION, "C", {}),), (), "d"),
            "does not match kind",
        ),
        (
            Ieg(AID, SHA, (_n(NodeKind.SYMBOL, "b"), _n(NodeKind.SYMBOL, "a")), (), "d"),
            "not sorted",
        ),
    ],
)
def test_validator_detects_violations(ieg: Ieg, needle: str) -> None:
    assert any(needle in p for p in validate_ieg(ieg))


def test_validator_detects_duplicate_and_unsorted_edges() -> None:
    nodes = (_n(NodeKind.CRITERION, "C"), _n(NodeKind.SYMBOL, "S"), _n(NodeKind.SYMBOL, "T"))
    e1 = _e(EdgeKind.IMPLEMENTED_BY, "crit:C", "sym:T")
    e2 = _e(EdgeKind.IMPLEMENTED_BY, "crit:C", "sym:S")
    assert any("duplicate edge" in p for p in validate_ieg(Ieg(AID, SHA, nodes, (e1, e1), "d")))
    assert any("edges are not sorted" in p for p in validate_ieg(Ieg(AID, SHA, nodes, (e1, e2), "d")))


# ------------------------------------------------------------- determinism


def test_shuffled_inputs_give_identical_json() -> None:
    base = build(**full_inputs()).to_json()
    rng = random.Random(7)
    for _ in range(15):
        data = full_inputs()
        for v in data.values():
            rng.shuffle(v)
        assert build(**data).to_json() == base


def test_repeat_is_byte_identical_and_digest_stable() -> None:
    a, b = build(**full_inputs()), build(**full_inputs())
    assert a.to_json() == b.to_json()
    assert a.inputs_digest == b.inputs_digest and len(a.inputs_digest) == 64


def test_digest_changes_with_inputs_and_ignores_collected_at() -> None:
    base = build(**full_inputs())
    data = full_inputs()
    data["symbol_test"] = data["symbol_test"][:-1]
    assert build(**data).inputs_digest != base.inputs_digest
    data = full_inputs()
    data["evidence"] = [replace(e, collected_at="2030-01-01T00:00:00Z") for e in data["evidence"]]
    assert build(**data).inputs_digest == base.inputs_digest
    assert build(**full_inputs()).inputs_digest == base.inputs_digest
    other = build_ieg(analysis_id="other", head_sha=SHA, **full_inputs())
    assert other.inputs_digest != base.inputs_digest


def test_duplicate_input_rows_do_not_change_graph_nodes() -> None:
    once = build(**full_inputs())
    data = full_inputs()
    data["criteria"] = data["criteria"] * 2
    data["symbols"] = data["symbols"] * 2
    twice = build(**data)
    assert twice.nodes == once.nodes


# ------------------------------------------------- dirty input / orphan policy


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"criteria": [], "symbols": [sym()], "criterion_symbol": [cs()]}, "unknown_criterion"),
        ({"criteria": [crit()], "symbols": [], "criterion_symbol": [cs()]}, "unknown_symbol"),
        ({"symbols": [], "symbol_test": [st()]}, "unknown_symbol"),
        ({"criteria": [], "criterion_test": [ct()]}, "unknown_criterion"),
        ({"symbols": [sym()], "criteria": [crit()], "criterion_symbol": [cs(score=float("nan"))]}, "invalid_weight"),
        ({"symbols": [sym()], "symbol_test": [st(score=float("inf"))]}, "invalid_weight"),
        ({"criteria": [crit()], "criterion_test": [ct(w=float("-inf"))]}, "invalid_weight"),
        ({"tamper": [finding(test_id=None, symbol="missing")]}, "unknown_symbol"),
        ({"evidence": [item(analysis_id="other")]}, "evidence_other_analysis"),
        ({"evidence": [item(head_sha="b" * 40)]}, "evidence_other_analysis"),
        ({"evidence": [item(kind=EvidenceKind.TAMPER_FINDING, subject="tf_x")]}, "evidence_subject_missing"),
    ],
)
def test_bad_edges_are_dropped_and_reported(kwargs: dict[str, Any], code: str) -> None:
    ieg, rep = build_ieg_with_report(analysis_id=AID, head_sha=SHA, **kwargs)
    assert validate_ieg(ieg) == ()
    assert rep.dropped_edges >= 1
    assert code in {n.code for n in rep.notes}
    assert not any(e.kind in (EdgeKind.IMPLEMENTED_BY, EdgeKind.ADDRESSED_BY) for e in ieg.edges) or code == "unknown_symbol"


@pytest.mark.parametrize(("raw", "expected"), [(1.7, 1.0), (-0.2, 0.0), (0.123456789, 0.123457)])
def test_weights_are_clamped_and_rounded(raw: float, expected: float) -> None:
    ieg, rep = build_ieg_with_report(
        analysis_id=AID, head_sha=SHA, criteria=[crit()], symbols=[sym()], criterion_symbol=[cs(score=raw)]
    )
    assert ieg.edges[0].weight == expected
    assert ("weight_clamped" in {n.code for n in rep.notes}) is (raw in (1.7, -0.2))


def test_orphan_and_unlinked_criteria_are_reported_not_hidden() -> None:
    data = full_inputs()
    data["criteria"] = data["criteria"] + [crit("C4"), crit("C5")]
    data["criterion_symbol"] = data["criterion_symbol"] + [cs("C5", "S2")]
    ieg, rep = build_ieg_with_report(analysis_id=AID, head_sha=SHA, **data)
    assert rep.unlinked_criteria == ("C3", "C4")
    assert set(rep.untested_criteria) == {"C3", "C4", "C5"}  # C3/C4 unlinked, C5 has no relevance edge
    assert node_id(NodeKind.CRITERION, "C4") in {n.node_id for n in ieg.nodes}


def test_symbol_without_tests_and_criterion_symbol_without_tests_is_untested() -> None:
    rep = report(criteria=[crit()], symbols=[sym()], criterion_symbol=[cs()])
    assert rep.unlinked_criteria == () and rep.untested_criteria == ("C1",)
    # symbol tests without a relevance edge do not count (F4)
    rep = report(criteria=[crit()], symbols=[sym()], criterion_symbol=[cs()], symbol_test=[st()])
    assert rep.untested_criteria == ("C1",)


def test_test_nodes_created_on_demand_and_annotated() -> None:
    ieg = build(**full_inputs())
    tests = {n.ref: n for n in ieg.nodes if n.kind is NodeKind.TEST}
    assert set(tests) == {"t.py::test_a", "t.py::test_b", "t.py::test_c"}
    a = tests["t.py::test_a"].attrs
    assert a["changed_in_pr"] is True and a["outcome"] == "passed" and a["n_assertions"] == 0
    assert tests["t.py::test_c"].attrs["outcome"] is None
    assert tests["t.py::test_c"].attrs["path"] == "t.py"


def test_changed_test_without_links_is_an_isolated_node() -> None:
    ieg = build(changed_test_ids=["tests/x.py::test_new"])
    assert [n.node_id for n in ieg.nodes] == ["tst:tests/x.py::test_new"]
    assert ieg.edges == ()


@pytest.mark.parametrize(
    ("outcomes", "expected"),
    [
        ([Outcome.PASSED, Outcome.FAILED], "failed"),
        ([Outcome.PASSED, Outcome.PASSED], "passed"),
        ([Outcome.PASSED, Outcome.ERROR, Outcome.FAILED], "error"),
        ([Outcome.PASSED, Outcome.SKIPPED], "skipped"),
        ([Outcome.PASSED, Outcome.FLAKY, Outcome.SKIPPED], "flaky"),
        ([Outcome.NOT_RUN, Outcome.PASSED], "not_run"),
    ],
)
def test_parametrized_case_outcomes_aggregate_worst_wins(outcomes, expected) -> None:
    cases = [CaseOutcomeInput("t.py::test_a", None, None, None, o) for o in outcomes]
    for order in (cases, cases[::-1]):
        ieg = build(symbols=[sym()], symbol_test=[st()], cases=order)
        (t,) = [n for n in ieg.nodes if n.kind is NodeKind.TEST]
        assert t.attrs["outcome"] == expected


def test_case_without_test_id_is_noted_and_unknown_case_creates_no_node() -> None:
    cases = [
        CaseOutcomeInput(None, "f.py", "C", "n", Outcome.FAILED),
        CaseOutcomeInput("ghost.py::test_x", None, None, None, Outcome.FAILED),
    ]
    ieg, rep = build_ieg_with_report(analysis_id=AID, head_sha=SHA, cases=cases)
    assert ieg.nodes == ()
    assert "case_unmatched" in {n.code for n in rep.notes}


# ----------------------------------------------------- duplicates and cycles


def test_duplicate_edges_merge_to_max_weight_and_union_reasons() -> None:
    r1, r2 = Reason("a", "x"), Reason("b", "y")
    links = [
        CriterionSymbolEdgeInput("C1", "S1", 0.4, 2, {"lexical": 0.1}, (r1,)),
        CriterionSymbolEdgeInput("C1", "S1", 0.9, 1, {"lexical": 0.9}, (r2,)),
    ]
    for order in (links, links[::-1]):
        ieg, rep = build_ieg_with_report(
            analysis_id=AID, head_sha=SHA, criteria=[crit()], symbols=[sym()], criterion_symbol=order
        )
        (e,) = ieg.edges
        assert e.weight == 0.9 and e.attrs["rank"] == 1
        assert e.reasons == (r1, r2)
        assert rep.merged_edges == 1


def test_same_pair_different_methods_stay_separate_and_paths_collapse() -> None:
    ieg = build(
        criteria=[crit()], symbols=[sym()],
        criterion_symbol=[cs()],
        symbol_test=[st(kind="direct_call", score=0.6), st(kind="dynamic_coverage", score=0.9)],
    )
    assert sum(1 for e in ieg.edges if e.kind is EdgeKind.EXERCISED_BY) == 2
    (p,) = IegIndex(ieg).paths("C1")
    assert p.w_st == 0.9


def test_conflicting_duplicate_nodes_keep_canonical_smallest() -> None:
    a, b = sym("S1", path="a.py"), sym("S1", path="b.py")
    outs = {
        build_ieg_with_report(analysis_id=AID, head_sha=SHA, symbols=order)[0].to_json()
        for order in ([a, b], [b, a])
    }
    assert len(outs) == 1
    rep = report(symbols=[a, b])
    assert "duplicate_node_conflict" in {n.code for n in rep.notes}


def test_conflicting_assertion_records_are_deterministic() -> None:
    a = feats()
    b = replace(feats(), n_assertions=3)
    outs = {build(assertions=o).to_json() for o in ([a, b], [b, a])}
    assert len(outs) == 1


def test_graph_is_acyclic_for_arbitrary_link_soup() -> None:
    rng = random.Random(3)
    ids = [f"S{i}" for i in range(20)]
    tests = [f"t.py::test_{i}" for i in range(20)]
    ieg = build(
        criteria=[crit(f"C{i}") for i in range(10)],
        symbols=[sym(s) for s in ids],
        criterion_symbol=[cs(f"C{rng.randrange(10)}", rng.choice(ids), rng.random()) for _ in range(80)],
        symbol_test=[st(rng.choice(ids), rng.choice(tests), rng.random()) for _ in range(80)],
        criterion_test=[ct(f"C{rng.randrange(10)}", rng.choice(tests), rng.random()) for _ in range(40)],
    )
    assert validate_ieg(ieg) == ()
    # Layering: every edge goes strictly forward in the layer order, so no cycle exists.
    layer = {NodeKind.CRITERION: 0, NodeKind.FINDING: 0, NodeKind.SYMBOL: 1, NodeKind.TEST: 2, NodeKind.EVIDENCE: 3}
    kind_of = {n.node_id: n.kind for n in ieg.nodes}
    for e in ieg.edges:
        assert layer[kind_of[e.src]] < layer[kind_of[e.dst]] or e.kind is EdgeKind.AFFECTS


def test_ids_are_unique_even_with_colliding_refs_across_kinds() -> None:
    ieg = build(criteria=[crit("x")], symbols=[sym("x")], changed_test_ids=["x"], tamper=[finding("x", test_id=None)])
    ids = [n.node_id for n in ieg.nodes]
    assert sorted(ids) == ["crit:x", "sym:x", "tfd:x", "tst:x"]


# ------------------------------------------------------------------ tamper


def test_tamper_finding_affects_test_and_symbol() -> None:
    ieg = build(
        symbols=[sym("S1")],
        tamper=[finding("tf_1", symbol="S1", test_id="t.py::test_a", confidence=0.75)],
    )
    idx = IegIndex(ieg)
    assert idx.findings_for_test("t.py::test_a") == ("tf_1",)
    assert idx.findings_for_symbol("S1") == ("tf_1",)
    (e, _) = idx.out_edges("tfd:tf_1", EdgeKind.AFFECTS), None
    assert {x.weight for x in e} == {0.75}
    assert e[0].attrs == {"severity": "high", "rule_id": "T001"}


def test_finding_with_no_known_target_is_kept_and_reported() -> None:
    ieg, rep = build_ieg_with_report(analysis_id=AID, head_sha=SHA, tamper=[finding(test_id=None)])
    assert [n.kind for n in ieg.nodes] == [NodeKind.FINDING]
    assert "finding_unattached" in {n.code for n in rep.notes}


def test_finding_node_omits_snippets() -> None:
    f = finding(old_snippet="secret old", new_snippet="secret new")
    ieg = build(tamper=[f])
    assert "snippet" not in json.dumps(ieg.to_dict()) and "secret" not in ieg.to_json()


def test_tamper_evidence_hangs_off_its_finding() -> None:
    ev = item("ev_t", subject="tf_1", kind=EvidenceKind.TAMPER_FINDING, outcome=None, severity="high", rule_id="T001")
    ieg = build(tamper=[finding("tf_1")], evidence=[ev])
    assert validate_ieg(ieg) == ()
    (e,) = [e for e in ieg.edges if e.kind is EdgeKind.PRODUCED]
    assert e.src == "tfd:tf_1" and e.dst == "evd:ev_t"
    assert e.method == "ci_upload"


# ---------------------------------------------------------------- evidence


def test_evidence_node_attrs_and_produced_edge() -> None:
    ieg = build(evidence=[item("ev_1", flaky=FlakyInfo(True, "rerun", None))])
    ev = next(n for n in ieg.nodes if n.kind is NodeKind.EVIDENCE)
    assert ev.attrs["outcome"] == "passed" and ev.attrs["flaky"] is True
    assert ev.attrs["freshness"] == 1.0 and ev.attrs["independence"] == 0.8
    assert IegIndex(ieg).evidence_for_test("t.py::test_a") == ("ev_1",)


# ------------------------------------------------------------ stage A input


def test_build_from_stage_a_equals_keyword_build() -> None:
    d = full_inputs()
    stage = StageAInput(
        analysis_id=AID, repository_id="r", head_sha=SHA, changeset_ref="cs",
        criteria=tuple(d["criteria"]), symbols=tuple(d["symbols"]),
        criterion_symbol=tuple(d["criterion_symbol"]), symbol_test=tuple(d["symbol_test"]),
        criterion_test=tuple(d["criterion_test"]), assertions=tuple(d["assertions"]),
        tamper=tuple(d["tamper"]), changed_test_ids=frozenset(d["changed_test_ids"]),
    )
    a = build_ieg_from_stage_a(stage, cases=d["cases"], evidence=d["evidence"])
    assert a == build(**d)


# ----------------------------------------------------------------- queries


def test_paths_return_three_weights() -> None:
    idx = IegIndex(build(**full_inputs()))
    paths = idx.paths("C1")
    assert [(p.symbol_id, p.test_id, p.w_cs, p.w_st, p.r_ct) for p in paths] == [
        ("S1", "t.py::test_a", 0.9, 0.8, 0.7),
        ("S1", "t.py::test_b", 0.9, 0.8, 0.0),
    ]
    assert all(len(p.edge_ids) == (3 if p.r_ct else 2) for p in paths)


def test_query_helpers() -> None:
    idx = IegIndex(build(**full_inputs()))
    assert idx.tests_for_criterion("C2") == ("t.py::test_a", "t.py::test_b", "t.py::test_c")
    assert idx.addressed_tests("C2") == ("t.py::test_c",)
    assert idx.reachable_evidence("C2") == ("ev_1", "ev_2")
    assert idx.criteria_for_symbol("S1") == ("C1", "C2")
    assert idx.unlinked_criteria() == ("C3",)
    assert idx.paths("C3") == () and idx.paths("nope") == ()
    assert idx.node("crit:C1").kind is NodeKind.CRITERION and idx.node("crit:zz") is None
    assert len(idx.nodes_of_kind(NodeKind.SYMBOL)) == 2
    assert len(idx.in_edges("sym:S1", EdgeKind.IMPLEMENTED_BY)) == 2


def test_addressed_only_test_is_reachable_but_has_no_path() -> None:
    idx = IegIndex(build(criteria=[crit()], criterion_test=[ct()]))
    assert idx.paths("C1") == ()
    assert idx.tests_for_criterion("C1") == ("t.py::test_a",)


def test_no_cross_analysis_edges() -> None:
    d = full_inputs()
    d["evidence"] = d["evidence"] + [item("ev_x", analysis_id="other")]
    ieg = build(**d)
    assert "evd:ev_x" not in {n.node_id for n in ieg.nodes}
    assert all(e.dst != "evd:ev_x" for e in ieg.edges)


# ------------------------------------------------------------ serialization


def test_json_round_trip_is_lossless() -> None:
    ieg = build(**full_inputs())
    again = Ieg.from_json(ieg.to_json())
    assert again == ieg
    assert again.to_json() == ieg.to_json()
    assert validate_ieg(again) == ()
    assert IegIndex(again).paths("C1") == IegIndex(ieg).paths("C1")


def test_serialized_shape_matches_design_fields() -> None:
    d = build(**full_inputs()).to_dict()
    assert set(d) == {"analysis_id", "head_sha", "nodes", "edges", "inputs_digest", "algo_version"}
    assert set(d["nodes"][0]) == {"node_id", "kind", "ref", "attrs"}
    assert set(d["edges"][0]) == {"edge_id", "kind", "src", "dst", "weight", "method", "reasons", "attrs"}
    assert d["algo_version"] == "ieg-1"
    json.dumps(d)  # plain JSON types only


def test_tuple_inputs_in_attrs_are_normalised_to_lists() -> None:
    ieg = build(criteria=[crit(hints_paths=("b.py", "a.py"), hints_tests=("t",))])
    assert ieg.nodes[0].attrs["hints_paths"] == ["a.py", "b.py"]


def test_unknown_json_keys_are_ignored_on_read() -> None:
    d = build(**full_inputs()).to_dict()
    d["future_field"] = 1
    d["nodes"][0]["extra"] = 2
    assert Ieg.from_dict(d).nodes[0].node_id == d["nodes"][0]["node_id"]


# ------------------------------------------------------------- performance


def _big(n_crit: int = 100, n_sym: int = 800, n_test: int = 2100) -> dict[str, Any]:
    rng = random.Random(11)
    syms = [f"S{i}" for i in range(n_sym)]
    tests = [f"tests/t{i // 20}.py::test_{i}" for i in range(n_test)]
    return {
        "criteria": [crit(f"C{i}") for i in range(n_crit)],
        "symbols": [sym(s) for s in syms],
        "criterion_symbol": [cs(f"C{i}", s, rng.random()) for i in range(n_crit) for s in rng.sample(syms, 3)],
        "symbol_test": [st(s, t, rng.random()) for s in syms for t in rng.sample(tests, 3)],
        "criterion_test": [ct(f"C{i}", t, rng.random()) for i in range(n_crit) for t in rng.sample(tests, 5)],
    }


def test_paths_on_2k_node_graph_under_50ms() -> None:
    ieg = build(**_big())
    assert len(ieg.nodes) >= 2000
    assert validate_ieg(ieg) == ()
    idx = IegIndex(ieg)
    start = time.perf_counter()
    total = sum(len(idx.paths(f"C{i}")) for i in range(100))
    per_query_ms = (time.perf_counter() - start) * 1000 / 100
    assert total > 0
    assert per_query_ms < 50
    worst = 0.0
    for i in range(100):
        t0 = time.perf_counter()
        idx.reachable_evidence(f"C{i}")
        worst = max(worst, (time.perf_counter() - t0) * 1000)
    assert worst < 50


def test_build_time_on_2k_node_graph_is_bounded() -> None:
    data = _big()
    start = time.perf_counter()
    build(**data)
    assert time.perf_counter() - start < 5.0


def test_non_numeric_weight_is_dropped_not_raised() -> None:
    ieg, rep = build_ieg_with_report(
        analysis_id=AID, head_sha=SHA, criteria=[crit()], symbols=[sym()],
        criterion_symbol=[CriterionSymbolEdgeInput("C1", "S1", "abc", 1)],  # type: ignore[arg-type]
    )
    assert ieg.edges == () and rep.dropped_edges == 1


def test_build_ieg_with_report_notes_are_sorted_and_unique() -> None:
    _, rep = build_ieg_with_report(analysis_id=AID, head_sha=SHA, **full_inputs())
    assert list(rep.notes) == sorted(set(rep.notes), key=lambda r: (r.code, r.detail, r.ref or ""))


def test_finding_with_invalid_confidence_is_kept_at_full_weight() -> None:
    ieg, rep = build_ieg_with_report(
        analysis_id=AID, head_sha=SHA, tamper=[finding(confidence=float("nan"))]
    )
    assert [e.weight for e in ieg.edges] == [1.0]
    assert rep.dropped_edges == 0
    assert "finding_confidence_defaulted" in {n.code for n in rep.notes}
