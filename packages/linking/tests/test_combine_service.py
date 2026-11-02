# ruff: noqa: E402, I001  (helper import needs the sys.path setup below; no conftest to avoid plugin-name clashes)
"""Combination properties and the end-to-end linking service."""

from __future__ import annotations

import itertools
import json
import random
import time

import pytest
import sys as _sys
from pathlib import Path as _Path

_HERE = str(_Path(__file__).parent)
if _HERE not in _sys.path:  # helper module lives next to the tests (importlib mode)
    _sys.path.insert(0, _HERE)

from linking_helpers import crit, sym
from radius_linking.application import (
    CombineConfig,
    LinkingConfig,
    combine_scores,
    link_criteria,
    select_candidates,
)
from radius_linking.domain import (
    COMBINED,
    CriterionInput,
    Link,
    LinkSet,
    Reason,
    RerankAdjustment,
    RerankResult,
)
from radius_linking.infrastructure.linkers import ChangePriorLinker, default_linkers
from radius_linking.infrastructure.rerank import FixedReranker, OverlapReranker

CFG = CombineConfig()

DISCOUNT = sym(
    "src/pricing.py",
    "apply_discount",
    docstring="Reduce price by percent, rounded to 2 decimals.",
    identifiers=("percent", "price", "ValueError"),
    literals=("percent must be between 0 and 100",),
)
EMAIL = sym(
    "src/emails.py", "normalize_email", docstring="Lowercase and strip an email."
)
FMT = sym(
    "src/pricing_fmt.py",
    "apply_discount_label",
    change="formatting_only",
    behavioral=False,
    docstring="Discount label for price.",
)
TEST_SYM = sym("tests/test_pricing.py", "test_apply_discount", is_test=True)


def run(criteria, symbols, **kw):
    return link_criteria(
        criteria,
        symbols,
        linkers=kw.pop("linkers", default_linkers()),
        prior=kw.pop("prior", ChangePriorLinker()),
        **kw,
    )


# ------------------------------------------------------------------ combination


def test_combine_zero_evidence_is_zero():
    assert combine_scores({}, 1.0, CFG) == 0.0
    assert combine_scores({"lexical": 0.0}, 1.0, CFG) == 0.0


def test_combine_single_linker_uses_weight_and_prior():
    assert combine_scores({"lexical": 0.5}, 1.0, CFG) == pytest.approx(0.8 * 0.5)
    assert combine_scores({"lexical": 0.5}, 0.0, CFG) == pytest.approx(0.8 * 0.5 * 0.5)


def test_combine_noisy_or_across_linkers():
    got = combine_scores({"lexical": 0.5, "identifier": 0.5}, 1.0, CFG)
    assert got == pytest.approx(1 - (1 - 0.4) * (1 - 0.45))


def test_combine_caps_non_explicit_at_095_and_explicit_at_099():
    assert (
        combine_scores({"identifier": 1.0, "lexical": 1.0, "structural": 1.0}, 1.0, CFG)
        == 0.95
    )
    assert combine_scores({"explicit": 1.0, "lexical": 1.0}, 1.0, CFG) == 0.99


def test_combine_unknown_linker_has_no_weight():
    assert combine_scores({"mystery": 1.0}, 1.0, CFG) == 0.0


def test_combine_is_monotone_in_every_input():
    rng = random.Random(7)
    names = ["explicit", "lexical", "identifier", "structural"]
    for _ in range(300):
        base = {n: rng.random() for n in names}
        prior = rng.random()
        before = combine_scores(base, prior, CFG)
        for n in names:
            bumped = dict(base)
            bumped[n] = min(1.0, base[n] + rng.random() * 0.5)
            assert combine_scores(bumped, prior, CFG) >= before - 1e-12
        assert combine_scores(base, min(1.0, prior + 0.3), CFG) >= before - 1e-12
        assert 0.0 <= before <= 1.0


def test_combine_is_order_independent():
    scores = {"explicit": 0.3, "lexical": 0.6, "identifier": 0.2}
    values = {
        combine_scores(dict(p), 0.7, CFG)
        for p in itertools.permutations(scores.items())
    }
    assert len(values) == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"weights": {"lexical": 1.5}},
        {"prior_strength": 2.0},
        {"cap_other": 0.99, "cap_explicit": 0.9},
        {"min_score": 1.0},
        {"top_k": 0},
    ],
)
def test_combine_config_validation(kwargs):
    with pytest.raises(ValueError):
        CombineConfig(**kwargs)


