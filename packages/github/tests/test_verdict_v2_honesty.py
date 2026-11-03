"""Honest alpha wording: labels, disclaimer, Check Run mapping, author-hint flag."""

from __future__ import annotations

import pytest
from radius_github.verdict_v2 import markdown as md
from radius_github.verdict_v2.view import VerdictV2View

HEAD = "4f2a9d1c0b7e6a53f8c1d2e3b4a59687c0d1e2f3"
TITLE = "Radius v2 alpha - static evidence only - uncalibrated"
TABLE_HEAD = "| # | Criterion |"


def view_of(payload: dict) -> VerdictV2View:
    return VerdictV2View.from_payload(payload)


def make_payload(verdict, decided_by, criteria, *, coverage=1.0, pending=False, status="ok",
                 rules_inputs=None) -> dict:
    rows = []
    for cid, state, s in criteria:
        items = []
        if state in ("proven", "weak", "unevidenced") and s > 0:
            items = [{
                "evidence_id": f"ev_{cid}", "test_id": f"tests/test_x.py::test_{cid}",
                "outcome": "passed", "status": "counted", "a_static": 1.0, "d_eff": 0.6,
                "i": 0.8, "f": 1.0, "l": 0.9, "term": s, "contribution": s,
            }]
        rows.append({
            "criterion_id": cid, "text": f"criterion text {cid}", "state": state, "S": s,
            "S_raw": s, "weight": 1.0, "flags": [], "items": items,
        })
    counts = {k: sum(1 for _, st, _ in criteria if st == k)
              for k in ("proven", "weak", "unevidenced", "contradicted", "excluded")}
    return {
        "verdict_version": 2, "algo_version": "verdict-v2-alpha-1", "profile": "alpha-static",
        "mode": "on", "status": status, "analysis_id": "an-1", "head_sha": HEAD, "revision": 1,
        "verdict": verdict, "pending": pending, "reasons": [],
        "summary": {"criteria_total": len(criteria), **counts, "uim": 0.0,
                    "intent_coverage": coverage, "tamper": {}, "evidence_basis": "static_only"},
        "criteria": rows, "tamper_findings": [], "unlinked_symbols": [], "next_actions": [],
        "justification": {
            "schema": "verdict-v2-justification-1", "verdict": verdict, "decided_by": decided_by,
            "rules": [{"id": decided_by, "label": "x", "fired": True,
                       "inputs": rules_inputs or {}, "refs": {}}],
            "thresholds": {"tau_support": 0.5, "uim_max": 0.2, "min_intent_coverage": 0.5},
        },
    }


def render(*args, **kwargs) -> str:
    return md.render_comment(view_of(make_payload(*args, **kwargs)))


# ------------------------------------------------------------------ label mapping


def test_internal_states_are_unchanged_and_presented_as_supported() -> None:
    assert set(md.STATE_LABELS) == {"proven", "weak", "unevidenced", "contradicted", "excluded"}
    assert md.STATE_LABELS["proven"] == "SUPPORTED"
    assert md.STATE_LABELS["unevidenced"] == "UNSUPPORTED"
    assert "PROVEN" not in md.STATE_LABELS.values()
    assert md.VERDICT_LABELS["verified"] == "Supported by static evidence (alpha)"
    assert md.VERDICT_LABELS["insufficient_evidence"].startswith("Not verified")


@pytest.mark.parametrize("verdict", ["verified", "failed", "insufficient_evidence", "needs_review"])
def test_no_comment_says_proven_or_verified(verdict) -> None:
    body = render(verdict, "R4", [("c1", "proven", 0.7), ("c2", "unevidenced", 0.0)])
    assert "proven" not in body.lower()
    assert "verified" not in body.replace("Not verified", "").lower()
    assert "SUPPORTED" in body


def test_legend_is_present_under_the_table() -> None:
    body = render("verified", "R4", [("c1", "proven", 0.7)])
    assert md.LEGEND in body
    assert (
        md.LEGEND
        == "supported = static assertion strength above threshold; not a proof of correctness"
    )
    assert body.index(md.LEGEND) > body.index(TABLE_HEAD)


# ------------------------------------------------------------- top-of-comment disclaimer


