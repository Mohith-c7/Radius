"""IN-10: span/text matching with hand-computed expectations."""

from __future__ import annotations

import pytest
from radius_intent.evaluation.matching import (
    SpanRef,
    best_iou,
    greedy_one_to_one,
    match_by_iou,
    match_by_text,
    span_iou,
    text_similarity,
)


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ((0, 10), (0, 10), 1.0),
        ((0, 10), (0, 5), 0.5),  # containment: 5 / 10
        ((0, 10), (5, 15), 5 / 15),  # partial overlap: 5 / 15
        ((0, 5), (5, 9), 0.0),  # touching spans share no characters
        ((0, 5), (7, 9), 0.0),  # disjoint
        ((3, 4), (3, 4), 1.0),  # single character
        ((0, 4), (1, 3), 0.5),  # inner span: 2 / 4
    ],
)
def test_span_iou_hand_computed(a, b, expected):
    assert span_iou(*a, *b) == pytest.approx(expected)
    assert span_iou(*b, *a) == pytest.approx(expected)  # symmetric


def test_threshold_is_inclusive_at_exactly_half():
    gold = [[SpanRef("s", 0, 10)]]
    assert len(match_by_iou([SpanRef("s", 0, 5)], gold, 0.5)) == 1
    assert match_by_iou([SpanRef("s", 0, 4)], gold, 0.5) == []  # IoU 0.4


def test_threshold_is_configurable():
    gold = [[SpanRef("s", 0, 10)]]
    pred = [SpanRef("s", 0, 7)]  # IoU 0.7
    assert match_by_iou(pred, gold, 0.7)
    assert not match_by_iou(pred, gold, 0.8)


def test_spans_in_different_sources_never_match():
    assert match_by_iou([SpanRef("a", 0, 10)], [[SpanRef("b", 0, 10)]], 0.5) == []


def test_alt_span_in_other_source_matches():
    gold = [[SpanRef("a", 0, 10), SpanRef("b", 20, 30)]]
    assert best_iou(SpanRef("b", 20, 30), gold[0]) == 1.0
    assert match_by_iou([SpanRef("b", 20, 30)], gold, 0.5)[0].gold_index == 0


def test_one_to_one_duplicate_gold_needs_two_predictions():
    gold = [[SpanRef("s", 0, 10)], [SpanRef("s", 0, 10)]]
    one = match_by_iou([SpanRef("s", 0, 10)], gold, 0.5)
    assert [(m.pred_index, m.gold_index) for m in one] == [(0, 0)]  # lowest index wins
    two = match_by_iou([SpanRef("s", 0, 10), SpanRef("s", 0, 10)], gold, 0.5)
    assert [(m.pred_index, m.gold_index) for m in two] == [(0, 0), (1, 1)]


def test_one_prediction_is_never_credited_twice():
    preds = [SpanRef("s", 0, 20)]
    gold = [[SpanRef("s", 0, 10)], [SpanRef("s", 10, 20)]]  # IoU 0.5 each
    assert len(match_by_iou(preds, gold, 0.5)) == 1


def test_greedy_prefers_higher_iou_and_breaks_ties_by_index():
    # pred0 overlaps gold0 (0.5) and gold1 (1.0); pred1 only gold1 (0.6)
    pairs = [(0.5, 0, 0), (1.0, 0, 1), (0.6, 1, 1)]
    assert [(m.pred_index, m.gold_index) for m in greedy_one_to_one(pairs)] == [(0, 1)]
    ties = [(1.0, 1, 0), (1.0, 0, 0)]
    assert [(m.pred_index, m.gold_index) for m in greedy_one_to_one(ties)] == [(0, 0)]


def test_greedy_is_independent_of_candidate_order():
    pairs = [(0.9, 0, 0), (0.9, 1, 1), (0.6, 0, 1), (0.6, 1, 0)]
    assert greedy_one_to_one(pairs) == greedy_one_to_one(list(reversed(pairs)))


def test_unicode_offsets_are_code_points():
    text = "\U0001f680 ship it"  # the emoji is ONE code point
    assert len(text) == 9
    assert span_iou(0, len(text), 0, len(text)) == 1.0


def test_text_similarity_cases():
    assert text_similarity("Users CAN export", "users can  export") == 1.0
    assert text_similarity("a b c d", "a b c e") == pytest.approx(3 / 5)
    assert text_similarity("", "word") == 0.0
    assert text_similarity("ＡＢＣ", "abc") == 1.0  # NFKC full-width


def test_match_by_text_exact_and_fuzzy_and_veto():
    preds = ["the cat sat", "unrelated words here"]
    gold = [["the cat sat"], ["the cat sat down"]]
    exact = match_by_text(preds, gold, 1.0)
    assert [(m.pred_index, m.gold_index) for m in exact] == [(0, 0)]
    fuzzy = match_by_text(preds, gold, 0.7)
    assert [(m.pred_index, m.gold_index) for m in fuzzy] == [(0, 0)]
    vetoed = match_by_text(preds, gold, 1.0, allowed=lambda i, j: False)
    assert vetoed == []


def test_match_by_text_uses_best_of_several_gold_texts():
    out = match_by_text(["report export"], [["something else", "report export"]], 1.0)
    assert len(out) == 1