def test_configurable_weights_change_the_ranking():
    only_lex = CombineConfig(weights={"lexical": 1.0})
    assert combine_scores({"identifier": 1.0}, 1.0, only_lex) == 0.0


# ------------------------------------------------------------------ service


def test_end_to_end_ranks_matching_symbol_first_with_reasons():
    ls = run(
        [crit("apply_discount reduces the price by percent")], [DISCOUNT, EMAIL, FMT]
    )
    top = ls.links[0]
    assert (
        top.symbol_id == DISCOUNT.symbol_id and top.rank == 1 and top.linker == COMBINED
    )
    assert {e.linker for e in top.evidence} >= {"identifier", "lexical", "change_prior"}
    assert [x.rank for x in ls.for_criterion("C1")] == list(
        range(1, len(ls.for_criterion("C1")) + 1)
    )


def test_behavioral_change_outranks_formatting_only_with_equal_text_evidence():
    a = sym("src/a.py", "refund_order", docstring="refund the order")
    b = sym(
        "src/b.py",
        "refund_order",
        change="formatting_only",
        behavioral=False,
        docstring="refund the order",
    )
    ls = run([crit("refund the order")], [b, a])
    assert ls.links[0].symbol_id == a.symbol_id
    assert ls.links[0].score > ls.links[1].score


def test_per_linker_links_are_kept_for_ablation():
    ls = run([crit("apply_discount reduces the price")], [DISCOUNT, EMAIL])
    assert {x.linker for x in ls.by_linker} >= {"lexical", "identifier", "change_prior"}
    assert ls.ranking("C1", "lexical")[0] == DISCOUNT.symbol_id
    assert ls.ranking("C1")[0] == DISCOUNT.symbol_id


def test_algo_versions_and_config_recorded():
    ls = run([crit("price")], [DISCOUNT], snapshot_id="snap-1", changeset_ref="cs-1")
    assert ls.snapshot_id == "snap-1" and ls.changeset_ref == "cs-1"
    assert ls.algo_versions["lexical"] == "lexical-bm25-v1"
    assert ls.algo_versions["combiner"].startswith("noisy-or")
    assert ls.algo_versions["change_prior"] == "change-prior-v1"
    assert ls.config["combine"]["weights"]["explicit"] == 1.0


def test_no_candidates_yields_empty_linkset():
    ls = run([crit("anything")], [])
    assert ls.links == () and ls.by_linker == ()


def test_no_criteria_yields_empty_linkset():
    assert run([], [DISCOUNT]).links == ()


def test_empty_criterion_text_produces_no_links_and_a_diagnostic():
    ls = run([crit("   ")], [DISCOUNT])
    assert ls.links == ()
    assert "empty_criterion:C1" in ls.diagnostics


def test_empty_text_with_hint_still_links_explicitly():
    ls = run([crit("", paths=("src/pricing.py",))], [DISCOUNT, EMAIL])
    assert ls.links[0].symbol_id == DISCOUNT.symbol_id
    assert ls.links[0].evidence[0].linker == "explicit"
    # the structural linker adds the same-directory neighbour below the hinted symbol
    assert (
        ls.links[1].symbol_id == EMAIL.symbol_id
        and ls.links[1].score < ls.links[0].score
    )
    assert not any(d.startswith("empty_criterion") for d in ls.diagnostics)


def test_criterion_with_no_evidence_gets_no_links_but_others_do():
    ls = run(
        [crit("zzz qqq www", "C1"), crit("apply_discount", "C2")], [DISCOUNT, EMAIL]
    )
    assert ls.for_criterion("C1") == ()
    assert ls.for_criterion("C2")


def test_test_symbols_are_excluded_by_default_and_optionally_kept():
    c = crit("apply_discount")
    assert all(
        x.symbol_id != TEST_SYM.symbol_id for x in run([c], [DISCOUNT, TEST_SYM]).links
    )
    ls = run(
        [c], [DISCOUNT, TEST_SYM], config=LinkingConfig(exclude_test_symbols=False)
    )
    assert TEST_SYM.symbol_id in {x.symbol_id for x in ls.links}
    assert "excluded_test_symbols:1" in run([c], [DISCOUNT, TEST_SYM]).diagnostics


