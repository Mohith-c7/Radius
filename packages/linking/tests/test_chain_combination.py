# ruff: noqa: E402, I001  (helper import needs the sys.path setup below; no conftest to avoid plugin-name clashes)
"""Table-driven tests of the chain rule, aggregation and criterion handling (LK-06)."""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_HERE = str(_Path(__file__).parent)
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)

import pytest

from chain_helpers import edge, link, reason, symdoc
from radius_linking.application import (
    ChainConfig,
    aggregate_support,
    build_support_links,
    explain,
    score_chain,
)

CFG = ChainConfig()

# (id, c2s kwargs, s2t kwargs, status, expected score)  -- hand computed from the module docs
CHAIN_CASES = [
    ("plain", dict(a=0.8), dict(b=0.9), "passed", 0.72),
    ("unknown-status-same", dict(a=0.8), dict(b=0.9), "unknown", 0.72),
    ("both-one", dict(a=1.0), dict(b=1.0), "passed", 0.95),
    ("both-half", dict(a=0.5), dict(b=0.5), "passed", 0.25),
    ("hop1-weak", dict(a=0.2), dict(b=0.9), "passed", 0.18),
    ("hop2-weak", dict(a=0.9), dict(b=0.2), "passed", 0.18),
    ("hop1-below-floor", dict(a=0.04), dict(b=0.9), "passed", 0.0),
    ("hop2-below-floor", dict(a=0.9), dict(b=0.04), "passed", 0.0),
    ("both-below-floor", dict(a=0.01), dict(b=0.01), "passed", 0.0),
    ("at-floor", dict(a=0.05), dict(b=1.0), "passed", 0.05),
    ("below-min-chain", dict(a=0.1), dict(b=0.05), "passed", 0.0),
    ("zero-hop1", dict(a=0.0), dict(b=0.9), "passed", 0.0),
    ("zero-hop2", dict(a=0.9), dict(b=0.0), "passed", 0.0),
    # explicit hints dominate hop 1
    ("explicit-lifts-hop1", dict(a=0.3, explicit=0.9), dict(b=0.9), "passed", 0.7695),
    ("explicit-weaker-than-a", dict(a=0.9, explicit=0.5), dict(b=0.9), "passed", 0.81),
    (
        "explicit-zero-score-reason-ignored",
        dict(a=0.6, explicit=0.0),
        dict(b=0.5),
        "passed",
        0.3,
    ),
    ("explicit-only-evidence", dict(a=0.9, explicit=0.9), dict(b=1.0), "passed", 0.9),
    # dynamic evidence dominates hop 2
    (
        "dynamic-lifts-hop2",
        dict(a=0.8),
        dict(b=0.5, kind="dynamic_coverage"),
        "passed",
        0.736,
    ),
    (
        "dynamic-via-component",
        dict(a=0.8),
        dict(b=0.5, comps=(("dynamic", 0.9),)),
        "passed",
        0.736,
    ),
    (
        "dynamic-already-high",
        dict(a=0.8),
        dict(b=0.98, kind="dynamic_coverage"),
        "passed",
        0.784,
    ),
    (
        "dynamic-beats-low-conf-flag",
        dict(a=0.8),
        dict(b=0.5, kind="dynamic_coverage", low=True),
        "passed",
        0.736,
    ),
    (
        "dynamic-rescues-hop2-floor",
        dict(a=0.8),
        dict(b=0.06, kind="dynamic_coverage"),
        "passed",
        0.736,
    ),
    (
        "static-no-dominance",
        dict(a=0.8),
        dict(b=0.5, kind="direct_call"),
        "passed",
        0.4,
    ),
    # low confidence static
    ("low-confidence", dict(a=0.8), dict(b=0.9, low=True), "passed", 0.612),
    # agreement bonus (a=.8, b=.9, base .72)
    (
        "agree-hop1-two-linkers",
        dict(a=0.8, linkers=("lexical", "identifier")),
        dict(b=0.9),
        "passed",
        0.748,
    ),
    (
        "agree-both-two",
        dict(a=0.8, linkers=("lexical", "identifier")),
        dict(b=0.9, comps=(("static", 0.9), ("naming", 0.5))),
        "passed",
        0.776,
    ),
    (
        "agree-hop2-two",
        dict(a=0.8),
        dict(b=0.9, comps=(("static", 0.9), ("naming", 0.5))),
        "passed",
        0.748,
    ),
    (
        "agree-saturated",
        dict(a=0.8, linkers=("lexical", "identifier", "structural")),
        dict(b=0.9, comps=(("static", 0.9), ("naming", 0.5), ("dynamic", 0.4))),
        "passed",
        0.8152,
    ),
    (
        "agree-needs-both-hops-strong",
        dict(a=0.8, linkers=("lexical", "identifier")),
        dict(b=0.45),
        "passed",
        0.36,
    ),
    (
        "prior-and-rerank-are-not-agreement",
        dict(a=0.8, linkers=("lexical", "change_prior", "rerank")),
        dict(b=0.9),
        "passed",
        0.72,
    ),
    (
        "single-component-no-bonus",
        dict(a=0.8),
        dict(b=0.9, comps=(("static", 0.9),)),
        "passed",
        0.72,
    ),
    # caps
    ("cap-other", dict(a=0.99), dict(b=0.99), "passed", 0.95),
    (
        "cap-explicit-without-dynamic",
        dict(a=0.99, explicit=0.95),
        dict(b=0.99),
        "passed",
        0.95,
    ),
    (
        "cap-dynamic-without-explicit",
        dict(a=0.99),
        dict(b=0.99, kind="dynamic_coverage"),
        "passed",
        0.95,
    ),
    (
        "cap-strong",
        dict(a=0.99, explicit=0.95, linkers=("explicit", "lexical")),
        dict(b=1.0, kind="dynamic_coverage", comps=(("static", 0.9), ("dynamic", 0.9))),
        "passed",
        0.99,
    ),
    (
        "explicit-weak-hint-not-strong",
        dict(a=0.99, explicit=0.4, linkers=("explicit", "lexical")),
        dict(b=1.0, kind="dynamic_coverage", comps=(("static", 0.9), ("dynamic", 0.9))),
        "passed",
        0.95,
    ),
    # test status
    ("failed", dict(a=0.8), dict(b=0.9), "failed", 0.288),
    ("flaky", dict(a=0.8), dict(b=0.9), "flaky", 0.36),
    ("skipped", dict(a=0.8), dict(b=0.9), "skipped", 0.072),
    ("status-not-in-table", dict(a=0.8), dict(b=0.9), "weird", 0.72),
    ("failed-after-cap", dict(a=0.99), dict(b=0.99), "failed", 0.38),
    ("skipped-drops-below-min", dict(a=0.2), dict(b=0.3), "skipped", 0.0),
]