@pytest.mark.parametrize("status", ["ok", "error", "skipped"])
def test_disclaimer_is_the_first_visible_line(status) -> None:
    verdict = "verified" if status == "ok" else None
    criteria = [("c1", "proven", 0.7)] if status == "ok" else []
    body = render(verdict, "R4", criteria, status=status)
    visible = [ln for ln in body.split("\n") if ln and not ln.startswith("<!--")]
    assert visible[0] == md.DISCLAIMER
    assert visible[1].startswith("## Radius verdict (v2 alpha):")
    assert "Alpha - static evidence only - uncalibrated" in md.DISCLAIMER


def test_disclaimer_has_no_html_or_quote_syntax() -> None:
    assert "<" not in md.DISCLAIMER
    assert not md.DISCLAIMER.startswith(">")


def test_check_run_summary_starts_with_the_disclaimer() -> None:
    check = md.render_check_run(view_of(make_payload("verified", "R4", [("c1", "proven", 0.7)])))
    assert check.summary.startswith(md.DISCLAIMER)


# ---------------------------------------------------------- Check Run conclusion table

#: (verdict, deciding rule, pending, status, advisory, strict): the documented table.
CONCLUSION_TABLE = [
    ("verified", "R4", False, "ok", "neutral", "success"),
    ("failed", "R1a", False, "ok", "failure", "failure"),
    ("failed", "R1b", False, "ok", "failure", "failure"),
    ("failed", "R1c", False, "ok", "failure", "failure"),
    ("failed", "R9", False, "ok", "neutral", "neutral"),
    ("insufficient_evidence", "R2b", False, "ok", "neutral", "neutral"),
    ("needs_review", "R3a", False, "ok", "neutral", "neutral"),
    ("verified", "R4", True, "ok", "neutral", "neutral"),
    ("verified", "R4", False, "error", "neutral", "neutral"),
    ("bogus", "R4", False, "ok", "neutral", "neutral"),
]


@pytest.mark.parametrize(
    ("verdict", "rule", "pending", "status", "advisory", "strict"), CONCLUSION_TABLE
)
def test_check_conclusion_table(verdict, rule, pending, status, advisory, strict) -> None:
    payload = make_payload(
        verdict, rule, [("c1", "proven", 0.6)], pending=pending, status=status
    )
    view = view_of(payload)
    assert md.check_conclusion(view) == advisory
    assert md.check_conclusion(view, mode="advisory") == advisory
    assert md.check_conclusion(view, mode="strict") == strict
    assert md.render_check_run(view).conclusion == advisory
    assert md.render_check_run(view, conclusions="strict").conclusion == strict


def test_advisory_never_yields_success_for_any_verdict_or_rule() -> None:
    rules = ("R1a", "R1b", "R1c", "R2a", "R2e", "R2b", "R2c", "R2d", "R3a", "R3b", "R3c", "R4")
    for verdict in ("verified", "failed", "insufficient_evidence", "needs_review"):
        for rule in rules:
            view = view_of(make_payload(verdict, rule, [("c1", "proven", 0.6)]))
            assert md.check_conclusion(view) != "success"


def test_unknown_conclusion_mode_is_advisory() -> None:
    view = view_of(make_payload("verified", "R4", [("c1", "proven", 0.6)]))
    assert md.check_conclusion(view, mode="whatever") == "neutral"
    assert md.CONCLUSION_MODES == ("advisory", "strict")


@pytest.mark.parametrize(
    ("kwargs", "tail"),
    [
        ({"verdict": "verified"}, "Supported by static evidence (alpha) (1/1 criteria supported)"),
        ({"verdict": "failed"}, "Failed (1/1 criteria supported)"),
        ({"verdict": "insufficient_evidence", "pending": True}, "awaiting CI test results"),
        ({"verdict": None, "status": "error"}, "verdict unavailable"),
    ],
)
def test_check_title_carries_the_caveat(kwargs, tail) -> None:
    base = {"decided_by": "R4", "criteria": [("c1", "proven", 0.6)]}
    view = view_of(make_payload(**{**base, **kwargs}))
    title = md.check_title(view)
    assert title == f"{TITLE}: {tail}"
    assert title.startswith(md.CHECK_TITLE_PREFIX)
    assert len(title) <= md.CHECK_TITLE_MAX


# ----------------------------------------------------------- author-supplied hint flag


def payload_with_hints(n_flagged: int, total: int = 3) -> dict:
    criteria = [(f"c{i}", "proven", 0.7) for i in range(total)]
    payload = make_payload("verified", "R4", criteria)
    for row in payload["criteria"][:n_flagged]:
        row["flags"] = ["author_supplied_hint", "static_only"]
    return payload


