"""Verdict v2 store, publish switch and republish-after-CI outbox (VS-07, VS-08).

The renderer is the port ``radius_github.verdict_v2.ports.VerdictRenderer``; the
real renderer is VD-06, so a fake renderer is used here. GitHub is a fake client.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
import radius_worker.runner as worker_runner
from radius_evidence.domain.inputs import StageAInput
from radius_github.verdict_v2.markdown import MarkdownRenderer, parse_v2_marker
from radius_github.verdict_v2.view import VerdictV2View
from radius_shared.database import enums as db_enums
from radius_shared.database.base import Base
from radius_shared.database.models import (
    Analysis,
    Organization,
    PullRequest,
    Repository,
)
from radius_shared.verdict_v2_flag import VerdictV2Mode
from radius_shared.verdict_v2_repository import SqlVerdictV2Repository, backoff_seconds
from radius_shared.verdict_v2_testing import HEAD, make_bundle, make_error_bundle
from radius_worker.config import WorkerSettings
from radius_worker.runner import SqlAlchemyWorkerRuntime
from radius_worker.verdict_v2 import publish as pub
from radius_worker.verdict_v2.requests import process_pending
from radius_worker.verdict_v2.store import SqlVerdictStore
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

T0 = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
BOT = {"type": "Bot"}


class FakeRenderer(MarkdownRenderer):
    """The REAL renderer (VD-06), counting calls."""

    def __init__(self) -> None:
        self.calls = 0

    def render_comment(self, view: VerdictV2View) -> str:
        self.calls += 1
        return super().render_comment(view)


class FakeGitHub:
    def __init__(self) -> None:
        self.check_runs: list[dict] = []
        self.comments: list[dict] = []
        self.writes = 0
        self.fail_next = 0
        self.live_head: str | None = HEAD
        self.pr_number = 7

    def create_installation_token(self, installation_id):
        return type("T", (), {"token": "ghs_x"})()

    def get_pull_request(self, *, number, **_):
        # GET /pulls/{number}: works for any PR, not only the first 100 open ones (B-15)
        if self.live_head is None or number != self.pr_number:
            return {}
        return {"number": number, "head": {"sha": self.live_head}}

    def list_check_runs_for_ref(self, *, ref, check_name, **_):
        return [r for r in self.check_runs if r["head_sha"] == ref and r["name"] == check_name]

    def _maybe_fail(self):
        if self.fail_next:
            self.fail_next -= 1
            raise RuntimeError("github 502 ghp_" + "z" * 36)

    def create_check_run(self, **kw):
        self._maybe_fail()
        self.writes += 1
        run = {**kw, "id": len(self.check_runs) + 1, "started_at": str(len(self.check_runs))}
        self.check_runs.append(run)
        return run

    def update_check_run(self, *, check_run_id, **kw):
        self._maybe_fail()
        self.writes += 1
        run = next(r for r in self.check_runs if r["id"] == check_run_id)
        run.update(kw)
        return run

    def list_issue_comments(self, **_):
        return list(self.comments)

    def create_issue_comment(self, **kw):
        self._maybe_fail()
        self.writes += 1
        self.comments.append({"id": len(self.comments) + 1, "user": BOT, "body": kw["body"]})

    def update_issue_comment(self, *, comment_id, body, **_):
        self._maybe_fail()
        self.writes += 1
        next(c for c in self.comments if c["id"] == comment_id)["body"] = body


class Env:
    def __init__(self, mode: str = "on", **settings) -> None:
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.factory = sessionmaker(bind=engine, expire_on_commit=False)
        self.github = FakeGitHub()
        self.renderer = FakeRenderer()
        self.settings = WorkerSettings(
            GITHUB_APP_ID="app-id",
            GITHUB_APP_PRIVATE_KEY="key",
            RADIUS_FEATURE_VERDICT_V2=mode,
            **settings,
        )
        with self.factory() as session:
            self.org_a, self.analysis = self._tenant(session, "A", 111, 7)
            self.org_b, self.analysis_b = self._tenant(session, "B", 222, 8)
            session.commit()

    @staticmethod
    def _tenant(session: Session, name: str, installation: int, number: int):
        org = Organization(name=name, github_installation_id=installation)
        repo = Repository(
            organization=org,
            github_repository_id=installation,
            name="radius",
            owner="acme",
            default_branch="main",
            clone_url="https://github.com/acme/radius.git",
            visibility=db_enums.RepositoryVisibility.PRIVATE,
            status=db_enums.RepositoryStatus.CONNECTED,
        )
        pr = PullRequest(
            repository=repo,
            github_pr_number=number,
            title="t",
            source_branch="f",
            target_branch="main",
            author="o",
            status=db_enums.PullRequestStatus.OPEN,
            opened_at=T0,
        )
        analysis = Analysis(
            repository=repo,
            pull_request=pr,
            commit_sha=HEAD,
            status=db_enums.AnalysisStatus.COMPLETED,
            started_at=T0,
            created_at=T0,
        )
        session.add_all([org, repo, pr, analysis])
        session.flush()
        return org.id, analysis.id

    def store(self, bundle=None, mode: str = "on", org=None, analysis=None):
        return SqlVerdictStore(self.factory, VerdictV2Mode(mode)).save(
            org or self.org_a,
            analysis or self.analysis,
            bundle or make_bundle(str(analysis or self.analysis)),
        )

    def publish(self, **kw) -> pub.PublishOutcome:
        with self.factory() as session:
            outcome = pub.publish_latest(
                session,
                organization_id=kw.pop("org", self.org_a),
                analysis_id=kw.pop("analysis", self.analysis),
                settings=self.settings,
                github_client=self.github,
                renderer=kw.pop("renderer", self.renderer),
            )
            session.commit()
            return outcome


# -- store ----------------------------------------------------------------


def test_store_is_idempotent_and_off_mode_is_refused() -> None:
    env = Env()
    assert env.store() is True
    assert env.store() is False
    with pytest.raises(ValueError, match="flag is off"):
        SqlVerdictStore(env.factory, VerdictV2Mode.OFF)


def test_store_returns_stage_a_as_a_dataclass() -> None:
    env = Env()
    stage_a = StageAInput(
        analysis_id=str(env.analysis),
        repository_id="r1",
        head_sha=HEAD,
        changeset_ref="base..head",
        criteria=(),
        symbols=(),
        criterion_symbol=(),
        symbol_test=(),
        criterion_test=(),
        assertions=(),
        tamper=(),
        tamper_waived=0,
        tamper_unanalyzable=(),
        changed_test_ids=frozenset({"t::a"}),
        agent_signal=False,
        degraded=(),
        algo_versions={"symbol_changes": "symbol-changes-v1"},
    )
    bundle = make_bundle(str(env.analysis))
    bundle["stage_a"] = stage_a.to_dict()
    store = SqlVerdictStore(env.factory, VerdictV2Mode.ON)
    assert store.latest_stage_a(env.org_a, env.analysis) is None
    store.save(env.org_a, env.analysis, bundle)
    assert store.latest_stage_a(env.org_a, env.analysis) == stage_a
    assert store.latest_stage_a(env.org_b, env.analysis) is None


# -- publish --------------------------------------------------------------


def test_publish_creates_one_check_run_and_one_comment_with_the_v2_marker() -> None:
    env = Env()
    env.store()

    outcome = env.publish()

    assert (outcome.status, outcome.reason) == ("published", "ok")
    assert len(env.github.check_runs) == 1
    run = env.github.check_runs[0]
    assert run["name"] == "Radius confidence"
    assert run["conclusion"] == "neutral"
    assert run["title"].startswith("Radius v2 alpha - static evidence only - uncalibrated: ")
    assert "criteria supported" in run["title"]
    assert run["summary"].startswith("**Alpha - static evidence only - uncalibrated.**")
    assert "**Why:**" in run["summary"]
    assert len(env.github.comments) == 1
    body = env.github.comments[0]["body"]
    assert body.startswith("<!-- radius-confidence-report -->\n<!-- radius-verdict-v2")
    assert parse_v2_marker(body) is not None
    with env.factory() as session:
        stored = SqlVerdictV2Repository(session).latest(env.org_a, env.analysis)
    assert stored.published_digest == outcome.digest
    assert stored.publish_error is None


def test_identical_republish_is_a_no_op_and_changes_update_in_place() -> None:
    env = Env()
    env.store()
    env.publish()
    writes = env.github.writes

    again = env.publish()
    assert again.status == "unchanged"
    assert env.github.writes == writes

    env.store(make_bundle(str(env.analysis), variant="b", verdict="verified"))
    changed = env.publish()
    assert changed.status == "published"
    assert len(env.github.check_runs) == 1
    assert len(env.github.comments) == 1
    assert parse_v2_marker(env.github.comments[0]["body"])[0] == 2
    # Advisory by default: even a `verified` verdict is never a green check.
    assert env.github.check_runs[0]["conclusion"] == "neutral"


def test_strict_conclusions_knob_makes_verified_a_success() -> None:
    env = Env(RADIUS_VERDICT_V2_CHECK_CONCLUSIONS="strict")
    assert env.settings.verdict_v2_check_conclusions == "strict"
    env.store(make_bundle(str(env.analysis), variant="b", verdict="verified"))
    env.publish()
    assert env.github.check_runs[0]["conclusion"] == "success"


def test_unknown_conclusions_value_stays_advisory() -> None:
    env = Env(RADIUS_VERDICT_V2_CHECK_CONCLUSIONS="STRICTLY")
    assert env.settings.verdict_v2_check_conclusions == "advisory"
    assert Env().settings.verdict_v2_check_conclusions == "advisory"


def test_pending_verdict_is_completed_neutral_not_left_running() -> None:
    env = Env()
    env.store(make_bundle(str(env.analysis), pending=True, verdict="insufficient_evidence"))
    env.publish()
    run = env.github.check_runs[0]
    assert run["status"] == "completed"
    assert run["conclusion"] == "neutral"
    assert run["title"] == "Radius v2 alpha - static evidence only - uncalibrated: awaiting CI test results"


def test_an_existing_v1_comment_is_adopted_not_duplicated() -> None:
    env = Env()
    env.github.comments.append(
        {"id": 99, "user": BOT, "body": "<!-- radius-confidence-report -->\nv1 body"}
    )
    env.store()
    env.publish()
    assert len(env.github.comments) == 1
    assert env.github.comments[0]["id"] == 99
    # one comment per PR (D10): the v1 comment is adopted and now carries both markers
    assert parse_v2_marker(env.github.comments[0]["body"]) is not None
    assert env.github.comments[0]["body"].startswith("<!-- radius-confidence-report -->")


def test_a_human_comment_quoting_the_marker_is_never_edited() -> None:
    env = Env()
    env.github.comments.append(
        {"id": 5, "user": {"type": "User"}, "body": "quote <!-- radius-verdict-v2 rev=1 digest=abcdef12 -->"}
    )
    env.store()
    env.publish()
    assert env.github.comments[0]["body"].startswith("quote")
    assert len(env.github.comments) == 2


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"mode": "off"}, "flag_off"),
        ({"mode": "shadow"}, "flag_shadow"),
        ({"mode": "on", "GITHUB_PUBLISH_RESULTS": False}, "publishing_disabled"),
    ],
)
def test_flag_and_publish_switch_gate_everything(kwargs, reason) -> None:
    env = Env(**kwargs)
    env.store(mode="shadow" if kwargs["mode"] == "off" else kwargs["mode"]) if kwargs[
        "mode"
    ] != "off" else None
    outcome = env.publish()
    assert (outcome.status, outcome.reason) == ("skipped", reason)
    assert env.github.writes == 0


def test_inactive_installation_is_skipped() -> None:
    env = Env()
    env.store()
    with env.factory() as session:
        session.get(Organization, env.org_a).github_installation_status = (
            db_enums.GitHubInstallationStatus.REMOVED.value
            if hasattr(db_enums.GitHubInstallationStatus, "REMOVED")
            else "removed"
        )
        session.commit()
    assert env.publish().reason == "installation_inactive"
    assert env.github.writes == 0


def test_error_row_and_missing_row_and_missing_renderer_are_skipped() -> None:
    env = Env()
    assert env.publish().reason == "not_computed"
    env.store(make_error_bundle(str(env.analysis)))
    assert env.publish().reason == "v2_not_ok"
    env.store()
    assert env.publish(renderer=None).reason == "renderer_unavailable"
    assert env.github.writes == 0


def test_other_organizations_analysis_is_never_published() -> None:
    env = Env()
    env.store(org=env.org_b, analysis=env.analysis_b)
    outcome = env.publish(org=env.org_a, analysis=env.analysis_b)
    assert outcome.reason == "analysis_not_found"
    assert env.github.writes == 0


def test_stale_heads_are_never_published() -> None:
    env = Env()
    other_head = "b" * 40
    env.store(make_bundle(str(env.analysis), head_sha=other_head))
    assert env.publish().reason == "stale_head"

    env2 = Env()
    env2.store()
    with env2.factory() as session:
        analysis = session.get(Analysis, env2.analysis)
        newer = Analysis(
            repository_id=analysis.repository_id,
            pull_request_id=analysis.pull_request_id,
            commit_sha="c" * 40,
            status=db_enums.AnalysisStatus.PENDING,
            started_at=T0 + timedelta(minutes=5),
            created_at=T0 + timedelta(minutes=5),
        )
        session.add(newer)
        session.commit()
    assert env2.publish().reason == "superseded_analysis"

    env3 = Env()
    env3.store()
    env3.github.live_head = "d" * 40  # GitHub says the PR moved on
    assert env3.publish().reason == "stale_head_on_github"
    assert env3.github.writes == 0


def test_b15_unknown_live_head_fails_closed_and_old_prs_are_found_directly() -> None:
    env = Env()
    env.store()
    env.github.live_head = None  # GitHub gave nothing usable: never write on an unknown head
    outcome = env.publish()
    assert (outcome.status, outcome.reason) == ("skipped", "live_head_unknown")
    assert env.github.writes == 0
    env.github.live_head = HEAD  # the PR is asked for directly, so its position in any list is moot
    assert env.publish().status == "published"


def test_github_failure_records_a_redacted_error_and_raises() -> None:
    env = Env()
    env.store()
    env.github.fail_next = 1
    with pytest.raises(pub.PublishError) as caught:
        env.publish()
    assert "ghp_" not in str(caught.value)
    assert (caught.value.organization_id, str(caught.value.row_id) != "") == (env.org_a, True)


# -- outbox ---------------------------------------------------------------


class Recomputer:
    def __init__(self, env: Env, fail: int = 0, rearm: bool = False) -> None:
        self.env, self.fail, self.rearm, self.calls = env, fail, rearm, 0

    def recompute(self, session, organization_id, analysis_id) -> bool:
        self.calls += 1
        if self.fail:
            self.fail -= 1
            raise RuntimeError("scoring failed")
        if self.rearm:
            SqlVerdictV2Repository(session).enqueue_request(
                organization_id, analysis_id, now=datetime.now(UTC) + timedelta(seconds=1)
            )
        return True


def _enqueue(env: Env, org=None, analysis=None, now=T0) -> None:
    with env.factory() as session:
        SqlVerdictV2Repository(session).enqueue_request(
            org or env.org_a, analysis or env.analysis, now=now
        )
        session.commit()


def _pending(env: Env, org=None, analysis=None):
    with env.factory() as session:
        return SqlVerdictV2Repository(session).get_request(
            org or env.org_a, analysis or env.analysis
        )


def _run(env: Env, recomputer=None, now=T0 + timedelta(seconds=1)):
    return process_pending(
        session_factory=env.factory,
        settings=env.settings,
        github_client=env.github,
        recomputer=recomputer,
        renderer=env.renderer,
        now=now,
    )


def test_ci_results_trigger_recompute_and_in_place_republish() -> None:
    env = Env()
    env.store()
    env.publish()
    # CI arrives: the recomputer stores a new revision, the outbox publishes it.
    recomputer = type(
        "R",
        (),
        {
            "recompute": lambda self, session, org, aid: SqlVerdictV2Repository(session).save(
                org,
                aid,
                make_bundle(str(aid), variant="after-ci", verdict="verified"),
                mode="on",
            ).changed
        },
    )()
    _enqueue(env)

    summary = _run(env, recomputer)

    assert summary.processed == 1
    assert summary.results[0].status == "done"
    assert _pending(env) is None
    assert len(env.github.check_runs) == 1 and len(env.github.comments) == 1
    assert env.github.check_runs[0]["conclusion"] == "neutral"
    assert parse_v2_marker(env.github.comments[0]["body"])[0] == 2


def test_replayed_requests_collapse_into_one_publish() -> None:
    env = Env()
    env.store()
    for _ in range(3):
        _enqueue(env)
    assert _run(env).processed == 1
    assert _run(env).processed == 0
    assert env.github.writes == 2  # one check run + one comment


def test_flag_off_claims_nothing() -> None:
    env = Env(mode="off")
    _enqueue(env)
    assert _run(env).processed == 0
    assert _pending(env) is not None


def test_shadow_recomputes_but_never_publishes_and_completes() -> None:
    env = Env(mode="shadow")
    env.store(mode="shadow")
    recomputer = Recomputer(env)
    _enqueue(env)
    summary = _run(env, recomputer)
    assert recomputer.calls == 1
    assert summary.results[0].detail == "skipped:flag_shadow"
    assert env.github.writes == 0
    assert _pending(env) is None


def test_failures_retry_with_backoff_then_succeed() -> None:
    env = Env()
    env.store()
    _enqueue(env)
    recomputer = Recomputer(env, fail=1)

    first = _run(env, recomputer)
    assert first.results[0].status == "retry"
    pending = _pending(env)
    assert pending.attempts == 1 and pending.last_error == "scoring failed"

    assert _run(env, recomputer, now=T0 + timedelta(seconds=2)).processed == 0  # backing off
    later = T0 + timedelta(seconds=1 + backoff_seconds(1) + 1)
    second = _run(env, recomputer, now=later)
    assert second.results[0].status == "done"
    assert _pending(env) is None
    assert env.github.writes == 2


def test_github_failure_in_the_outbox_retries_and_keeps_the_row() -> None:
    env = Env()
    env.store()
    env.github.fail_next = 1
    _enqueue(env)
    assert _run(env).results[0].status == "retry"
    assert _pending(env).attempts == 1
    with env.factory() as session:
        stored = SqlVerdictV2Repository(session).latest(env.org_a, env.analysis)
    assert stored.publish_error and "ghp_" not in stored.publish_error
    assert stored.published_digest is None
    ok = _run(env, now=T0 + timedelta(seconds=1 + backoff_seconds(1) + 1))
    assert ok.results[0].status == "done"


def test_request_arriving_during_work_is_kept_for_another_pass() -> None:
    env = Env()
    env.store()
    _enqueue(env)
    recomputer = Recomputer(env, rearm=True)
    summary = _run(env, recomputer)
    assert summary.results[0].status == "retry"
    assert _pending(env) is not None


def test_requests_of_two_tenants_are_processed_independently() -> None:
    env = Env()
    env.store()
    env.store(org=env.org_b, analysis=env.analysis_b)
    _enqueue(env)
    _enqueue(env, env.org_b, env.analysis_b)
    summary = _run(env)
    assert summary.processed == 2
    assert _pending(env) is None and _pending(env, env.org_b, env.analysis_b) is None


# -- runner switch --------------------------------------------------------


def _runtime(env: Env, monkeypatch, recomputer=None) -> SqlAlchemyWorkerRuntime:
    monkeypatch.setattr(pub, "load_renderer", lambda: env.renderer)
    return SqlAlchemyWorkerRuntime(
        session_factory=env.factory,
        repository_cache_dir=Path("cache"),
        git_client=object(),
        settings=env.settings,
        github_client=env.github,
        verdict_v2_recomputer=recomputer,
    )


def test_run_loop_pass_consumes_the_outbox(monkeypatch) -> None:
    env = Env()
    env.store()
    _enqueue(env, now=datetime.now(UTC) - timedelta(seconds=5))
    runtime = _runtime(env, monkeypatch)
    runtime._process_verdict_v2_requests()
    assert _pending(env) is None
    assert parse_v2_marker(env.github.comments[0]["body"]) is not None


def test_job_publish_uses_v2_when_on_and_ok_and_v1_otherwise(monkeypatch) -> None:
    v1_calls: list[str] = []

    class V1Publisher:
        def __init__(self, client) -> None:
            pass

        def publish(self, **kw) -> None:
            v1_calls.append("v1")

    monkeypatch.setattr(worker_runner, "GitHubAnalysisPublisher", V1Publisher)
    monkeypatch.setattr(worker_runner, "_github_report", lambda s, a, c: type("R", (), {"pull_request_number": 7})())

    def run(env: Env) -> None:
        monkeypatch.setattr(pub, "load_renderer", lambda: env.renderer)
        with env.factory() as session:
            worker_runner._publish_github_result(
                session=session,
                analysis_id=env.analysis,
                settings=env.settings,
                github_client=env.github,
            )
            session.commit()

    on_ok = Env()
    on_ok.store()
    run(on_ok)
    assert v1_calls == [] and len(on_ok.github.comments) == 1

    on_err = Env()
    on_err.store(make_error_bundle(str(on_err.analysis)))
    run(on_err)
    assert v1_calls == ["v1"] and on_err.github.comments == []

    shadow = Env(mode="shadow")
    shadow.store(mode="shadow")
    run(shadow)
    assert v1_calls == ["v1", "v1"] and shadow.github.comments == []

    off = Env(mode="off")
    run(off)
    assert v1_calls == ["v1", "v1", "v1"]

    broken = Env()
    broken.store()
    broken.github.fail_next = 1
    run(broken)  # v2 publish fails -> v1 still goes out
    assert v1_calls[-1] == "v1" and len(v1_calls) == 4


def test_ids_are_uuids() -> None:
    env = Env()
    assert isinstance(env.analysis, UUID)


def test_recompute_failure_marker_replaces_a_published_verdict_with_unavailable() -> None:
    from radius_worker.verdict_v2.scoring import build_error_bundle

    env = Env()
    env.store(make_bundle(str(env.analysis), verdict="verified"))
    assert env.publish().status == "published"
    before = env.github.comments[-1]["body"]

    bundle = build_error_bundle(
        analysis_id=str(env.analysis), head_sha=HEAD, code="recompute_failed:ValueError"
    )
    env.store(bundle)
    outcome = env.publish()

    assert outcome.status == "published"
    body = env.github.comments[-1]["body"]
    assert body != before
    assert "unavailable" in body.lower()
    assert env.github.check_runs[-1]["conclusion"] == "action_required"


def test_ordinary_v2_error_row_is_still_not_published() -> None:
    from radius_worker.verdict_v2.scoring import build_error_bundle

    env = Env()
    env.store(build_error_bundle(analysis_id=str(env.analysis), head_sha=HEAD, code="ValueError"))
    assert env.publish().reason == "v2_not_ok"


# -- B-09: the reconciler ----------------------------------------------------


def _upload(env: Env, when: datetime, sha: str = "a1") -> None:
    from radius_shared.database.models import TestResultUpload

    with env.factory() as session:
        session.add(
            TestResultUpload(
                analysis_id=env.analysis, commit_sha=HEAD, body_sha256=sha * 32, status="passed",
                created_at=when,
            )
        )
        session.commit()


def test_b09_lost_enqueue_is_recovered_by_the_sweep_and_not_repeated() -> None:
    from radius_worker.verdict_v2.requests import reconcile_stale

    env = Env()
    with env.factory() as session:
        SqlVerdictV2Repository(session).save(
            env.org_a, env.analysis, make_bundle(str(env.analysis)), mode="on", now=T0
        )
        session.commit()
    _upload(env, T0 + timedelta(minutes=10))  # CI arrived, the enqueue was swallowed

    # within the grace window (the normal debounced path may still be running): nothing
    assert reconcile_stale(env.factory, now=T0 + timedelta(minutes=11), grace_seconds=3600) == 0
    assert reconcile_stale(env.factory, now=T0 + timedelta(minutes=20)) == 1
    with env.factory() as session:
        assert SqlVerdictV2Repository(session).get_request(env.org_a, env.analysis) is not None
    assert reconcile_stale(env.factory, now=T0 + timedelta(minutes=21)) == 0  # already queued


def test_b09_a_recompute_that_changes_nothing_is_not_swept_again() -> None:
    from radius_worker.verdict_v2.requests import reconcile_stale

    env = Env()
    with env.factory() as session:
        repo = SqlVerdictV2Repository(session)
        repo.save(env.org_a, env.analysis, make_bundle(str(env.analysis)), mode="on", now=T0)
        session.commit()
    _upload(env, T0 + timedelta(minutes=10))
    assert reconcile_stale(env.factory, now=T0 + timedelta(minutes=20)) == 1
    with env.factory() as session:  # the recompute ran, inputs identical: touch only
        repo = SqlVerdictV2Repository(session)
        claim = repo.claim_request(now=T0 + timedelta(minutes=21))
        out = repo.save(
            env.org_a, env.analysis, make_bundle(str(env.analysis)), mode="on",
            now=T0 + timedelta(minutes=21),
        )
        assert out.changed is False
        repo.complete_request(claim)
        session.commit()
    assert reconcile_stale(env.factory, now=T0 + timedelta(minutes=40)) == 0


def test_b09_analyses_without_any_verdict_are_left_alone() -> None:
    from radius_worker.verdict_v2.requests import reconcile_stale

    env = Env()
    _upload(env, T0)
    assert reconcile_stale(env.factory, now=T0 + timedelta(hours=1)) == 0
