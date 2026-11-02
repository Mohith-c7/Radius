"""Verdict v2 renderer: goldens, structure, truncation, injection, marker, upsert."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest
from radius_github.verdict_v2 import markdown as md
from radius_github.verdict_v2.view import VerdictV2View

ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "docs" / "research" / "design").is_dir()
)
DESIGN = ROOT / "docs" / "research" / "design"
GOLDEN = Path(__file__).resolve().parent / "golden_verdict_v2"
EXAMPLE = json.loads((DESIGN / "verdict_v2.example.08.json").read_text(encoding="utf-8"))
EXPECT = json.loads((DESIGN / "verdict_v2.fixture_expectations.json").read_text(encoding="utf-8"))
CORPUS = ROOT / "tests" / "security" / "prompt_injection" / "corpus" / "corpus_v1.jsonl"
HEAD = "4f2a9d1c0b7e6a53f8c1d2e3b4a59687c0d1e2f3"
INVISIBLE = re.compile(
    "[\u0000-\u0008\u000b-\u001f\u007f-\u009f­​-‏ -‮⁠-⁩﻿]"
)


def view_of(payload: dict[str, Any]) -> VerdictV2View:
    return VerdictV2View.from_payload(payload)


def example_view() -> VerdictV2View:
    return view_of(EXAMPLE)


def read_golden(name: str) -> str:
    return (GOLDEN / name).read_text(encoding="utf-8").replace("\r\n", "\n")


def strip_code(text: str) -> str:
    """Remove code spans (escaped backticks are not delimiters)."""

    return re.sub(r"`[^`]*`", "", text.replace("\\`", ""))


# ---------------------------------------------------------------- payload builder


def make_payload(
    verdict: str | None,
    decided_by: str,
    criteria: list[tuple[str, str, float]],
    *,
    uim: float = 0.0,
    coverage: float = 1.0,
    pending: bool = False,
    status: str = "ok",
    tamper: list[dict[str, Any]] | None = None,
    rules_inputs: dict[str, Any] | None = None,
    refs: dict[str, Any] | None = None,
    flags: list[str] | None = None,
    next_actions: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    rows = []
    for cid, state, s in criteria:
        items = []
        if state in ("proven", "weak", "unevidenced") and s > 0:
            items = [
                {
                    "evidence_id": f"ev_{cid}",
                    "test_id": f"tests/test_x.py::test_{cid}",
                    "outcome": "passed",
                    "status": "counted",
                    "a_static": 1.0 if state != "unevidenced" else 0.2,
                    "d_eff": 0.6,
                    "i": 0.8,
                    "f": 1.0,
                    "l": 0.9,
                    "term": s,
                    "contribution": s,
                }
            ]
        rows.append(
            {
                "criterion_id": cid,
                "text": f"criterion text {cid}",
                "state": state,
                "S": s,
                "S_raw": s,
                "weight": 1.0,
                "flags": list(flags or []),
                "items": items,
            }
        )
    counts = {k: sum(1 for _, st, _ in criteria if st == k) for k in
              ("proven", "weak", "unevidenced", "contradicted", "excluded")}
    payload: dict[str, Any] = {
        "verdict_version": 2,
        "algo_version": "verdict-v2-alpha-1",
        "profile": "alpha-static",
        "mode": "on",
        "status": status,
        "analysis_id": "an-1",
        "head_sha": HEAD,
        "revision": 1,
        "verdict": verdict,
        "pending": pending,
        "reasons": [],
        "summary": {
            "criteria_total": len(criteria),
            **counts,
            "uim": uim,
            "intent_coverage": coverage,
            "tamper": {},
            "evidence_basis": "static_only",
        },
        "criteria": rows,
        "tamper_findings": tamper or [],
        "unlinked_symbols": [],
        "next_actions": next_actions or [],
        "justification": {
            "schema": "verdict-v2-justification-1",
            "verdict": verdict,
            "decided_by": decided_by,
            "rules": [
                {
                    "id": decided_by,
                    "label": "x",
                    "fired": True,
                    "inputs": rules_inputs or {},
                    "refs": refs or {},
                }
            ],
            "thresholds": {"tau_support": 0.5, "uim_max": 0.2, "min_intent_coverage": 0.5},
        },
    }
    payload.update(extra)
    return payload


# ----------------------------------------------------------------------- goldens


def test_worked_example_matches_golden() -> None:
    assert md.render_comment(example_view()) == read_golden("fixture_08_worked_example.md")


def test_worked_example_key_lines_are_exactly_the_design_text() -> None:
    body = md.render_comment(example_view())
    lines = body.split("\n")
    assert lines[0] == "<!-- radius-confidence-report -->"
    assert lines[2] == "## Radius verdict (v2 alpha): Not verified - insufficient evidence"
    assert (
        "**1 of 4 stated criteria proven** | unproven intent mass **0.75** (limit 0.20) | "
        "intent coverage **100%** | evidence: static assertion strength only (no mutation testing)"
    ) in lines
    assert (
        "**Why:** 3 of 4 criteria are below the support threshold 0.50 (C2, C3, C4), so the "
        "unproven intent mass 0.75 exceeds 0.20."
    ) in body
    assert "| # | Criterion | State | Support | Evidence |" in lines
    assert "| C1 | `a password needs at least 8 characters` | PROVEN | 0.60 / 0.50 |" in body
    assert "| C2 | `a password needs at least one digit` | WEAK | 0.43 / 0.50 |" in body
    assert "| UNPROVEN | 0.14 / 0.50 |" in body
    assert (
        "| C4 | `a password must not be on the common-password list (case-insensitive)` | "
        "UNPROVEN | 0.00 / 0.50 | no linked test |"
    ) in lines
    assert "### What to do next" in lines
    assert "<summary>Per-criterion evidence</summary>" in body
    assert "<summary>Legacy v1 signals (file-level selection, uncalibrated heuristic score)</summary>" in body


def test_golden_tamper_failed() -> None:
    payload = make_payload(
        "failed",
        "R1c",
        [("c1", "unevidenced", 0.0), ("c2", "weak", 0.2)],
        uim=1.0,
        tamper=[
            {
                "finding_id": "tf_1",
                "rule_id": "T004",
                "severity": "high",
                "path": "tests/test_a.py",
                "reason": "assertion weakened to `is not None`",
                "symbol": "test_a",
                "old_snippet": "assert f(1) == 2",
                "new_snippet": "assert f(1) is not None",
            }
        ],
        rules_inputs={"threshold": "high", "max_severity": "high", "finding_ids": ["tf_1"]},
        refs={"finding_ids": ["tf_1"]},
        flags=["tampered", "static_only"],
    )
    assert md.render_comment(view_of(payload)) == read_golden("tamper_failed.md")


def test_golden_pending() -> None:
    payload = make_payload(
        "insufficient_evidence",
        "R2p",
        [("c1", "unevidenced", 0.0)],
        uim=1.0,
        pending=True,
        flags=["pending_results"],
        rules_inputs={"results_received": False},
    )
    assert md.render_comment(view_of(payload)) == read_golden("pending.md")


def test_golden_verified() -> None:
    payload = make_payload(
        "verified",
        "R4",
        [("c1", "proven", 0.73), ("c2", "proven", 0.6)],
        dashboard_url="https://dashboard.example/a/1",
    )
    assert md.render_comment(view_of(payload)) == read_golden("verified.md")


def test_golden_error_status() -> None:
    payload = make_payload(None, "R4", [], status="error", error={"detail": "boom @user"})
    assert md.render_comment(view_of(payload)) == read_golden("error.md")


# -------------------------------------------------- the 8 fixtures (structure checks)

FIXTURE_RULES = {
    "R1c": {"threshold": "high", "max_severity": "high", "finding_ids": ["tf_1"]},
    "R2a": {"testable_criteria": 0},
    "R2b": {"uim": 1.0, "uim_max": 0.2, "criteria": [{"criterion_id": "c1"}]},
    "R2c": {"intent_coverage": 0.333, "min": 0.5},
    "R4": {},
}
LABELS = {
    "verified": "Verified",
    "failed": "Failed",
    "insufficient_evidence": "Not verified - insufficient evidence",
    "needs_review": "Needs human review",
}


def fixture_payload(fx: dict[str, Any], mode: str) -> dict[str, Any]:
    states = fx[mode]["states"]
    rows = [(cid, st, fx[mode]["S"][cid]) for cid, st in states.items()]
    decided = fx["decided_by"][:3] if mode == "gold" else (
        "R2b" if fx["decided_by"].startswith("R2c (gold)") else fx["decided_by"][:3]
    )
    tamper = [
        {
            "finding_id": f"tf_{n}",
            "rule_id": t["rule_id"],
            "severity": t["severity"],
            "path": "tests/x.py",
            "reason": "r",
        }
        for n, t in enumerate(fx.get("expected_tamper", []))
    ]
    inputs = dict(FIXTURE_RULES.get(decided, {}))
    refs = {"criterion_ids": [cid for cid, st, s in rows if s < 0.5], "finding_ids": [t["finding_id"] for t in tamper]}
    return make_payload(
        fx["expected_verdict"],
        decided,
        rows,
        uim=fx[mode]["uim"],
        coverage=fx["intent_coverage"],
        tamper=tamper,
        rules_inputs=inputs,
        refs=refs,
    )


FIXTURE_CASES = [(f, m) for f in EXPECT["fixtures"] for m in ("gold", "auto")]


@pytest.mark.parametrize(
    ("fx", "mode"), FIXTURE_CASES, ids=[f"{f['fixture'][:2]}-{m}" for f, m in FIXTURE_CASES]
)
def test_fixture_comments_are_well_formed(fx: dict[str, Any], mode: str) -> None:
    view = view_of(fixture_payload(fx, mode))
    body = md.render_comment(view)
    assert body.startswith("<!-- radius-confidence-report -->\n<!-- radius-verdict-v2 rev=1 digest=")
    assert f"## Radius verdict (v2 alpha): {LABELS[fx['expected_verdict']]}" in body
    assert "static assertion strength only" in body
    assert len(body) <= md.MAX_COMMENT_CHARS
    assert body.count("<details>") == body.count("</details>")
    # One table row per criterion.
    assert sum(1 for line in body.split("\n") if re.match(r"\| C\d+ \|", line)) == len(fx[mode]["states"])
    # Deterministic.
    assert md.render_comment(view) == body
    check = md.render_check_run(view)
    expected = {"verified": "success", "failed": "failure"}.get(fx["expected_verdict"], "neutral")
    assert check.conclusion == expected


# ------------------------------------------------------------------ check run


def test_check_run_for_the_worked_example() -> None:
    check = md.render_check_run(example_view())
    assert check.title == "Radius v2: Not verified - insufficient evidence (1/4 criteria proven)"
    assert check.conclusion == "neutral"
    assert check.details_url == EXAMPLE["dashboard_url"]
    assert check.summary.startswith("**1 of 4 stated criteria proven**")
    assert "**Why:**" in check.summary
    assert check.text == md.render_comment(example_view())


@pytest.mark.parametrize(
    ("verdict", "pending", "status", "conclusion"),
    [
        ("verified", False, "ok", "success"),
        ("failed", False, "ok", "failure"),
        ("insufficient_evidence", False, "ok", "neutral"),
        ("needs_review", False, "ok", "neutral"),
        ("insufficient_evidence", True, "ok", "neutral"),
        ("verified", True, "ok", "neutral"),
        ("verified", False, "error", "neutral"),
        ("verified", False, "skipped", "neutral"),
        (None, False, "ok", "neutral"),
        ("bogus", False, "ok", "neutral"),
    ],
)
def test_check_conclusion_mapping(verdict: str | None, pending: bool, status: str, conclusion: str) -> None:
    view = view_of(make_payload(verdict, "R4", [("c1", "proven", 0.6)], pending=pending, status=status))
    assert md.check_conclusion(view) == conclusion
    assert md.render_check_run(view).conclusion == conclusion


@pytest.mark.parametrize(
    ("kwargs", "title"),
    [
        ({"verdict": "verified"}, "Radius v2: Verified (1/1 criteria proven)"),
        ({"verdict": "failed"}, "Radius v2: Failed (1/1 criteria proven)"),
        ({"verdict": "needs_review"}, "Radius v2: Needs human review (1/1 criteria proven)"),
        ({"verdict": "insufficient_evidence", "pending": True}, "Radius v2: awaiting CI test results"),
        ({"verdict": None, "status": "error"}, "Radius v2: verdict unavailable"),
    ],
)
def test_check_titles(kwargs: dict[str, Any], title: str) -> None:
    view = view_of(make_payload(**{"decided_by": "R4", "criteria": [("c1", "proven", 0.6)], **kwargs}))
    assert md.check_title(view) == title


def test_check_run_text_and_summary_stay_within_github_limits() -> None:
    payload = make_payload("verified", "R4", [(f"c{n}", "proven", 0.6) for n in range(400)])
    check = md.render_check_run(view_of(payload))
    assert len(check.text) < md.GITHUB_LIMIT
    assert len(check.summary) < md.GITHUB_LIMIT
    assert len(check.title) <= md.CHECK_TITLE_MAX


def test_details_url_is_dropped_when_unsafe() -> None:
    payload = copy.deepcopy(EXAMPLE)
    payload["dashboard_url"] = "javascript:alert(1)"
    view = view_of(payload)
    assert md.render_check_run(view).details_url is None
    assert "[details]" not in md.render_comment(view)


# ---------------------------------------------------------------- wording rules


def test_never_claims_more_than_static_evidence() -> None:
    body = md.render_comment(view_of(make_payload("verified", "R4", [("c1", "proven", 0.7)])))
    assert "static assertion strength only" in body
    assert "no mutation testing" in body
    assert "no language model judged correctness" in body
    assert "uncalibrated" in body
    assert "No rule found a problem" in body
    for forbidden in ("guarantee", "bug-free", "correct code", "100% safe", "probability of"):
        assert forbidden not in body.lower()


def test_pending_comment_says_awaiting_ci_and_scores_nothing() -> None:
    payload = make_payload(
        "insufficient_evidence", "R2p", [("c1", "unevidenced", 0.0)], pending=True,
        flags=["pending_results"], rules_inputs={"results_received": False},
    )
    view = view_of(payload)
    body = md.render_comment(view)
    assert "Awaiting CI test results" in body
    assert "No CI test results have been uploaded" in body
    assert "(awaiting CI)" in body
    assert md.check_title(view) == "Radius v2: awaiting CI test results"


@pytest.mark.parametrize(
    ("decided", "inputs", "refs", "needle"),
    [
        ("R1a", {}, {"criterion_ids": ["c1"]}, "Failing tests contradict criteria C1."),
        ("R1b", {"failed_cases": 3}, {}, "3 CI test case(s) failed"),
        ("R1c", {"threshold": "high"}, {"finding_ids": ["a", "b"]}, "2 tamper finding(s) at severity high or above"),
        ("R2a", {}, {}, "No behavioral, testable criterion was found"),
        ("R2c", {"intent_coverage": 0.333, "min": 0.5}, {}, "Only 33% of the behavioral changes"),
        ("R2d", {"blocking": ["truncated", "unsupported_language:ts"]}, {}, "The analysis was incomplete"),
        ("R3a", {}, {"finding_ids": ["a"]}, "need a human review"),
        ("R3b", {}, {"criterion_ids": ["c1"]}, "depend on a flaky test"),
        ("R3c", {}, {"criterion_ids": ["c1"]}, "rest on a weak link"),
        ("R4", {}, {}, "No rule found a problem"),
        ("R9", {}, {}, "See the justification in the dashboard."),
    ],
)
def test_why_sentence_per_deciding_rule(decided: str, inputs: dict, refs: dict, needle: str) -> None:
    verdict = {"R1": "failed", "R2": "insufficient_evidence", "R3": "needs_review", "R4": "verified"}.get(decided[:2])
    view = view_of(make_payload(verdict or "insufficient_evidence", decided, [("c1", "proven", 0.6)], rules_inputs=inputs, refs=refs))
    assert needle in md.render_comment(view)


def test_r4_without_criteria_says_no_behavioral_change() -> None:
    body = md.render_comment(view_of(make_payload("verified", "R4", [])))
    assert "No behavioral change was detected and no criteria were stated." in body
    assert "| # |" not in body


def test_why_falls_back_to_first_reason() -> None:
    payload = make_payload("insufficient_evidence", "R9", [("c1", "weak", 0.3)])
    payload["justification"] = {}
    payload["reasons"] = [{"code": "x", "detail": "ping @all"}]
    assert "ping `@all`" in md.render_comment(view_of(payload))


def test_error_and_skipped_status_render_unavailable() -> None:
    err = md.render_comment(view_of(make_payload(None, "R4", [], status="error")))
    assert "Verdict unavailable" in err and "could not be computed" in err
    skip = md.render_comment(view_of(make_payload(None, "R4", [], status="skipped")))
    assert "was skipped" in skip
    assert "stated criteria proven" not in err


@pytest.mark.parametrize(
    ("state", "label"),
    [
        ("proven", "PROVEN"),
        ("weak", "WEAK"),
        ("unevidenced", "UNPROVEN"),
        ("contradicted", "CONTRADICTED"),
        ("excluded", "EXCLUDED"),
        ("made_up", "UNKNOWN"),
    ],
)
def test_state_labels(state: str, label: str) -> None:
    body = md.render_comment(view_of(make_payload("insufficient_evidence", "R2b", [("c1", state, 0.3)])))
    assert f"| {label}" in body


def test_excluded_criterion_shows_reason_and_no_support() -> None:
    payload = make_payload("insufficient_evidence", "R2a", [("c1", "excluded", 0.0)])
    payload["criteria"][0]["reasons"] = [{"code": "not_testable", "detail": "vague"}]
    body = md.render_comment(view_of(payload))
    assert "| EXCLUDED | - | not scored (not testable) |" in body


def test_flags_become_tags_and_unknown_flags_are_dropped() -> None:
    payload = make_payload(
        "needs_review", "R3a", [("c1", "proven", 0.6)],
        flags=["tampered", "flaky_evidence", "static_only", "made_up<script>"],
    )
    body = md.render_comment(view_of(payload))
    assert "PROVEN (flaky, tampered)" in body
    assert "made_up" not in body


def test_failing_items_are_counted_in_the_evidence_cell() -> None:
    payload = make_payload("failed", "R1a", [("c1", "contradicted", 0.0)])
    payload["criteria"][0]["items"] = [
        {"evidence_id": "e", "test_id": "t.py::test_a", "outcome": "failed", "status": "gated:failed", "a_static": 1.0},
        {"evidence_id": "f", "test_id": "t.py::test_b", "outcome": "skipped", "status": "gated:skipped", "a_static": 1.0},
    ]
    body = md.render_comment(view_of(payload))
    assert "no test counted; 1 failing; 1 not counted" in body
    assert "not counted (gated:failed)" in body


# ------------------------------------------------------------------- explain


def test_explain_criterion_sentences_come_from_fields() -> None:
    view = example_view()
    text = md.explain_all(view)
    c2 = text["c_2f6a11"]
    assert c2.startswith("C2 is weak: support 0.43 is below the threshold 0.50.")
    assert "strongest assertion strength 1.00 (strong)" in c2
    assert "No test is linked to it." in text["c_d3a2f7"]
    assert "unproven" in text["c_81b0c4"]


def test_explain_without_threshold_and_with_flags() -> None:
    payload = make_payload("needs_review", "R3a", [("c1", "proven", 0.6)],
                           flags=["tampered", "flaky_evidence", "stale_evidence", "unconfirmed",
                                  "low_link_confidence", "needs_typed_evidence"])
    c = view_of(payload).criteria[0]
    out = md.explain_criterion(c)
    assert out.startswith("This criterion is proven: support 0.60.")
    for sentence in ("tamper finding", "flaky", "not bound to this commit", "not confirmed",
                     "link between the criterion and the code is weak", "typed evidence"):
        assert sentence in out


def test_explain_states() -> None:
    def explain(state: str, **kw: Any) -> str:
        payload = make_payload("insufficient_evidence", "R2b", [("c1", state, kw.get("s", 0.3))],
                               flags=kw.get("flags"))
        return md.explain_criterion(view_of(payload).criteria[0], label="C1", tau=0.5)

    assert "excluded from scoring" in explain("excluded")
    assert "contradicted: a linked test failed" in explain("contradicted")
    assert "no linked test has a strong assertion" in explain("weak", flags=["no_strong_assertion"])
    assert "No linked test counted as evidence." in explain("unevidenced", s=0.0) or "No test is linked" in explain("unevidenced", s=0.0)


# --------------------------------------------------------------------- size


def test_many_criteria_are_capped_with_a_marker() -> None:
    payload = make_payload("insufficient_evidence", "R2b", [(f"c{n}", "weak", 0.3) for n in range(250)], uim=1.0)
    body = md.render_comment(view_of(payload))
    rows = [ln for ln in body.split("\n") if re.match(r"\| C\d+ \|", ln)]
    assert len(rows) == md.MAX_TABLE_ROWS
    assert "+150 more criteria, see the dashboard." in body
    assert len(body) <= md.MAX_COMMENT_CHARS


def test_huge_inputs_never_exceed_the_limit_and_keep_details_balanced() -> None:
    long = "x" * 5000
    payload = make_payload(
        "failed", "R1c", [(f"c{n}", "weak", 0.3) for n in range(100)], uim=1.0,
        tamper=[{"finding_id": f"tf_{n}", "rule_id": "T001", "severity": "high", "path": long,
                 "reason": long, "old_snippet": long, "new_snippet": long} for n in range(300)],
        next_actions=[{"code": "c", "text": long, "criterion_id": "c1"} for _ in range(50)],
        unlinked_symbols=[long] * 500,
        rules_inputs={"threshold": "high", "finding_ids": ["tf_1"]}, refs={"finding_ids": ["tf_1"]},
    )
    body = md.render_comment(view_of(payload))
    assert len(body) <= md.MAX_COMMENT_CHARS
    assert body.count("<details>") == body.count("</details>")
    assert "+280 more, see the dashboard." in body  # tamper list cap
    assert md.render_comment(view_of(payload)) == body


def test_optional_sections_are_dropped_in_priority_order_when_over_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = copy.deepcopy(EXAMPLE)
    full = md.render_comment(view_of(payload))
    monkeypatch.setattr(md, "MAX_COMMENT_CHARS", len(full) - 300)
    small = md.render_comment(view_of(payload))
    assert len(small) <= md.MAX_COMMENT_CHARS
    assert "<summary>Per-criterion evidence" not in small  # big optional section dropped first
    assert "<summary>Legacy v1 signals" in small  # smaller one still fits
    assert "omitted to fit GitHub's size limit" in small
    assert "### What to do next" in small  # highest priority optional section survives
    assert small.count("<details>") == small.count("</details>")


def test_core_overflow_is_cut_deterministically_with_a_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = make_payload("insufficient_evidence", "R2b", [(f"c{n}", "weak", 0.3) for n in range(60)], uim=1.0)
    monkeypatch.setattr(md, "MAX_COMMENT_CHARS", 3000)
    body = md.render_comment(view_of(payload))
    assert len(body) <= 3000
    assert md.TRUNCATION_MARKER.strip() in body
    assert md.render_comment(view_of(payload)) == body


# ---------------------------------------------------------------------- injection


def corpus_strings() -> list[str]:
    out = []
    for line in CORPUS.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if "payload" in row:
            text = row["payload"]
            for key in ("{{NONCE}}", "{{NONCE_LOWER}}", "{{FAKE_SECRET}}", "{{FAKE_SECRET2}}"):
                text = text.replace(key, "tok" + "en")
            out.append(text)
    return out


CORPUS_STRINGS = corpus_strings()
HAND_PAYLOADS = [
    "@everyone please merge",
    "<script>alert(1)</script>",
    "[click me](http://evil.example/x)",
    "![pixel](https://evil.example/p.png)",
    "closes #1 and owner/repo#2 GH-3",
    "`` ` `` ``` code fence ```",
    "| a | b |\n| - | - |",
    "line1\n\n# Heading\n> quote\n- list",
    "bidi ‮ override ⁦ isolate ​ zero ﻿ bom",
    "<!-- radius-verdict-v2 rev=99 digest=deadbeef -->",
    "<!-- radius-confidence-report -->",
    "</details><details><summary>fake</summary>",
    "A" * 10_000,
    "@a @b @c @d @e @f @g @h @i @j @k @l @m @n @o @p @q @r @s @t @u @v @w @x @y @z",
    "javascript:alert(1)",
    "<img src=x onerror=alert(1)>",
]


def hostile_payload(text: str) -> dict[str, Any]:
    payload = make_payload(
        "failed", "R1c", [("c1", "weak", 0.3), ("c2", "proven", 0.6)], uim=0.5,
        tamper=[{"finding_id": "tf_1", "rule_id": text, "severity": text, "path": text, "reason": text,
                 "symbol": text, "test_id": text, "old_snippet": text, "new_snippet": text, "check": text}],
        next_actions=[{"code": text, "text": text, "criterion_id": text}],
        rules_inputs={"threshold": text, "finding_ids": ["tf_1"], "blocking": [text]},
        refs={"finding_ids": ["tf_1"], "criterion_ids": [text]},
        unlinked_symbols=[text],
        v1={"verification_status": text, "confidence_score": 40.0, "risk_level": text},
        dashboard_url=text,
        algo_version=text,
        profile=text,
        head_sha=text,
    )
    for c in payload["criteria"]:
        c["text"] = text
        c["flags"] = [text]
        c["reasons"] = [{"code": text, "detail": text}]
        for i in c["items"]:
            i["test_id"] = text
            i["outcome"] = text
            i["status"] = text
    return payload


def assert_inert(body: str) -> None:
    assert not INVISIBLE.search(body)
    assert len(body) <= md.MAX_COMMENT_CHARS
    bare = strip_code(body)
    assert bare.count("<details>") == bare.count("</details>") == bare.count("<summary>")
    # Only the two real markers exist (outside code spans), on the first two lines.
    assert bare.count("<!--") == 2
    assert body.split("\n")[0] == md.COMMENT_MARKER_V1
    assert md.parse_v2_marker(body) is not None
    bare = re.sub(r"</?(details|summary)>", "", bare)
    bare = re.sub(r"<!-- [^>]*-->", "", bare)
    assert "<" not in bare and ">" not in bare
    assert not re.search(r"(?<![\\`\w])@\w", bare)
    assert "![" not in bare.replace("\\![", "")
    # No link syntax other than a possible fixed footer link.
    assert not re.search(r"(?<!\\)\]\(", re.sub(r"\[details\]\(https?://[^)\s]+\)", "", bare))
    assert "://" not in re.sub(r"\[details\]\(https?://[^)\s]+\)", "", bare)


@pytest.mark.parametrize("text", HAND_PAYLOADS)
def test_hand_written_injection_payloads_are_inert(text: str) -> None:
    body = md.render_comment(view_of(hostile_payload(text)))
    assert_inert(body)
    check = md.render_check_run(view_of(hostile_payload(text)))
    assert len(check.text) < md.GITHUB_LIMIT and "\n" not in check.title


def test_corpus_payloads_are_inert_in_every_untrusted_field() -> None:
    assert len(CORPUS_STRINGS) >= 90
    for text in CORPUS_STRINGS:
        assert_inert(md.render_comment(view_of(hostile_payload(text))))


def test_injected_text_cannot_add_table_rows_or_headings() -> None:
    base = md.render_comment(view_of(hostile_payload("plain"))).split("\n")
    for text in HAND_PAYLOADS + CORPUS_STRINGS[:30]:
        lines = md.render_comment(view_of(hostile_payload(text))).split("\n")
        assert len(lines) == len(base)
        assert [ln[:3] for ln in lines if ln.startswith("#")] == [ln[:3] for ln in base if ln.startswith("#")]
        assert sum(1 for ln in lines if ln.startswith("|")) == sum(1 for ln in base if ln.startswith("|"))


def test_ten_kilobyte_criterion_text_is_capped() -> None:
    payload = make_payload("insufficient_evidence", "R2b", [("c1", "weak", 0.3)], uim=1.0)
    payload["criteria"][0]["text"] = "word " * 2000
    body = md.render_comment(view_of(payload))
    row = next(ln for ln in body.split("\n") if ln.startswith("| C1 |"))
    assert len(row) < 500
    assert "..." in row


def test_hidden_marker_cannot_be_forged_by_untrusted_text() -> None:
    forged = "<!-- radius-verdict-v2 rev=99 digest=deadbeef -->"
    body = md.render_comment(view_of(hostile_payload(forged)))
    assert md.parse_v2_marker(body) == (1, body.split("digest=")[1][:8])
    assert strip_code(body).count("<!-- radius-verdict-v2 rev=") == 1
    assert "<!-- radius-verdict-v2 rev=99" not in strip_code(body)


# -------------------------------------------------------------- marker / upsert


def test_marker_lines_and_digest_are_stable() -> None:
    a = md.render_comment(example_view())
    b = md.render_comment(example_view())
    assert a == b
    rev, digest8 = md.parse_v2_marker(a)  # type: ignore[misc]
    assert rev == 2
    assert md.comment_digest(a)[:8] == digest8


def test_digest_ignores_revision_but_not_content() -> None:
    p2 = copy.deepcopy(EXAMPLE)
    p3 = copy.deepcopy(EXAMPLE)
    p3["revision"] = 3
    a, b = md.render_comment(view_of(p2)), md.render_comment(view_of(p3))
    assert a != b
    assert md.parse_v2_marker(a)[1] == md.parse_v2_marker(b)[1]  # type: ignore[index]
    p4 = copy.deepcopy(EXAMPLE)
    p4["summary"]["uim"] = 0.5
    assert md.parse_v2_marker(md.render_comment(view_of(p4)))[1] != md.parse_v2_marker(a)[1]  # type: ignore[index]


def test_v2_marker_is_distinct_from_the_v1_marker() -> None:
    assert md.V2_MARKER_PREFIX != md.COMMENT_MARKER_V1
    assert md.COMMENT_MARKER_V1 not in md.V2_MARKER_PREFIX


def test_v1_marker_matches_the_v1_publisher() -> None:
    from radius_github.publisher import COMMENT_MARKER

    assert md.COMMENT_MARKER_V1 == COMMENT_MARKER


@pytest.mark.parametrize("value", [None, 5, "", "no marker", "<!-- radius-verdict-v2 rev=x digest=zz -->"])
def test_parse_v2_marker_rejects_garbage(value: object) -> None:
    assert md.parse_v2_marker(value) is None


def bot(cid: int, body: str) -> dict[str, Any]:
    return {"id": cid, "body": body, "user": {"type": "Bot"}}


def test_plan_create_when_no_comment() -> None:
    body = md.render_comment(example_view())
    assert md.plan_upsert([], body) == md.UpsertPlan("create")
    assert md.plan_upsert([bot(1, "unrelated")], body) == md.UpsertPlan("create")


def test_plan_update_v1_comment_in_place() -> None:
    body = md.render_comment(example_view())
    v1 = bot(7, f"{md.COMMENT_MARKER_V1}\n## Radius Confidence Report")
    assert md.plan_upsert([v1], body) == md.UpsertPlan("update", 7)


def test_plan_skip_when_digest_equal_and_update_when_changed() -> None:
    body = md.render_comment(example_view())
    assert md.plan_upsert([bot(9, body)], body) == md.UpsertPlan("skip", 9)
    changed = copy.deepcopy(EXAMPLE)
    changed["summary"]["uim"] = 0.1
    other = md.render_comment(view_of(changed))
    assert md.plan_upsert([bot(9, body)], other) == md.UpsertPlan("update", 9)
    bumped = copy.deepcopy(EXAMPLE)
    bumped["revision"] = 9
    assert md.plan_upsert([bot(9, body)], md.render_comment(view_of(bumped))) == md.UpsertPlan("skip", 9)


def test_plan_ignores_human_quotes_and_prefers_v2_comment() -> None:
    body = md.render_comment(example_view())
    human = {"id": 1, "body": body, "user": {"type": "User"}}
    assert md.plan_upsert([human], body) == md.UpsertPlan("create")
    v1 = bot(2, md.COMMENT_MARKER_V1)
    v2 = bot(3, body)
    assert md.find_existing_comment([v1, v2])["id"] == 3  # type: ignore[index]
    assert md.find_existing_comment([bot(4, md.COMMENT_MARKER_V1)])["id"] == 4  # type: ignore[index]
    assert md.find_existing_comment([{"body": md.COMMENT_MARKER_V1, "user": {"type": "Bot"}}]) is None
    assert md.find_existing_comment([{"id": 1, "body": md.COMMENT_MARKER_V1, "user": "x"}]) is None
    assert md.find_existing_comment([{"id": 1, "body": md.COMMENT_MARKER_V1}]) is not None


def test_one_comment_across_v1_v2_v2_sequence() -> None:
    """Fake client: v1 -> v2 -> v2 (same) -> v2 (changed) keeps exactly one comment."""

    comments: list[dict[str, Any]] = []

    def apply(body: str) -> str:
        plan = md.plan_upsert(comments, body)
        if plan.action == "create":
            comments.append(bot(len(comments) + 1, body))
        elif plan.action == "update":
            next(c for c in comments if c["id"] == plan.comment_id)["body"] = body
        return plan.action

    assert apply(f"{md.COMMENT_MARKER_V1}\nv1 body") == "create"
    first = md.render_comment(example_view())
    assert apply(first) == "update"
    assert apply(first) == "skip"
    changed = copy.deepcopy(EXAMPLE)
    changed["revision"] = 3
    changed["summary"]["proven"] = 2
    assert apply(md.render_comment(view_of(changed))) == "update"
    assert len(comments) == 1


# ------------------------------------------------------------ item detail lines


@pytest.mark.parametrize(
    ("a_static", "word"), [(1.0, "strong"), (0.8, "strong"), (0.35, "partial"), (0.2, "weak"), (0.0, "none")]
)
def test_strength_words(a_static: float, word: str) -> None:
    assert md._strength_word(a_static) == word


def test_item_lines_show_flaky_and_tamper_factors_and_overflow() -> None:
    payload = make_payload("needs_review", "R3b", [("c1", "proven", 0.6)])
    base = payload["criteria"][0]["items"][0]
    payload["criteria"][0]["items"] = [
        {**base, "evidence_id": f"e{n}", "flaky_f": 0.7, "tamper_penalty": 0.5, "a_static": 0.35, "d_eff": 0.35}
        for n in range(12)
    ]
    body = md.render_comment(view_of(payload))
    assert "flaky factor 0.70" in body and "tamper penalty 0.50" in body
    assert "+4 more items, see the dashboard." in body
    assert "(partial)" in body


def test_markdown_renderer_matches_ports() -> None:
    from radius_github.verdict_v2.ports import VerdictRenderer

    renderer: VerdictRenderer = md.MarkdownRenderer()
    view = example_view()
    assert renderer.render_comment(view) == md.render_comment(view)
    assert renderer.render_check_summary(view) == md.render_check_run(view).summary
