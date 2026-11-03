"""Opt-in data retention (RADIUS_RETENTION_DAYS): only disposable tables, batched, dry-run."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from radius_shared.database import enums as db_enums
from radius_shared.database.base import Base
from radius_shared.database.models import IdempotencyKey, Organization, Repository
from radius_shared.database.verdict_v2 import (
    MutationResultCacheRow,
    VerdictV2RequestRow,
)
from radius_worker import maintenance
from radius_worker.config import WorkerSettings
from radius_worker.maintenance import normalise_retention_days, run_retention
from radius_worker.runner import SqlAlchemyWorkerRuntime
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
OLD = NOW - timedelta(days=40)
YOUNG = NOW - timedelta(days=2)


@pytest.fixture
def env():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as s:
        org = Organization(
            name="A", github_installation_id=1, github_installation_status="active"
        )
        repo = Repository(
            organization=org,
            github_repository_id=1,
            name="r",
            owner="o",
            default_branch="main",
            clone_url="https://example.invalid/o/r.git",
            visibility=db_enums.RepositoryVisibility.PRIVATE,
            status=db_enums.RepositoryStatus.CONNECTED,
        )
        s.add_all([org, repo])
        s.commit()
        return factory, org.id, repo.id


def _idem(org, created, n):
    return IdempotencyKey(
        organization_id=org,
        key=f"k{n}",
        scope="s",
        request_hash="h" * 64,
        status_code=200,
        response_body={},
        created_at=created,
    )


def _outbox(org, requested, attempts):
    return VerdictV2RequestRow(
        organization_id=org,
        analysis_id=uuid4(),
        reason="ci",
        requested_at=requested,
        available_at=requested,
        attempts=attempts,
    )


def _cache(org, repo, created, n):
    return MutationResultCacheRow(
        organization_id=org,
        repository_id=repo,
        cache_key=f"{n:064d}",
        status="killed",
        killed_by=[],
        algo_version="v1",
        created_at=created,
    )


def _count(factory, model):
    with factory() as s:
        return s.scalar(select(func.count()).select_from(model))


def _seed(factory, org, repo):
    with factory() as s:
        s.add_all(
            [
                _idem(org, OLD, 1),
                _idem(org, OLD, 2),
                _idem(org, YOUNG, 3),
                _outbox(org, OLD, attempts=5),  # dead letter, old -> deleted
                _outbox(org, OLD, attempts=1),  # old but still retryable -> kept
                _outbox(org, YOUNG, attempts=5),  # dead but young -> kept
                _cache(org, repo, OLD, 1),
                _cache(org, repo, YOUNG, 2),
            ]
        )
        s.commit()


def test_deletes_only_expired_disposable_rows(env) -> None:
    factory, org, repo = env
    _seed(factory, org, repo)
    report = run_retention(factory, retention_days=30, now=NOW)
    assert report.counts == {
        "idempotency_keys": 2,
        "verdict_v2_requests": 1,
        "mutation_result_cache": 1,
    }
    assert _count(factory, IdempotencyKey) == 1
    assert _count(factory, VerdictV2RequestRow) == 2
    assert _count(factory, MutationResultCacheRow) == 1
    # Other tables are untouched.
    assert _count(factory, Organization) == 1
    assert _count(factory, Repository) == 1
    # A second pass is a no-op.
    assert run_retention(factory, retention_days=30, now=NOW).total == 0


def test_dry_run_counts_but_deletes_nothing(env) -> None:
    factory, org, repo = env
    _seed(factory, org, repo)
    report = run_retention(factory, retention_days=30, now=NOW, dry_run=True)
    assert report.dry_run and report.total == 4
    assert _count(factory, IdempotencyKey) == 3
    assert _count(factory, VerdictV2RequestRow) == 3
    assert _count(factory, MutationResultCacheRow) == 2


def test_off_deletes_nothing(env) -> None:
    factory, org, repo = env
    _seed(factory, org, repo)
    assert run_retention(factory, retention_days=0, now=NOW).total == 0
    assert _count(factory, IdempotencyKey) == 3


def test_window_below_minimum_is_raised_to_seven_days(env) -> None:
    factory, org, repo = env
    with factory() as s:
        s.add_all([_idem(org, NOW - timedelta(days=3), 1), _idem(org, NOW - timedelta(days=8), 2)])
        s.commit()
    # 1 day requested: the 3-day-old row must survive because the floor is 7 days.
    report = run_retention(factory, retention_days=1, now=NOW)
    assert report.counts["idempotency_keys"] == 1
    assert _count(factory, IdempotencyKey) == 1


def test_deletes_in_bounded_batches(env) -> None:
    factory, org, _ = env
    with factory() as s:
        s.add_all([_idem(org, OLD, n) for n in range(25)])
        s.commit()
    # 10 per batch, at most 2 batches per pass: 20 deleted, 5 left for the next pass.
    report = run_retention(factory, retention_days=30, now=NOW, batch_size=10, max_batches=2)
    assert report.counts["idempotency_keys"] == 20
    assert _count(factory, IdempotencyKey) == 5
    report = run_retention(factory, retention_days=30, now=NOW, batch_size=10, max_batches=2)
    assert report.counts["idempotency_keys"] == 5
    assert _count(factory, IdempotencyKey) == 0


def test_only_the_disposable_tables_are_targets() -> None:
    names = {name for name, _, _ in maintenance._targets(NOW)}
    assert names == {
        "idempotency_keys",
        "verdict_v2_requests",
        "mutation_result_cache",
        "auth_sessions",
        "auth_tokens",
        "auth_oauth_flows",
    }
    for forbidden in ("analyses", "verdict_v2", "confidence_reports", "audit_log"):
        assert forbidden not in names


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, 0), ("", 0), ("abc", 0), (-5, 0), (0, 0), (1, 7), (6, 7), (7, 7), ("30", 30)],
)
def test_normalise_retention_days(raw, expected) -> None:
    assert normalise_retention_days(raw) == expected


def test_settings_default_off_and_clamped() -> None:
    assert WorkerSettings().retention_days == 0
    assert WorkerSettings().retention_dry_run is False
    assert WorkerSettings(RADIUS_RETENTION_DAYS=3).retention_days == 7
    assert WorkerSettings(RADIUS_RETENTION_DAYS=45).retention_days == 45
    assert WorkerSettings(RADIUS_RETENTION_DAYS="junk").retention_days == 0


def test_runtime_pass_never_raises_and_respects_dry_run(env) -> None:
    factory, org, repo = env
    _seed(factory, org, repo)
    runtime = SqlAlchemyWorkerRuntime.__new__(SqlAlchemyWorkerRuntime)
    runtime.session_factory = factory
    runtime.settings = WorkerSettings(RADIUS_RETENTION_DAYS=30, RADIUS_RETENTION_DRY_RUN=True)
    runtime.run_retention()
    assert _count(factory, IdempotencyKey) == 3  # dry run
    runtime.settings = WorkerSettings(RADIUS_RETENTION_DAYS=30)
    runtime.run_retention()
    assert _count(factory, IdempotencyKey) == 1

    def boom(*_a, **_k):
        raise RuntimeError("db down")

    runtime.session_factory = boom
    runtime.run_retention()  # swallowed, logged


def test_expired_sign_in_sessions_tokens_and_flows_are_purged_live_ones_kept(env) -> None:
    """C-13: auth_sessions / auth_tokens / auth_oauth_flows no longer grow without bound."""

    import app.models as auth_models
    from app.database import Base as AuthBase

    factory, _org, _repo = env
    engine = factory.kw["bind"]
    AuthBase.metadata.create_all(bind=engine)
    live = NOW + timedelta(days=5)
    with factory() as s:
        user = auth_models.User(name="A", email="a@example.test")
        s.add(user)
        s.flush()
        s.add_all(
            [
                auth_models.AuthSession(user_id=user.id, expires_at=OLD),  # expired long ago
                auth_models.AuthSession(user_id=user.id, expires_at=live, revoked_at=OLD),  # revoked long ago
                auth_models.AuthSession(user_id=user.id, expires_at=live),  # live: must survive
                auth_models.AuthSession(user_id=user.id, expires_at=YOUNG),  # expired 2 days ago: inside the window
                auth_models.AuthToken(user_id=user.id, purpose="verify_email", token_hash="h1", expires_at=OLD),
                auth_models.AuthToken(user_id=user.id, purpose="verify_email", token_hash="h2", expires_at=live),
                auth_models.AuthOAuthFlow(
                    flow_hash="f1", state_hash="s", provider="google", nonce="n", code_verifier="v", expires_at=OLD
                ),
            ]
        )
        s.commit()

    dry = run_retention(factory, retention_days=30, now=NOW, dry_run=True)
    assert dry.counts["auth_sessions"] == 2 and dry.counts["auth_tokens"] == 1
    assert _count(factory, auth_models.AuthSession) == 4

    report = run_retention(factory, retention_days=30, now=NOW)
    assert report.counts["auth_sessions"] == 2
    assert report.counts["auth_tokens"] == 1
    assert report.counts["auth_oauth_flows"] == 1
    assert _count(factory, auth_models.AuthSession) == 2  # the live one and the recently expired one
    assert _count(factory, auth_models.AuthToken) == 1
    assert _count(factory, auth_models.User) == 1  # accounts are never retention targets
