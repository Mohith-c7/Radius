"""VD-04/VD-05 through the real Stage A/B on the F-14 fixtures (acceptance harness).

Real Stage A (LK-01/02/03/04, EV-02) on the fixture checkout, the repository config
injected as Stage A would capture it at the BASE ref, then Stage B, the real renderer
and the shared API payload builder. Covers policy overlay and provenance, waivers
(applied, expired, non-waivable), the P1/P2 rules, the Check Run mapping, the audit
record and the security properties (a policy or waiver never turns a failure green).
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import random
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from radius_evidence.domain.enums import Outcome
from radius_github.verdict_v2 import markdown as md
from radius_github.verdict_v2.view import VerdictV2View
from radius_shared.verdict_v2_payload import StoredVerdict, build_payload
from radius_worker.verdict_v2 import adapters
from radius_worker.verdict_v2.collect import default_repo_config
from radius_worker.verdict_v2.scoring import ScoringPipeline, build_stage_b

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "docs" / "research" / "design").is_dir())
BASE_REF = "b" * 40
TODAY = datetime(2026, 11, 2, tzinfo=UTC)
REASON = "Legacy skip is tracked in SEC-42 and reviewed every sprint"


def _load_script():
    spec = importlib.util.spec_from_file_location("verdict_v2_run_policy", ROOT / "scripts" / "verdict_v2_run.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RUN = _load_script()
DIRS = {p.name: p for p in RUN.fixture_dirs([])}
F01, F02, F04 = "01_correct_strong_tests", "02_correct_weak_tests", "04_test_tampering"


@pytest.fixture(scope="module")
def stage_a():
    return {n: RUN.collect_stage_a(DIRS[n], "gold", "static") for n in (F01, F02, F04)}


@pytest.fixture(scope="module")
def cases():
    out = {}
    for n in (F01, F02, F04):
        exp = json.loads((DIRS[n] / "expected.json").read_text(encoding="utf-8"))
        out[n] = adapters.case_inputs(RUN.cases_for(exp)).items
    return out


def entry(text):
    if text is None:
        return {"status": "absent"}
    return {"status": "ok", "text": text, "sha256": hashlib.sha256(text.encode()).hexdigest()}


def repo_config(policy=None, waivers=None, head=None, base_ref=BASE_REF):
    out = {"base_ref": base_ref, "policy": entry(policy), "waivers": entry(waivers)}
    if head is not None:
        out["head_policy"] = entry(head)
    return out


def score(sa, case_rows, config=None, *, clock=TODAY, **replace):
    if config is not None:
        replace["repo_config"] = config
    sa = dataclasses.replace(sa, **replace)
    stage_b = build_stage_b(sa, cases=case_rows, uploads=1)
    return ScoringPipeline(mode="shadow", clock=lambda: clock).score_full(stage_b)


def failing(case_rows):
    first = dataclasses.replace(case_rows[0], outcome=Outcome.FAILED)
    return (first, *case_rows[1:])


def waiver_text(findings, *, expires="2026-12-01", created="2026-10-30", owner="alice", reason=REASON):
    return "version: 1\nwaivers:\n" + "".join(
        f"  - id: W-{i}\n    finding: {fid}\n    reason: \"{reason}\"\n    owner: {owner}\n"
        f"    created: {created}\n    expires: {expires}\n"
        for i, fid in enumerate(findings, 1)
    )


# ------------------------------------------------------------------- baseline


@pytest.mark.parametrize("config", [None, {}, repo_config(), repo_config(policy="version: 1\n")])
def test_no_policy_or_an_empty_one_changes_nothing(stage_a, cases, config) -> None:
    base = score(stage_a[F01], cases[F01])
    got = score(stage_a[F01], cases[F01], config)
    assert got.payload["verdict"] == base.payload["verdict"] == "verified"
    assert got.result.verdict.config_digest == base.result.verdict.config_digest
    assert "waivers" not in got.payload
    assert [c["state"] for c in got.payload["criteria"]] == [c["state"] for c in base.payload["criteria"]]
    assert [r["id"] for r in got.payload["justification"]["rules"]] == [r["id"] for r in base.payload["justification"]["rules"]]
    if config in (None, {}, repo_config()):
        assert "policy" not in got.payload


# -------------------------------------------------------------- policy overlay


def test_threshold_override_changes_the_verdict_and_names_the_policy_line(stage_a, cases) -> None:
    text = "version: 1\nmode: advisory\nthresholds:\n  tau_support: 0.9\n"
    got = score(stage_a[F01], cases[F01], repo_config(policy=text))
    assert got.payload["verdict"] == "insufficient_evidence"
    assert got.payload["justification"]["thresholds"]["tau_support"] == 0.9
    assert got.result.verdict.config_digest != score(stage_a[F01], cases[F01]).result.verdict.config_digest
    policy = got.payload["policy"]
    prov = {p["key"]: p for p in policy["provenance"]}
    assert prov["thresholds.tau_support"]["line"] == 4 and prov["thresholds.tau_support"]["origin"] == "base"
    assert prov["mode"]["line"] == 2
    assert policy["source"]["ref"] == BASE_REF and policy["source"]["origin"] == "base"
    assert policy["source"]["sha256"] == hashlib.sha256(text.encode()).hexdigest()
    # the same provenance is inside the justification tree
    assert got.payload["justification"]["policy"]["provenance"] == policy["provenance"]


def test_loosened_threshold_stays_inside_the_safe_bound(stage_a, cases) -> None:
    text = "version: 1\nthresholds:\n  uim_max: 0.95\n  tau_support: 0.01\n"
    got = score(stage_a[F02], cases[F02], repo_config(policy=text))
    errors = got.payload["policy"]["errors"]
    assert len(errors) == 2 and all("outside the allowed range" in e for e in errors)
    assert got.payload["justification"]["thresholds"]["uim_max"] == 0.2  # default kept
    assert got.payload["verdict"] == "insufficient_evidence"


def test_p1_required_state_per_path(stage_a, cases) -> None:
    sa = stage_a[F01]
    sa = dataclasses.replace(
        sa, criteria=tuple(dataclasses.replace(c, weight=0.2) if c.criterion_id == "C2" else c for c in sa.criteria)
    )
    text = "version: 1\nthresholds:\n  tau_support: 0.65\nrequire:\n  - paths: [src/**]\n    min_state: proven\n"
    plain = score(sa, cases[F01], repo_config(policy="version: 1\nthresholds:\n  tau_support: 0.65\n"))
    assert plain.payload["verdict"] == "verified"  # C2 is weak but light enough to pass
    got = score(sa, cases[F01], repo_config(policy=text))
    assert got.payload["verdict"] == "insufficient_evidence"
    assert got.payload["justification"]["decided_by"] == "P1"
    ids = [r["id"] for r in got.payload["justification"]["rules"]]
    assert ids.index("P1") == ids.index("R2d") + 1 and "P2" in ids and len(ids) == 14
    unmet = got.payload["policy"]["unmet"]["required"]
    assert [(u["criterion_id"], u["state"], u["line"]) for u in unmet] == [("C2", "weak", 5)]
    assert got.payload["reasons"][0]["rule_id"] == "P1"
    assert got.payload["reasons"][0]["code"] == "policy_requirement_unmet"


def test_p1_does_not_reach_a_failure_but_sits_below_r1(stage_a, cases) -> None:
    text = "version: 1\nrequire:\n  - paths: [src/**]\n    min_state: proven\n"
    got = score(stage_a[F01], failing(cases[F01]), repo_config(policy=text))
    assert got.payload["verdict"] == "failed"
    assert got.payload["justification"]["decided_by"] == "R1a"


def test_p2_requires_a_non_agent_authored_test(stage_a, cases) -> None:
    text = "version: 1\nthresholds:\n  tau_support: 0.3\nevidence:\n  require_non_agent_test: true\n"
    human = score(stage_a[F01], cases[F01], repo_config(policy=text))
    assert human.payload["verdict"] == "verified"
    agent = score(stage_a[F01], cases[F01], repo_config(policy=text), agent_signal=True)
    assert agent.payload["justification"]["decided_by"] == "P2"
    assert agent.payload["verdict"] == "insufficient_evidence"
    assert {u["criterion_id"] for u in agent.payload["policy"]["unmet"]["evidence"]} == {"C1", "C2"}
    # without the policy the same agent PR is not blocked by P2
    assert score(stage_a[F01], cases[F01], agent_signal=True).payload["justification"]["decided_by"] != "P2"


def test_exclude_paths_only_shrink_the_coverage_denominator(stage_a, cases) -> None:
    text = "version: 1\nexclude:\n  paths: ['src/**', 'tests/**']\n"
    got = score(stage_a[F04], cases[F04], repo_config(policy=text))
    assert got.payload["summary"]["intent_coverage"] == 1.0
    # tamper findings under excluded paths are NOT hidden
    assert got.payload["verdict"] == "failed" and got.payload["justification"]["decided_by"] == "R1c"
    assert len(got.payload["tamper_findings"]) == 4


def test_invalid_base_policy_is_visible_and_blocks_a_pass(stage_a, cases) -> None:
    got = score(stage_a[F01], cases[F01], repo_config(policy="version: 9\n"))
    assert got.payload["verdict"] == "insufficient_evidence"
    assert got.payload["justification"]["decided_by"] == "R2d"
    assert got.payload["policy"]["status"] == "invalid" and got.payload["policy"]["errors"]
    assert "policy_invalid" in got.payload["justification"]["rules"][7]["inputs"]["blocking"]


def test_unreadable_policy_does_not_read_as_no_policy(stage_a, cases) -> None:
    cfg = {"base_ref": BASE_REF, "policy": {"status": "unreadable"}, "waivers": {"status": "unreadable"}}
    got = score(stage_a[F01], cases[F01], cfg)
    assert got.payload["justification"]["decided_by"] == "R2d"
    assert got.payload["policy"]["status"] == "unreadable"


def test_head_policy_tightening_is_applied_only_with_the_base_opt_in(stage_a, cases) -> None:
    head = "version: 1\nthresholds:\n  tau_support: 0.9\n"
    off = score(stage_a[F01], cases[F01], repo_config(policy="version: 1\nmode: advisory\n", head=head))
    assert off.payload["verdict"] == "verified"
    on = score(stage_a[F01], cases[F01], repo_config(policy="version: 1\nhead_policy: tighten_only\n", head=head))
    assert on.payload["verdict"] == "insufficient_evidence"
    origins = {p["key"]: p["origin"] for p in on.payload["policy"]["provenance"]}
    assert origins["thresholds.tau_support"] == "head"
    loosen = score(
        stage_a[F01],
        cases[F01],
        repo_config(
            policy="version: 1\nhead_policy: tighten_only\nthresholds:\n  tau_support: 0.7\n",
            head="version: 1\nthresholds:\n  tau_support: 0.3\n",
        ),
    )
    assert loosen.payload["justification"]["thresholds"]["tau_support"] == 0.7
    assert loosen.payload["policy"]["ignored_head"][0]["key"] == "thresholds.tau_support"


# ------------------------------------------------------------- tamper policy


def test_high_tamper_rules_cannot_be_disabled_without_an_acknowledgement(stage_a, cases) -> None:
    rules = "".join(f"    {r}:\n      enabled: false\n" for r in ("T001", "T002", "T004", "T005"))
    got = score(stage_a[F04], cases[F04], repo_config(policy="version: 1\ntamper:\n  rules:\n" + rules))
    assert got.payload["justification"]["decided_by"] == "R1c"
    refused = got.payload["policy"]["tamper"]["refused"]
    assert len(refused) == 4 and {r["code"] for r in refused} == {"needs_allow_disable"}
    assert got.payload["policy"]["tamper"]["acknowledgements"] == []


def test_acknowledged_disable_is_recorded_in_the_verdict(stage_a, cases) -> None:
    rules = "".join(
        f"    {r}:\n      enabled: false\n      allow_disable: 'Security signed off on this, SEC-99'\n"
        for r in ("T001", "T002", "T004", "T005")
    )
    got = score(stage_a[F04], cases[F04], repo_config(policy="version: 1\ntamper:\n  rules:\n" + rules))
    assert got.payload["justification"]["decided_by"] != "R1c"
    tamper = got.payload["policy"]["tamper"]
    assert len(tamper["acknowledgements"]) == 4 and len(tamper["disabled"]) == 4
    assert all(a["reason"] == "Security signed off on this, SEC-99" for a in tamper["acknowledgements"])
    assert got.payload["justification"]["policy"]["tamper"]["acknowledgements"] == tamper["acknowledgements"]


def test_tamper_threshold_can_make_medium_findings_fail(stage_a, cases) -> None:
    text = "version: 1\ntamper:\n  rules:\n    T002: critical\n    T001: low\n"
    got = score(stage_a[F04], cases[F04], repo_config(policy=text))
    sev = {t["rule_id"]: t["severity"] for t in got.payload["tamper_findings"]}
    assert sev["T002"] == "critical" and sev["T001"] == "high"  # lowering a high finding was refused
    assert got.payload["policy"]["tamper"]["refused"][0]["rule"] == "T001"


# ------------------------------------------------------------------- waivers


def test_waived_findings_are_shown_not_hidden(stage_a, cases) -> None:
    fids = sorted(t.finding_id for t in stage_a[F04].tamper)
    got = score(stage_a[F04], cases[F04], repo_config(waivers=waiver_text(fids)))
    assert got.payload["justification"]["decided_by"] != "R1c"
    findings = got.payload["tamper_findings"]
    assert len(findings) == 4 and all(f["waived"] for f in findings)
    assert {f["waiver"]["owner"] for f in findings} == {"alice"}
    assert all(f["waiver"]["reason"] == REASON for f in findings)
    assert got.payload["summary"]["tamper_waived"] == 4
    assert got.payload["summary"]["tamper"] == {"critical": 0, "high": 0, "medium": 0, "low": 0}
    # the audit record: which waivers applied, to what
    audit = got.payload["waivers"]
    assert [a["id"] for a in audit["applied"]] == ["W-1", "W-2", "W-3", "W-4"]
    assert sorted(f for a in audit["applied"] for f in a["finding_ids"]) == fids
    assert audit["evaluated_on"] == "2026-11-02" and audit["audit_digest"].startswith("sha256:")
    assert audit["source"]["path"] == ".radius/waivers.yml" and audit["source"]["ref"] == BASE_REF
    # and it is part of the stored bundle
    assert got.bundle["verdict"]["waivers"] == audit and len(got.bundle["verdict"]["tamper_waived"]) == 4


def test_the_renderer_marks_waived_findings_and_lists_the_audit(stage_a, cases) -> None:
    fids = sorted(t.finding_id for t in stage_a[F04].tamper)
    got = score(stage_a[F04], cases[F04], repo_config(waivers=waiver_text(fids, owner="'@acme/qa'")))
    body = md.render_comment(VerdictV2View.from_payload(got.payload))
    assert body.count("**WAIVED**") == 4
    assert "alice" not in body and "acme" in body and "SEC-42" in body
    assert "Waivers (4 applied)" in body and "expires 2026-12-01" in body


def test_hostile_waiver_text_is_escaped(stage_a, cases) -> None:
    fid = stage_a[F04].tamper[0].finding_id
    evil = "see <script>alert(1)</script> @everyone [x](http://evil.test) `tick`"
    got = score(stage_a[F04], cases[F04], repo_config(waivers=waiver_text([fid], reason=evil)))
    body = md.render_comment(VerdictV2View.from_payload(got.payload))
    assert "<script>" not in body and "&lt;script&gt;" in body
    assert "](http://evil.test)" not in body
    assert "`@everyone`" in body and " @everyone" not in body  # mention only inside a code span


def test_expired_waiver_is_ignored_and_reported(stage_a, cases) -> None:
    fids = [t.finding_id for t in stage_a[F04].tamper]
    text = waiver_text(fids, created="2026-09-01", expires="2026-10-15")
    got = score(stage_a[F04], cases[F04], repo_config(waivers=text))
    assert got.payload["justification"]["decided_by"] == "R1c"
    audit = got.payload["waivers"]
    assert audit["applied"] == [] and {i["code"] for i in audit["ignored"]} == {"expired"}
    body = md.render_comment(VerdictV2View.from_payload(got.payload))
    assert "Not applied" in body and "expired" in body


def test_a_waiver_expires_by_the_scoring_date(stage_a, cases) -> None:
    fids = [t.finding_id for t in stage_a[F04].tamper]
    cfg = repo_config(waivers=waiver_text(fids, expires="2026-11-02"))
    on_day = score(stage_a[F04], cases[F04], cfg, clock=datetime(2026, 11, 2, 23, tzinfo=UTC))
    next_day = score(stage_a[F04], cases[F04], cfg, clock=datetime(2026, 11, 3, 1, tzinfo=UTC))
    assert on_day.payload["justification"]["decided_by"] != "R1c"
    assert next_day.payload["justification"]["decided_by"] == "R1c"
    assert on_day.result.verdict.inputs_digest != next_day.result.verdict.inputs_digest


def test_recomputing_on_the_same_day_is_idempotent(stage_a, cases) -> None:
    fids = [t.finding_id for t in stage_a[F04].tamper]
    cfg = repo_config(waivers=waiver_text(fids))
    a = score(stage_a[F04], cases[F04], cfg, clock=datetime(2026, 11, 2, 1, tzinfo=UTC))
    b = score(stage_a[F04], cases[F04], cfg, clock=datetime(2026, 11, 2, 22, tzinfo=UTC))
    assert a.result.verdict.inputs_digest == b.result.verdict.inputs_digest
    assert a.payload["waivers"]["audit_digest"] == b.payload["waivers"]["audit_digest"]


def test_rule_waiver_with_path_scope(stage_a, cases) -> None:
    text = (
        "version: 1\nwaivers:\n  - id: R-1\n    rule: T002\n    paths: [tests/**]\n"
        f"    reason: \"{REASON}\"\n    owner: alice\n    created: 2026-10-30\n    expires: 2026-12-01\n"
    )
    got = score(stage_a[F04], cases[F04], repo_config(waivers=text))
    waived = [f for f in got.payload["tamper_findings"] if f.get("waived")]
    assert [f["rule_id"] for f in waived] == ["T002"]
    assert got.payload["justification"]["decided_by"] == "R1c"  # the other three remain


def test_criterion_waiver_excludes_the_criterion_with_a_visible_reason(stage_a, cases) -> None:
    text = (
        "version: 1\nwaivers:\n  - id: C-1\n    criterion: C2\n"
        f"    reason: \"{REASON}\"\n    owner: alice\n    created: 2026-10-30\n    expires: 2026-12-01\n"
    )
    got = score(stage_a[F01], cases[F01], repo_config(waivers=text))
    c2 = next(c for c in got.payload["criteria"] if c["criterion_id"] == "C2")
    assert c2["state"] == "excluded"
    assert c2["reasons"][0]["code"] == "waived" and "alice" in c2["reasons"][0]["detail"]
    assert got.payload["waivers"]["applied"][0]["criterion_id"] == "C2"


def test_a_contradicted_criterion_cannot_be_waived_and_ci_failures_stay_failures(stage_a, cases) -> None:
    waivers = "version: 1\nwaivers:\n" + "".join(
        f"  - id: C-{c}\n    criterion: {c}\n    reason: \"{REASON}\"\n    owner: alice\n"
        "    created: 2026-10-30\n    expires: 2026-12-01\n"
        for c in ("C1", "C2")
    )
    got = score(stage_a[F01], failing(cases[F01]), repo_config(waivers=waivers))
    states = {c["criterion_id"]: c["state"] for c in got.payload["criteria"]}
    assert states["C1"] == "contradicted" and states["C2"] == "excluded"
    assert got.payload["verdict"] == "failed" and got.payload["justification"]["decided_by"] == "R1a"
    ignored = got.payload["waivers"]["ignored"]
    assert [(i["id"], i["code"]) for i in ignored] == [("C-C1", "not_waivable_contradicted")]


def test_waivers_in_the_head_only_have_no_effect(stage_a, cases) -> None:
    # Stage A reads waivers.yml from the base only: a PR that adds one finds it absent.
    got = score(stage_a[F04], cases[F04], repo_config(waivers=None))
    assert got.payload["justification"]["decided_by"] == "R1c" and "waivers" not in got.payload


def test_invalid_waivers_file_ignores_every_waiver(stage_a, cases) -> None:
    got = score(stage_a[F04], cases[F04], repo_config(waivers="version: 1\nwaivers: [\n"))
    assert got.payload["justification"]["decided_by"] == "R1c"
    assert got.payload["waivers"]["status"] == "invalid" and got.payload["waivers"]["errors"]


# ------------------------------------------------------------ renderer / API


@pytest.mark.parametrize(
    ("mode", "verdict", "pending", "expected"),
    [
        # DEC-030: without a blocking policy nothing is green; failure needs hard evidence (R1*).
        (None, "verified", False, "neutral"),
        (None, "failed", False, "failure"),
        (None, "insufficient_evidence", False, "neutral"),
        (None, "needs_review", False, "neutral"),
        (None, "verified", True, "neutral"),
        ("advisory", "verified", False, "neutral"),
        ("advisory", "failed", False, "neutral"),
        ("advisory", "insufficient_evidence", False, "neutral"),
        ("advisory", "needs_review", False, "neutral"),
        ("blocking", "verified", False, "success"),
        ("blocking", "failed", False, "failure"),
        ("blocking", "insufficient_evidence", False, "failure"),
        ("blocking", "needs_review", False, "failure"),
        ("blocking", "insufficient_evidence", True, "failure"),
    ],
)
def test_check_run_conclusion_follows_the_policy_mode(stage_a, cases, mode, verdict, pending, expected) -> None:
    payload = score(stage_a[F01], cases[F01]).payload
    payload = {**payload, "verdict": verdict, "pending": pending}
    if verdict == "failed":
        payload["justification"] = {**payload["justification"], "decided_by": "R1b"}
    if mode:
        payload["policy"] = {"present": True, "status": "ok", "mode": mode}
    view = VerdictV2View.from_payload(payload)
    assert md.check_conclusion(view) == expected
    # the operator knob only turns a non-blocking `verified` green; blocking is unaffected
    strict = md.check_conclusion(view, mode="strict")
    assert strict == ("success" if verdict == "verified" and not pending else expected)


def test_mode_changes_only_the_conclusion_never_the_verdict(stage_a, cases) -> None:
    results = {
        mode: score(stage_a[F02], cases[F02], repo_config(policy=f"version: 1\nmode: {mode}\n"))
        for mode in ("advisory", "blocking")
    }
    assert {r.payload["verdict"] for r in results.values()} == {"insufficient_evidence"}
    assert {r.result.verdict.inputs_digest for r in results.values()} != set()
    conclusions = {m: md.check_conclusion(VerdictV2View.from_payload(r.payload)) for m, r in results.items()}
    assert conclusions == {"advisory": "neutral", "blocking": "failure"}


def test_policy_summary_and_section_render(stage_a, cases) -> None:
    text = "version: 1\nmode: blocking\nthresholds:\n  tau_support: 0.9\n"
    got = score(stage_a[F01], cases[F01], repo_config(policy=text))
    body = md.render_comment(VerdictV2View.from_payload(got.payload))
    assert "**Policy:** blocking, from the base branch" in body
    assert "`thresholds.tau_support`" in body and "policy line 4" in body
    check = md.render_check_run(VerdictV2View.from_payload(got.payload))
    assert check.conclusion == "failure"


def test_api_payload_carries_policy_and_waivers(stage_a, cases) -> None:
    fids = sorted(t.finding_id for t in stage_a[F04].tamper)
    got = score(
        stage_a[F04],
        cases[F04],
        repo_config(policy="version: 1\nmode: blocking\n", waivers=waiver_text(fids[:2])),
    )
    verdict = got.bundle["verdict"]
    stored = StoredVerdict(
        row_id="r", organization_id="o", analysis_id=verdict["analysis_id"], head_sha=verdict["head_sha"],
        revision=1, inputs_digest=got.bundle["inputs_digest"], status="ok", mode="shadow",
        verdict=verdict["verdict"], pending=False, reason_code=None, algo_version=verdict["algo_version"],
        profile=verdict["profile"], config_digest=verdict["config_digest"], bundle=got.bundle,
        justification=verdict["justification"], error_detail=None, fallback=None, published_at=None,
        published_digest=None, publish_error=None, computed_at=TODAY,
    )
    api = build_payload(stored)
    assert api["policy"]["mode"] == "blocking"
    assert len([f for f in api["tamper_findings"] if f.get("waived")]) == 2
    assert api["summary"]["tamper_waived"] == 2
    assert api["waivers"]["applied"][0]["id"] == "W-1"
    assert api["policy"] == got.payload["policy"] and api["waivers"] == got.payload["waivers"]


# --------------------------------------------------- security property tests


def _random_policy(rng: random.Random) -> str:
    lines = ["version: 1", f"mode: {rng.choice(['advisory', 'blocking'])}", "thresholds:"]
    lines += [
        f"  tau_support: {round(rng.uniform(0.3, 0.9), 2)}",
        f"  uim_max: {round(rng.uniform(0.0, 0.4), 2)}",
        f"  intent_coverage_min: {round(rng.uniform(0.3, 1.0), 2)}",
        f"  link_review_min: {round(rng.uniform(0.3, 0.9), 2)}",
        f"  cap_static: {round(rng.uniform(0.3, 0.8), 2)}",
        "tamper:",
        f"  fail_on_at_least: {rng.choice(['medium', 'high'])}",
        "  rules:",
        "    T001:\n      enabled: false\n      allow_disable: 'acknowledged by the security owner'",
        "    T002: info",
        "exclude:",
        "  paths: ['src/**', 'tests/**']",
    ]
    if rng.random() < 0.5:
        lines += ["require:", "  - paths: ['src/**']", "    min_state: weak"]
    return "\n".join(lines) + "\n"


def _random_waivers(rng: random.Random, finding_ids: list[str]) -> str:
    out = ["version: 1", "waivers:"]
    targets = [("criterion", "C1"), ("criterion", "C2"), ("rule", "T001"), ("rule", "T002")]
    targets += [("finding", f) for f in finding_ids]
    for i, (kind, target) in enumerate(rng.sample(targets, rng.randint(2, len(targets)))):
        out += [f"  - id: P-{i}", f"    {kind}: {target}"]
        if kind == "rule":
            out.append("    paths: ['**/*.py']")
        out += [f"    reason: \"{REASON}\"", "    owner: alice", "    created: 2026-10-30", "    expires: 2026-12-01"]
    return "\n".join(out) + "\n"


@pytest.mark.parametrize("seed", range(40))
def test_no_policy_or_waiver_can_turn_a_ci_failure_into_a_pass(stage_a, cases, seed) -> None:
    rng = random.Random(seed)
    fids = [t.finding_id for t in stage_a[F01].tamper]
    cfg = repo_config(policy=_random_policy(rng), waivers=_random_waivers(rng, fids))
    got = score(stage_a[F01], failing(cases[F01]), cfg)
    assert got.payload["verdict"] == "failed"
    assert got.payload["justification"]["decided_by"] in {"R1a", "R1b"}
    states = {c["criterion_id"]: c["state"] for c in got.payload["criteria"]}
    assert states["C1"] == "contradicted"


@pytest.mark.parametrize("seed", range(20))
def test_random_policies_never_turn_a_tampered_pr_green_without_waiver(stage_a, cases, seed) -> None:
    rng = random.Random(100 + seed)
    # T001 may be disabled WITH an acknowledgement, but T004/T005/T002 stay high: still failed
    # unless every one of them is lowered/disabled, which the random policy never does.
    cfg = repo_config(policy=_random_policy(rng))
    got = score(stage_a[F04], cases[F04], cfg)
    assert got.payload["verdict"] == "failed"
    assert got.payload["justification"]["decided_by"] == "R1c"


@pytest.mark.parametrize("seed", range(20))
def test_random_head_policy_never_loosens_the_base_result(stage_a, cases, seed) -> None:
    rng = random.Random(200 + seed)
    base = "version: 1\nhead_policy: tighten_only\n" + _random_policy(rng).split("\n", 1)[1]
    head = _random_policy(rng)
    for name in (F01, F04):
        alone = score(stage_a[name], cases[name], repo_config(policy=base))
        both = score(stage_a[name], cases[name], repo_config(policy=base, head=head))
        order = ["verified", "needs_review", "insufficient_evidence", "failed"]
        assert order.index(both.payload["verdict"]) >= order.index(alone.payload["verdict"]), (name, seed)


# ------------------------------------------------------------ collect (git)


def _git(repo: Path, *args: str) -> str:
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.test", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.test", "PATH": __import__("os").environ["PATH"],
           "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""), "HOME": str(repo)}
    out = subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True, check=True)  # noqa: S603, S607
    return out.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path):
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / ".radius").mkdir()
    (tmp_path / ".radius" / "policy.yml").write_text("version: 1\nmode: blocking\nthresholds:\n  uim_max: 0.05\n", encoding="utf-8")
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    base = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "checkout", "-q", "-b", "pr")
    # the PR weakens its own policy and adds a waiver for itself
    (tmp_path / ".radius" / "policy.yml").write_text("version: 1\nmode: advisory\nthresholds:\n  uim_max: 0.4\n", encoding="utf-8")
    (tmp_path / ".radius" / "waivers.yml").write_text(waiver_text(["tf_0123456789abcdef"]), encoding="utf-8")
    (tmp_path / "a.py").write_text("x = 2\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "head")
    head = _git(tmp_path, "rev-parse", "HEAD")
    # a second base that opted in to tighten-only head policies
    _git(tmp_path, "checkout", "-q", "main")
    (tmp_path / ".radius" / "policy.yml").write_text("version: 1" + chr(10) + "head_policy: tighten_only" + chr(10), encoding="utf-8")
    _git(tmp_path, "commit", "-q", "-am", "opt in")
    opt_in = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "checkout", "-q", "pr")
    return SimpleNamespace(path=tmp_path, base=base, head=head, opt_in=opt_in)


def test_collect_reads_policy_and_waivers_from_the_base_commit_not_the_pr_head(repo) -> None:
    path, base, head = repo.path, repo.base, repo.head
    cfg = default_repo_config(SimpleNamespace(repository_path=path, base_ref=base, head_ref=head))
    assert "mode: blocking" in cfg["policy"]["text"] and "uim_max: 0.05" in cfg["policy"]["text"]
    assert cfg["waivers"]["status"] == "absent"  # the PR's own waiver is invisible
    assert "head_policy" not in cfg and cfg["base_ref"] == base
    assert cfg["policy"]["sha256"] == hashlib.sha256(cfg["policy"]["text"].encode()).hexdigest()


def test_collect_reads_the_head_copy_only_after_the_base_opt_in(repo) -> None:
    cfg = default_repo_config(
        SimpleNamespace(repository_path=repo.path, base_ref=repo.opt_in, head_ref=repo.head)
    )
    assert cfg["head_policy"]["status"] == "ok" and "advisory" in cfg["head_policy"]["text"]


def test_collect_with_an_unresolvable_base_is_unreadable_not_absent(repo) -> None:
    cfg = default_repo_config(SimpleNamespace(repository_path=repo.path, base_ref="f" * 40, head_ref=repo.head))
    assert cfg["policy"]["status"] == "unreadable" and cfg["waivers"]["status"] == "unreadable"


@pytest.mark.parametrize("command", [SimpleNamespace(), SimpleNamespace(repository_path=None, base_ref="x"), SimpleNamespace(repository_path="/tmp", base_ref=None)])
def test_collect_without_a_base_ref_reports_no_base(command) -> None:
    cfg = default_repo_config(command)
    assert cfg["policy"]["status"] == "no_base" and cfg["waivers"]["status"] == "no_base"


def test_collect_end_to_end_applies_the_base_policy_and_ignores_the_head(repo, stage_a, cases) -> None:
    cfg = default_repo_config(SimpleNamespace(repository_path=repo.path, base_ref=repo.base, head_ref=repo.head))
    got = score(stage_a[F02], cases[F02], cfg)
    assert got.payload["policy"]["mode"] == "blocking"
    assert got.payload["justification"]["thresholds"]["uim_max"] == 0.05  # base, not the PR's 0.4
    assert "waivers" not in got.payload
    assert UUID(got.payload["analysis_id"])
