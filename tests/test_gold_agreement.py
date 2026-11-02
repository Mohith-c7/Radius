"""IN-09: agreement statistics and matching, checked against hand-computed values.

Synthetic annotations only; nothing here is real gold data.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gold_agreement as ga  # noqa: E402
import gold_lib as gl  # noqa: E402

NOW = "2026-01-01T00:00:00+00:00"


# ---------------------------------------------------------------- statistics


def test_kappa_wikipedia_style_hand_value():
    # 50 items: yes/yes 20, A yes B no 5, A no B yes 10, no/no 15.
    pairs = [("y", "y")] * 20 + [("y", "n")] * 5 + [("n", "y")] * 10 + [("n", "n")] * 15
    r = ga.cohen_kappa(pairs)
    assert r["po"] == pytest.approx(0.7)
    assert r["pe"] == pytest.approx(0.5)  # 0.5*0.6 + 0.5*0.4
    assert r["kappa"] == pytest.approx(0.4)
    assert r["n"] == 50


def test_kappa_perfect_none_and_degenerate():
    assert ga.cohen_kappa([("a", "a"), ("b", "b"), ("c", "c")])["kappa"] == pytest.approx(1.0)
    # complete disagreement: po 0, pe 0.5 -> -1
    assert ga.cohen_kappa([("a", "b"), ("b", "a")])["kappa"] == pytest.approx(-1.0)
    # one category used by both: chance agreement 1, kappa undefined (not 1.0, not an error)
    assert ga.cohen_kappa([("a", "a")] * 5)["kappa"] is None
    assert ga.cohen_kappa([])["kappa"] is None


def test_kappa_three_category_hand_value():
    # A: a a a b b c ; B: a a b b c c -> po 4/6; A marg a .5 b .333 c .167; B marg a .333 b .333 c .333
    pairs = [("a", "a"), ("a", "a"), ("a", "b"), ("b", "b"), ("b", "c"), ("c", "c")]
    pe = 0.5 * (1 / 3) + (1 / 3) * (1 / 3) + (1 / 6) * (1 / 3)
    assert ga.cohen_kappa(pairs)["kappa"] == pytest.approx((4 / 6 - pe) / (1 - pe))
    assert pe == pytest.approx(1 / 6 + 1 / 9 + 1 / 18)


def test_alpha_nominal_two_coders_hand_value():
    # units [a,a] [a,b] [b,b] [b,b]: o_ab = o_ba = 1, n_a = 3, n_b = 5, n = 8
    # alpha = 1 - 7 * 2 / (2 * 3 * 5) = 8 / 15
    r = ga.krippendorff_alpha_nominal([["a", "a"], ["a", "b"], ["b", "b"], ["b", "b"]])
    assert r["alpha"] == pytest.approx(8 / 15)
    assert r["n_values"] == pytest.approx(8)


def test_alpha_with_unequal_unit_sizes_hand_value():
    # [a,b] and [a,a,b]: o_aa 1, o_ab 2, o_ba 2, n_a 3, n_b 2, n 5
    # alpha = 1 - 4 * 4 / 12 = -1/3
    r = ga.krippendorff_alpha_nominal([["a", "b"], ["a", "a", "b"]])
    assert r["alpha"] == pytest.approx(-1 / 3)


def test_alpha_perfect_and_undefined_and_singletons_ignored():
    assert ga.krippendorff_alpha_nominal([["a", "a"], ["b", "b"]])["alpha"] == pytest.approx(1.0)
    assert ga.krippendorff_alpha_nominal([["a", "a"], ["a", "a"]])["alpha"] is None
    assert ga.krippendorff_alpha_nominal([["a"], ["b"]])["alpha"] is None
    r = ga.krippendorff_alpha_nominal([["a", "a"], ["b", "b"], ["c"]])
    assert r["alpha"] == pytest.approx(1.0) and r["n_units"] == 2


def test_two_coder_alpha_close_to_kappa_for_balanced_labels():
    pairs = [("a", "a")] * 10 + [("b", "b")] * 10 + [("a", "b")] * 2 + [("b", "a")] * 2
    k = ga.cohen_kappa(pairs)["kappa"]
    a = ga.krippendorff_alpha_nominal([[x, y] for x, y in pairs])["alpha"]
    assert abs(k - a) < 0.02  # alpha ~ pi (Scott), kappa ~ pi when marginals match


# ---------------------------------------------------------------- matching


def sp(sid: str, s: int, e: int) -> dict:
    return {"source_id": sid, "start": s, "end": e}


def crit(i: int, span: dict, label="behavioral_testable", text="x") -> dict:
    return {"id": f"c{i}", "explicit": True, "span": span, "text": text, "testability": label}


def test_iou_arithmetic():
    assert gl.span_iou(sp("s", 0, 10), sp("s", 0, 10)) == 1.0
    assert gl.span_iou(sp("s", 0, 10), sp("s", 10, 20)) == 0.0  # half-open: touching is disjoint
    assert gl.span_iou(sp("s", 0, 10), sp("s", 5, 15)) == pytest.approx(5 / 15)
    assert gl.span_iou(sp("s", 0, 10), sp("t", 0, 10)) == 0.0


def test_threshold_is_inclusive_at_exactly_half():
    a, b = [crit(1, sp("s", 0, 10))], [crit(1, sp("s", 0, 20))]
    pairs, ua, ub = ga.match_criteria(a, b, 0.5)  # IoU exactly 0.5 -> match
    assert len(pairs) == 1 and not ua and not ub
    pairs, ua, ub = ga.match_criteria(a, [crit(1, sp("s", 0, 21))], 0.5)  # 10/21 < 0.5
    assert not pairs and ua == [0] and ub == [0]


def test_matching_is_one_to_one_and_prefers_best_iou():
    a = [crit(1, sp("s", 0, 20))]
    b = [crit(1, sp("s", 0, 10)), crit(2, sp("s", 0, 12))]
    pairs, ua, ub = ga.match_criteria(a, b, 0.5)
    assert pairs == [(0, 1, pytest.approx(12 / 20))]
    assert ub == [0] and not ua


def test_identical_spans_tie_broken_by_text_similarity():
    a = [crit(1, sp("s", 0, 30), text="returns 400 when name missing"),
         crit(2, sp("s", 0, 30), text="returns 400 when email missing")]
    b = [crit(1, sp("s", 0, 30), text="returns 400 when email missing"),
         crit(2, sp("s", 0, 30), text="returns 400 when name missing")]
    pairs, _, _ = ga.match_criteria(a, b, 0.5)
    assert sorted((i, j) for i, j, _ in pairs) == [(0, 1), (1, 0)]


def test_different_sources_never_match():
    pairs, ua, ub = ga.match_criteria([crit(1, sp("a", 0, 10))], [crit(1, sp("b", 0, 10))], 0.5)
    assert not pairs and ua == [0] and ub == [0]


# ---------------------------------------------------------------- per-PR comparison


TEXT = "line one is here\nline two is here\n\nline three is here\n"


def make_pair(a_crits, b_crits, *, ws=(True, True)):
    src_text = TEXT
    sources = [gl.make_source("pr-body", "pr_body", src_text, fetched_at=NOW)]
    src = {
        "schema_version": gl.SOURCES_SCHEMA_VERSION, "pr_id": "o__r__pr1",
        "pr": {"repo": "o/r", "number": 1, "author_type": "human"},
        "sources": sources, "sources_digest": gl.sources_digest(sources),
        "sanitizer": "canonicalize_text", "text_redistributable": True, "synthetic": True,
    }
    docs = []
    for aid, crits, w in (("synth-a", a_crits, ws[0]), ("synth-b", b_crits, ws[1])):
        d = gl.new_annotation("o__r__pr1", src, aid, now=NOW, synthetic=True)
        d["criteria"] = crits
        d["well_specified"] = w
        d["status"] = "complete"
        docs.append(d)
    return src, docs[0], docs[1]


def span_crit(i, start, end, label="behavioral_testable"):
    return {"id": f"c{i}", "explicit": True, "span": sp("pr-body", start, end),
            "text": TEXT[start:end], "testability": label}


def test_perfect_agreement_metrics():
    c = [span_crit(1, 0, 16), span_crit(2, 17, 33, "subjective_or_vague")]
    src, a, b = make_pair(c, [dict(x) for x in c])
    comp = ga.compare_pr(src, a, b)
    rep = ga.build_report([comp], n_boot=0, synthetic=True)
    assert rep["overall"]["span_f1"] == 1.0
    assert rep["overall"]["presence_kappa"]["kappa"] == pytest.approx(1.0)
    assert rep["overall"]["testability_kappa"]["kappa"] == pytest.approx(1.0)
    assert rep["overall"]["testability_alpha"]["alpha"] == pytest.approx(1.0)
    assert rep["overall"]["exact_span_share"] == 1.0
    assert rep["disagreements"] == []


def test_no_agreement_metrics():
    src, a, b = make_pair([span_crit(1, 0, 16)], [span_crit(1, 17, 33)])
    comp = ga.compare_pr(src, a, b)
    rep = ga.build_report([comp], n_boot=0, synthetic=True)
    assert rep["overall"]["span_f1"] == 0.0
    # units: line1 (1,0), line2 (0,1), line3 (0,0): po 1/3; pa A=1/3 yes, B=1/3 yes
    # pe = (1/3)(1/3) + (2/3)(2/3) = 5/9 ; kappa = (1/3 - 5/9) / (4/9) = -0.5
    assert rep["overall"]["presence_kappa"]["kappa"] == pytest.approx(-0.5)
    kinds = {d["type"] for d in rep["disagreements"]}
    assert kinds == {"only_a", "only_b"}


def test_partial_agreement_and_testability_conflict():
    a = [span_crit(1, 0, 16), span_crit(2, 17, 33, "structural_checkable")]
    b = [span_crit(1, 0, 16), span_crit(2, 17, 33, "subjective_or_vague"), span_crit(3, 35, 56)]
    src, ra, rb = make_pair(a, b)
    comp = ga.compare_pr(src, ra, rb)
    rep = ga.build_report([comp], n_boot=0, synthetic=True)
    assert len(comp["matched"]) == 2 and len(comp["only_b"]) == 1
    assert rep["overall"]["span_f1"] == pytest.approx(2 * 2 / (2 + 3))
    # testability pairs (behav,behav) (struct,vague): po .5, pe = .5*.5 + .5*0 ... marginals differ
    # A: behav .5 struct .5 ; B: behav .5 vague .5 -> pe = .25 ; kappa = (.5-.25)/.75
    assert rep["overall"]["testability_kappa"]["kappa"] == pytest.approx(1 / 3)
    types = sorted(d["type"] for d in rep["disagreements"])
    assert types == ["only_b", "testability_conflict"]


def test_boundary_case_overlap_below_threshold_is_flagged_not_matched():
    a = [span_crit(1, 0, 10)]
    b = [span_crit(1, 0, 21)]  # IoU 10/21 < 0.5
    src, ra, rb = make_pair(a, b)
    comp = ga.compare_pr(src, ra, rb)
    assert not comp["matched"] and len(comp["boundary"]) == 1
    types = [d["type"] for d in ga.disagreements([comp])]
    assert types == ["overlap_below_threshold"]  # not double counted as only_a/only_b


def test_span_boundary_disagreement_inside_threshold():
    a, b = [span_crit(1, 0, 16)], [span_crit(1, 0, 12)]  # IoU .75, same label
    src, ra, rb = make_pair(a, b)
    comp = ga.compare_pr(src, ra, rb)
    assert len(comp["matched"]) == 1 and not comp["matched"][0]["exact"]
    assert [d["type"] for d in ga.disagreements([comp])] == ["span_boundary"]


def test_implicit_criteria_counted_not_matched():
    imp = {"id": "c9", "explicit": False, "span": None, "text": "should not break login",
           "testability": "behavioral_testable"}
    src, ra, rb = make_pair([span_crit(1, 0, 16), imp], [span_crit(1, 0, 16)])
    rep = ga.build_report([ga.compare_pr(src, ra, rb)], n_boot=0, synthetic=True)
    assert rep["overall"]["n_implicit_a"] == 1 and rep["overall"]["n_implicit_b"] == 0
    assert rep["overall"]["span_f1"] == 1.0
    assert [d["type"] for d in rep["disagreements"]] == ["implicit_a"]


def test_empty_annotations_do_not_crash():
    src, ra, rb = make_pair([], [])
    rep = ga.build_report([ga.compare_pr(src, ra, rb)], n_boot=0, synthetic=True)
    assert rep["overall"]["span_f1"] is None
    assert rep["overall"]["presence_kappa"]["kappa"] is None  # nobody marked any unit


def test_bootstrap_is_seeded_and_brackets_the_estimate():
    comps = []
    for i in range(12):
        a = [span_crit(1, 0, 16), span_crit(2, 17, 33)]
        b = [span_crit(1, 0, 16)] if i % 3 == 0 else [span_crit(1, 0, 16), span_crit(2, 17, 33)]
        src, ra, rb = make_pair(a, b)
        comps.append(ga.compare_pr(src, ra, rb))
    r1 = ga.build_report(comps, n_boot=300, seed=5, synthetic=True)
    r2 = ga.build_report(comps, n_boot=300, seed=5, synthetic=True)
    assert r1["overall"]["ci95"] == r2["overall"]["ci95"]
    lo, hi = r1["overall"]["ci95"]["span_f1"]
    assert lo <= r1["overall"]["span_f1"] <= hi
    assert math.isclose(r1["overall"]["span_f1"], 2 * 20 / (24 + 20))


def test_per_source_kind_breakdown():
    sources = [gl.make_source("pr-body", "pr_body", "alpha beta gamma\n", fetched_at=NOW),
               gl.make_source("issue-1", "issue", "delta epsilon zeta\n", fetched_at=NOW)]
    src = {"schema_version": gl.SOURCES_SCHEMA_VERSION, "pr_id": "o__r__pr1",
           "pr": {"repo": "o/r", "number": 1, "author_type": "agent"},
           "sources": sources, "sources_digest": gl.sources_digest(sources),
           "sanitizer": "x", "text_redistributable": True, "synthetic": True}

    def doc(aid, crits):
        d = gl.new_annotation("o__r__pr1", src, aid, now=NOW, synthetic=True)
        d["criteria"], d["well_specified"], d["status"] = crits, True, "complete"
        return d

    body = {"id": "c1", "explicit": True, "span": sp("pr-body", 0, 16), "text": "alpha beta gamma",
            "testability": "behavioral_testable"}
    issue_a = {"id": "c2", "explicit": True, "span": sp("issue-1", 0, 18), "text": "delta epsilon zeta",
               "testability": "subjective_or_vague"}
    comp = ga.compare_pr(src, doc("synth-a", [body, issue_a]), doc("synth-b", [dict(body)]))
    rep = ga.build_report([comp], n_boot=0, synthetic=True)
    assert rep["by_source_kind"]["pr_body"]["span_f1"] == 1.0
    assert rep["by_source_kind"]["issue"]["span_f1"] == 0.0
    assert rep["by_source_kind"]["issue"]["n_a"] == 1 and rep["by_source_kind"]["issue"]["n_b"] == 0
    assert rep["by_author_type"]["agent"]["n_prs"] == 1


# ---------------------------------------------------------------- skeleton


def test_skeleton_prefills_agreed_and_leaves_rest_pending():
    a = [span_crit(1, 0, 16), span_crit(2, 17, 33, "structural_checkable")]
    b = [span_crit(1, 0, 16), span_crit(2, 17, 33, "subjective_or_vague"), span_crit(3, 35, 56)]
    src, ra, rb = make_pair(a, b)
    comp = ga.compare_pr(src, ra, rb)
    sk = ga.build_skeleton(src, ra, rb, comp, "synth-c", now=NOW)
    res = [c["resolution"] for c in sk["criteria"]]
    assert res.count("agreed") == 1 and res.count("pending") == 2
    assert sk["status"] == "skeleton"
    errs, _ = gl.validate_annotation_doc(sk, src)
    assert errs == []
    agreed = next(c for c in sk["criteria"] if c["resolution"] == "agreed")
    assert agreed["origin"] == {"synth-a": "c1", "synth-b": "c1"}


def test_skeleton_all_agreed_is_complete():
    c = [span_crit(1, 0, 16)]
    src, ra, rb = make_pair(c, [dict(c[0])])
    sk = ga.build_skeleton(src, ra, rb, ga.compare_pr(src, ra, rb), "synth-c", now=NOW)
    assert sk["status"] == "complete"
    assert gl.validate_annotation_doc(sk, src, require_complete=True)[0] == []


def test_skeleton_adjudicator_must_be_third_person():
    c = [span_crit(1, 0, 16)]
    src, ra, rb = make_pair(c, [dict(c[0])])
    with pytest.raises(gl.GoldError):
        ga.build_skeleton(src, ra, rb, ga.compare_pr(src, ra, rb), "synth-a", now=NOW)


def test_skeleton_well_specified_conflict_is_unresolved():
    c = [span_crit(1, 0, 16)]
    src, ra, rb = make_pair(c, [dict(c[0])], ws=(True, False))
    sk = ga.build_skeleton(src, ra, rb, ga.compare_pr(src, ra, rb), "synth-c", now=NOW)
    assert sk["well_specified"] is None and sk["well_specified_conflict"] == [True, False]
    assert sk["status"] == "skeleton"