def test_links_only_reference_input_symbols():
    class Rogue:
        name, version = "rogue", "1"

        def link(self, criteria, symbols, context):
            ok = Link(
                "C1",
                symbols[0].symbol_id,
                "rogue",
                0.9,
                (Reason("rogue", "k", "d", 0.9),),
            )
            bad = Link(
                "C1", "ghost-symbol", "rogue", 1.0, (Reason("rogue", "k", "d", 1.0),)
            )
            return [ok, bad]

    cfg = LinkingConfig(combine=CombineConfig(weights={"rogue": 1.0}))
    ls = run([crit("x")], [DISCOUNT], linkers=[Rogue()], config=cfg)
    assert {x.symbol_id for x in ls.links + ls.by_linker} == {DISCOUNT.symbol_id}
    assert "dropped_foreign_link:rogue" in ls.diagnostics


def test_links_without_reasons_or_with_zero_score_are_dropped():
    class Lazy:
        name, version = "lazy", "1"

        def link(self, criteria, symbols, context):
            return [
                Link("C1", symbols[0].symbol_id, "lazy", 0.9, ()),
                Link(
                    "C1",
                    symbols[0].symbol_id,
                    "lazy",
                    0.0,
                    (Reason("lazy", "k", "d", 0.0),),
                ),
            ]

    cfg = LinkingConfig(combine=CombineConfig(weights={"lazy": 1.0}))
    assert run([crit("x")], [DISCOUNT], linkers=[Lazy()], config=cfg).links == ()


def test_failing_linker_is_isolated():
    class Boom:
        name, version = "boom", "1"

        def link(self, criteria, symbols, context):
            raise RuntimeError("nope")

    seen = []
    ls = run(
        [crit("apply_discount")],
        [DISCOUNT],
        linkers=[Boom(), *default_linkers()],
        on_error=lambda n, e: seen.append(n),
    )
    assert ls.links and "linker_failed:boom:RuntimeError" in ls.diagnostics
    assert seen == ["boom"]


def test_duplicate_symbols_and_criteria_are_collapsed():
    ls = run([crit("apply_discount"), crit("apply_discount")], [DISCOUNT, DISCOUNT])
    assert len(ls.for_criterion("C1")) == 1


def test_top_k_limits_links_per_criterion():
    symbols = [
        sym(f"src/m{i}.py", f"discount_{i}", docstring="discount") for i in range(8)
    ]
    cfg = LinkingConfig(combine=CombineConfig(top_k=3))
    ls = run([crit("discount")], symbols, config=cfg)
    assert len(ls.for_criterion("C1")) == 3


def test_max_symbols_truncates_deterministically_keeping_behavioral_first():
    symbols = [
        sym(f"src/m{i}.py", f"f{i}", change="formatting_only", behavioral=False)
        for i in range(3)
    ]
    symbols.append(sym("src/z.py", "g"))
    kept, diags = select_candidates(symbols, LinkingConfig(max_symbols=2))
    assert len(kept) == 2 and any(s.qualified_name == "g" for s in kept)
    assert "truncated_symbols:2" in diags


def test_determinism_same_inputs_same_bytes_and_order_independent():
    symbols = [
        DISCOUNT,
        EMAIL,
        FMT,
        sym("src/cart.py", "Cart.add", docstring="add price to cart"),
    ]
    criteria = [
        crit("apply_discount reduces price", "C1"),
        crit("emails are lowercased", "C2"),
    ]
    a = run(criteria, symbols).to_json()
    b = run(criteria, symbols).to_json()
    c = run(list(reversed(criteria)), list(reversed(symbols))).to_json()
    assert a == b == c


def test_linkset_roundtrips_through_json():
    ls = run([crit("apply_discount reduces the price")], [DISCOUNT, EMAIL])
    again = LinkSet.from_json(ls.to_json())
    assert again == ls
    assert json.loads(ls.to_json(indent=2))["algo_version"]


