"""Explicit-hint, structural-proximity and change-prior linkers."""

from __future__ import annotations

import pytest
from linking_helpers import by_symbol, crit, sym
from radius_linking.domain import LinkContext
from radius_linking.infrastructure.linkers import (
    ChangePriorLinker,
    ExplicitLinker,
    StructuralLinker,
    match_hints,
)
from radius_linking.infrastructure.linkers.common import (
    glob_match,
    is_test_path,
    noisy_or,
    pattern_specificity,
)

CTX = LinkContext()


# ------------------------------------------------------------------ globs / helpers


@pytest.mark.parametrize(
    ("pattern", "path", "ok"),
    [
        ("src/pricing.py", "src/pricing.py", True),
        ("src/pricing.py", "src/other.py", False),
        ("src/*.py", "src/pricing.py", True),
        ("src/*.py", "src/sub/pricing.py", False),
        ("src/**/*.py", "src/a/b/pricing.py", True),
        ("src/**", "src/a/b.py", True),
        ("**/pricing.py", "pricing.py", True),
        ("**/pricing.py", "x/y/pricing.py", True),
        ("src/", "src/a.py", True),
        ("src", "src/a.py", True),
        ("src", "srcx/a.py", False),
        ("./src/a.py", "src/a.py", True),
        ("src\\a.py", "src/a.py", True),
        ("a?.py", "ab.py", True),
        ("", "a.py", False),
    ],
)
def test_glob_match(pattern, path, ok):
    assert glob_match(pattern, path) is ok


def test_pattern_specificity_orders_hints():
    assert pattern_specificity("src/pricing.py") > pattern_specificity("src/*.py")
    assert pattern_specificity("src/*.py") > pattern_specificity("src/**")
    assert pattern_specificity("src/") == pattern_specificity("**") == 0.5


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tests/test_x.py", True),
        ("src/test_x.py", True),
        ("src/x_test.py", True),
        ("web/app.test.ts", True),
        ("web/__tests__/a.ts", True),
        ("src/conftest.py", True),
        ("src/contest.py", False),
        ("src/pricing.py", False),
    ],
)
def test_is_test_path(path, expected):
    assert is_test_path(path) is expected


def test_noisy_or_basics():
    assert noisy_or([]) == 0.0
    assert noisy_or([0.5, 0.5]) == pytest.approx(0.75)
    assert noisy_or([1.0, 0.3]) == 1.0


# ------------------------------------------------------------------ explicit

A = sym("src/pricing.py", "apply_discount")
B = sym("src/pricing.py", "line_total")
C = sym("src/cart.py", "Cart.add")
D = sym("lib/other.py", "unrelated")


def run_explicit(c, symbols):
    return by_symbol(ExplicitLinker().link([c], symbols, CTX))


def test_exact_file_hint_matches_all_symbols_in_file():
    got = run_explicit(crit("x", paths=("src/pricing.py",)), [A, B, C, D])
    assert set(got) == {A.symbol_id, B.symbol_id}
    assert got[A.symbol_id].score == pytest.approx(0.85)
    assert got[A.symbol_id].evidence[0].kind == "path_hint"
    assert got[A.symbol_id].evidence[0].linker == "explicit"


def test_path_symbol_hint_is_strongest_and_selective():
    got = run_explicit(crit("x", paths=("src/pricing.py::apply_discount",)), [A, B])
    assert set(got) == {A.symbol_id}
    assert got[A.symbol_id].score == pytest.approx(0.95)


def test_path_symbol_hint_matches_class_members():
    got = run_explicit(crit("x", paths=("src/cart.py::Cart",)), [C])
    assert set(got) == {C.symbol_id}


def test_wildcard_and_directory_hints_are_weaker():
    wild = run_explicit(crit("x", paths=("src/*.py",)), [A])[A.symbol_id].score
    broad = run_explicit(crit("x", paths=("src/**",)), [A])[A.symbol_id].score
    assert wild == pytest.approx(0.7) and broad == pytest.approx(0.5)


def test_multiple_hints_take_the_max_and_keep_all_reasons():
    got = run_explicit(
        crit("x", paths=("src/**", "src/pricing.py::apply_discount")), [A]
    )[A.symbol_id]
    assert got.score == pytest.approx(0.95)
    assert len(got.evidence) == 2
    assert got.evidence[0].score >= got.evidence[1].score


def test_no_hints_no_links():
    assert ExplicitLinker().link([crit("anything")], [A, B], CTX) == []


def test_hint_matching_nothing_yields_nothing():
    assert run_explicit(crit("x", paths=("docs/**",)), [A, B]) == {}


def test_blank_path_hint_is_ignored():
    assert match_hints(crit("x", paths=("::foo",)), [A]) == {}


def test_path_mentioned_in_criterion_text_links_file():
    got = run_explicit(crit("Update `src/pricing.py` so that it rounds"), [A, C])
    assert set(got) == {A.symbol_id}
    assert got[A.symbol_id].evidence[0].kind == "path_mention"
    assert got[A.symbol_id].score == pytest.approx(0.9)


def test_path_mention_matches_by_suffix_not_substring():
    got = run_explicit(crit("see pricing.py"), [A, sym("src/xpricing.py", "f")])
    assert set(got) == {A.symbol_id}


