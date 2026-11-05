# ruff: noqa: E402, I001  (helper import needs the sys.path setup below; no conftest to avoid plugin-name clashes)
"""Monotonicity, determinism, serialization and performance of the chain model (LK-06)."""

from __future__ import annotations

import random
import sys as _sys
import time
from pathlib import Path as _Path

_HERE = str(_Path(__file__).parent)
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)

import pytest

from chain_helpers import reason
from radius_linking.application import ChainConfig, build_support_links, score_chain
from radius_linking.domain import (
    COMBINED,
    CriterionSupportLinks,
    Link,
    SupportLinkSet,
    SymbolTestEdge,
)

CFG = ChainConfig()
KINDS = ("direct_call", "import_reference", "name_convention", "dynamic_coverage")
LINKERS = ("lexical", "identifier", "structural", "explicit")
COMPS = ("static", "naming", "dynamic")
STATUSES = ("passed", "failed", "flaky", "skipped", "unknown")


def rand_link(rng: random.Random, cid: str, sid: str) -> Link:
    names = rng.sample(LINKERS, rng.randint(1, 3))
    ev = tuple(reason(n, round(rng.random(), 3)) for n in names)
    return Link(cid, sid, COMBINED, round(rng.random(), 3), ev)


def rand_edge(rng: random.Random, sid: str, tid: str) -> SymbolTestEdge:
    comps = tuple(
        (n, round(rng.random(), 3)) for n in rng.sample(COMPS, rng.randint(0, 3))
    )
    return SymbolTestEdge(
        sid,
        tid,
        round(rng.random(), 3),
        kind=rng.choice(KINDS),
        low_confidence=rng.random() < 0.3,
        components=comps,
    )


def scenario(seed: int, n_sym=4, n_tests=3):
    rng = random.Random(seed)
    links = [rand_link(rng, "C1", f"S{i}") for i in range(n_sym) if rng.random() < 0.8]
    edges = [
        rand_edge(rng, f"S{i}", f"T{i}_{j}")
        for i in range(n_sym)
        for j in range(n_tests)
        if rng.random() < 0.7
    ]
    status = {e.test_id: rng.choice(STATUSES) for e in edges}
    return links, edges, status, rng


def conf(links, edges, status):
    res = build_support_links(["C1"], links, edges, test_status=status)
    return res.criteria[0].link_confidence


def bump_edge(e: SymbolTestEdge, **changes) -> SymbolTestEdge:
    fields = dict(
        symbol_id=e.symbol_id,
        test_id=e.test_id,
        score=e.score,
        kind=e.kind,
        linker=e.linker,
        low_confidence=e.low_confidence,
        evidence=e.evidence,
        components=e.components,
    )
    fields.update(changes)
    return SymbolTestEdge(**fields)


SEEDS = range(40)


@pytest.mark.parametrize("seed", SEEDS)
def test_adding_a_chain_never_lowers_confidence(seed):
    links, edges, status, rng = scenario(seed)
    base = conf(links, edges, status)
    extra_edge = rand_edge(rng, "S0", "T_new")
    extra_link = rand_link(rng, "C1", "S_new")
    assert conf(links, [*edges, extra_edge], status) >= base
    new_edges = [*edges, rand_edge(rng, "S_new", "T_n2")]
    assert conf([*links, extra_link], new_edges, status) >= base


@pytest.mark.parametrize("seed", SEEDS)
def test_raising_any_score_never_lowers_confidence(seed):
    links, edges, status, rng = scenario(seed)
    base = conf(links, edges, status)
    if links:
        i = rng.randrange(len(links))
        old = links[i]
        bumped = Link(
            old.criterion_id,
            old.symbol_id,
            old.linker,
            min(1.0, old.score + 0.1),
            old.evidence,
        )
        assert conf([*links[:i], bumped, *links[i + 1 :]], edges, status) >= base
    if edges:
        j = rng.randrange(len(edges))
        better = bump_edge(edges[j], score=min(1.0, edges[j].score + 0.1))
        assert conf(links, [*edges[:j], better, *edges[j + 1 :]], status) >= base


@pytest.mark.parametrize("seed", SEEDS)
def test_removing_a_hop_cannot_raise(seed):
    links, edges, status, rng = scenario(seed)
    base = conf(links, edges, status)
    if edges:
        k = rng.randrange(len(edges))
        assert conf(links, [*edges[:k], *edges[k + 1 :]], status) <= base
    if links:
        k = rng.randrange(len(links))
        assert conf([*links[:k], *links[k + 1 :]], edges, status) <= base
    assert conf([], edges, status) == 0.0
    assert conf(links, [], status) == 0.0


@pytest.mark.parametrize("seed", SEEDS)
def test_adding_evidence_to_a_chain_never_lowers_it(seed):
    rng = random.Random(seed)
    lk, ed = rand_link(rng, "C1", "S1"), rand_edge(rng, "S1", "T1")
    st = rng.choice(STATUSES)
    base = score_chain(lk, ed, st, CFG).score

    def with_ev(extra):
        return Link(
            lk.criterion_id, lk.symbol_id, lk.linker, lk.score, (*lk.evidence, extra)
        )

    dyn = bump_edge(ed, kind="dynamic_coverage")
    comp = bump_edge(ed, components=(*ed.components, ("naming", 0.5)))
    assert score_chain(with_ev(reason("lexical", 0.4)), ed, st, CFG).score >= base
    assert score_chain(with_ev(reason("explicit", 0.9)), ed, st, CFG).score >= base
    assert score_chain(lk, dyn, st, CFG).score >= base
    assert score_chain(lk, comp, st, CFG).score >= base