def test_comment_flags_criteria_that_rely_on_author_hints() -> None:
    body = md.render_comment(view_of(payload_with_hints(2)))
    assert "**2 criteria rely on author-supplied test hints**" in body
    assert "author-supplied hint" in body
    one = md.render_comment(view_of(payload_with_hints(1)))
    assert "**1 criterion relies on author-supplied test hints**" in one
    assert "author-supplied" not in md.render_comment(view_of(payload_with_hints(0)))


def test_summary_count_alone_is_enough_for_the_flag() -> None:
    payload = payload_with_hints(0)
    payload["summary"]["author_hint_criteria"] = 3
    view = view_of(payload)
    assert md.author_hint_count(view) == 3
    assert "3 criteria rely on author-supplied test hints" in md.render_comment(view)
    assert "3 criteria rely" in md.render_check_run(view).summary


def test_hint_line_comes_before_the_table_and_is_in_the_check_summary() -> None:
    view = view_of(payload_with_hints(1))
    body = md.render_comment(view)
    assert body.index("relies on author-supplied") < body.index(TABLE_HEAD)
    assert "relies on author-supplied" in md.render_check_run(view).summary


# --------------------------------------------------------------- intent coverage signal


def test_low_intent_coverage_is_called_out_next_to_the_number() -> None:
    low = render(
        "insufficient_evidence",
        "R2c",
        [("c1", "proven", 0.7)],
        coverage=0.33,
        rules_inputs={"intent_coverage": 0.33, "min": 0.5},
    )
    assert "intent coverage **33%** (below the minimum 50%" in low
    fine = render("verified", "R4", [("c1", "proven", 0.7)], coverage=0.9)
    assert "below the minimum" not in fine


# ------------------------------------------------------------------ view / provenance


def test_view_round_trips_provenance_and_hints() -> None:
    payload = make_payload("verified", "R4", [("c1", "proven", 0.7)])
    payload["criteria"][0]["provenance"] = "author_head_spec"
    payload["criteria"][0]["hints"] = [
        {"kind": "tests", "value": "tests/test_x.py", "provenance": "author_head_spec"},
        "not a mapping",
    ]
    payload["summary"]["author_hint_criteria"] = 1
    view = VerdictV2View.from_payload(payload)
    c = view.criteria[0]
    assert c.provenance == "author_head_spec"
    assert c.hints == (
        {"kind": "tests", "value": "tests/test_x.py", "provenance": "author_head_spec"},
    )
    assert VerdictV2View.from_payload(view.to_dict()) == view
    assert view.summary.author_hint_criteria == 1


def test_view_defaults_for_a_pre_contract_3_payload() -> None:
    view = view_of(make_payload("verified", "R4", [("c1", "proven", 0.7)]))
    assert view.criteria[0].provenance == "author_pr_body"
    assert view.criteria[0].hints == ()
    assert view.summary.author_hint_criteria == 0


def test_untrusted_hint_text_never_reaches_the_comment() -> None:
    payload = make_payload("verified", "R4", [("c1", "proven", 0.7)])
    payload["criteria"][0]["hints"] = [
        {"kind": "tests", "value": "@everyone <script>x</script>", "provenance": "author_head_spec"}
    ]
    body = md.render_comment(view_of(payload))
    assert "@everyone" not in body
    assert "<script>" not in body


# ------------------------------------------- combined table: policy mode x knob (DEC-030)

#: (policy mode, verdict, rule, pending, knob) -> conclusion
COMBINED = [
    (None, "verified", "R4", False, "advisory", "neutral"),
    (None, "verified", "R4", False, "strict", "success"),
    ("advisory", "verified", "R4", False, "advisory", "neutral"),
    ("advisory", "verified", "R4", False, "strict", "success"),
    ("blocking", "verified", "R4", False, "advisory", "success"),
    ("blocking", "verified", "R4", True, "advisory", "failure"),
    ("blocking", "insufficient_evidence", "R2b", False, "strict", "failure"),
    ("blocking", "needs_review", "R3a", False, "advisory", "failure"),
    ("blocking", "failed", "R1c", False, "advisory", "failure"),
    ("advisory", "failed", "R1c", False, "advisory", "neutral"),
    ("advisory", "needs_review", "R3a", False, "strict", "neutral"),
]


