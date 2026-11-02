"""Tokenization edge cases and BM25 correctness against hand-computed values."""

from __future__ import annotations

import math

import pytest
from radius_linking.domain.bm25 import BM25Index
from radius_linking.domain.text import (
    code_terms,
    name_terms,
    split_identifier,
    stem,
    terms,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("applyDiscount", ["apply", "discount"]),
        ("apply_discount", ["apply", "discount"]),
        ("ApplyDiscount", ["apply", "discount"]),
        ("HTTPServer", ["http", "server"]),
        ("parseHTTPResponse2", ["parse", "http", "response2"]),
        ("kebab-case-name", ["kebab", "case", "name"]),
        ("MAX_RETRIES", ["max", "retries"]),
        ("__init__", ["init"]),
        ("a.b.c", ["a", "b", "c"]),
        ("", []),
        ("___", []),
        ("http2Client", ["http2", "client"]),
    ],
)
def test_split_identifier(name, expected):
    assert split_identifier(name) == expected


def test_split_identifier_unicode_and_fullwidth():
    assert split_identifier("calcularDescuento") == ["calcular", "descuento"]
    assert split_identifier("ÜberSchön") == ["über", "schön"]
    assert split_identifier("日本語_名前") == ["日本語", "名前"]
    # NFKC folds full-width letters and ligatures
    assert split_identifier("ＡＢＣ_def") == ["abc", "def"]


def test_stem_is_conservative_and_deterministic():
    assert stem("discounts") == "discount"
    assert stem("policies") == "policy"
    assert stem("classes") == "class"
    assert stem("class") == "class"
    assert stem("status") == "status"
    assert stem("running") == "run"
    assert stem("rounded") == "round"
    assert stem("is") == "is"
    assert stem("bus") == "bus"


def test_terms_drop_stopwords_and_keep_multiplicity():
    assert terms("The price and the PRICE") == ["price", "price"]
    assert terms("returns the price") == ["price"]


def test_terms_split_identifiers_inside_prose():
    assert terms("calls applyDiscount() when percent is set") == [
        "call",
        "apply",
        "discount",
        "percent",
        "set",
    ]


def test_code_terms_remove_language_keywords():
    assert code_terms("def total(self, items) -> int: return None") == ["total", "item"]


def test_terms_keep_numbers_but_drop_single_letters():
    assert terms("round to 2 decimals x") == ["round", "2", "decimal"]


def test_name_terms_keep_short_parts_and_stem():
    assert name_terms("Cart.add_items") == ["cart", "add", "item"]
    assert name_terms("a_b") == ["a", "b"]


def test_terms_on_empty_and_punctuation_only():
    assert terms("") == []
    assert terms("!!! ... ???") == []


# ---------------------------------------------------------------- BM25


def _index():
    # N=3, avgdl = (3 + 2 + 5) / 3
    return BM25Index.from_tokens(
        {
            "d1": ["apple", "apple", "banana"],
            "d2": ["banana", "cherry"],
            "d3": ["cherry", "date", "date", "date", "date"],
        }
    )


def test_bm25_idf_matches_hand_computation():
    idx = _index()
    assert idx.n_docs == 3
    assert idx.avgdl == pytest.approx(10 / 3)
    assert idx.idf("apple") == pytest.approx(math.log(1 + 2.5 / 1.5))  # df=1
    assert idx.idf("banana") == pytest.approx(math.log(1 + 1.5 / 2.5))  # df=2
    assert idx.idf("missing") == pytest.approx(math.log(1 + 3.5 / 0.5))  # df=0


def test_bm25_score_matches_hand_computation():
    idx = _index()
    # tf=2, |d|=3: norm = 1 - .75 + .75 * 3 / (10/3) = 0.925
    expected = math.log(8 / 3) * 2 * 2.2 / (2 + 1.2 * 0.925)
    assert expected == pytest.approx(1.3876684, abs=1e-6)
    assert idx.score(["apple"], "d1") == pytest.approx(expected)
    assert idx.score(["apple"], "d2") == 0.0
    # banana: d1 (|d|=3) and d2 (|d|=2); shorter document scores higher
    s1, s2 = idx.score(["banana"], "d1"), idx.score(["banana"], "d2")
    assert s1 == pytest.approx(math.log(1.6) * 2.2 / (1 + 1.2 * 0.925))
    assert s2 == pytest.approx(
        math.log(1.6) * 2.2 / (1 + 1.2 * (0.25 + 0.75 * 2 / (10 / 3)))
    )
    assert s2 > s1


def test_bm25_multi_term_is_sum_and_duplicates_in_query_count_once():
    idx = _index()
    both = idx.score(["apple", "banana"], "d1")
    assert both == pytest.approx(
        idx.score(["apple"], "d1") + idx.score(["banana"], "d1")
    )
    assert idx.score(["apple", "apple"], "d1") == idx.score(["apple"], "d1")


def test_bm25_scores_only_matching_docs_and_sorted():
    idx = _index()
    assert list(idx.scores(["cherry"])) == ["d2", "d3"]
    assert idx.scores(["zzz"]) == {}


def test_bm25_term_scores_explain_total():
    idx = _index()
    parts = idx.term_scores(["apple", "banana", "zzz"], "d1")
    assert set(parts) == {"apple", "banana"}
    assert sum(parts.values()) == pytest.approx(idx.score(["apple", "banana"], "d1"))


def test_bm25_fractional_term_frequencies_weight_fields():
    heavy = BM25Index({"a": {"x": 3.0}, "b": {"x": 1.0}})
    assert heavy.score(["x"], "a") > heavy.score(["x"], "b")


def test_bm25_empty_corpus_and_validation():
    idx = BM25Index({})
    assert idx.n_docs == 0 and idx.scores(["a"]) == {}
    with pytest.raises(ValueError):
        BM25Index({}, b=1.5)
    with pytest.raises(ValueError):
        BM25Index({}, k1=-1)


def test_bm25_max_term_score_bounds_every_score():
    idx = _index()
    for doc in ("d1", "d2", "d3"):
        for term in ("apple", "banana", "cherry", "date"):
            assert idx.score([term], doc) <= idx.max_term_score(term) + 1e-12


def test_bm25_is_order_independent():
    a = BM25Index.from_tokens({"d1": ["a", "b"], "d2": ["b", "c"]})
    b = BM25Index.from_tokens({"d2": ["b", "c"], "d1": ["a", "b"]})
    assert a.scores(["a", "b"]) == b.scores(["b", "a"])