def test_chain_never_exceeds_caps_or_one():
    rng = random.Random(7)
    for _ in range(500):
        lk, ed = rand_link(rng, "C1", "S1"), rand_edge(rng, "S1", "T1")
        p = score_chain(lk, ed, rng.choice(STATUSES), CFG)
        assert 0.0 <= p.score <= CFG.cap_strong
        if not (p.explicit >= 0.5 and p.dynamic):
            assert p.score <= CFG.cap_other


@pytest.mark.parametrize("seed", range(10))
def test_input_order_does_not_change_output(seed):
    links, edges, status, rng = scenario(seed, 6, 4)
    a = build_support_links(["C1"], links, edges, test_status=status).to_json()
    rng.shuffle(links)
    rng.shuffle(edges)
    b = build_support_links(["C1"], links, edges, test_status=status).to_json()
    assert a == b


def test_repeated_runs_identical():
    links, edges, status, _ = scenario(3, 6, 4)
    runs = {
        build_support_links(["C1"], links, edges, test_status=status).to_json()
        for _ in range(3)
    }
    assert len(runs) == 1


def multi(seed: int, n_crit=6, n_sym=5, n_tests=3):
    rng = random.Random(seed)
    cids = [f"C{i}" for i in range(n_crit)]
    links = [
        rand_link(rng, c, f"S{i}")
        for c in cids
        for i in range(n_sym)
        if rng.random() < 0.6
    ]
    edges = [
        rand_edge(rng, f"S{i}", f"T{j}") for i in range(n_sym) for j in range(n_tests)
    ]
    return cids, links, edges


@pytest.mark.parametrize("seed", range(8))
def test_json_round_trip_is_exact(seed):
    cids, links, edges = multi(seed)
    res = build_support_links(cids, links, edges)
    again = SupportLinkSet.from_json(res.to_json())
    assert again == res
    assert again.to_json() == res.to_json()
    for cs in res.criteria:
        assert CriterionSupportLinks.from_dict(cs.to_dict()) == cs


def test_serialisation_is_sorted_and_labelled():
    cids, links, edges = multi(1)
    res = build_support_links(cids, links, edges)
    assert [c.criterion_id for c in res.criteria] == sorted(cids)
    d = res.to_dict()
    assert d["score_kind"] == "link_confidence_uncalibrated"
    assert d["algo_version"] == "link-chain-v1"
    for cs in res.criteria:
        keys = [(-c.support_score, c.symbol_id, c.test_id) for c in cs.chains]
        assert keys == sorted(keys)
        assert all(c.score_kind == "link_confidence_uncalibrated" for c in cs.chains)


def test_symbol_test_edge_from_object_duck_typing():
    class Comp:
        linker = "dynamic"
        score = 0.9

    class Kind:
        value = "dynamic_coverage"

    class Obj:
        symbol_id = "S"
        test_id = "T"
        score = 0.95
        kind = Kind()
        linker = "combined"
        low_confidence = False
        evidence = ("a", "b")
        components = (Comp(),)

    e = SymbolTestEdge.from_object(Obj())
    assert e.is_dynamic and e.kind == "dynamic_coverage"
    assert e.components == (("dynamic", 0.9),)
    assert SymbolTestEdge.from_dict(e.to_dict()) == e


def test_edge_and_support_validation():
    with pytest.raises(ValueError):
        SymbolTestEdge("S", "T", 1.5)
    with pytest.raises(ValueError):
        CriterionSupportLinks("C", link_confidence=2.0)


def test_performance_bound_2000_criteria_50_symbols_20_tests():
    rng = random.Random(0)
    n_crit, n_sym, n_tests = 2000, 50, 20
    cids = [f"C{i}" for i in range(n_crit)]
    ev = (reason("lexical", 0.5), reason("identifier", 0.4))
    links = [
        Link(c, f"S{s}", COMBINED, round(rng.random(), 3), ev)
        for c in cids
        for s in range(n_sym)
    ]
    edges = [
        SymbolTestEdge(
            f"S{s}", f"T{s}_{t}", round(rng.random(), 3), kind=rng.choice(KINDS)
        )
        for s in range(n_sym)
        for t in range(n_tests)
    ]
    start = time.perf_counter()
    res = build_support_links(cids, links, edges)
    elapsed = time.perf_counter() - start
    assert len(res.criteria) == n_crit
    assert all(len(c.chains) <= CFG.max_chains_kept for c in res.criteria)
    # Generous: it takes ~18 s on a busy developer laptop and more on a shared CI runner. The bound
    # only has to catch an order-of-magnitude (for example quadratic) regression.
    assert elapsed < 90.0, f"took {elapsed:.1f}s"
