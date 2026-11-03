"""Verdict v2 store and outbox (VS-07): memory, SQLite and opt-in PostgreSQL.

PostgreSQL is opt-in: set ``VERDICT_V2_TEST_POSTGRES_URL`` to a database already
migrated with ``alembic upgrade head``; all writes are rolled back.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from radius_shared.database.base import Base
from radius_shared.database.enums import (
    AnalysisStatus,
    PullRequestStatus,
    RepositoryVisibility,
)
from radius_shared.database.models import (
    Analysis,
    Organization,
    PullRequest,
    Repository,
)
from radius_shared.verdict_v2_payload import build_payload
from radius_shared.verdict_v2_repository import (
    InMemoryVerdictV2Repository,
    SqlVerdictV2Repository,
    StageAUnavailableError,
    backoff_seconds,
    cap_bundle,
)
from radius_shared.verdict_v2_testing import make_bundle, make_error_bundle
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

T0 = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)


@dataclass
class Env:
    repo: object
    org_a: UUID
    org_b: UUID
    an_a: UUID
    an_a2: UUID
    an_b: UUID
    session: Session | None = None


def _analysis(session: Session, org: Organization) -> Analysis:
    repository = Repository(
        organization=org,
        github_repository_id=uuid4().int % 10**9,
        name="radius",
        owner="acme",
        default_branch="main",
        clone_url="https://github.com/acme/radius.git",
        visibility=RepositoryVisibility.PRIVATE,
    )
    pull_request = PullRequest(
        repository=repository,
        github_pr_number=1,
        title="t",
        source_branch="f",
        target_branch="main",
        author="a",
        status=PullRequestStatus.OPEN,
        opened_at=T0,
    )
    analysis = Analysis(
        repository=repository,
        pull_request=pull_request,
        commit_sha="4f2a9d1c0b7e6a53f8c1d2e3b4a59687c0d1e2f3",
        status=AnalysisStatus.PENDING,
        started_at=T0,
        created_at=T0,
    )
    session.add_all([repository, pull_request, analysis])
    return analysis


@pytest.fixture(params=["memory", "sql", "postgres"])
def env(request: pytest.FixtureRequest):
    if request.param == "memory":
        yield Env(InMemoryVerdictV2Repository(), uuid4(), uuid4(), uuid4(), uuid4(), uuid4())
        return
    connection = outer = None
    if request.param == "postgres":
        url = os.environ.get("VERDICT_V2_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("VERDICT_V2_TEST_POSTGRES_URL not set")
        engine = create_engine(url)
        connection = engine.connect()
        outer = connection.begin()
        session = Session(connection, join_transaction_mode="create_savepoint")
    else:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        session = Session(engine)
    try:
        org_a, org_b = Organization(name="A"), Organization(name="B")
        a1, a2, b1 = _analysis(session, org_a), _analysis(session, org_a), _analysis(session, org_b)
        session.flush()
        yield Env(
            SqlVerdictV2Repository(session), org_a.id, org_b.id, a1.id, a2.id, b1.id, session
        )
    finally:
        session.close()
        if outer is not None:
            outer.rollback()
            connection.close()


def test_save_then_latest_roundtrips_summary_columns(env: Env) -> None:
    bundle = make_bundle(str(env.an_a))
    out = env.repo.save(env.org_a, env.an_a, bundle, mode="on", now=T0)

    assert (out.created, out.changed, out.revision) == (True, True, 1)
    stored = env.repo.latest(env.org_a, env.an_a)
    assert stored is not None
    assert stored.revision == 1
    assert stored.status == "ok"
    assert stored.mode == "on"
    assert stored.verdict == "insufficient_evidence"
    assert stored.reason_code == "unproven_intent_mass"
    assert stored.head_sha == bundle["head_sha"]
    assert stored.inputs_digest == bundle["inputs_digest"]
    assert stored.justification["decided_by"] == "R2b"
    assert stored.bundle["verdict"]["uim"] == 0.5
    assert stored.published_at is None


def test_save_is_idempotent_on_the_inputs_digest(env: Env) -> None:
    bundle = make_bundle(str(env.an_a))
    first = env.repo.save(env.org_a, env.an_a, bundle, mode="on")
    again = env.repo.save(env.org_a, env.an_a, bundle, mode="on")

    assert again.row_id == first.row_id
    assert (again.created, again.changed, again.revision) == (False, False, 1)


def test_new_inputs_get_the_next_revision(env: Env) -> None:
    env.repo.save(env.org_a, env.an_a, make_bundle(str(env.an_a), variant="a"), mode="on")
    second = env.repo.save(env.org_a, env.an_a, make_bundle(str(env.an_a), variant="b"), mode="on")

    assert second.revision == 2
    assert env.repo.latest(env.org_a, env.an_a).revision == 2


def test_returning_to_an_older_digest_moves_it_to_the_top_and_clears_publish(env: Env) -> None:
    a = make_bundle(str(env.an_a), variant="a")
    first = env.repo.save(env.org_a, env.an_a, a, mode="on")
    env.repo.mark_published(env.org_a, first.row_id, "d" * 64, now=T0)
    env.repo.save(env.org_a, env.an_a, make_bundle(str(env.an_a), variant="b"), mode="on")

    back = env.repo.save(env.org_a, env.an_a, a, mode="on")

    assert back.row_id == first.row_id
    assert (back.created, back.changed, back.revision) == (False, True, 3)
    latest = env.repo.latest(env.org_a, env.an_a)
    assert latest.row_id == str(first.row_id)
    assert latest.published_digest is None


def test_tenant_isolation_for_rows_and_publish_state(env: Env) -> None:
    saved = env.repo.save(env.org_a, env.an_a, make_bundle(str(env.an_a)), mode="on")

    assert env.repo.latest(env.org_b, env.an_a) is None
    assert env.repo.latest_stage_a(env.org_b, env.an_a) is None
    assert env.repo.mark_published(env.org_b, saved.row_id, "e" * 64) is False
    assert env.repo.record_publish_error(env.org_b, saved.row_id, "x") is False
    assert env.repo.latest(env.org_a, env.an_a).published_digest is None
    assert env.repo.get_request(env.org_b, env.an_a) is None


def test_tenant_b_writes_never_surface_for_tenant_a(env: Env) -> None:
    env.repo.save(env.org_b, env.an_b, make_bundle(str(env.an_b)), mode="on")

    assert env.repo.latest(env.org_a, env.an_b) is None
    assert env.repo.latest(env.org_b, env.an_b) is not None


def test_error_bundle_is_stored_redacted_with_fallback(env: Env) -> None:
    secret = "ghp_" + "a" * 36
    bundle = make_error_bundle(str(env.an_a))
    bundle["error_detail"] = f"clone failed with token {secret}"

    env.repo.save(env.org_a, env.an_a, bundle, mode="on")

    stored = env.repo.latest(env.org_a, env.an_a)
    assert (stored.status, stored.verdict, stored.fallback) == ("error", None, "v1")
    assert stored.reason_code == "TimeoutError"
    assert secret not in (stored.error_detail or "")
    payload = build_payload(stored)
    assert payload["verdict"] is None
    assert payload["error"] == {"code": "TimeoutError", "fallback": "v1"}
    assert payload["criteria"] == []


@pytest.mark.parametrize(
    "mutate",
    [
        {"head_sha": "ABC"},
        {"head_sha": "A" * 40},
        {"status": "weird"},
        {"inputs_digest": "nope"},
        {"verdict": None},
    ],
)
def test_invalid_bundles_are_rejected(env: Env, mutate: dict) -> None:
    bundle = {**make_bundle(str(env.an_a)), **mutate}
    with pytest.raises(ValueError, match="bundle"):
        env.repo.save(env.org_a, env.an_a, bundle, mode="on")


def test_invalid_mode_is_rejected(env: Env) -> None:
    with pytest.raises(ValueError, match="mode"):
        env.repo.save(env.org_a, env.an_a, make_bundle(str(env.an_a)), mode="off")


def test_latest_stage_a_survives_a_later_error_row(env: Env) -> None:
    env.repo.save(env.org_a, env.an_a, make_bundle(str(env.an_a)), mode="on")
    env.repo.save(env.org_a, env.an_a, make_error_bundle(str(env.an_a)), mode="on")

    stage_a = env.repo.latest_stage_a(env.org_a, env.an_a)

    assert stage_a is not None
    assert stage_a["analysis_id"] == str(env.an_a)


def test_oversize_bundle_is_truncated_not_rejected(env: Env) -> None:
    bundle = make_bundle(str(env.an_a))
    bundle["evidence_items"] = [{"evidence_id": f"ev_{i}", "blob": "x" * 1000} for i in range(3000)]

    env.repo.save(env.org_a, env.an_a, bundle, mode="on")

    stored = env.repo.latest(env.org_a, env.an_a)
    assert stored.bundle["truncated"] is True
    assert "evidence_items" not in stored.bundle
    assert stored.bundle["verdict"]["uim"] == 0.5


def test_b04_big_stage_a_is_kept_whole_so_ci_results_can_still_rescore(env: Env) -> None:
    bundle = make_bundle(str(env.an_a))
    bundle["stage_a"]["symbols"] = [{"symbol_id": f"s{i}", "blob": "x" * 500} for i in range(5000)]
    bundle["evidence_items"] = [{"evidence_id": f"ev_{i}", "blob": "x" * 500} for i in range(3000)]

    env.repo.save(env.org_a, env.an_a, bundle, mode="on")

    stored = env.repo.latest(env.org_a, env.an_a)
    assert stored.bundle["truncated"] is True
    assert "evidence_items" not in stored.bundle
    stage_a = env.repo.latest_stage_a(env.org_a, env.an_a)
    assert stage_a is not None and len(stage_a["symbols"]) == 5000  # never half a Stage A


def test_b04_huge_stage_a_is_dropped_whole_and_marked_never_stale_fallback(env: Env) -> None:
    env.repo.save(env.org_a, env.an_a, make_bundle(str(env.an_a), variant="small"), mode="on")
    big = make_bundle(str(env.an_a), variant="big")
    big["stage_a"]["symbols"] = [{"blob": "x" * 1000} for _ in range(9000)]  # > 8 MB
    env.repo.save(env.org_a, env.an_a, big, mode="on")

    stored = env.repo.latest(env.org_a, env.an_a)
    assert stored.bundle["truncated"] is True
    assert stored.bundle["stage_a_dropped"] is True
    assert "stage_a" not in stored.bundle
    with pytest.raises(StageAUnavailableError):
        env.repo.latest_stage_a(env.org_a, env.an_a)  # not the older revision's stale intent


def test_b18_same_digest_save_updates_the_mode_and_bundle_revision_matches(env: Env) -> None:
    env.repo.save(env.org_a, env.an_a, make_bundle(str(env.an_a)), mode="shadow")
    out = env.repo.save(env.org_a, env.an_a, make_bundle(str(env.an_a)), mode="on")
    assert out.changed is False
    assert env.repo.latest(env.org_a, env.an_a).mode == "on"

    env.repo.save(env.org_a, env.an_a, make_bundle(str(env.an_a), variant="b"), mode="on")
    stored = env.repo.latest(env.org_a, env.an_a)
    assert stored.revision == 2
    assert stored.bundle["verdict"]["revision"] == 2

    env.repo.save(env.org_a, env.an_a, make_bundle(str(env.an_a)), mode="on")  # back on top
    stored = env.repo.latest(env.org_a, env.an_a)
    assert stored.revision == 3
    assert stored.bundle["verdict"]["revision"] == 3


def test_cap_bundle_leaves_small_bundles_alone() -> None:
    bundle = make_bundle("a")
    assert cap_bundle(bundle) is bundle


# -- outbox ---------------------------------------------------------------


def test_enqueue_collapses_replays_and_claim_complete_deletes(env: Env) -> None:
    env.repo.enqueue_request(env.org_a, env.an_a, "ci_results", now=T0)
    env.repo.enqueue_request(env.org_a, env.an_a, "ci_results", now=T0 + timedelta(seconds=1))

    claim = env.repo.claim_request(now=T0 + timedelta(seconds=2))
    assert claim is not None
    assert (claim.organization_id, claim.analysis_id, claim.attempts) == (
        env.org_a,
        env.an_a,
        1,
    )
    assert env.repo.claim_request(now=T0 + timedelta(seconds=3)) is None  # one row only
    assert env.repo.complete_request(claim) is True
    assert env.repo.get_request(env.org_a, env.an_a) is None
    assert env.repo.claim_request(now=T0 + timedelta(seconds=4)) is None


def test_request_arriving_during_work_survives_completion(env: Env) -> None:
    env.repo.enqueue_request(env.org_a, env.an_a, now=T0)
    claim = env.repo.claim_request(now=T0 + timedelta(seconds=1))
    env.repo.enqueue_request(env.org_a, env.an_a, now=T0 + timedelta(seconds=2))

    assert env.repo.complete_request(claim) is False
    again = env.repo.claim_request(now=T0 + timedelta(seconds=3))
    assert again is not None
    assert again.attempts == 1  # a fresh request resets the attempt counter
    assert env.repo.complete_request(again) is True


def test_b16_re_request_while_running_keeps_the_claim_so_no_second_worker_starts(env: Env) -> None:
    env.repo.enqueue_request(env.org_a, env.an_a, now=T0)
    claim = env.repo.claim_request(now=T0 + timedelta(seconds=1))
    env.repo.enqueue_request(env.org_a, env.an_a, now=T0 + timedelta(seconds=2))

    # the first worker is still running: nobody else may claim the analysis
    assert env.repo.claim_request(now=T0 + timedelta(seconds=3)) is None
    assert env.repo.get_request(env.org_a, env.an_a).claimed is True

    # it finishes, notices the newer request and releases the claim for exactly one more pass
    assert env.repo.complete_request(claim) is False
    again = env.repo.claim_request(now=T0 + timedelta(seconds=4))
    assert again is not None and again.claim_token != claim.claim_token
    assert env.repo.complete_request(again) is True


def test_b16_a_dead_workers_claim_still_expires_with_the_lease(env: Env) -> None:
    env.repo.enqueue_request(env.org_a, env.an_a, now=T0)
    env.repo.claim_request(now=T0 + timedelta(seconds=1), lease_seconds=60)
    env.repo.enqueue_request(env.org_a, env.an_a, now=T0 + timedelta(seconds=2))
    assert env.repo.claim_request(now=T0 + timedelta(seconds=30), lease_seconds=60) is None
    assert env.repo.claim_request(now=T0 + timedelta(seconds=90), lease_seconds=60) is not None


def test_failure_releases_with_backoff_and_redacted_error(env: Env) -> None:
    secret = "ghp_" + "b" * 36
    env.repo.enqueue_request(env.org_a, env.an_a, now=T0)
    claim = env.repo.claim_request(now=T0)
    env.repo.fail_request(claim, RuntimeError(f"boom {secret}"), now=T0)

    pending = env.repo.get_request(env.org_a, env.an_a)
    assert pending.claimed is False
    assert pending.attempts == 1
    assert secret not in (pending.last_error or "")
    assert env.repo.claim_request(now=T0 + timedelta(seconds=1)) is None  # backing off
    retry = env.repo.claim_request(now=T0 + timedelta(seconds=backoff_seconds(1) + 0.1))
    assert retry is not None and retry.attempts == 2


def test_attempts_are_capped(env: Env) -> None:
    env.repo.enqueue_request(env.org_a, env.an_a, now=T0)
    now = T0
    for _ in range(3):
        claim = env.repo.claim_request(now=now, max_attempts=3)
        assert claim is not None
        env.repo.fail_request(claim, "x", now=now)
        now += timedelta(hours=1)
    assert env.repo.claim_request(now=now, max_attempts=3) is None
    assert env.repo.get_request(env.org_a, env.an_a).attempts == 3


def test_stale_claim_can_be_reclaimed_after_the_lease(env: Env) -> None:
    env.repo.enqueue_request(env.org_a, env.an_a, now=T0)
    first = env.repo.claim_request(now=T0, lease_seconds=60)
    assert env.repo.claim_request(now=T0 + timedelta(seconds=30), lease_seconds=60) is None
    second = env.repo.claim_request(now=T0 + timedelta(seconds=61), lease_seconds=60)
    assert second is not None and second.claim_token != first.claim_token
    assert env.repo.complete_request(first) is False  # the old worker lost the claim
    assert env.repo.complete_request(second) is True


def test_claims_come_oldest_first_across_tenants(env: Env) -> None:
    env.repo.enqueue_request(env.org_b, env.an_b, now=T0)
    env.repo.enqueue_request(env.org_a, env.an_a, now=T0 + timedelta(seconds=1))

    first = env.repo.claim_request(now=T0 + timedelta(seconds=5))
    second = env.repo.claim_request(now=T0 + timedelta(seconds=5))

    assert (first.organization_id, second.organization_id) == (env.org_b, env.org_a)


def test_invalid_reason_is_rejected(env: Env) -> None:
    with pytest.raises(ValueError, match="reason"):
        env.repo.enqueue_request(env.org_a, env.an_a, "nope")


def test_backoff_grows_and_is_capped() -> None:
    assert [backoff_seconds(n) for n in (1, 2, 3)] == [2.0, 4.0, 8.0]
    assert backoff_seconds(50) == 300.0


def test_b17_outcomes_survive_a_truncated_bundle_through_the_quality_row_status() -> None:
    from radius_shared.verdict_v2_payload import _outcome_from_status

    for status, outcome in [
        ("counted", "passed"),
        ("gated:outcome_failed", "failed"),
        ("gated:outcome_error", "error"),
        ("gated:outcome_skipped", "skipped"),
        ("gated:zero_quality", "not_run"),
        (None, "not_run"),
    ]:
        assert _outcome_from_status(status) == outcome

    bundle = make_bundle("an-1")
    item = bundle["verdict"]["criteria"][0]["items"][0]
    item["status"] = "gated:outcome_failed"
    item["outcome"] = None
    bundle["evidence_items"] = []  # as after the size cap
    repo = InMemoryVerdictV2Repository()
    org, an = uuid4(), uuid4()
    repo.save(org, an, bundle, mode="on")
    payload = build_payload(repo.latest(org, an))
    assert payload["criteria"][0]["items"][0]["outcome"] == "failed"
