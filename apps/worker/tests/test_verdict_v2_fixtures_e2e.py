"""Verdict v2 end to end on the 8 F-14 fixtures with the real Stage A producers (VS-05/06).

Gold mode (the author's hints, no relevance) is normative and must reproduce the
design numbers. Auto mode (VS-04 relevance, no hints) depends on linking quality:
the PR verdict is asserted except for the documented, reviewed differences.
Also covers the runner hook: flag off has no effect, flag on never fails the job.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
import radius_worker.runner as worker_runner
from radius_analysis.infrastructure import SqlAlchemyAnalysisJobQueue
from radius_shared.database import enums as db_enums
from radius_shared.database.base import Base
from radius_shared.database.models import (
    Analysis,
    AnalysisJob,
    Organization,
    PullRequest,
    Repository,
)
from radius_worker.runner import SqlAlchemyWorkerRuntime
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "docs" / "research" / "design").is_dir())
EXPECT = json.loads(
    (ROOT / "docs" / "research" / "design" / "verdict_v2.fixture_expectations.json").read_text(
        encoding="utf-8"
    )
)
BY_NAME = {f["fixture"]: f for f in EXPECT["fixtures"]}
TOL = EXPECT["tolerance"]
FIXTURES = sorted(BY_NAME)


def _load_script():
    spec = importlib.util.spec_from_file_location("verdict_v2_run", ROOT / "scripts" / "verdict_v2_run.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RUN = _load_script()
DIRS = {p.name: p for p in RUN.fixture_dirs([])}


@pytest.fixture(scope="module")
def gold() -> dict[str, dict]:
    return {n: RUN.run_collect(DIRS[n], "gold", "static") for n in FIXTURES}


@pytest.fixture(scope="module")
def auto() -> dict[str, dict]:
    return {n: RUN.run_collect(DIRS[n], "auto", "static") for n in FIXTURES}


@pytest.mark.parametrize("name", FIXTURES)
def test_gold_mode_reproduces_the_design(gold, name) -> None:
    exp, payload = BY_NAME[name], gold[name]
    assert payload["verdict"] == exp["expected_verdict"]
    assert payload["justification"]["decided_by"] == exp["decided_by"].split(" ")[0]
    states = {c["criterion_id"]: c for c in payload["criteria"]}
    for cid, state in exp["gold"]["states"].items():
        assert states[cid]["state"] == state
        if state != "excluded":
            assert states[cid]["S"] == pytest.approx(exp["gold"]["S"][cid], abs=TOL)
    assert payload["summary"]["uim"] == pytest.approx(exp["gold"]["uim"], abs=TOL)
    assert payload["summary"]["intent_coverage"] == pytest.approx(exp["intent_coverage"], abs=TOL)


#: Reviewed auto-mode differences from verdict_v2.fixture_expectations.json (honest diff).
#: VS-04 relevance credits 01's C1 tests with r_ct 0.1-0.4 (well below the 1.0 of a hint),
#: so the PR stays insufficient_evidence instead of verified. Never the other way round.
KNOWN_AUTO_VERDICT = {"01_correct_strong_tests": "insufficient_evidence"}
RANK = {"failed": 0, "insufficient_evidence": 1, "needs_review": 2, "verified": 3}


@pytest.mark.parametrize("name", FIXTURES)
def test_auto_mode_verdict_is_expected_or_more_cautious(auto, name) -> None:
    want = KNOWN_AUTO_VERDICT.get(name, BY_NAME[name]["expected_verdict"])
    assert auto[name]["verdict"] == want
    # never more optimistic than the design expects (false safety is the costly error)
    assert RANK[auto[name]["verdict"]] <= RANK[BY_NAME[name]["expected_verdict"]]


def test_no_wrong_pr_is_verified_in_any_mode(gold, auto) -> None:
    for name in FIXTURES:
        for payload in (gold[name], auto[name]):
            if payload["verdict"] == "verified":
                assert name == "01_correct_strong_tests"


def test_fixture_06_offline_is_needs_review_and_with_a_registry_failed() -> None:
    """DEC-028: an unverifiable guarded import is medium (R3a needs_review offline);
    a registry that says the package does not exist makes it ``registry_missing`` (R1c)."""

    offline = RUN.run_collect(DIRS["06_hallucinated_dependency"], "gold", "none")
    assert offline["verdict"] == "needs_review"
    assert offline["justification"]["decided_by"] == "R3a"
    assert {(t["check"], t["severity"]) for t in offline["tamper_findings"]} == {
        ("unverified_guarded_import", "medium")
    }
    online = RUN.run_collect(DIRS["06_hallucinated_dependency"], "gold", "static")
    assert online["verdict"] == "failed" and online["justification"]["decided_by"] == "R1c"


def test_stage_a_is_deterministic_on_a_fixture() -> None:
    one = RUN.run_collect(DIRS["08_multi_criterion_partial_evidence"], "auto", "static")
    two = RUN.run_collect(DIRS["08_multi_criterion_partial_evidence"], "auto", "static")
    assert json.dumps(one, sort_keys=True) == json.dumps(two, sort_keys=True)


def test_symbol_ids_agree_between_linkers(gold) -> None:
    """Design 3.4 assumption: LK-02 and LK-03 use the LK-01 symbol id string."""

    for name in FIXTURES:
        stage_a = RUN.collect_stage_a(DIRS[name], "gold", "static")
        symbols = {s.symbol_id for s in stage_a.symbols}
        assert {e.symbol_id for e in stage_a.criterion_symbol} <= symbols
        assert {e.symbol_id for e in stage_a.symbol_test} <= symbols


# ------------------------------------------------------------------ runner hook

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
SHA = "e" * 40


class _NoGitHub:
    def create_installation_token(self, installation_id):
        raise AssertionError("not used")


class _FakeOrchestrator:
    def execute(self, command):
        return None


def _persist(factory) -> UUID:
    with factory() as session:
        org = Organization(name="Acme", github_installation_id=9,
                           github_installation_status="active")
        repo = Repository(
            organization=org, github_repository_id=3, name="r", owner="o",
            default_branch="main", clone_url="https://example.invalid/o/r.git",
            visibility=db_enums.RepositoryVisibility.PRIVATE,
            status=db_enums.RepositoryStatus.CONNECTED)
        pr = PullRequest(repository=repo, github_pr_number=1, title="t", source_branch="f",
                         target_branch="main", author="a",
                         status=db_enums.PullRequestStatus.OPEN, opened_at=NOW)
        analysis = Analysis(repository=repo, pull_request=pr, commit_sha=SHA,
                            status=db_enums.AnalysisStatus.PENDING, started_at=NOW,
                            created_at=NOW)
        session.add_all([org, repo, pr, analysis])
        session.flush()
        SqlAlchemyAnalysisJobQueue(session).enqueue(analysis.id)
        session.commit()
        return analysis.id


def _runtime(monkeypatch, factory, **settings):
    monkeypatch.setattr(worker_runner, "_create_sql_orchestrator", lambda s, c: _FakeOrchestrator())
    monkeypatch.setattr(worker_runner, "load_persisted_analysis_command", lambda **kw: object())
    monkeypatch.setattr(worker_runner, "_github_clone_headers", lambda **kw: ())
    monkeypatch.setattr(worker_runner, "_github_installation_id", lambda **kw: 9)
    return SqlAlchemyWorkerRuntime(
        session_factory=factory,
        repository_cache_dir=Path("cache"),
        git_client=object(),
        settings=worker_runner.WorkerSettings(GITHUB_PUBLISH_RESULTS=False, **settings),
        github_client=_NoGitHub(),
    )


def _factory():
    engine = create_engine("sqlite+pysqlite:///:memory:",
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _job_status(factory, analysis_id) -> str:
    with factory() as session:
        return session.scalar(
            select(AnalysisJob.status).where(AnalysisJob.analysis_id == analysis_id)
        ).value


@pytest.mark.parametrize(("mode", "expect"), [("off", False), ("shadow", True), ("on", True)])
def test_runtime_factory_wires_the_stage_b_recomputer(monkeypatch, mode, expect) -> None:
    from radius_worker.verdict_v2.scoring import StageBRecomputer

    factory = _factory()
    monkeypatch.setattr(worker_runner, "require_sandbox_ready", lambda *a, **k: None)
    monkeypatch.setattr(worker_runner, "create_database_engine", lambda s: object())
    monkeypatch.setattr(worker_runner, "create_session_factory", lambda e: factory)
    settings = worker_runner.WorkerSettings(RADIUS_FEATURE_VERDICT_V2=mode)
    runtime = worker_runner.create_sql_worker_runtime(settings)
    assert isinstance(runtime.verdict_v2_recomputer, StageBRecomputer) is expect


def test_runner_flag_off_never_calls_verdict_v2(monkeypatch) -> None:
    import radius_worker.verdict_v2.scoring as scoring

    def must_not_run(**kwargs):
        raise AssertionError("verdict v2 must not run with the flag off")

    monkeypatch.setattr(scoring, "run_verdict_v2_for_analysis", must_not_run)
    factory = _factory()
    analysis_id = _persist(factory)
    assert _runtime(monkeypatch, factory).run_once() is True
    assert _job_status(factory, analysis_id) == "completed"


@pytest.mark.parametrize("mode", ["shadow", "on"])
def test_runner_flag_on_failure_never_fails_the_job(monkeypatch, mode) -> None:
    import radius_worker.verdict_v2.scoring as scoring

    calls = []
    real = scoring.run_verdict_v2_for_analysis

    def spy(**kwargs):
        calls.append(kwargs["analysis_id"])
        return real(**kwargs)  # command is object(): Stage A errors, swallowed

    monkeypatch.setattr(scoring, "run_verdict_v2_for_analysis", spy)
    factory = _factory()
    analysis_id = _persist(factory)
    rt = _runtime(monkeypatch, factory, RADIUS_FEATURE_VERDICT_V2=mode)
    assert rt.run_once() is True
    assert calls == [analysis_id]
    assert _job_status(factory, analysis_id) == "completed"