@pytest.mark.parametrize(
    "name,c2s,s2t,status,expected", CHAIN_CASES, ids=[c[0] for c in CHAIN_CASES]
)
def test_chain_score_table(name, c2s, s2t, status, expected):
    got = score_chain(link(**c2s), edge(**s2t), status, CFG).score
    assert got == pytest.approx(expected, abs=1e-4)


AGG_CASES = [
    ("empty", [], 0.0),
    ("single", [0.8], 0.8),
    ("two", [0.8, 0.5], 0.87),
    ("two-order-irrelevant", [0.5, 0.8], 0.87),
    ("three", [0.8, 0.5, 0.5], 0.90185),
    ("zeros-ignored", [0.8, 0.0, 0.0], 0.8),
    ("cap", [0.95, 0.95, 0.95], 0.95),
    ("single-over-cap", [1.0], 0.95),
    ("top-n-limits", [0.5] * 20, None),
    ("tiny", [0.01], 0.01),
]


@pytest.mark.parametrize(
    "name,supports,expected", AGG_CASES, ids=[c[0] for c in AGG_CASES]
)
def test_aggregate_table(name, supports, expected):
    got = aggregate_support(supports, CFG)
    if expected is None:
        assert got == aggregate_support([0.5] * CFG.agg_top_n, CFG)
        assert got <= CFG.cap_other
    else:
        assert got == pytest.approx(expected, abs=1e-6)


def test_aggregate_strong_cap():
    assert aggregate_support([0.99, 0.99], CFG, strong=True) == pytest.approx(0.99)
    assert aggregate_support([0.99, 0.99], CFG, strong=False) == pytest.approx(0.95)


