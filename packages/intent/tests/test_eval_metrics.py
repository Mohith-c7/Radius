"""IN-10: per-PR scoring, metric definitions, bootstrap and agreement stats."""
# ruff: noqa: E402, I001  (helper import needs the sys.path setup below, as in the IN-03 tests)
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
if _HERE not in _sys.path:  # helper module lives next to the tests (importlib mode)
    _sys.path.insert(0, _HERE)

import math

import pytest
from eval_helpers import case, pred
from radius_intent.domain import IntentSourceKind, Testability
from radius_intent.evaluation.metrics import (
    MatchConfig,
    PredictedCriterion,
    compute_metrics,
    confusion_matrix,
    group_counts,
    group_names,
    score_case,
)
from radius_intent.evaluation.stats import (
    bootstrap_metrics,
    cohen_kappa,
    f1_score,
    paired_bootstrap_diff,
    percentile,
    sum_vectors,
)

T, V, N = (
    Testability.BEHAVIORAL_TESTABLE,
    Testability.SUBJECTIVE_OR_VAGUE,
    Testability.NON_FUNCTIONAL_MEASURABLE,
)


def metrics_of(*scores):
    return compute_metrics(sum_vectors([s.vector for s in scores]))


def test_hand_computed_case():
    # gold [0,10) [20,30) [40,50); preds: IoU .5 hit, IoU .5 hit, stray, stray
    c = case(gold=((0, 10), (20, 30), (40, 50)))
    s = score_case(c, [pred(0, 5), pred(25, 30), pred(12, 14), pred(55, 60)])
    m = metrics_of(s)
    assert (s.n_pred, s.n_gold) == (4, 3)
    assert m["iou.all.precision"] == pytest.approx(2 / 4)
    assert m["iou.all.recall"] == pytest.approx(2 / 3)
    assert m["iou.all.f1"] == pytest.approx(2 * 2 / (4 + 3))
    assert s.false_negatives == ("G2",)
    assert [fp["start"] for fp in s.false_positives] == [12, 55]
    assert m["span.mean_iou"] == pytest.approx(0.5)
    assert m["span.exact_rate"] == 0.0


def test_perfect_extractor_scores_one_and_empty_extractor_scores_zero_recall():
    c = case(gold=((0, 10), (20, 30)))
    perfect = metrics_of(score_case(c, [pred(0, 10), pred(20, 30)]))
    assert perfect["iou.all.f1"] == perfect["iou.all.precision"] == 1.0
    assert perfect["iou.all.recall"] == 1.0
    assert perfect["span.exact_rate"] == 1.0
    empty = metrics_of(score_case(c, []))
    assert empty["iou.all.recall"] == 0.0
    assert empty["iou.all.f1"] == 0.0
    assert empty["iou.all.precision"] is None  # undefined, not 0
    assert empty["abstention.empty_prediction_rate"] == 1.0


def test_pr_without_gold_and_false_positive_rate():
    a = score_case(case("a"), [])
    b = score_case(case("b"), [pred(0, 5), pred(7, 9)])
    c = score_case(case("c", gold=((0, 10),)), [pred(0, 10)])
    m = metrics_of(a, b, c)
    assert m["nogold.share"] == pytest.approx(2 / 3)
    assert m["nogold.fp_rate"] == pytest.approx(1 / 2)
    assert m["nogold.mean_predictions"] == pytest.approx(1.0)
    assert m["iou.all.precision"] == pytest.approx(1 / 3)
    assert m["coverage.any_hit_rate"] == 1.0


def test_macro_metrics_average_over_prs_not_criteria():
    big = score_case(case("big", gold=tuple((i * 10, i * 10 + 9) for i in range(5))), [])
    small = score_case(case("small", gold=((0, 9),)), [pred(0, 9)])
    m = metrics_of(big, small)
    assert m["iou.all.recall"] == pytest.approx(1 / 6)  # micro: 1 of 6
    assert m["iou.all.macro_recall"] == pytest.approx(0.5)  # macro: (0 + 1) / 2
    assert m["iou.all.macro_f1"] == pytest.approx(0.5)
    assert m["iou.all.macro_precision"] == pytest.approx(1.0)  # only `small` predicted