def test_test_hint_links_by_module_and_name():
    t = crit(
        "x", tests=("tests/test_pricing.py::test_apply_discount_rejects_negative",)
    )
    got = run_explicit(t, [A, B, C])
    assert got[A.symbol_id].score == pytest.approx(0.8)  # file stem + name tokens
    assert got[B.symbol_id].score == pytest.approx(0.35)  # file stem only
    assert C.symbol_id not in got
    assert got[A.symbol_id].evidence[0].kind == "test_hint"


def test_test_hint_name_only_match():
    t = crit("x", tests=("tests/test_misc.py::test_cart_add_works",))
    got = run_explicit(t, [C, A])
    assert set(got) == {C.symbol_id}
    assert got[C.symbol_id].score == pytest.approx(0.45)


def test_explicit_is_deterministic_regardless_of_symbol_order():
    c = crit("x", paths=("src/*.py",))
    one = ExplicitLinker().link([c], [A, B, C], CTX)
    two = ExplicitLinker().link([c], [C, B, A], CTX)
    assert {x.symbol_id: x.score for x in one} == {x.symbol_id: x.score for x in two}


# ------------------------------------------------------------------ structural


class Graph:
    def __init__(self, table):
        self.table = table

    def neighbors(self, ref):
        return self.table.get(ref, {})


def run_struct(c, symbols, graph=None, **kw):
    ctx = LinkContext(neighbors=graph)
    return by_symbol(StructuralLinker(**kw).link([c], symbols, ctx))


def test_structural_needs_seed_from_hints():
    assert run_struct(crit("anything at all"), [A, B]) == {}


def test_same_file_neighbour_scored_by_seed_and_proximity():
    seed = crit("x", paths=("src/pricing.py::apply_discount",))
    got = run_struct(seed, [A, B, C, D])
    assert A.symbol_id not in got  # seeds belong to the explicit linker
    assert got[B.symbol_id].score == pytest.approx(0.95 * 0.6)
    assert got[B.symbol_id].evidence[0].kind == "same_file"
    assert got[C.symbol_id].score == pytest.approx(0.95 * 0.35)  # same directory
    assert got[C.symbol_id].evidence[0].kind == "same_dir"
    assert D.symbol_id not in got


def test_adjacent_directory_gets_weakest_proximity():
    deep = sym("src/pkg/inner.py", "f")
    seed = crit("x", paths=("src/pricing.py::apply_discount",))
    got = run_struct(seed, [A, deep])
    assert got[deep.symbol_id].score == pytest.approx(0.95 * 0.2)


def test_broad_hint_is_not_a_seed():
    assert run_struct(crit("x", paths=("src/**",)), [A, B]) == {}


def test_call_graph_neighbours_decay_with_hops():
    far = sym("lib/far.py", "far_fn")
    near = sym("lib/near.py", "near_fn")
    graph = Graph({A.ref: {near.ref: 1, far.ref: 3, "x::y": 1}})
    seed = crit("x", paths=("src/pricing.py::apply_discount",))
    got = run_struct(seed, [A, near, far], graph)
    assert got[near.symbol_id].score == pytest.approx(0.95 * 0.7)
    assert got[far.symbol_id].score == pytest.approx(0.95 * 0.7 * 0.6**2)
    assert got[near.symbol_id].evidence[0].kind == "call_graph"


def test_call_graph_beyond_max_hops_is_ignored_and_cap_applies():
    far = sym("lib/far.py", "far_fn")
    seed = crit("x", paths=("src/pricing.py::apply_discount",))
    assert run_struct(seed, [A, far], Graph({A.ref: {far.ref: 9}})) == {}
    near = sym("lib/near.py", "near_fn")
    got = run_struct(seed, [A, near], Graph({A.ref: {near.ref: 1}}))
    assert max(x.score for x in got.values()) <= 0.7


def test_best_of_multiple_proximities_wins_and_reasons_are_kept():
    seed = crit("x", paths=("src/pricing.py::apply_discount",))
    graph = Graph({A.ref: {B.ref: 1}})
    got = run_struct(seed, [A, B], graph)[B.symbol_id]
    assert got.score == pytest.approx(0.95 * 0.7)
    assert {e.kind for e in got.evidence} == {"same_file", "call_graph"}


# ------------------------------------------------------------------ change prior


def test_behavioral_changes_outrank_formatting_and_docstring_only():
    p = ChangePriorLinker()
    body = p.prior(sym(change="modified_body"))[0]
    doc = p.prior(sym(change="docstring_or_comment_only", behavioral=False))[0]
    fmt = p.prior(sym(change="formatting_only", behavioral=False))[0]
    assert body > doc > fmt
    assert doc <= 0.25 and fmt <= 0.25


def test_non_behavioral_is_capped_even_with_custom_priors():
    p = ChangePriorLinker({"formatting_only": 0.9})
    assert p.prior(sym(change="formatting_only", behavioral=False))[0] == 0.25


def test_unknown_change_kind_falls_back_on_behavioral_flag():
    p = ChangePriorLinker()
    assert p.prior(sym(change="brand_new_kind", behavioral=True))[0] == 0.8
    assert p.prior(sym(change="brand_new_kind", behavioral=False))[0] == 0.2


def test_prior_reason_names_the_change_kind():
    value, why = ChangePriorLinker().prior(sym(change="added"))
    assert value == 1.0 and "added" in why.detail and why.linker == "change_prior"


def test_prior_link_form_covers_every_pair():
    links = ChangePriorLinker().link([crit("a"), crit("b", "C2")], [A, B], CTX)
    assert len(links) == 4