def test_diminishing_returns():
    gains = []
    prev = 0.0
    for n in range(1, 6):
        cur = aggregate_support([0.5] * n, CFG)
        gains.append(cur - prev)
        prev = cur
    assert all(g > 0 for g in gains)
    assert all(a > b for a, b in zip(gains, gains[1:], strict=False))


SPEC_CASES = [
    (1, 1.0),
    (2, 1.0),
    (3, 1 / 1.15),
    (4, 1 / 1.3),
    (6, 1 / 1.6),
    (10, 0.5),
    (100, 0.5),
]


@pytest.mark.parametrize("n_criteria,expected", SPEC_CASES)
def test_specificity_factor(n_criteria, expected):
    """Tests shared by many criteria are penalised (specificity), floored at 0.5."""
    cids = [f"C{i}" for i in range(n_criteria)]
    links = [link(c, "S1", a=0.8) for c in cids]
    res = build_support_links(cids, links, [edge("S1", "T1", b=0.9)])
    for cs in res.criteria:
        assert cs.chains[0].specificity == pytest.approx(expected, abs=1e-6)
        assert cs.chains[0].support_score == pytest.approx(0.72 * expected, abs=2e-6)
        if expected < 1:
            assert any(r.kind == "specificity_penalty" for r in cs.chains[0].reasons)


def test_specificity_ignores_weak_chains():
    """A weak chain (below spec_min) through the same test does not count as a covered criterion."""
    cids = ["C1", "C2", "C3", "C4"]
    links = [link("C1", "S1", a=0.8), link("C2", "S1", a=0.8)] + [
        link(c, "S1", a=0.2) for c in ("C3", "C4")
    ]
    res = build_support_links(cids, links, [edge("S1", "T1", b=0.9)])
    assert (
        res.criteria[0].chains[0].specificity == 1.0
    )  # only 2 strong criteria: within free


# ------------------------------------------------------------ criterion handling
def run(cids, links, edges, **kw):
    return build_support_links(cids, links, edges, **kw)


def test_single_chain_end_to_end_with_reasons():
    res = run(["C1"], [link("C1", "S1", a=0.8)], [edge("S1", "T1", b=0.9)])
    cs = res.criteria[0]
    assert cs.unlinked_reason is None
    assert cs.link_confidence == pytest.approx(0.72)
    assert cs.score_kind == "link_confidence_uncalibrated" == res.score_kind
    kinds = [r.kind for r in cs.chains[0].reasons]
    assert kinds[:3] == ["hop1_criterion_symbol", "hop2_symbol_test", "chain_noisy_and"]
    assert any(r.kind == "aggregate_term" for r in cs.reasons)
    assert res.calibration is None


def test_no_symbol_candidates():
    cs = run(["C1"], [], [edge("S1", "T1")]).criteria[0]
    assert (cs.unlinked_reason, cs.link_confidence, cs.chains) == (
        "no_symbol_candidates",
        0.0,
        (),
    )
    assert not cs.suspicious


def test_unknown_criterion_links_ignored():
    cs = run(["C1"], [link("OTHER", "S1")], [edge("S1", "T1")]).criteria[0]
    assert cs.unlinked_reason == "no_symbol_candidates"


def test_untested_change():
    cs = run(["C1"], [link("C1", "S1", a=0.9)], [edge("S9", "T1")]).criteria[0]
    assert cs.unlinked_reason == "untested_change"
    assert cs.link_confidence == 0.0
    assert any(r.kind == "untested_symbol" for r in cs.reasons)


def test_tests_without_symbol_is_suspicious():
    cs = run(["C1"], [], [], hinted_tests={"C1": ["tests/test_a.py::test_x"]}).criteria[
        0
    ]
    assert cs.unlinked_reason == "tests_without_symbol"
    assert cs.suspicious and cs.link_confidence == 0.0
    assert any(r.kind == "hinted_test_without_symbol" for r in cs.reasons)


def test_hinted_tests_do_not_matter_when_symbols_exist():
    cs = run(
        ["C1"], [link("C1", "S1")], [edge("S1", "T1")], hinted_tests={"C1": ["t::x"]}
    ).criteria[0]
    assert cs.unlinked_reason is None and not cs.suspicious


NON_BEHAVIORAL = [
    "formatting_only",
    "docstring_or_comment_only",
    "docstring_only",
    "comment_only",
    "modified_body",  # is_behavioral=False alone also excludes
]