def test_per_source_kind_slices_and_author_groups():
    c = case("k", gold=((0, 10),), kind=IntentSourceKind.ISSUE, ws=True, author="agent")
    m = metrics_of(score_case(c, [pred(0, 10)]))
    assert m["iou.kind:issue.f1"] == 1.0
    assert m["iou.well_specified.f1"] == 1.0
    assert m["iou.author:agent.f1"] == 1.0
    assert "iou.not_well_specified.f1" not in m
    total = sum_vectors([score_case(c, [pred(0, 10)]).vector])
    assert group_names(total)[0] == "all"
    assert group_counts(total, "kind:issue", "iou") == {"pred": 1, "gold": 1, "tp": 1}


def test_not_well_specified_group():
    m = metrics_of(score_case(case(gold=((0, 5),), ws=False), [pred(0, 5)]))
    assert m["iou.not_well_specified.f1"] == 1.0


def test_prediction_in_unknown_source_counts_as_false_positive():
    c = case(gold=((0, 10),))
    m = metrics_of(score_case(c, [pred(0, 10, source_id="ghost")]))
    assert m["iou.all.precision"] == 0.0
    assert m["iou.kind:unknown.precision"] == 0.0


def test_text_modes_use_text_not_spans():
    c = case(text="Users can export CSV. Done.", gold=((0, 21),))
    exact = score_case(c, [pred(25, 27, text="users can export csv.")])
    fuzzy = score_case(c, [pred(25, 27, text="users can export csv files")])
    me, mf = metrics_of(exact), metrics_of(fuzzy)
    assert me["iou.all.recall"] == 0.0 and me["text_exact.all.recall"] == 1.0
    assert mf["text_exact.all.recall"] == 0.0 and mf["text_fuzzy.all.recall"] == 1.0
    strict = score_case(
        c,
        [pred(25, 27, text="users can export csv files")],
        MatchConfig(text_threshold=0.9),
    )
    assert metrics_of(strict)["text_fuzzy.all.recall"] == 0.0


def test_testability_confusion_accuracy_kappa():
    c = case(gold=((0, 5), (10, 15), (20, 25), (30, 35)), labels=(T, T, V, N))
    preds = [
        pred(0, 5, testability=T.value),
        pred(10, 15, testability=V.value),
        pred(20, 25, testability=V.value),
        pred(30, 35, testability=None),  # abstains
    ]
    s = score_case(c, preds)
    m = metrics_of(s)
    assert m["tx.n"] == 4
    assert m["tx.accuracy"] == pytest.approx(2 / 4)
    assert m["tx.abstain_rate"] == pytest.approx(1 / 4)
    # po = .5; rows T2 V1 N1, cols T1 V2 unrated1 -> pe = (2*1 + 1*2 + 0) / 16 = .25
    assert m["tx.kappa"] == pytest.approx((0.5 - 0.25) / 0.75)
    # F1: T 2*1/(2+1)=2/3, V 2*1/(1+2)=2/3, N 0 -> mean 4/9
    assert m["tx.macro_f1"] == pytest.approx(4 / 9)
    conf = confusion_matrix(sum_vectors([s.vector]))
    assert conf[T.value] == {T.value: 1, V.value: 1}
    assert conf[N.value] == {"unrated": 1}


def test_testability_undefined_without_labels():
    m = metrics_of(score_case(case(gold=((0, 5),)), [pred(0, 5)]))
    assert m["tx.n"] == 0 and m["tx.accuracy"] is None and m["tx.kappa"] is None


def test_unrated_predictions_are_counted():
    m = metrics_of(score_case(case(gold=((0, 5),)), [pred(0, 5), pred(9, 12)]))
    assert m["testability.unrated_pred_rate"] == 1.0


def test_match_config_validation():
    for bad in (0, -0.1, 1.5):
        with pytest.raises(ValueError):
            MatchConfig(iou_threshold=bad)
    assert MatchConfig().as_dict() == {"iou_threshold": 0.5, "text_threshold": 0.8}


def test_predicted_criterion_defaults():
    p = PredictedCriterion("s", 0, 1, "t")
    assert p.testability is None and p.method == "deterministic"


# ------------------------------------------------------------------ statistics


def test_percentile_interpolates():
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    assert percentile([5.0], 0.9) == 5.0
    assert percentile([1.0, 2.0], 0.0) == 1.0 and percentile([1.0, 2.0], 1.0) == 2.0
    with pytest.raises(ValueError):
        percentile([], 0.5)
    with pytest.raises(ValueError):
        percentile([1.0], 1.5)


