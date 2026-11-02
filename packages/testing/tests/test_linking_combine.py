"""Combiner, model and evaluation-hook tests (LK-03)."""

from __future__ import annotations

import itertools
import json

import pytest
from radius_testing.linking import (
    LinkKind,
    LinkSet,
    SymbolTestLink,
    combine_links,
    combined_score,
)
from radius_testing.linking.evaluation import (
    ablation,
    evaluate_linksets,
    prf,
    select_tests,
)
from radius_testing.linking.model import LinkTarget, make_test_id, normalize_test_id

S, T = "python:a.py::f", "tests/test_a.py::test_x"


def link(linker, score, kind, symbol=S, test=T, **kw):
    return SymbolTestLink(symbol, test, linker, score, kind, algo_version=f"{linker}-v1", **kw)


def ls(*links):
    return LinkSet.of(links, algo_version="x")


STATIC = ls(link("static", 0.9, LinkKind.DIRECT_CALL, evidence=("calls f",)))
NAMING = ls(link("naming", 0.6, LinkKind.NAME_CONVENTION, evidence=("test_f matches f",)))
DYN = ls(link("dynamic", 0.8, LinkKind.DYNAMIC_COVERAGE, evidence=("3 lines hit",)))


def test_naming_alone_is_capped():
    assert combine_links(naming=NAMING).links[0].score == 0.5


def test_static_alone_is_kept_and_capped():
    assert combine_links(static=STATIC).links[0].score == 0.9
    high = ls(link("static", 1.0, LinkKind.DIRECT_CALL))
    assert combine_links(static=high).links[0].score == 0.90


def test_agreement_boosts():
    mid = ls(link("static", 0.7, LinkKind.DIRECT_CALL))
    only = combine_links(static=mid).links[0].score
    both = combine_links(static=mid, naming=NAMING).links[0]
    assert only < both.score <= 0.90


def test_dynamic_dominates():
    dyn_only = combine_links(dynamic=DYN).links[0]
    assert dyn_only.score >= 0.92 and dyn_only.kind == LinkKind.DYNAMIC_COVERAGE
    weak_static = ls(link("static", 0.2, LinkKind.IMPORT_REFERENCE))
    both = combine_links(static=weak_static, dynamic=DYN).links[0]
    assert both.score > combine_links(static=weak_static).links[0].score
    assert both.score >= dyn_only.score
    strong = combine_links(static=STATIC, naming=NAMING, dynamic=DYN).links[0]
    assert 0.92 < strong.score <= 0.99


def test_dynamic_outranks_any_static_only_link():
    dyn = ls(link("dynamic", 0.7, LinkKind.DYNAMIC_COVERAGE))
    assert combine_links(dynamic=dyn).links[0].score > combined_score(1.0, 1.0)


def test_per_linker_scores_and_evidence_preserved():
    out = combine_links(STATIC, NAMING, DYN).links[0]
    assert {c.linker: c.score for c in out.components} == {"static": 0.9, "naming": 0.6, "dynamic": 0.8}
    assert out.linker == "combined" and out.algo_version == "link-combine-v1"
    assert out.evidence[0] == "3 lines hit"  # dynamic first
    assert set(out.evidence) == {"calls f", "test_f matches f", "3 lines hit"}


def test_missing_dynamic_never_lowers():
    with_static = combine_links(static=STATIC).links[0].score
    assert combine_links(static=STATIC, dynamic=ls()).links[0].score == with_static


GRID = [0.0, 0.05, 0.3, 0.6, 0.9, 1.0]


def test_monotone_in_every_input():
    for s, n in itertools.product(GRID, GRID):
        chain = [combined_score(s, n, d) for d in (None, 0.0, 0.7, 0.85, 1.0)]
        assert chain == sorted(chain), (s, n)
    for n, d in itertools.product(GRID, [None, 0.7, 1.0]):
        scores = [combined_score(s, n, d) for s in GRID]
        assert scores == sorted(scores), (n, d)
    for s, d in itertools.product(GRID, [None, 0.7, 1.0]):
        scores = [combined_score(s, n, d) for n in GRID]
        assert scores == sorted(scores), (s, d)


def test_scores_stay_in_unit_interval_and_caps_hold():
    for s, n in itertools.product(GRID, GRID):
        assert 0.0 <= combined_score(s, n, None) <= 0.90
        assert 0.0 <= combined_score(s, n, 1.0) <= 0.99
    assert combined_score(0, 1.0, None) == 0.5