@pytest.mark.parametrize("change", NON_BEHAVIORAL)
def test_non_behavioral_symbols_excluded(change):
    doc = symdoc("S1", change=change, behavioral=False)
    cs = run(
        ["C1"], [link("C1", "S1")], [edge("S1", "T1")], symbols={"S1": doc}
    ).criteria[0]
    assert cs.unlinked_reason == "only_non_behavioral_symbols"
    assert any(r.kind == "excluded_non_behavioral" for r in cs.reasons)


def test_behavioral_flag_alone_excludes_and_formatting_kind_alone_excludes():
    cs = run(
        ["C1"],
        [link("C1", "S1")],
        [edge("S1", "T1")],
        symbols={"S1": symdoc("S1", change="formatting_only", behavioral=True)},
    ).criteria[0]
    assert cs.unlinked_reason == "only_non_behavioral_symbols"
    cs = run(
        ["C1"],
        [link("C1", "S1")],
        [edge("S1", "T1")],
        symbols={"S1": symdoc("S1", change="modified_body", behavioral=False)},
    ).criteria[0]
    assert cs.unlinked_reason == "only_non_behavioral_symbols"


def test_mixed_symbols_keep_behavioral_one():
    cs = run(
        ["C1"],
        [link("C1", "S1", a=0.9), link("C1", "S2", a=0.8)],
        [edge("S1", "T1", b=0.9), edge("S2", "T2", b=0.9)],
        symbols={"S1": symdoc("S1", change="formatting_only"), "S2": symdoc("S2")},
    ).criteria[0]
    assert [c.symbol_id for c in cs.chains] == ["S2"]
    assert any(r.kind == "excluded_non_behavioral" for r in cs.reasons)


def test_unknown_symbol_info_is_kept():
    cs = run(["C1"], [link("C1", "S1")], [edge("S1", "T1")], symbols={}).criteria[0]
    assert cs.chains


@pytest.mark.parametrize(
    "status,factor",
    [
        ("passed", 1.0),
        ("unknown", 1.0),
        ("flaky", 0.5),
        ("failed", 0.4),
        ("skipped", 0.1),
    ],
)
def test_test_status_discount_end_to_end(status, factor):
    cs = run(
        ["C1"],
        [link("C1", "S1", a=0.8)],
        [edge("S1", "T1", b=0.9)],
        test_status={"T1": status},
    ).criteria[0]
    assert cs.link_confidence == pytest.approx(0.72 * factor, abs=1e-5)
    if factor < 1:
        assert any(r.kind == "test_status_discount" for r in cs.chains[0].reasons)
    assert cs.chains[0].test_status == status


def test_failed_test_only_is_weak_chain_not_untested():
    cs = run(
        ["C1"],
        [link("C1", "S1", a=0.2)],
        [edge("S1", "T1", b=0.3)],
        test_status={"T1": "skipped"},
    ).criteria[0]
    assert cs.unlinked_reason == "only_weak_chains"


def test_flaky_discounted_but_good_test_wins():
    cs = run(
        ["C1"],
        [link("C1", "S1", a=0.8)],
        [edge("S1", "T1", b=0.9), edge("S1", "T2", b=0.85)],
        test_status={"T1": "flaky"},
    ).criteria[0]
    assert cs.chains[0].test_id == "T2"


def test_same_test_via_two_symbols_counted_once():
    one = run(["C1"], [link("C1", "S1", a=0.8)], [edge("S1", "T1", b=0.9)]).criteria[0]
    two = run(
        ["C1"],
        [link("C1", "S1", a=0.8), link("C1", "S2", a=0.8)],
        [edge("S1", "T1", b=0.9), edge("S2", "T1", b=0.9)],
    ).criteria[0]
    assert len(two.chains) == 2
    assert two.link_confidence == one.link_confidence


def test_two_different_tests_raise_confidence_with_diminishing_returns():
    one = run(["C1"], [link("C1", "S1", a=0.8)], [edge("S1", "T1", b=0.9)]).criteria[0]
    two = run(
        ["C1"],
        [link("C1", "S1", a=0.8)],
        [edge("S1", "T1", b=0.9), edge("S1", "T2", b=0.9)],
    ).criteria[0]
    assert two.link_confidence == pytest.approx(1 - 0.28 * (1 - 0.7 * 0.72), abs=1e-5)
    assert two.link_confidence > one.link_confidence