def test_cohen_kappa_known_values():
    assert cohen_kappa({("a", "a"): 10, ("b", "b"): 10}) == 1.0
    # classic 2x2: po = .7, pe = .5 -> kappa .4
    table = {("y", "y"): 20, ("y", "n"): 5, ("n", "y"): 10, ("n", "n"): 15}
    assert cohen_kappa(table) == pytest.approx(0.4)
    assert cohen_kappa({}) is None
    assert cohen_kappa({("a", "a"): 4}) is None  # chance agreement is 1


def test_f1_score_edges():
    assert f1_score(None, 0.5) is None
    assert f1_score(0.0, 0.0) == 0.0
    assert f1_score(1.0, 0.5) == pytest.approx(2 / 3)


def _vectors():
    cases = [
        score_case(
            case(f"c{i}", gold=((0, 10),)),
            [pred(0, 10)] if i % 3 else [pred(30, 40)],
        )
        for i in range(12)
    ]
    return [c.vector for c in cases]


def _dicts(result):
    return {k: v.as_dict() for k, v in result.items()}


def test_bootstrap_is_deterministic_for_a_seed_and_differs_across_seeds():
    vectors = _vectors()
    a = bootstrap_metrics(vectors, compute_metrics, resamples=200, seed=7)
    b = bootstrap_metrics(vectors, compute_metrics, resamples=200, seed=7)
    c = bootstrap_metrics(vectors, compute_metrics, resamples=200, seed=8)
    assert _dicts(a) == _dicts(b)
    assert _dicts(a) != _dicts(c)


def test_bootstrap_interval_brackets_point_estimate_and_handles_degenerate():
    vectors = _vectors()
    iv = bootstrap_metrics(vectors, compute_metrics, resamples=300, seed=1)["iou.all.recall"]
    assert iv.low <= iv.estimate <= iv.high
    assert iv.estimate == pytest.approx(8 / 12)
    perfect = [
        score_case(case(f"p{i}", gold=((0, 5),)), [pred(0, 5)]).vector for i in range(5)
    ]
    f1 = bootstrap_metrics(perfect, compute_metrics, resamples=50, seed=1)["iou.all.f1"]
    assert (f1.low, f1.high) == (1.0, 1.0)


def test_bootstrap_validates_inputs():
    with pytest.raises(ValueError):
        bootstrap_metrics([], compute_metrics, resamples=10, seed=1)
    with pytest.raises(ValueError):
        bootstrap_metrics(_vectors(), compute_metrics, resamples=0, seed=1)
    with pytest.raises(ValueError):
        bootstrap_metrics(_vectors(), compute_metrics, resamples=5, seed=1, confidence=1.0)


def test_bootstrap_undefined_metric_has_no_interval():
    vectors = [score_case(case("e"), []).vector]
    iv = bootstrap_metrics(vectors, compute_metrics, resamples=20, seed=1)
    assert iv["nogold.fp_rate"].estimate == 0.0
    assert iv["iou.all.precision" if "iou.all.precision" in iv else "nogold.share"]


def test_nan_is_ignored_in_intervals():
    out = bootstrap_metrics(
        [{"a": 1.0}],
        lambda t: {"m": math.nan if t.get("a") else 1.0},
        resamples=5,
        seed=1,
    )
    assert out["m"].n_valid == 0 and out["m"].low is None


def test_paired_bootstrap_detects_a_clear_difference_and_is_deterministic():
    good = [
        score_case(case(f"c{i}", gold=((0, 10),)), [pred(0, 10)]).vector for i in range(15)
    ]
    bad = [score_case(case(f"c{i}", gold=((0, 10),)), []).vector for i in range(15)]
    d1 = paired_bootstrap_diff(good, bad, compute_metrics, resamples=200, seed=3)
    d2 = paired_bootstrap_diff(good, bad, compute_metrics, resamples=200, seed=3)
    assert d1["iou.all.recall"].as_dict() == d2["iou.all.recall"].as_dict()
    r = d1["iou.all.recall"]
    assert r.estimate == 1.0 and r.excludes_zero and r.low == 1.0 and r.p_value < 0.05
    same = paired_bootstrap_diff(good, good, compute_metrics, resamples=100, seed=3)
    assert same["iou.all.f1"].estimate == 0.0
    assert not same["iou.all.f1"].excludes_zero
    assert same["iou.all.f1"].p_value == 1.0
    # precision is undefined for the empty side, so its difference is too
    assert d1["iou.all.precision"].estimate is None


def test_paired_bootstrap_requires_matching_clusters():
    with pytest.raises(ValueError):
        paired_bootstrap_diff(_vectors(), _vectors()[:-1], compute_metrics, resamples=5, seed=1)