@pytest.mark.parametrize(("pmode", "verdict", "rule", "pending", "knob", "expected"), COMBINED)
def test_combined_conclusion_table(pmode, verdict, rule, pending, knob, expected) -> None:
    payload = make_payload(verdict, rule, [("c1", "proven", 0.6)], pending=pending)
    if pmode:
        payload["policy"] = {"present": True, "status": "ok", "mode": pmode}
    view = view_of(payload)
    assert md.check_conclusion(view, mode=knob) == expected
    assert md.render_check_run(view, conclusions=knob).conclusion == expected


def test_blocking_policy_never_makes_an_unavailable_verdict_fail() -> None:
    payload = make_payload(None, "R4", [], status="error")
    payload["policy"] = {"mode": "blocking"}
    assert md.check_conclusion(view_of(payload)) == "neutral"


def test_r2e_check_run_is_neutral_and_never_success_even_when_strict() -> None:
    for inputs in ({}, {"not_applicable": True}):
        view = view_of(make_payload("insufficient_evidence", "R2e", [], rules_inputs=inputs))
        assert md.check_conclusion(view) == "neutral"
        assert md.check_conclusion(view, mode="strict") == "neutral"


# ------------------------------------------------- B-10: blocking mode and unusable policy

_NA = {"not_applicable": True}
_POLICY_OK_BLOCKING = {"status": "ok", "mode": "blocking", "errors": []}


def _view(verdict, rule, *, pending=False, policy=None, inputs=None, status="ok", error=None):
    payload = make_payload(
        verdict, rule, [("c1", "proven", 0.6)], pending=pending, status=status, rules_inputs=inputs
    )
    if policy is not None:
        payload["policy"] = policy
    if error is not None:
        payload["error"] = error
    return view_of(payload)


#: (view kwargs, expected conclusion): the full documented table for policy modes.
B10_TABLE = [
    # no policy file: unchanged advisory behaviour
    (dict(verdict="verified", rule="R4"), "neutral"),
    (dict(verdict="failed", rule="R1a"), "failure"),
    # blocking, readable
    (dict(verdict="verified", rule="R4", policy=_POLICY_OK_BLOCKING), "success"),
    (dict(verdict="verified", rule="R4", pending=True, policy=_POLICY_OK_BLOCKING), "failure"),
    (dict(verdict="insufficient_evidence", rule="R2b", policy=_POLICY_OK_BLOCKING), "failure"),
    (dict(verdict="needs_review", rule="R3a", policy=_POLICY_OK_BLOCKING), "failure"),
    (dict(verdict="failed", rule="R1b", policy=_POLICY_OK_BLOCKING), "failure"),
    # docs-only / inert-only: nothing to verify, never red in blocking mode
    (dict(verdict="insufficient_evidence", rule="R2e", inputs=_NA, policy=_POLICY_OK_BLOCKING), "neutral"),
    # R2e because there are NO criteria (not inert-only) stays red
    (dict(verdict="insufficient_evidence", rule="R2e", inputs={"not_applicable": False},
          policy=_POLICY_OK_BLOCKING), "failure"),
    # advisory policy never fails
    (dict(verdict="failed", rule="R1a", policy={"status": "ok", "mode": "advisory"}), "neutral"),
    # an unusable base policy is never a silent pass
    (dict(verdict="verified", rule="R4", policy={"status": "unreadable", "mode": None}), "action_required"),
    (dict(verdict="insufficient_evidence", rule="R2b", policy={"status": "too_large", "mode": None}),
     "action_required"),
    (dict(verdict="needs_review", rule="R3a", policy={"status": "ok", "mode": None, "errors": ["x"]}),
     "action_required"),
    (dict(verdict="failed", rule="R1a", policy={"status": "unreadable", "mode": None}), "failure"),
    # an unavailable verdict: neutral, except a refresh that failed after one was published
    (dict(verdict=None, rule="R4", status="error"), "neutral"),
    (dict(verdict=None, rule="R4", status="error", error={"code": "recompute_failed:ValueError"}),
     "action_required"),
    (dict(verdict=None, rule="R4", status="error", error={"code": "stage_a_not_stored"}),
     "action_required"),
]


@pytest.mark.parametrize(("kwargs", "expected"), B10_TABLE)
def test_b10_conclusion_table(kwargs, expected) -> None:
    assert md.check_conclusion(_view(**kwargs)) == expected
    # the strict knob never lowers any of these outcomes below the documented ones
    if expected in ("failure", "action_required"):
        assert md.check_conclusion(_view(**kwargs), mode="strict") == expected