def test_symbol_and_test_limits():
    cfg = ChainConfig(
        max_symbols_per_criterion=2, max_tests_per_symbol=1, max_chains_kept=2
    )
    links = [link("C1", f"S{i}", a=0.9 - i * 0.01) for i in range(5)]
    edges = [
        edge(f"S{i}", f"T{i}{j}", b=0.9 - j * 0.1) for i in range(5) for j in range(3)
    ]
    cs = run(["C1"], links, edges, config=cfg).criteria[0]
    assert [(c.symbol_id, c.test_id) for c in cs.chains] == [
        ("S0", "T00"),
        ("S1", "T10"),
    ]


def test_best_duplicate_inputs_win():
    cs = run(
        ["C1"],
        [link("C1", "S1", a=0.4), link("C1", "S1", a=0.8)],
        [edge("S1", "T1", b=0.5), edge("S1", "T1", b=0.9)],
    ).criteria[0]
    assert len(cs.chains) == 1 and cs.link_confidence == pytest.approx(0.72)


def test_non_combined_links_ignored():
    cs = run(
        ["C1"], [link("C1", "S1", main="lexical", combined=False)], [edge("S1", "T1")]
    ).criteria[0]
    assert cs.unlinked_reason == "no_symbol_candidates"


def test_strong_cap_applies_to_criterion():
    c2s = link("C1", "S1", a=0.99, explicit=0.95, linkers=("explicit", "lexical"))
    e = edge(
        "S1",
        "T1",
        b=1.0,
        kind="dynamic_coverage",
        comps=(("static", 0.9), ("dynamic", 0.9)),
    )
    e2 = edge(
        "S1",
        "T2",
        b=1.0,
        kind="dynamic_coverage",
        comps=(("static", 0.9), ("dynamic", 0.9)),
    )
    cs = run(["C1"], [c2s], [e, e2]).criteria[0]
    assert 0.95 < cs.link_confidence <= 0.99
    plain = run(
        ["C1"],
        [link("C1", "S1", a=0.99)],
        [edge("S1", "T1", b=1.0), edge("S1", "T2", b=1.0)],
    ).criteria[0]
    assert plain.link_confidence <= 0.95
    assert any(r.kind == "aggregate_cap" for r in plain.reasons)


def test_explain_lists_every_number_source():
    cs = run(
        ["C1"],
        [link("C1", "S1", a=0.8)],
        [edge("S1", "T1", b=0.9)],
        test_status={"T1": "flaky"},
    ).criteria[0]
    text = "\n".join(explain(cs))
    for needle in (
        "C1",
        "link_confidence_uncalibrated",
        "hop1_criterion_symbol",
        "test_status_discount",
        "aggregate_term",
    ):
        assert needle in text
    assert "unlinked" in "\n".join(explain(run(["C2"], [], []).criteria[0]))


def test_criteria_sorted_and_deduplicated():
    res = run(["C2", "C1", "C2"], [], [])
    assert [c.criterion_id for c in res.criteria] == ["C1", "C2"]
    assert res.for_criterion("C2") is not None and res.for_criterion("zz") is None


def test_reason_helper_scores_valid():
    assert reason("explicit", 0.5).score == 0.5


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(cap_other=0.99, cap_strong=0.9),
        dict(decay=1.5),
        dict(spec_floor=0.0),
        dict(agg_top_n=0),
        dict(max_symbols_per_criterion=0),
        dict(max_tests_per_symbol=0),
        dict(max_chains_kept=0),
        dict(agree_full=0),
        dict(status_factors={"failed": 2.0}),
        dict(hop_floor=-0.1),
    ],
)
def test_config_validation(kwargs):
    with pytest.raises(ValueError):
        ChainConfig(**kwargs)


def test_config_is_recorded_and_changes_scores():
    cfg = ChainConfig(status_factors={"failed": 0.0})
    res = run(
        ["C1"],
        [link("C1", "S1")],
        [edge("S1", "T1")],
        test_status={"T1": "failed"},
        config=cfg,
    )
    assert res.criteria[0].unlinked_reason == "only_weak_chains"
    assert res.config["status_factors"] == {"failed": 0.0}
    assert res.config["combiner"] == "link-chain-v1"
