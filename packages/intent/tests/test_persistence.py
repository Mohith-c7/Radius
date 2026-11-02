"""IntentRepository contract tests: run against memory and SQLAlchemy (SQLite)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from radius_intent.domain import (
    Criterion,
    CriterionState,
    ExtractionMethod,
    IntentSnapshot,
    IntentSource,
    IntentSourceKind,
    InvalidStateTransitionError,
    Span,
    Testability,
)
from radius_intent.infrastructure import (
    InMemoryIntentRepository,
    SqlAlchemyIntentRepository,
)
from radius_intent.interfaces import (
    MAX_SOURCE_TEXT_BYTES,
    AnalysisNotFoundError,
    CriterionNotFoundError,
    InvalidIdentifierError,
    SnapshotConflictError,
    SnapshotNotFoundError,
    SourceNotFoundError,
    SourceTooLargeError,
)
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
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

T0 = datetime(2026, 11, 2, 12, 0, 0, 123456, tzinfo=UTC)


@dataclass
class Env:
    repo: object
    org_a: UUID
    org_b: UUID
    analysis_a: str
    analysis_a2: str
    analysis_b: str
    session: Session | None = None


def _make_analysis(session: Session, org: Organization) -> Analysis:
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
        commit_sha="a" * 40,
        status=AnalysisStatus.PENDING,
        started_at=T0,
        created_at=T0,
    )
    session.add_all([repository, pull_request, analysis])
    return analysis


@pytest.fixture(params=["memory", "sql", "postgres"])
def env(request: pytest.FixtureRequest):
    if request.param == "memory":
        yield Env(
            InMemoryIntentRepository(),
            uuid4(),
            uuid4(),
            str(uuid4()),
            str(uuid4()),
            str(uuid4()),
        )
        return
    if request.param == "postgres":
        # Opt-in: INTENT_TEST_POSTGRES_URL must point at a database already
        # migrated with `alembic upgrade head`. Everything is rolled back.
        url = os.environ.get("INTENT_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("INTENT_TEST_POSTGRES_URL not set")
        engine = create_engine(url)
        connection = engine.connect()
        outer = connection.begin()
        session = Session(connection, join_transaction_mode="create_savepoint")
    else:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        connection = outer = None
        session = Session(engine)
    try:
        org_a, org_b = Organization(name="A"), Organization(name="B")
        a1 = _make_analysis(session, org_a)
        a2 = _make_analysis(session, org_a)
        b1 = _make_analysis(session, org_b)
        session.flush()
        yield Env(
            SqlAlchemyIntentRepository(session),
            org_a.id,
            org_b.id,
            str(a1.id),
            str(a2.id),
            str(b1.id),
            session,
        )
    finally:
        session.close()
        if outer is not None:
            outer.rollback()
            connection.close()


def make_source(
    source_id: str = "42",
    kind: IntentSourceKind = IntentSourceKind.PR_BODY,
    text: str = "Users can log in.\nAdmins can delete users.",
    **kw,
) -> IntentSource:
    return IntentSource.from_text(source_id, kind, text, T0, **kw)


def make_criterion(
    source: IntentSource,
    start: int = 0,
    end: int | None = None,
    **kw,
) -> Criterion:
    span = Span(source.source_id, start, len(source.text) if end is None else end)
    return Criterion.create(
        source,
        span,
        extraction_method=kw.pop("extraction_method", ExtractionMethod.DETERMINISTIC),
        extractor_version=kw.pop("extractor_version", "det-1"),
        **kw,
    )


def make_snapshot(
    analysis_id: str,
    criteria: tuple[Criterion, ...],
    sources: tuple[IntentSource, ...],
    *,
    version: int = 1,
    parent: str | None = None,
    snapshot_id: str | None = None,
    created_at: datetime = T0,
) -> IntentSnapshot:
    return IntentSnapshot(
        snapshot_id=snapshot_id or str(uuid4()),
        analysis_id=analysis_id,
        version=version,
        created_at=created_at,
        criteria=criteria,
        sources=tuple(s.ref for s in sources),
        parent_snapshot_id=parent,
    )


def seeded(env: Env, **snapshot_kw):
    source = make_source()
    c1 = make_criterion(source, 0, 17, weight=0.5).with_testability(
        Testability.TESTABLE, "clear"
    )
    c2 = make_criterion(source, 18, len(source.text))
    env.repo.save_sources(env.org_a, env.analysis_a, (source,))
    snap = make_snapshot(env.analysis_a, (c1, c2), (source,), **snapshot_kw)
    return source, snap


def test_round_trip_is_equal_and_ordered(env: Env) -> None:
    source, snap = seeded(env)
    saved = env.repo.save_snapshot(env.org_a, snap)
    assert saved == snap
    assert env.repo.get_snapshot(env.org_a, snap.snapshot_id) == snap
    assert env.repo.get_latest_snapshot(env.org_a, env.analysis_a) == snap
    assert [c.id for c in saved.criteria] == [c.id for c in snap.criteria]
    assert env.repo.get_sources(env.org_a, env.analysis_a) == (source,)


def test_criteria_order_is_preserved_not_sorted(env: Env) -> None:
    source = make_source(text="zzz first\naaa second\nmmm third")
    env.repo.save_sources(env.org_a, env.analysis_a, (source,))
    crits = (
        make_criterion(source, 0, 9),
        make_criterion(source, 10, 20),
        make_criterion(source, 21, 30),
    )
    snap = make_snapshot(env.analysis_a, crits, (source,))
    env.repo.save_snapshot(env.org_a, snap)
    loaded = env.repo.get_snapshot(env.org_a, snap.snapshot_id)
    assert [c.text for c in loaded.criteria] == ["zzz first", "aaa second", "mmm third"]


def test_save_snapshot_is_idempotent_on_content(env: Env) -> None:
    source, snap = seeded(env)
    first = env.repo.save_snapshot(env.org_a, snap)
    # Same content, different generated id and created_at: no new snapshot.
    again = make_snapshot(
        env.analysis_a,
        snap.criteria,
        (source,),
        created_at=T0 + timedelta(minutes=5),
    )
    second = env.repo.save_snapshot(env.org_a, again)
    assert second == first
    assert env.repo.list_snapshots(env.org_a, env.analysis_a) == (first,)
    # Saving the very same object again is also a no-op.
    assert env.repo.save_snapshot(env.org_a, snap) == first


def test_resave_after_confirmation_returns_current_state(env: Env) -> None:
    _, snap = seeded(env)
    env.repo.save_snapshot(env.org_a, snap)
    env.repo.record_state_change(
        env.org_a,
        snap.snapshot_id,
        snap.criteria[0].id,
        CriterionState.CONFIRMED,
        actor="u1",
        changed_at=T0,
    )
    again = env.repo.save_snapshot(env.org_a, snap)
    assert again.criteria[0].state is CriterionState.CONFIRMED
    assert len(env.repo.list_snapshots(env.org_a, env.analysis_a)) == 1


def test_different_content_same_version_conflicts(env: Env) -> None:
    source, snap = seeded(env)
    env.repo.save_snapshot(env.org_a, snap)
    other = make_snapshot(env.analysis_a, (snap.criteria[0],), (source,))
    with pytest.raises(SnapshotConflictError):
        env.repo.save_snapshot(env.org_a, other)
    reuse_id = make_snapshot(
        env.analysis_a2,
        (),
        (),
        snapshot_id=snap.snapshot_id,
    )
    with pytest.raises(SnapshotConflictError):
        env.repo.save_snapshot(env.org_a, reuse_id)


def test_versions_parent_and_latest(env: Env) -> None:
    source, v1 = seeded(env)
    env.repo.save_snapshot(env.org_a, v1)
    v2 = v1.next_version(
        str(uuid4()), T0 + timedelta(hours=1), (v1.criteria[0],), (source.ref,)
    )
    env.repo.save_snapshot(env.org_a, v2)
    assert env.repo.get_latest_snapshot(env.org_a, env.analysis_a) == v2
    listed = env.repo.list_snapshots(env.org_a, env.analysis_a)
    assert [s.version for s in listed] == [1, 2]
    assert listed[1].parent_snapshot_id == v1.snapshot_id
    orphan = make_snapshot(
        env.analysis_a,
        (),
        (),
        version=3,
        parent=str(uuid4()),
    )
    with pytest.raises(SnapshotNotFoundError):
        env.repo.save_snapshot(env.org_a, orphan)


def test_snapshot_requires_saved_sources(env: Env) -> None:
    source = make_source()
    snap = make_snapshot(env.analysis_a, (make_criterion(source),), (source,))
    with pytest.raises(SourceNotFoundError):
        env.repo.save_snapshot(env.org_a, snap)


def test_old_snapshot_keeps_its_source_version(env: Env) -> None:
    old = make_source(text="Old statement here.")
    new = make_source(text="Old statement here. Plus more.")
    env.repo.save_sources(env.org_a, env.analysis_a, (old,))
    v1 = make_snapshot(env.analysis_a, (make_criterion(old, 0, 19),), (old,))
    env.repo.save_snapshot(env.org_a, v1)
    env.repo.save_sources(env.org_a, env.analysis_a, (new,))
    v2 = v1.next_version(
        str(uuid4()), T0, (make_criterion(new, 0, 19),), (new.ref,)
    )
    env.repo.save_snapshot(env.org_a, v2)
    assert len(env.repo.get_sources(env.org_a, env.analysis_a)) == 2
    assert env.repo.get_snapshot(env.org_a, v1.snapshot_id) == v1
    assert env.repo.get_snapshot(env.org_a, v2.snapshot_id) == v2


def test_save_sources_is_idempotent_and_ordered(env: Env) -> None:
    s1 = make_source("b", IntentSourceKind.ISSUE, "issue text")
    s2 = make_source("a", IntentSourceKind.PR_BODY, "body text")
    s3 = make_source("a", IntentSourceKind.ISSUE, "other issue")
    env.repo.save_sources(env.org_a, env.analysis_a, (s1, s2))
    env.repo.save_sources(env.org_a, env.analysis_a, (s2, s3, s1))
    got = env.repo.get_sources(env.org_a, env.analysis_a)
    assert got == (s3, s1, s2)  # (kind, source_id): issue/a, issue/b, pr_body/a


def test_source_flags_roundtrip(env: Env) -> None:
    src = make_source(
        text="trimmed",
        raw_text="trimmed and a much longer original",
        truncated=True,
        suspicious_content_removed=True,
    )
    env.repo.save_sources(env.org_a, env.analysis_a, (src,))
    (got,) = env.repo.get_sources(env.org_a, env.analysis_a)
    assert got == src
    assert got.truncated and got.suspicious_content_removed
    assert got.raw_text_hash == src.raw_text_hash


def test_unicode_roundtrip(env: Env) -> None:
    text = "Usuário pode entrar ‮ rtl ​ zero-width 日本語 \U0001f600 é"
    src = make_source(text=text)
    env.repo.save_sources(env.org_a, env.analysis_a, (src,))
    crit = make_criterion(src)
    snap = make_snapshot(env.analysis_a, (crit,), (src,))
    env.repo.save_snapshot(env.org_a, snap)
    loaded = env.repo.get_snapshot(env.org_a, snap.snapshot_id)
    assert loaded == snap
    assert loaded.criteria[0].text == text.strip()
    (got,) = env.repo.get_sources(env.org_a, env.analysis_a)
    assert got.text == text


def test_source_size_limit(env: Env) -> None:
    at_limit = make_source("big", text="a" * MAX_SOURCE_TEXT_BYTES)
    env.repo.save_sources(env.org_a, env.analysis_a, (at_limit,))
    (got,) = env.repo.get_sources(env.org_a, env.analysis_a)
    assert len(got.text) == MAX_SOURCE_TEXT_BYTES
    over = make_source("big2", text="a" * (MAX_SOURCE_TEXT_BYTES + 1))
    with pytest.raises(SourceTooLargeError):
        env.repo.save_sources(env.org_a, env.analysis_a, (over,))
    # The limit is in bytes, not characters.
    wide = make_source("wide", text="日" * (MAX_SOURCE_TEXT_BYTES // 3 + 1))
    with pytest.raises(SourceTooLargeError):
        env.repo.save_sources(env.org_a, env.analysis_a, (wide,))
    with pytest.raises(SourceTooLargeError):
        env.repo.save_sources(
            env.org_a, env.analysis_a, (make_source("nul", text="a\x00b"),)
        )
    assert len(env.repo.get_sources(env.org_a, env.analysis_a)) == 1


def test_tenant_isolation(env: Env) -> None:
    source, snap = seeded(env)
    env.repo.save_snapshot(env.org_a, snap)
    crit_id = snap.criteria[0].id
    assert env.repo.get_snapshot(env.org_b, snap.snapshot_id) is None
    assert env.repo.get_latest_snapshot(env.org_b, env.analysis_a) is None
    assert env.repo.list_snapshots(env.org_b, env.analysis_a) == ()
    assert env.repo.get_sources(env.org_b, env.analysis_a) == ()
    assert env.repo.list_state_changes(env.org_b, snap.snapshot_id) == ()
    with pytest.raises(SnapshotNotFoundError):
        env.repo.record_state_change(
            env.org_b,
            snap.snapshot_id,
            crit_id,
            CriterionState.CONFIRMED,
            actor="mallory",
            changed_at=T0,
        )
    untouched = env.repo.get_snapshot(env.org_a, snap.snapshot_id)
    assert untouched.criteria[0].state is CriterionState.PROPOSED
    # Org B cannot publish into org A's analysis, nor reuse A's snapshot id.
    if isinstance(env.repo, SqlAlchemyIntentRepository):
        with pytest.raises(AnalysisNotFoundError):
            env.repo.save_sources(env.org_b, env.analysis_a, (source,))
        with pytest.raises(AnalysisNotFoundError):
            env.repo.save_snapshot(env.org_b, snap)
    else:
        with pytest.raises(SourceNotFoundError):
            env.repo.save_snapshot(env.org_b, snap)
    assert env.repo.get_snapshot(env.org_a, snap.snapshot_id) == untouched


def test_same_analysis_reads_do_not_cross_analyses(env: Env) -> None:
    _, snap = seeded(env)
    env.repo.save_snapshot(env.org_a, snap)
    assert env.repo.list_snapshots(env.org_a, env.analysis_a2) == ()
    assert env.repo.get_latest_snapshot(env.org_a, env.analysis_a2) is None


def test_state_transitions_are_audited(env: Env) -> None:
    _, snap = seeded(env)
    env.repo.save_snapshot(env.org_a, snap)
    cid = snap.criteria[0].id
    other = snap.criteria[1].id
    t1, t2, t3 = T0, T0 + timedelta(minutes=1), T0 + timedelta(minutes=2)
    confirmed = env.repo.record_state_change(
        env.org_a, snap.snapshot_id, cid, CriterionState.CONFIRMED,
        actor="alice", changed_at=t1, reason="looks right",
    )
    assert confirmed.state is CriterionState.CONFIRMED
    edited = env.repo.record_state_change(
        env.org_a, snap.snapshot_id, cid, CriterionState.EDITED,
        actor="bob", changed_at=t2, new_text="Users can sign in.",
    )
    assert edited.text == "Users can sign in."
    assert edited.id == cid
    env.repo.record_state_change(
        env.org_a, snap.snapshot_id, other, CriterionState.REJECTED,
        actor="alice", changed_at=t3, reason="out of scope",
    )
    loaded = env.repo.get_snapshot(env.org_a, snap.snapshot_id)
    assert loaded.get(cid) == edited
    assert loaded.get(other).state is CriterionState.REJECTED

    trail = env.repo.list_state_changes(env.org_a, snap.snapshot_id, cid)
    assert [(c.old_state, c.new_state, c.actor) for c in trail] == [
        (CriterionState.PROPOSED, CriterionState.CONFIRMED, "alice"),
        (CriterionState.CONFIRMED, CriterionState.EDITED, "bob"),
    ]
    assert trail[0].reason == "looks right"
    assert trail[0].changed_at == t1
    assert trail[1].old_text == snap.criteria[0].text
    assert trail[1].new_text == "Users can sign in."
    assert trail[0].old_text is None
    whole = env.repo.list_state_changes(env.org_a, snap.snapshot_id)
    assert len(whole) == 3
    assert whole[-1].criterion_id == other


def test_illegal_transition_is_rejected_and_not_audited(env: Env) -> None:
    _, snap = seeded(env)
    env.repo.save_snapshot(env.org_a, snap)
    cid = snap.criteria[0].id
    with pytest.raises(InvalidStateTransitionError):
        env.repo.record_state_change(
            env.org_a, snap.snapshot_id, cid, CriterionState.PROPOSED,
            actor="a", changed_at=T0,
        )
    with pytest.raises(InvalidIdentifierError):
        env.repo.record_state_change(
            env.org_a, snap.snapshot_id, cid, CriterionState.EDITED,
            actor="a", changed_at=T0,
        )
    with pytest.raises(InvalidIdentifierError):
        env.repo.record_state_change(
            env.org_a, snap.snapshot_id, cid, CriterionState.CONFIRMED,
            actor="a", changed_at=T0, new_text="x",
        )
    with pytest.raises(InvalidIdentifierError):
        env.repo.record_state_change(
            env.org_a, snap.snapshot_id, cid, CriterionState.CONFIRMED,
            actor=" ", changed_at=T0,
        )
    with pytest.raises(InvalidIdentifierError):
        env.repo.record_state_change(
            env.org_a, snap.snapshot_id, cid, CriterionState.CONFIRMED,
            actor="a", changed_at=datetime(2026, 1, 1),
        )
    with pytest.raises(CriterionNotFoundError):
        env.repo.record_state_change(
            env.org_a, snap.snapshot_id, "crit_missing", CriterionState.CONFIRMED,
            actor="a", changed_at=T0,
        )
    with pytest.raises(SnapshotNotFoundError):
        env.repo.record_state_change(
            env.org_a, str(uuid4()), cid, CriterionState.CONFIRMED,
            actor="a", changed_at=T0,
        )
    assert env.repo.list_state_changes(env.org_a, snap.snapshot_id) == ()
    assert (
        env.repo.get_snapshot(env.org_a, snap.snapshot_id).criteria[0].state
        is CriterionState.PROPOSED
    )


def test_non_utc_timestamps_compare_equal_after_roundtrip(env: Env) -> None:
    tz = timezone(timedelta(hours=5, minutes=30))
    src = IntentSource.from_text(
        "1", IntentSourceKind.PR_BODY, "Must work.", T0.astimezone(tz)
    )
    env.repo.save_sources(env.org_a, env.analysis_a, (src,))
    (got,) = env.repo.get_sources(env.org_a, env.analysis_a)
    assert got.fetched_at == src.fetched_at


def test_invalid_ids_are_rejected_on_write_and_empty_on_read(env: Env) -> None:
    with pytest.raises(InvalidIdentifierError):
        env.repo.save_sources(env.org_a, "not-a-uuid", ())
    with pytest.raises(InvalidIdentifierError):
        env.repo.save_sources(env.org_a, env.analysis_a.upper(), ())
    assert env.repo.get_snapshot(env.org_a, "nope") is None
    assert env.repo.list_snapshots(env.org_a, "nope") == ()


def test_unknown_analysis_is_rejected_by_sql(env: Env) -> None:
    if not isinstance(env.repo, SqlAlchemyIntentRepository):
        pytest.skip("memory repository has no analyses table")
    with pytest.raises(AnalysisNotFoundError):
        env.repo.save_sources(env.org_a, str(uuid4()), ())
    # Another organization's analysis looks identical to a missing one.
    with pytest.raises(AnalysisNotFoundError):
        env.repo.save_sources(env.org_a, env.analysis_b, ())


def test_sql_rows_carry_organization_id(env: Env) -> None:
    if env.session is None:
        pytest.skip("sql only")
    from radius_shared.database import intent as rows
    from sqlalchemy import select

    _, snap = seeded(env)
    env.repo.save_snapshot(env.org_a, snap)
    env.repo.record_state_change(
        env.org_a, snap.snapshot_id, snap.criteria[0].id, CriterionState.CONFIRMED,
        actor="u", changed_at=T0,
    )
    for model in (
        rows.IntentSourceRow,
        rows.IntentSnapshotRow,
        rows.IntentSnapshotSourceRow,
        rows.IntentCriterionRow,
        rows.IntentCriterionStateChangeRow,
    ):
        found = env.session.scalars(select(model)).all()
        assert found
        assert {r.organization_id for r in found} == {env.org_a}
