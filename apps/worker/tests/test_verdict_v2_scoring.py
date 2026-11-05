"""Stage B pipeline (VS-03/VS-06 composition) on the VS-01 gold bundles of the 8 fixtures."""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import random
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from radius_evidence.domain.config import VerdictV2Config
from radius_evidence.domain.inputs import StageBInput, TamperFindingInput
from radius_github.verdict_v2.markdown import render_check_run, render_comment
from radius_github.verdict_v2.view import VerdictV2View
from radius_shared.verdict_v2_flag import VerdictV2Mode
from radius_worker.verdict_v2 import scoring
from radius_worker.verdict_v2.sources import NoOutcomes, OutcomeFacts

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "docs" / "research" / "design").is_dir())
DESIGN = ROOT / "docs" / "research" / "design"
EXPECT = json.loads((DESIGN / "verdict_v2.fixture_expectations.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((DESIGN / "verdict_v2.schema.json").read_text(encoding="utf-8"))
TOL = EXPECT["tolerance"]
BY_NAME = {f["fixture"]: f for f in EXPECT["fixtures"]}
FIXTURES = sorted(BY_NAME)
CLOCK = lambda: datetime(2026, 11, 2, tzinfo=UTC)  # noqa: E731


def _load_loader():
    spec = importlib.util.spec_from_file_location(
        "vs01_loader", ROOT / "benchmarks" / "fixtures" / "verdict_v2" / "loader.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


LOADER = _load_loader()


def pipeline() -> scoring.ScoringPipeline:
    return scoring.ScoringPipeline(mode="shadow", clock=CLOCK)


# ------------------------------------------------------------------ gold mode


@pytest.mark.parametrize("fixture", FIXTURES)
def test_gold_verdict_states_and_support_match_the_design(fixture: str) -> None:
    exp = BY_NAME[fixture]
    scored = pipeline().score_full(LOADER.stage_b(fixture, mode="gold"))
    payload = scored.payload
    assert payload["verdict"] == exp["expected_verdict"]
    assert payload["justification"]["decided_by"] == exp["decided_by"].split(" ")[0]
    got = {c["criterion_id"]: c for c in payload["criteria"]}
    for cid, state in exp["gold"]["states"].items():
        assert got[cid]["state"] == state, (fixture, cid)
        if state != "excluded":
            assert got[cid]["S"] == pytest.approx(exp["gold"]["S"][cid], abs=TOL), (fixture, cid)
    assert payload["summary"]["uim"] == pytest.approx(exp["gold"]["uim"], abs=TOL)
    assert payload["summary"]["intent_coverage"] == pytest.approx(exp["intent_coverage"], abs=TOL)


def test_gold_06_without_registry_degrades_to_needs_review() -> None:
    bundle = LOADER.load_bundle("06_hallucinated_dependency")
    stage_b = LOADER.stage_b("06_hallucinated_dependency", mode="gold")
    variant = bundle["tamper_variants"]["no_registry"]["findings"]
    sa = dataclasses.replace(
        stage_b.stage_a,
        tamper=tuple(
            dataclasses.replace(TamperFindingInput.from_dict(f), severity="medium")
            for f in variant
        ),
    )
    payload = pipeline().score_full(dataclasses.replace(stage_b, stage_a=sa)).payload
    assert payload["verdict"] == "needs_review"
    assert payload["justification"]["decided_by"] == "R3a"


def test_pending_without_ci_results() -> None:
    stage_b = LOADER.stage_b("01_correct_strong_tests", mode="gold")
    pending = dataclasses.replace(stage_b, cases=(), uploads=0, results_received=False)
    payload = pipeline().score_full(pending).payload
    assert payload["verdict"] == "insufficient_evidence" and payload["pending"] is True
    assert payload["justification"]["decided_by"] == "R2p"
    assert all("pending_results" in c["flags"] for c in payload["criteria"])


def test_failing_ci_case_fails_the_verdict() -> None:
    stage_b = LOADER.stage_b("01_correct_strong_tests", mode="gold")
    first = stage_b.cases[0]
    failed = dataclasses.replace(first, outcome=type(first.outcome)("failed"))
    sb = dataclasses.replace(stage_b, cases=(failed, *stage_b.cases[1:]))
    payload = pipeline().score_full(sb).payload
    assert payload["verdict"] == "failed"
    assert any(c["state"] == "contradicted" for c in payload["criteria"])


# ------------------------------------------------------------------ properties


@pytest.mark.parametrize("fixture", ["01_correct_strong_tests", "08_multi_criterion_partial_evidence"])
def test_deterministic_and_order_independent(fixture: str) -> None:
    sb = LOADER.stage_b(fixture, mode="gold")
    first = pipeline().score_full(sb).bundle
    again = pipeline().score_full(sb).bundle
    assert json.dumps(first, sort_keys=True) == json.dumps(again, sort_keys=True)

    rng = random.Random(7)
    sa = sb.stage_a
    shuffled_a = dataclasses.replace(
        sa,
        **{
            name: tuple(rng.sample(list(getattr(sa, name)), len(getattr(sa, name))))
            for name in ("criteria", "symbols", "criterion_symbol", "symbol_test",
                         "criterion_test", "assertions")
        },
    )
    cases = tuple(rng.sample(list(sb.cases), len(sb.cases)))
    other = pipeline().score_full(dataclasses.replace(sb, stage_a=shuffled_a, cases=cases))
    base = pipeline().score_full(sb)

    def view(scored):
        return {
            c["criterion_id"]: (c["state"], c["S"]) for c in scored.payload["criteria"]
        }

    assert other.payload["verdict"] == base.payload["verdict"]
    assert view(other) == view(base)
    assert other.payload["summary"] == base.payload["summary"]


# ------------------------------------------------------------------ contracts

_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def validate(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Stdlib subset of JSON Schema (same subset as the VD-03 tests)."""

    errors: list[str] = []
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: const")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in enum")
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        ok = False
        for n in names:
            if n == "number":
                ok |= isinstance(value, (int, float)) and not isinstance(value, bool)
            elif n == "integer":
                ok |= isinstance(value, int) and not isinstance(value, bool)
            else:
                ok |= isinstance(value, _TYPES[n])
        if not ok:
            return [*errors, f"{path}: bad type {type(value).__name__}"]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above maximum")
    if isinstance(value, str) and "pattern" in schema and not re.search(schema["pattern"], value):
        errors.append(f"{path}: pattern")
    if isinstance(value, list) and "items" in schema:
        for i, v in enumerate(value):
            errors += validate(v, schema["items"], f"{path}[{i}]")
    if isinstance(value, dict):
        errors += [f"{path}: missing {k!r}" for k in schema.get("required", []) if k not in value]
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for k, v in value.items():
            if k in props:
                errors += validate(v, props[k], f"{path}.{k}")
            elif isinstance(extra, dict):
                errors += validate(v, extra, f"{path}.{k}")
    return errors


@pytest.mark.parametrize("fixture", FIXTURES)
def test_payload_conforms_to_the_schema_and_renders(fixture: str) -> None:
    payload = pipeline().score_full(LOADER.stage_b(fixture, mode="gold")).payload
    assert validate(payload, SCHEMA) == []
    view = VerdictV2View.from_payload(payload)
    body = render_comment(view)
    assert body.startswith("<!-- radius-confidence-report -->")
    assert len(body) < 60_000
    assert render_check_run(view).conclusion in {"success", "failure", "neutral"}


@pytest.mark.parametrize("fixture", FIXTURES)
def test_bundle_follows_the_store_contract(fixture: str) -> None:
    bundle = pipeline().score_full(LOADER.stage_b(fixture, mode="gold")).bundle
    assert bundle["schema"] == "verdict-v2-bundle-1"
    assert re.fullmatch(r"[0-9a-f]{40}", bundle["head_sha"])
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", bundle["inputs_digest"])
    assert bundle["status"] == "ok"
    assert bundle["verdict"]["verdict"] == BY_NAME[fixture]["expected_verdict"]
    assert bundle["stage_a"]["analysis_id"] == bundle["analysis_id"]
    # Stage B can be re-run from the stored Stage A alone (design 5.3)
    from radius_evidence.domain.inputs import StageAInput

    again = StageAInput.from_dict(json.loads(json.dumps(bundle["stage_a"])))
    assert again == LOADER.stage_a(fixture, mode="gold")
    json.dumps(bundle)  # serialisable


def _stored_from(scored, sb, bundle):
    from radius_shared.verdict_v2_payload import StoredVerdict

    return StoredVerdict(
        row_id="r", organization_id="o", analysis_id=sb.stage_a.analysis_id,
        head_sha=sb.stage_a.head_sha, revision=scored.payload["revision"],
        inputs_digest=bundle["inputs_digest"], status="ok", mode="shadow",
        verdict=bundle["verdict"]["verdict"], pending=bundle["verdict"]["pending"],
        reason_code=bundle["reason_code"], algo_version=bundle["algo_version"],
        profile=bundle["profile"], config_digest=bundle["config_digest"],
        bundle=bundle, justification=bundle["verdict"]["justification"],
        error_detail=None, fallback=None, published_at=None, published_digest=None,
        publish_error=None, computed_at=CLOCK(),
    )


@pytest.mark.parametrize("fixture", FIXTURES)
def test_b20_worker_payload_equals_what_the_api_serves_from_the_stored_bundle(fixture: str) -> None:
    """One builder: the payload computed by the worker and the payload the API serves from
    the stored row (after the JSON round trip of the database) must be identical."""

    from radius_shared.verdict_v2_payload import build_payload as served

    sb = LOADER.stage_b(fixture, mode="gold")
    scored = pipeline().score_full(sb)
    stored_bundle = json.loads(json.dumps(scored.bundle))  # what the SQL row holds

    api = served(_stored_from(scored, sb, stored_bundle))

    assert api == json.loads(json.dumps(scored.payload)), fixture
    assert json.dumps(api, sort_keys=True) == json.dumps(scored.payload, sort_keys=True)


def test_b20_there_is_no_second_payload_builder() -> None:
    """``scoring.build_payload`` only wraps the shared builder (guard against re-forking)."""

    import inspect

    src = inspect.getsource(scoring.build_payload)
    assert "shared_build_payload(" in src
    assert '"criteria"' not in src and '"summary"' not in src and "presentation(" not in src


def test_b20_old_stored_bundles_without_the_newer_keys_still_read() -> None:
    from radius_shared.verdict_v2_payload import build_payload as served

    sb = LOADER.stage_b("08_multi_criterion_partial_evidence", mode="gold")
    scored = pipeline().score_full(sb)
    old = json.loads(json.dumps(scored.bundle))
    for key in ("degraded", "suggested_tests", "mutation", "next_actions"):
        old.pop(key, None)
    for crit in old["verdict"]["criteria"]:
        crit.pop("confirmed_by", None)
        for reason in crit.get("reasons", []):
            reason.pop("refs", None)

    payload = served(_stored_from(scored, sb, old))

    assert payload["verdict"] == scored.payload["verdict"]
    assert payload["next_actions"] == scored.payload["next_actions"]  # derived when absent
    assert "suggested_tests" not in payload and "mutation" not in payload
    assert all("confirmed_by" not in c for c in payload["criteria"])


def test_b20_suggestions_are_sanitised_by_the_shared_builder_in_the_worker_payload() -> None:
    sb = LOADER.stage_b("08_multi_criterion_partial_evidence", mode="gold")
    cid = sb.stage_a.criteria[0].criterion_id

    def suggester(result, stage_b):  # noqa: ARG001
        class Report:
            items = ({"criterion_id": cid, "test_code": "def test_x():\n    assert 1\n",
                      "executed": True, "evidence": True, "provenance": "x"},)
            rejected = ()

        return Report()

    scored = scoring.ScoringPipeline(mode="shadow", clock=CLOCK, suggester=suggester).score_full(sb)

    (item,) = scored.payload["suggested_tests"]
    assert (item["executed"], item["evidence"], item["provenance"]) == (False, False, "llm_proposed")


def test_bundle_cap_drops_optional_parts_first() -> None:
    sb = LOADER.stage_b("08_multi_criterion_partial_evidence", mode="gold")
    cfg = VerdictV2Config()
    result = scoring.compute_pipeline(sb, config=cfg)
    big = scoring.build_bundle(result, sb, max_bytes=10**9)
    assert big["truncated"] is False and big["evidence_items"]
    small = scoring.build_bundle(result, sb, max_bytes=1000)
    assert small["truncated"] is True and small["evidence_items"] == []
    assert small["stage_b"]["cases"] == []
    assert small["verdict"]["verdict"] == big["verdict"]["verdict"]


def test_error_bundle_is_stable_and_code_only() -> None:
    sha = "a" * 40
    one = scoring.build_error_bundle(analysis_id="x", head_sha=sha, code="symbol_changes_failed")
    two = scoring.build_error_bundle(analysis_id="x", head_sha=sha, code="symbol_changes_failed")
    assert one == two and one["status"] == "error" and one["fallback"] == "v1"
    assert one["error_detail"] is None and one["verdict"] is None
    assert scoring.build_error_bundle(analysis_id="x", head_sha=None, code="c") is None


# ------------------------------------------------------------------ best-effort hook


class FakeCollector:
    def __init__(self, stage_a=None, exc: Exception | None = None) -> None:
        self.stage_a, self.exc, self.calls = stage_a, exc, 0

    def collect(self, analysis_id, command):  # noqa: ARG002
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.stage_a


class FakeStore:
    def __init__(self, *, fail: bool = False) -> None:
        self.saved: list[dict[str, Any]] = []
        self.fail = fail

    def save(self, organization_id, analysis_id, bundle):  # noqa: ARG002
        if self.fail:
            raise RuntimeError("secret " + "ghs_" + "x" * 20)
        self.saved.append(bundle)
        return True


class Outcomes:
    def __init__(self, facts: OutcomeFacts) -> None:
        self.facts = facts

    def load(self, analysis_id, stage_a):  # noqa: ARG002
        return self.facts


def _facts(fixture: str) -> OutcomeFacts:
    sb = LOADER.stage_b(fixture, mode="gold")
    return OutcomeFacts(cases=sb.cases, uploads=sb.uploads)


def test_flag_off_touches_nothing() -> None:
    collector, store = FakeCollector(), FakeStore()
    report = scoring.run_verdict_v2_best_effort(
        mode=VerdictV2Mode.OFF, analysis_id=uuid4(), command=object(),
        collector=collector, outcomes=NoOutcomes(), store=store, organization_id=uuid4(),
    )
    assert (report.status, report.reason_code) == ("skipped", "flag_off")
    assert collector.calls == 0 and store.saved == []


def test_best_effort_ok_persists_bundle() -> None:
    fx = "01_correct_strong_tests"
    store = FakeStore()
    report = scoring.run_verdict_v2_best_effort(
        mode=VerdictV2Mode.SHADOW, analysis_id=uuid4(), command=object(),
        collector=FakeCollector(LOADER.stage_a(fx, mode="gold")),
        outcomes=Outcomes(_facts(fx)), store=store, organization_id=uuid4(), clock=CLOCK,
    )
    assert report.status == "ok" and report.verdict == "verified" and report.persisted
    assert store.saved[0]["verdict"]["verdict"] == "verified"
    assert report.payload["mode"] == "shadow"


def test_best_effort_collect_failure_returns_error_and_stores_error_bundle() -> None:
    from radius_worker.verdict_v2.collect import StageAError

    store = FakeStore()
    report = scoring.run_verdict_v2_best_effort(
        mode=VerdictV2Mode.ON, analysis_id=uuid4(), command=object(),
        collector=FakeCollector(exc=StageAError("tamper_failed")),
        outcomes=NoOutcomes(), store=store, organization_id=uuid4(),
    )
    assert (report.status, report.reason_code) == ("error", "tamper_failed")
    assert report.verdict is None and report.payload is None
    assert store.saved == []  # head sha unknown: nothing storable, v1 stays


def test_best_effort_scoring_failure_stores_error_bundle_with_head() -> None:
    fx = "01_correct_strong_tests"
    sa = LOADER.stage_a(fx, mode="gold")
    bad_sa = dataclasses.replace(sa, head_sha="a" * 40)
    store = FakeStore()
    report = scoring.run_verdict_v2_best_effort(
        mode=VerdictV2Mode.ON, analysis_id=uuid4(), command=object(),
        collector=FakeCollector(bad_sa),
        outcomes=Outcomes(OutcomeFacts(cases=("not a case",), uploads=1)),  # type: ignore[arg-type]
        store=store, organization_id=uuid4(),
    )
    assert report.status == "error"
    assert store.saved and store.saved[0]["status"] == "error"
    assert store.saved[0]["fallback"] == "v1"
    assert "ghs_" not in json.dumps(store.saved[0])


def test_best_effort_store_failure_is_reported_without_message() -> None:
    fx = "01_correct_strong_tests"
    report = scoring.run_verdict_v2_best_effort(
        mode=VerdictV2Mode.SHADOW, analysis_id=uuid4(), command=object(),
        collector=FakeCollector(LOADER.stage_a(fx, mode="gold")),
        outcomes=Outcomes(_facts(fx)), store=FakeStore(fail=True), organization_id=uuid4(),
    )
    assert (report.status, report.reason_code, report.persisted) == ("error", "store_failed", False)


def test_for_analysis_with_flag_off_is_a_noop() -> None:
    settings = type("S", (), {"verdict_v2_mode": VerdictV2Mode.OFF})()
    report = scoring.run_verdict_v2_for_analysis(
        session_factory=lambda: (_ for _ in ()).throw(AssertionError("must not open a session")),
        analysis_id=uuid4(), command=object(), settings=settings,
    )
    assert report.reason_code == "flag_off"


def test_for_analysis_swallows_start_failures() -> None:
    settings = type("S", (), {"verdict_v2_mode": VerdictV2Mode.ON})()

    def boom():
        raise RuntimeError("db down")

    report = scoring.run_verdict_v2_for_analysis(
        session_factory=boom, analysis_id=uuid4(), command=object(), settings=settings
    )
    assert report.status == "error"


def test_stage_b_input_helper_counts_failures() -> None:
    sb = LOADER.stage_b("01_correct_strong_tests", mode="gold")
    built = scoring.build_stage_b(sb.stage_a, cases=sb.cases, uploads=2)
    assert isinstance(built, StageBInput)
    assert built.results_received and built.ci_failed_cases == 0
    assert not scoring.build_stage_b(sb.stage_a).results_received
