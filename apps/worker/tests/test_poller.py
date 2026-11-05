"""Opt-in pull request poller: the real GitHubAppClient against the in-memory FakeGitHubApp."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from radius_github import GitHubAppClient, GitHubAppSettings, GitHubRateLimitError
from radius_github.fake_app import FakeGitHubApp
from radius_shared.database import enums as db_enums
from radius_shared.database.base import Base
from radius_shared.database.models import (
    Analysis,
    AnalysisJob,
    Organization,
    Repository,
)
from radius_worker.config import WorkerSettings
from radius_worker.poller import PullRequestPoller
from radius_worker.runner import SqlAlchemyWorkerRuntime
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

SHA = [f"{n:040x}" for n in range(1, 40)]
INSTALLATION = 9001


@pytest.fixture(scope="module")
def key_pair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        .decode()
    )
    return private, public


class Env:
    def __init__(self, key_pair, **settings) -> None:
        private, public = key_pair
        self.github = FakeGitHubApp(public_key_pem=public)
        self.settings = WorkerSettings(
            GITHUB_APP_ID="12345",
            GITHUB_APP_PRIVATE_KEY=private,
            **{"RADIUS_GITHUB_POLL_INTERVAL_SECONDS": 60, **settings},
        )
        self.client = GitHubAppClient(
            GitHubAppSettings(GITHUB_APP_ID="12345", GITHUB_APP_PRIVATE_KEY=private),
            opener=self.github.opener,
            sleep=lambda _s: None,
        )
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        self._ids = iter(range(1, 1000))
        self.stop = threading.Event()

    def poller(self, client=None, **kwargs) -> PullRequestPoller:
        return PullRequestPoller(
            session_factory=self.session_factory,
            github_client=client or self.client,
            settings=self.settings,
            should_stop=self.stop.is_set,
            **kwargs,
        )

    def add_repository(
        self,
        name: str = "widgets",
        *,
        installation_id: int | None = INSTALLATION,
        installation_status: str = "active",
        status: db_enums.RepositoryStatus = db_enums.RepositoryStatus.CONNECTED,
    ):
        n = next(self._ids)
        with self.session_factory() as session:
            organization = (
                session.scalar(
                    select(Organization).where(
                        Organization.github_installation_id == installation_id
                    )
                )
                if installation_id is not None
                else None
            ) or Organization(
                name=f"Org {n}",
                github_installation_id=installation_id,
                github_installation_status=installation_status,
            )
            repository = Repository(
                organization=organization,
                github_repository_id=5000 + n,
                name=name,
                owner="acme",
                default_branch="main",
                clone_url=f"https://github.com/acme/{name}.git",
                visibility=db_enums.RepositoryVisibility.PRIVATE,
                status=status,
            )
            session.add_all([organization, repository])
            session.commit()
            return repository.id

    def analyses(self) -> list[Analysis]:
        with self.session_factory() as session:
            return list(session.scalars(select(Analysis).order_by(Analysis.created_at)))

    def jobs(self) -> int:
        with self.session_factory() as session:
            return len(list(session.scalars(select(AnalysisJob))))


@pytest.fixture
def env(key_pair) -> Env:
    return Env(key_pair)


def test_poll_queues_an_analysis_for_a_new_head_commit_once(env: Env) -> None:
    env.add_repository()
    env.github.add_pull(7, head_sha=SHA[0], title="Add discount")
    poller = env.poller()

    first = poller.poll_once()
    assert (first.repositories, first.started, first.errors) == (1, 1, 0)
    [analysis] = env.analyses()
    assert analysis.commit_sha == SHA[0]
    assert analysis.status == db_enums.AnalysisStatus.PENDING
    assert env.jobs() == 1

    again = poller.poll_once()
    assert again.started == 0
    assert len(env.analyses()) == 1 and env.jobs() == 1


def test_a_new_head_commit_gets_its_own_analysis(env: Env) -> None:
    env.add_repository()
    pull = env.github.add_pull(7, head_sha=SHA[0])
    poller = env.poller()
    poller.poll_once()

    pull["head"]["sha"] = SHA[1]  # someone pushed
    summary = poller.poll_once()

    assert summary.started == 1
    assert sorted(a.commit_sha for a in env.analyses()) == sorted([SHA[0], SHA[1]])
    assert env.jobs() == 2


def test_drafts_and_closed_pull_requests_are_not_analyzed(env: Env) -> None:
    env.add_repository()
    env.github.add_pull(1, head_sha=SHA[0], draft=True)
    env.github.add_pull(2, head_sha=SHA[1], state="closed")
    summary = env.poller().poll_once()

    assert summary.started == 0
    assert env.analyses() == []


def test_failed_analysis_is_not_retried_every_tick(env: Env) -> None:
    env.add_repository()
    env.github.add_pull(7, head_sha=SHA[0])
    poller = env.poller()
    poller.poll_once()
    with env.session_factory() as session:
        analysis = session.scalar(select(Analysis))
        analysis.status = db_enums.AnalysisStatus.FAILED
        analysis.completed_at = datetime.now(UTC)
        session.commit()

    assert poller.poll_once().started == 0
    assert len(env.analyses()) == 1


def test_per_tick_analysis_budget_defers_the_rest_to_the_next_tick(key_pair) -> None:
    env = Env(key_pair, RADIUS_GITHUB_POLL_MAX_ANALYSES_PER_TICK=2)
    env.add_repository()
    for number in range(1, 6):
        env.github.add_pull(number, head_sha=SHA[number])
    poller = env.poller()

    first = poller.poll_once()
    assert first.started == 2 and first.deferred == 3
    assert poller.poll_once().started == 2
    assert poller.poll_once().started == 1
    assert poller.poll_once().started == 0
    assert len(env.analyses()) == 5


def test_an_error_in_one_repository_does_not_stop_the_others(env: Env, caplog) -> None:
    env.add_repository("missing")  # GitHub (the fake) has no such repository: 404
    env.add_repository("widgets")
    env.github.add_pull(7, head_sha=SHA[0])

    with caplog.at_level(logging.INFO):
        summary = env.poller().poll_once()

    assert summary.errors == 1 and summary.repositories == 1 and summary.started == 1
    outcomes = [getattr(r, "outcome", None) for r in caplog.records]
    assert "poll_repository_error" in outcomes and "poll_tick" in outcomes


def test_token_failure_for_one_installation_still_polls_another(env: Env) -> None:
    env.add_repository("widgets")
    env.add_repository("other", installation_id=424242)  # the fake only knows 9001
    env.github.add_pull(7, head_sha=SHA[0])

    summary = env.poller().poll_once()

    assert summary.errors == 1 and summary.started == 1


def test_disconnected_suspended_and_unlinked_repositories_are_ignored(env: Env) -> None:
    env.add_repository(status=db_enums.RepositoryStatus.DISCONNECTED)
    env.add_repository("b", installation_id=111, installation_status="suspended")
    env.add_repository("c", installation_id=None)
    env.github.add_pull(7, head_sha=SHA[0])

    summary = env.poller().poll_once()

    assert summary.repositories == 0 and summary.errors == 0
    assert not any(path.endswith("/pulls") for _m, path in env.github.requests)


def test_configured_installation_id_wins_for_every_organization(key_pair) -> None:
    env = Env(key_pair, GITHUB_INSTALLATION_ID=INSTALLATION)
    env.add_repository(installation_id=None)
    env.github.add_pull(7, head_sha=SHA[0])

    assert env.poller().poll_once().started == 1


def test_rate_limited_installation_is_left_alone_until_the_reset(env: Env) -> None:
    env.add_repository()
    env.github.add_pull(7, head_sha=SHA[0])
    now = [1000.0]
    calls = {"n": 0}

    class Limited:
        settings = env.client.settings

        def create_installation_token(self, installation_id):
            return env.client.create_installation_token(installation_id)

        def list_pull_requests(self, **kwargs):
            calls["n"] += 1
            raise GitHubRateLimitError(
                "limited",
                kind="primary",
                retry_after_seconds=120.0,
                attempts=1,
                waited_seconds=0.0,
            )

    poller = env.poller(client=Limited(), clock=lambda: now[0])
    first = poller.poll_once()
    assert (
        calls["n"] == 1 and first.rate_limited_installations == 1 and first.errors == 0
    )

    now[0] += 60
    assert poller.poll_once().rate_limited_installations == 1
    assert calls["n"] == 1  # still backed off: no GitHub call

    now[0] += 61
    poller.poll_once()
    assert calls["n"] == 2  # backoff over


def test_repositories_take_turns_when_there_are_more_than_the_tick_limit(
    key_pair,
) -> None:
    env = Env(key_pair, RADIUS_GITHUB_POLL_MAX_REPOSITORIES_PER_TICK=1)
    env.add_repository("a")
    env.add_repository("b")
    poller = env.poller()

    seen = []
    for _ in range(4):
        before = len(env.github.requests)
        poller.poll_once()
        seen.append(
            {
                p
                for _m, p in env.github.requests[before:]
                if p.startswith("/repos/acme/")
            }
        )
    # Each tick lists exactly one repository (the fake answers 404 for unknown ones).
    assert all(len(s) <= 1 for s in seen)
    assert len(env.github.requests) > 0


def test_poll_once_survives_a_database_error(env: Env, caplog) -> None:
    def broken():
        raise RuntimeError("db is down")

    poller = env.poller()
    poller._session_factory = broken  # type: ignore[assignment]
    with caplog.at_level(logging.WARNING):
        summary = poller.poll_once()
    assert summary.errors == 1
    assert any(getattr(r, "outcome", None) == "poll_error" for r in caplog.records)


def test_interval_has_a_30_second_minimum_and_zero_means_off(key_pair) -> None:
    def interval(value) -> float:
        return WorkerSettings(
            RADIUS_GITHUB_POLL_INTERVAL_SECONDS=value
        ).github_poll_interval_seconds

    assert WorkerSettings().github_poll_interval_seconds == 0
    assert interval(0) == 0 and interval(-5) == 0
    assert interval(1) == 30 and interval(29.9) == 30
    assert interval(30) == 30 and interval(300) == 300


def test_delays_are_jittered_within_ten_percent(env: Env) -> None:
    low = env.poller(rng=lambda: 0.0)
    high = env.poller(rng=lambda: 1.0)
    assert low.next_delay() == pytest.approx(54.0)
    assert high.next_delay() == pytest.approx(66.0)
    assert 6.0 <= low.first_delay() < high.first_delay() <= 60.0


def _runtime(env: Env, tmp_path, **kwargs) -> SqlAlchemyWorkerRuntime:
    return SqlAlchemyWorkerRuntime(
        session_factory=env.session_factory,
        repository_cache_dir=tmp_path / "cache",
        git_client=None,  # type: ignore[arg-type]
        settings=env.settings,
        github_client=env.client,
        **kwargs,
    )


def test_runtime_builds_the_poller_only_when_enabled(key_pair, tmp_path) -> None:
    on = Env(key_pair)
    assert _runtime(on, tmp_path).poller is not None
    off = Env(key_pair, RADIUS_GITHUB_POLL_INTERVAL_SECONDS=0)
    assert _runtime(off, tmp_path).poller is None


def test_run_loop_polls_and_a_stop_request_ends_it(env: Env, tmp_path) -> None:
    env.add_repository()
    env.github.add_pull(7, head_sha=SHA[0])
    runtime = _runtime(env, tmp_path)
    runtime.poller._rng = lambda: 0.0  # type: ignore[union-attr]  # first tick after 6s: patch
    runtime.poller.first_delay = lambda: 0.0  # type: ignore[union-attr,method-assign]
    ticks = []
    real_poll = runtime.poller.poll_once  # type: ignore[union-attr]

    def poll_and_stop():
        ticks.append(1)
        result = real_poll()
        runtime.stop_event.set()
        return result

    runtime.poller.poll_once = poll_and_stop  # type: ignore[union-attr,method-assign]
    runtime.run_loop(poll_interval_seconds=0)  # returns because stop_event is set

    assert ticks == [1]
    assert [a.commit_sha for a in env.analyses()] == [SHA[0]]


def test_run_loop_does_not_start_when_stop_is_already_requested(
    env: Env, tmp_path
) -> None:
    runtime = _runtime(env, tmp_path)
    runtime.stop_event.set()
    runtime.run_loop(poll_interval_seconds=0)  # returns at once
    assert env.analyses() == []


def _fail_latest(env: Env, *, age: timedelta) -> None:
    """Mark every non-failed analysis failed, completed ``age`` ago."""

    with env.session_factory() as session:
        for analysis in session.scalars(select(Analysis)):
            if analysis.status != db_enums.AnalysisStatus.FAILED:
                analysis.status = db_enums.AnalysisStatus.FAILED
            analysis.completed_at = datetime.now(UTC) - age
        session.commit()


def test_failed_head_is_retried_after_the_delay_but_only_a_bounded_number_of_times(
    key_pair,
) -> None:
    env = Env(
        key_pair,
        RADIUS_GITHUB_POLL_FAILED_RETRIES=2,
        RADIUS_GITHUB_POLL_FAILED_RETRY_DELAY_SECONDS=900,
    )
    env.add_repository()
    env.github.add_pull(7, head_sha=SHA[0])
    poller = env.poller()
    assert poller.poll_once().started == 1

    # First failure: waits 900 s, then one retry.
    _fail_latest(env, age=timedelta(seconds=100))
    assert poller.poll_once().started == 0
    _fail_latest(env, age=timedelta(seconds=901))
    assert poller.poll_once().started == 1
    assert len(env.analyses()) == 2

    # Second failure: waits 1800 s (doubling), then the last retry.
    _fail_latest(env, age=timedelta(seconds=901))
    assert poller.poll_once().started == 0
    _fail_latest(env, age=timedelta(seconds=1801))
    assert poller.poll_once().started == 1
    assert len(env.analyses()) == 3

    # Third failure: the bound (1 + 2 retries) is reached, no further automatic retry.
    _fail_latest(env, age=timedelta(days=30))
    assert poller.poll_once().started == 0
    assert len(env.analyses()) == 3


def test_failed_head_retry_can_be_switched_off(key_pair) -> None:
    env = Env(key_pair, RADIUS_GITHUB_POLL_FAILED_RETRIES=0)
    env.add_repository()
    env.github.add_pull(7, head_sha=SHA[0])
    poller = env.poller()
    poller.poll_once()
    _fail_latest(env, age=timedelta(days=30))
    assert poller.poll_once().started == 0
    assert len(env.analyses()) == 1