def test_every_combined_link_has_reasons_and_valid_ranks():
    ls = run([crit("apply_discount reduces the price")], [DISCOUNT, EMAIL, FMT])
    for x in ls.links:
        assert x.evidence and 0 < x.score <= 1 and x.rank >= 1


def test_tenant_agnostic_purity_no_org_data_in_output():
    c = CriterionInput("C1", "apply_discount", state="confirmed")
    out = run([c], [DISCOUNT]).to_json()
    assert "organization" not in out and "tenant" not in out


def test_performance_bound_on_large_input():
    symbols = [
        sym(
            f"src/pkg{i % 40}/mod{i}.py",
            f"handle_item_{i}",
            docstring=f"handle item number {i} for customer flow {i % 17}",
            identifiers=(f"var{i}", "price", "total", "cart"),
            literals=(f"message {i}",),
        )
        for i in range(2000)
    ]
    criteria = [
        crit(f"handle item {i} and compute the cart total price", f"C{i}")
        for i in range(20)
    ]
    started = time.perf_counter()
    ls = run(criteria, symbols)
    assert time.perf_counter() - started < 15.0
    assert ls.links


# ------------------------------------------------------------------ rerank in the pipeline


def test_reranker_cannot_add_symbols_even_when_it_tries():
    ghost = "ghost-symbol"
    fake = FixedReranker(
        {ghost: (1.0, "invented"), EMAIL.symbol_id: (1.0, "not a candidate")}
    )
    ls = run([crit("apply_discount")], [DISCOUNT, EMAIL], reranker=fake)
    ids = {x.symbol_id for x in ls.links + ls.by_linker}
    assert ghost not in ids and EMAIL.symbol_id not in ids
    assert "rerank_ignored_non_candidate" in ls.diagnostics


def test_reranker_reorders_only_candidates_and_records_reason():
    a = sym("src/a.py", "discount_alpha", docstring="discount")
    b = sym("src/b.py", "discount_beta", docstring="discount")
    base = run([crit("discount")], [a, b])
    loser = base.links[-1].symbol_id
    fake = FixedReranker(
        {loser: (1.0, "model prefers this"), base.links[0].symbol_id: (0.0, "no")}
    )
    ls = run(
        [crit("discount")],
        [a, b],
        reranker=fake,
        config=LinkingConfig(rerank_weight=1.0),
    )
    assert ls.links[0].symbol_id == loser
    assert {x.symbol_id for x in ls.links} == {x.symbol_id for x in base.links}
    assert any(e.linker == "rerank" for e in ls.links[0].evidence)
    assert any(x.linker == "rerank" for x in ls.by_linker)
    assert any(k.startswith("reranker:") for k in ls.algo_versions)


def test_rerank_blend_keeps_scores_in_unit_interval():
    fake = FixedReranker({DISCOUNT.symbol_id: (5.0, "huge")})
    ls = run([crit("apply_discount")], [DISCOUNT], reranker=fake)
    assert 0 <= ls.links[0].score <= 1


def test_bad_rerank_score_type_is_ignored():
    class Weird:
        name, version = "weird", "1"

        def rerank(self, criterion, candidates):
            return RerankResult({candidates[0].symbol_id: RerankAdjustment("abc", "x")}, ("note",))  # type: ignore[arg-type]

    ls = run([crit("apply_discount")], [DISCOUNT], reranker=Weird())
    assert (
        "rerank_ignored_bad_score" in ls.diagnostics and "rerank:note" in ls.diagnostics
    )


def test_failing_reranker_falls_back_to_deterministic_order():
    class Boom:
        name, version = "boom", "1"

        def rerank(self, criterion, candidates):
            raise RuntimeError("x")

    base = run([crit("apply_discount")], [DISCOUNT])
    ls = run([crit("apply_discount")], [DISCOUNT], reranker=Boom())
    assert ls.links == base.links
    assert "reranker_failed:boom:RuntimeError" in ls.diagnostics


def test_overlap_reranker_is_deterministic_and_bounded():
    ls1 = run(
        [crit("apply discount price")], [DISCOUNT, EMAIL], reranker=OverlapReranker()
    )
    ls2 = run(
        [crit("apply discount price")], [DISCOUNT, EMAIL], reranker=OverlapReranker()
    )
    assert ls1.to_json() == ls2.to_json()
    assert all(0 <= x.score <= 1 for x in ls1.links)