def test_ranked_per_symbol_and_per_test():
    other = "tests/test_a.py::test_y"
    st = ls(
        link("static", 0.9, LinkKind.DIRECT_CALL),
        link("static", 0.4, LinkKind.INDIRECT_CALL, test=other),
        link("static", 0.7, LinkKind.DIRECT_CALL, symbol="python:a.py::g"),
    )
    out = combine_links(static=st)
    assert [x.test_id for x in out.for_symbol(S)] == [T, other]
    assert [x.symbol_id for x in out.for_test(T)] == [S, "python:a.py::g"]


def test_deterministic_regardless_of_input_order():
    links = [link("static", 0.9, LinkKind.DIRECT_CALL, symbol=f"s{i}", test=f"t{j}") for i in range(4) for j in range(4)]
    a = combine_links(static=ls(*links), naming=NAMING).to_json()
    b = combine_links(static=ls(*reversed(links)), naming=NAMING).to_json()
    assert a == b


def test_serialisation_round_trip_and_json_is_canonical():
    out = combine_links(STATIC, NAMING, DYN)
    again = LinkSet.from_dict(json.loads(out.to_json()))
    assert again.to_json() == out.to_json()
    assert json.loads(out.to_json())["links"][0]["kind"] == "dynamic_coverage"


def test_score_validation():
    with pytest.raises(ValueError):
        link("static", 1.2, LinkKind.DIRECT_CALL)
    with pytest.raises(ValueError):
        link("static", -0.1, LinkKind.DIRECT_CALL)


def test_normalize_test_id_handles_parametrisation_and_phases():
    assert normalize_test_id("tests/t.py::TestA::test_b[1-x::y]") == "tests/t.py::TestA::test_b"
    assert normalize_test_id("tests\\t.py::test_b|run") == "tests/t.py::test_b"
    assert normalize_test_id("tests/t.py::test_b") == "tests/t.py::test_b"
    assert make_test_id("p.py", None, "t") == "p.py::t"
    assert make_test_id("p.py", "C", "t") == "p.py::C::t"


def test_link_target_from_changed_symbol_duck_typing():
    class R:
        start, end = 3, 9

    class Sym:
        symbol_id, path, qualified_name, kind, language = "id", "a.py", "C.m.<locals>.x", "function", "python"
        new_range, old_range = R(), None

    tgt = LinkTarget.from_changed_symbol(Sym())
    assert tgt.new_range == (3, 9) and tgt.old_range is None
    assert tgt.entity_name == "C.m" and tgt.simple_name == "m" and tgt.class_name == "C"
    assert tgt.to_dict()["new_range"] == [3, 9]


def test_real_lk01_changed_symbol_is_accepted():
    from radius_analysis.symbol_changes import DictSnapshot, extract_symbol_changes
    from radius_analysis.symbol_changes.testing import dedent, make_diff

    base = {"src/p.py": dedent("def f(x):\n    return x\n")}
    head = {"src/p.py": dedent("def f(x):\n    return x + 1\n")}
    changes = extract_symbol_changes(DictSnapshot(base), DictSnapshot(head), make_diff(base, head))
    targets = [LinkTarget.from_changed_symbol(s) for s in changes.symbols]
    assert [t.qualified_name for t in targets] == ["f"] and targets[0].new_range is not None


def test_prf_basic_and_edge_cases():
    r = prf({"a", "b", "c"}, {"b", "c", "d"})
    assert (r.tp, r.fp, r.fn) == (2, 1, 1) and r.precision == pytest.approx(0.6667, abs=1e-3)
    assert prf(set(), set()).precision == 1.0
    assert prf(set(), {"a"}).recall == 0.0
    assert prf({"a[1]"}, {"a"}).tp == 1  # parametrisation suffix ignored
    assert prf({"a"}, {"b"}).f1 == 0.0


def test_select_tests_threshold_and_symbols():
    links = ls(
        link("static", 0.9, LinkKind.DIRECT_CALL),
        link("static", 0.2, LinkKind.IMPORT_REFERENCE, test="tests/test_a.py::weak"),
        link("static", 0.9, LinkKind.DIRECT_CALL, symbol="other", test="t3"),
    )
    assert select_tests(links, [S], min_score=0.3) == {T}
    assert select_tests(links, [S], min_score=0.0) == {T, "tests/test_a.py::weak"}


def test_ablation_variants():
    out = ablation(STATIC, NAMING, DYN, [S], {T})
    assert set(out) == {"only:static", "only:naming", "only:dynamic", "all", "without:static", "without:naming", "without:dynamic"}
    assert out["all"].recall == 1.0
    two = ablation(STATIC, NAMING, None, [S], {T})
    assert "static+naming" in two and "only:dynamic" not in two


def test_evaluate_linksets_scores():
    res = evaluate_linksets({"s": STATIC}, [S], {T, "other"})
    assert res["s"].precision == 1.0 and res["s"].recall == 0.5
