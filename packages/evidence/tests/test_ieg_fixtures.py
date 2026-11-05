"""IEGs for the 8 F-14 fixtures, built from their gold links via small adapters."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from radius_evidence.application.ieg_builder import build_ieg_with_report
from radius_evidence.domain.enums import EdgeKind, NodeKind, Outcome
from radius_evidence.domain.ieg import Ieg, IegIndex, validate_ieg
from radius_evidence.domain.inputs import (
    CaseOutcomeInput,
    CriterionInput,
    CriterionSymbolEdgeInput,
    CriterionTestEdgeInput,
    SymbolInput,
    SymbolTestEdgeInput,
    TamperFindingInput,
)
from radius_evidence.domain.model import AssertionFeatures

ROOT = next(
    p
    for p in Path(__file__).resolve().parents
    if (p / "docs" / "research" / "design").is_dir()
)
FIXTURES = ROOT / "benchmarks" / "fixtures" / "intent"
NAMES = sorted(p.name for p in FIXTURES.iterdir() if (p / "expected.json").is_file())
SHA = "c" * 40


def _symbol_id(ref: str) -> str:
    digest = hashlib.sha256(ref.encode()).hexdigest()[:12]
    return f"python:{ref}#function@{digest}"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name / "expected.json").read_text(encoding="utf-8"))


def inputs_for(name: str) -> dict[str, Any]:
    """Adapter: fixture gold data -> builder keyword inputs."""

    gold = _load(name)
    criteria = [
        CriterionInput(c["id"], c["text"], 1.0, c["testability"], "confirmed")
        for c in gold["criteria"]
    ]
    symbol_refs = sorted(
        {link["symbol"] for link in gold["links"]} | set(gold["unlinked_changed_symbols"])
    )
    symbols = [
        SymbolInput(
            _symbol_id(r), r.split("::")[0], r.split("::")[1], "function", "python",
            "modified", True, False, False,
        )
        for r in symbol_refs
    ]
    cs, st, ct = [], [], []
    for link in gold["links"]:
        sid = _symbol_id(link["symbol"])
        cs.append(CriterionSymbolEdgeInput(link["criterion"], sid, 0.95, 1, {"explicit": 0.95}))
        for t in link["tests"]:
            st.append(SymbolTestEdgeInput(sid, t, 0.9, "direct_call", 1))
            ct.append(CriterionTestEdgeInput(link["criterion"], t, 1.0, "intent_yml_hint", None))
    tests = sorted({t for link in gold["links"] for t in link["tests"]})
    assertions = [
        AssertionFeatures(
            t, t.split("::")[0], 1, 2, (), 0, False, False, None, False, (), ()
        )
        for t in tests
    ]
    tamper = [
        TamperFindingInput(
            "tf_" + hashlib.sha256(f"{f['rule']}{f['file']}{f.get('test')}".encode()).hexdigest()[:12],
            f["rule"], "check", f["assumed_severity"], 0.9, f["file"], None, f.get("test"), f["detail"],
        )
        for f in gold["tamper_findings"]
    ]
    head = gold["test_outcomes"].get("head", {})
    cases = [
        CaseOutcomeInput(t, None, None, None, Outcome(o)) for t, o in sorted(head.items())
    ]
    return {
        "criteria": criteria,
        "symbols": symbols,
        "criterion_symbol": cs,
        "symbol_test": st,
        "criterion_test": ct,
        "assertions": assertions,
        "tamper": tamper,
        "changed_test_ids": [],
        "cases": cases,
    }


def build(name: str) -> tuple[Ieg, Any]:
    return build_ieg_with_report(analysis_id=f"an-{name}", head_sha=SHA, **inputs_for(name))


@pytest.mark.parametrize("name", NAMES)
def test_fixture_graph_is_valid(name: str) -> None:
    ieg, rep = build(name)
    assert validate_ieg(ieg) == ()
    assert rep.dropped_edges == 0  # shared symbols repeat symbol->test edges: merged, not dropped


@pytest.mark.parametrize("name", NAMES)
def test_fixture_graph_matches_gold_links(name: str) -> None:
    gold = _load(name)
    idx = IegIndex(build(name)[0])
    for link in gold["links"]:
        cid = link["criterion"]
        assert idx.addressed_tests(cid) == tuple(sorted(link["tests"])), (name, cid)
        paths = idx.paths(cid)
        assert all(p.symbol_id == _symbol_id(link["symbol"]) for p in paths)
        assert all(p.w_cs == 0.95 and p.w_st == 0.9 for p in paths)
        # the shared symbol exposes sibling criteria's tests (F4); only r_ct > 0 are evidence
        assert {p.test_id for p in paths if p.r_ct > 0} == set(link["tests"])


@pytest.mark.parametrize("name", NAMES)
def test_fixture_counts(name: str) -> None:
    gold = _load(name)
    ieg = build(name)[0]
    count = {k: sum(1 for n in ieg.nodes if n.kind is k) for k in NodeKind}
    assert count[NodeKind.CRITERION] == len(gold["criteria"])
    assert count[NodeKind.SYMBOL] == len(
        {link["symbol"] for link in gold["links"]} | set(gold["unlinked_changed_symbols"])
    )
    assert count[NodeKind.TEST] == len({t for link in gold["links"] for t in link["tests"]})
    assert count[NodeKind.FINDING] == len(gold["tamper_findings"])
    assert sum(1 for e in ieg.edges if e.kind is EdgeKind.IMPLEMENTED_BY) == len(gold["links"])


@pytest.mark.parametrize("name", NAMES)
def test_fixture_determinism_and_round_trip(name: str) -> None:
    a, b = build(name)[0], build(name)[0]
    assert a.to_json() == b.to_json()
    assert Ieg.from_json(a.to_json()) == a


@pytest.mark.parametrize("name", NAMES)
def test_fixture_untested_criteria_match_gold(name: str) -> None:
    gold = _load(name)
    rep = build(name)[1]
    expected = [link["criterion"] for link in gold["links"] if not link["tests"]]
    assert sorted(rep.untested_criteria) == sorted(expected)
    assert rep.unlinked_criteria == ()


def test_fixture_08_c4_is_linked_to_code_but_has_no_tests() -> None:
    idx = IegIndex(build("08_multi_criterion_partial_evidence")[0])
    assert idx.addressed_tests("C4") == ()
    assert all(p.r_ct == 0.0 for p in idx.paths("C4"))
    assert sum(1 for p in idx.paths("C1") if p.r_ct > 0) == 2


def test_fixture_04_tamper_findings_attach_to_tests() -> None:
    idx = IegIndex(build("04_test_tampering")[0])
    for t in (
        "tests/test_stock.py::test_reserve_rejects_non_positive",
        "tests/test_stock.py::test_reserve_reduces_stock",
        "tests/test_stock.py::test_reserve_exact_stock",
    ):
        assert len(idx.findings_for_test(t)) == 1


def test_fixture_06_dependency_finding_is_unattached_but_kept() -> None:
    ieg, rep = build("06_hallucinated_dependency")
    assert sum(1 for n in ieg.nodes if n.kind is NodeKind.FINDING) == 1
    assert not any(e.kind is EdgeKind.AFFECTS for e in ieg.edges)
    assert "finding_unattached" in {n.code for n in rep.notes}


def test_fixture_04_deleted_test_finding_has_no_linked_node_beyond_its_test() -> None:
    gold = _load("04_test_tampering")
    deleted = next(f for f in gold["tamper_findings"] if f["rule"] == "T001")["test"]
    ieg = build("04_test_tampering")[0]
    assert node_exists(ieg, "tst:" + deleted)


def node_exists(ieg: Ieg, nid: str) -> bool:
    return any(n.node_id == nid for n in ieg.nodes)


def test_fixture_07_unlinked_changed_symbol_is_an_isolated_symbol() -> None:
    ieg = build("07_vague_intent")[0]
    idx = IegIndex(ieg)
    top = _symbol_id("src/report.py::top")
    assert node_exists(ieg, "sym:" + top)
    assert idx.criteria_for_symbol(top) == ()
