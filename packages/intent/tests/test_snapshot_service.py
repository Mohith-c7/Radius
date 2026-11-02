"""IN-06 IntentSnapshotService tests, run against both repository adapters."""

from __future__ import annotations

import ast
import json
import sys
import threading
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import radius_intent
from radius_intent.application import (
    SYSTEM_ACTOR,
    IntentSnapshotService,
    SnapshotBuildConflictError,
    SourceRequest,
    diff_snapshot_pair,
)
from radius_intent.application.merge import (
    Candidate,
    plan_merge,
    priority,
    select_criteria,
)
from radius_intent.domain import (
    Criterion,
    CriterionState,
    ExtractionMethod,
    IntentSnapshot,
    IntentSource,
    IntentSourceKind,
    InvalidStateTransitionError,
    Span,
)
from radius_intent.infrastructure import InMemoryIntentRepository
from radius_intent.infrastructure.rules import snapshot_content_hash
from radius_intent.interfaces import SnapshotConflictError, SnapshotNotFoundError

from . import test_persistence as _contract

T0 = _contract.T0
Env = _contract.Env
env = _contract.env  # the memory/sql repository fixture

S = CriterionState
LOGIN = "Users can log in with email"
DELETE = "Admins can delete users"
EXPIRE = "Sessions expire after one hour"


def at(minutes: int):
    return T0 + timedelta(minutes=minutes)


class LineExtractor:
    """Fake extractor: every non-blank line is one criterion."""

    def __init__(
        self,
        version: str = "det-1",
        method: ExtractionMethod = ExtractionMethod.DETERMINISTIC,
        kinds: set[IntentSourceKind] | None = None,
    ) -> None:
        self.version = version
        self.method = method
        self.kinds = kinds

    def extract(self, source: IntentSource) -> tuple[Criterion, ...]:
        if self.kinds is not None and source.kind not in self.kinds:
            return ()
        out, pos = [], 0
        for line in source.text.splitlines(keepends=True):
            text = line.strip()
            if text:
                start = pos + line.index(text)
                out.append(
                    Criterion.create(
                        source,
                        Span(source.source_id, start, start + len(text)),
                        extraction_method=self.method,
                        extractor_version=self.version,
                    )
                )
            pos += len(line)
        return tuple(out)


class Exploding:
    def extract(self, source: IntentSource):
        raise RuntimeError("boom")


class DictFetcher:
    def __init__(self, sources: dict[tuple[IntentSourceKind, str], IntentSource]):
        self.sources = sources
        self.fail = False

    def fetch(self, analysis_id, kind, reference):
        if self.fail:
            raise TimeoutError("github down")
        return self.sources.get((kind, reference))


def src(
    text: str,
    kind: IntentSourceKind = IntentSourceKind.PR_BODY,
    source_id: str = "42",
    fetched=T0,
) -> IntentSource:
    return IntentSource.from_text(source_id, kind, text, fetched)


def lines(*items: str) -> str:
    return "\n".join(items)


def make_service(env: Env, *extractors, fetcher=None) -> IntentSnapshotService:
    return IntentSnapshotService(env.repo, extractors or (LineExtractor(),), fetcher)


def confirm(env: Env, snap: IntentSnapshot, text: str, state=S.CONFIRMED, **kw):
    crit = next(c for c in snap.criteria if c.text == text)
    return env.repo.record_state_change(
        env.org_a, snap.snapshot_id, crit.id, state, actor="u1", changed_at=T0, **kw
    )


def by_text(snap: IntentSnapshot) -> dict[str, Criterion]:
    return {c.text: c for c in snap.criteria}


def build(env, service, *sources, minutes=0, analysis=None):
    return service.build_snapshot(
        analysis or env.analysis_a, env.org_a, list(sources), at(minutes)
    )


def rebuild(env, service, *sources, minutes=1, trigger="pull_request.edited"):
    return service.on_sources_changed(
        env.analysis_a, env.org_a, list(sources), at(minutes), trigger=trigger
    )


# --------------------------------------------------------------------- build


def test_first_build_creates_version_one(env: Env) -> None:
    result = build(env, make_service(env), src(lines(LOGIN, "", DELETE)))
    snap = result.snapshot
    assert result.created and snap.version == 1 and snap.parent_snapshot_id is None
    assert [c.text for c in snap.criteria] == [LOGIN, DELETE]
    assert all(c.state is S.PROPOSED for c in snap.criteria)
    assert env.repo.get_latest_snapshot(env.org_a, env.analysis_a) == snap
    assert env.repo.get_sources(env.org_a, env.analysis_a) == (
        src(lines(LOGIN, "", DELETE)),
    )


def test_rebuild_with_same_inputs_is_idempotent(env: Env) -> None:
    service = make_service(env)
    first = build(env, service, src(lines(LOGIN, DELETE)))
    again = rebuild(env, service, src(lines(LOGIN, DELETE)))
    refetched = rebuild(env, service, src(lines(LOGIN, DELETE), fetched=at(30)))
    assert not again.created and not refetched.created
    assert again.snapshot == first.snapshot == refetched.snapshot
    assert len(service.history(env.org_a, env.analysis_a)) == 1


def test_idempotent_after_human_decisions(env: Env) -> None:
    service = make_service(env)
    first = build(env, service, src(lines(LOGIN, DELETE)))
    confirm(env, first.snapshot, LOGIN)
    again = rebuild(env, service, src(lines(LOGIN, DELETE)))
    assert not again.created
    assert by_text(again.snapshot)[LOGIN].state is S.CONFIRMED
    assert len(service.history(env.org_a, env.analysis_a)) == 1


def test_determinism_same_inputs_same_content_hash() -> None:
    hashes = []
    for _ in range(2):
        repo = InMemoryIntentRepository()
        org, analysis = uuid4(), str(uuid4())
        service = IntentSnapshotService(repo, (LineExtractor(),))
        snap = service.build_snapshot(
            analysis,
            org,
            [src(lines(EXPIRE, LOGIN)), src("Fix it", IntentSourceKind.PR_TITLE, "t")],
            T0,
        ).snapshot
        hashes.append(snapshot_content_hash(replace_analysis(snap)))
    assert hashes[0] == hashes[1]


def replace_analysis(snap: IntentSnapshot) -> IntentSnapshot:
    from dataclasses import replace

    return replace(snap, analysis_id="fixed")


def test_criteria_order_is_deterministic_regardless_of_input_order(env: Env) -> None:
    a = src(lines(LOGIN, DELETE))
    t = src("Short title statement", IntentSourceKind.PR_TITLE, "t1")
    one = build(env, make_service(env), a, t).snapshot
    other = InMemoryIntentRepository()
    two = (
        IntentSnapshotService(other, (LineExtractor(),))
        .build_snapshot(str(uuid4()), uuid4(), [t, a], T0)
        .snapshot
    )
    assert [c.id for c in one.criteria] == [c.id for c in two.criteria]
    assert one.sources == two.sources
    kinds = [c.origin.source.kind for c in one.criteria]
    assert kinds == sorted(kinds, key=list(IntentSourceKind).index)


def test_fetches_via_port_and_records_absent_sources(env: Env) -> None:
    body = src(lines(LOGIN))
    fetcher = DictFetcher({(IntentSourceKind.PR_BODY, "42"): body})
    service = make_service(env, fetcher=fetcher)
    result = service.build_snapshot(
        env.analysis_a,
        env.org_a,
        [
            SourceRequest(IntentSourceKind.PR_BODY, "42"),
            SourceRequest(IntentSourceKind.ISSUE, "7"),
        ],
        T0,
    )
    assert result.snapshot.version == 1
    assert result.report.absent_sources == ("issue:7",)
    assert [d.code for d in result.report.diagnostics] == ["source_absent"]
    json.dumps(result.report.to_dict())


def test_request_without_fetcher_or_fetch_failure_is_a_diagnostic(env: Env) -> None:
    no_fetcher = make_service(env)
    result = no_fetcher.build_snapshot(
        env.analysis_a,
        env.org_a,
        [src(LOGIN), SourceRequest(IntentSourceKind.ISSUE, "7")],
        T0,
    )
    assert [d.code for d in result.report.diagnostics] == ["fetch_failed"]
    assert len(result.snapshot.criteria) == 1


def test_fetch_failure_retains_previous_criteria(env: Env) -> None:
    issue = src(lines(DELETE), IntentSourceKind.ISSUE, "7")
    fetcher = DictFetcher({(IntentSourceKind.ISSUE, "7"): issue})
    service = make_service(env, fetcher=fetcher)
    request = SourceRequest(IntentSourceKind.ISSUE, "7")
    first = service.build_snapshot(env.analysis_a, env.org_a, [request], T0)
    confirm(env, first.snapshot, DELETE)
    fetcher.fail = True
    second = service.on_sources_changed(env.analysis_a, env.org_a, [request], at(1))
    assert not second.created  # nothing else changed; confirmed criterion kept
    assert by_text(second.snapshot)[DELETE].state is S.CONFIRMED
    assert second.report.diagnostics[0].code == "fetch_failed"


def test_naive_now_is_rejected(env: Env) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        make_service(env).build_snapshot(
            env.analysis_a, env.org_a, [src(LOGIN)], T0.replace(tzinfo=None)
        )


def test_duplicate_sources_are_collapsed(env: Env) -> None:
    same = src(LOGIN)
    clash = src(DELETE)
    result = build(env, make_service(env), same, same, clash)
    assert [c.text for c in result.snapshot.criteria] == [LOGIN]
    assert [d.code for d in result.report.diagnostics] == ["duplicate_source"]


# ------------------------------------------------------------- extractor isolation


def test_extractor_failure_does_not_abort_other_sources_or_extractors(env: Env) -> None:
    body = src(lines(LOGIN))
    issue = src(lines(DELETE), IntentSourceKind.ISSUE, "7")
    only_issue = LineExtractor("det-2", kinds={IntentSourceKind.ISSUE})
    service = make_service(env, Exploding(), only_issue, LineExtractor())
    result = build(env, service, body, issue)
    assert {c.text for c in result.snapshot.criteria} == {LOGIN, DELETE}
    failures = [d for d in result.report.diagnostics if d.code == "extractor_failed"]
    assert {d.source for d in failures} == {"pr_body:42", "issue:7"}
    assert "boom" in failures[0].detail


def test_failed_extraction_keeps_previously_confirmed_criteria(env: Env) -> None:
    service = make_service(env)
    first = build(env, service, src(lines(LOGIN, DELETE)))
    confirm(env, first.snapshot, LOGIN)
    broken = IntentSnapshotService(env.repo, (Exploding(),))
    second = broken.on_sources_changed(
        env.analysis_a, env.org_a, [src(lines(LOGIN, DELETE, EXPIRE))], at(1)
    )
    assert by_text(second.snapshot)[LOGIN].state is S.CONFIRMED
    assert DELETE in by_text(second.snapshot)  # proposed criterion also retained
    assert (
        second.snapshot.sources[0].raw_text_hash
        == src(lines(LOGIN, DELETE, EXPIRE)).raw_text_hash
    )


def test_foreign_or_out_of_range_criteria_are_skipped(env: Env) -> None:
    other = src("other text here", source_id="99")

    class Bad:
        def extract(self, source):
            return LineExtractor().extract(other)

    result = build(env, make_service(env, Bad()), src(LOGIN))
    assert result.snapshot.criteria == ()
    assert [d.code for d in result.report.diagnostics] == ["invalid_criterion"]


# --------------------------------------------------------------- edits / carry-over


def test_edit_creates_new_version_and_carries_decisions(env: Env) -> None:
    service = make_service(env)
    v1 = build(env, service, src(lines(LOGIN, DELETE, EXPIRE))).snapshot
    confirm(env, v1, LOGIN)
    confirm(env, v1, DELETE, S.REJECTED)
    confirm(env, v1, EXPIRE, S.EDITED, new_text="Sessions end after 60 minutes")

    result = rebuild(
        env,
        service,
        src(lines("Intro: new section", LOGIN, DELETE, EXPIRE), fetched=at(5)),
    )
    v2 = result.snapshot
    assert (
        result.created and v2.version == 2 and v2.parent_snapshot_id == v1.snapshot_id
    )
    states = {c.id: c.state for c in v2.criteria}
    assert states[by_text(v1)[LOGIN].id] is S.CONFIRMED
    assert states[by_text(v1)[DELETE].id] is S.REJECTED
    edited = v2.get(by_text(v1)[EXPIRE].id)
    assert edited.state is S.EDITED and edited.text == "Sessions end after 60 minutes"
    assert by_text(v2)["Intro: new section"].state is S.PROPOSED
    # Older snapshot is untouched and still reachable.
    assert env.repo.get_snapshot(env.org_a, v1.snapshot_id).version == 1
    assert (
        by_text(env.repo.get_snapshot(env.org_a, v1.snapshot_id))[LOGIN].state
        is S.CONFIRMED
    )
    # Audit rows were written on the new snapshot through record_state_change.
    trail = env.repo.list_state_changes(
        env.org_a, v2.snapshot_id, by_text(v1)[LOGIN].id
    )
    assert [(t.old_state, t.new_state, t.actor) for t in trail] == [
        (S.PROPOSED, S.CONFIRMED, SYSTEM_ACTOR)
    ]
    assert "pull_request.edited" in trail[0].reason and "v1" in trail[0].reason
    assert {e.action for e in result.report.carry_events} == {"carried"}


def test_reworded_confirmed_criterion_needs_reconfirmation(env: Env) -> None:
    service = make_service(env)
    v1 = build(env, service, src(lines(LOGIN, DELETE))).snapshot
    confirm(env, v1, LOGIN)
    new_text = "Users can log in with email or SSO"
    result = rebuild(env, service, src(lines(new_text, DELETE)))
    v2 = result.snapshot
    reworded = by_text(v2)[new_text]
    assert reworded.state is S.NEEDS_RECONFIRMATION
    assert reworded.id != by_text(v1)[LOGIN].id
    assert LOGIN not in by_text(v2) and by_text(v2)[DELETE].state is S.PROPOSED
    trail = env.repo.list_state_changes(env.org_a, v2.snapshot_id, reworded.id)
    assert trail[-1].new_state is S.NEEDS_RECONFIRMATION
    assert by_text(v1)[LOGIN].id in trail[-1].reason
    event = next(
        e for e in result.report.carry_events if e.action == "needs_reconfirmation"
    )
    assert event.previous_id == by_text(v1)[LOGIN].id
    # A human can then re-confirm it.
    env.repo.record_state_change(
        env.org_a,
        v2.snapshot_id,
        reworded.id,
        S.CONFIRMED,
        actor="u1",
        changed_at=at(9),
    )
    # And the pending flag survives another unrelated rebuild.
    v3 = rebuild(
        env, service, src(lines(new_text, DELETE, EXPIRE)), minutes=10
    ).snapshot
    assert by_text(v3)[new_text].state is S.CONFIRMED


def test_unresolved_reconfirmation_flag_is_carried(env: Env) -> None:
    service = make_service(env)
    v1 = build(env, service, src(lines(LOGIN))).snapshot
    confirm(env, v1, LOGIN)
    reworded = "Users can log in with email or SSO"
    rebuild(env, service, src(lines(reworded)))
    v3 = rebuild(env, service, src(lines(reworded, EXPIRE)), minutes=2).snapshot
    assert by_text(v3)[reworded].state is S.NEEDS_RECONFIRMATION
    assert v3.version == 3


def test_vanished_confirmed_criterion_is_orphaned_not_dropped(env: Env) -> None:
    service = make_service(env)
    v1 = build(env, service, src(lines(LOGIN, DELETE, EXPIRE))).snapshot
    confirm(env, v1, DELETE)
    confirm(env, v1, EXPIRE, S.REJECTED)
    result = rebuild(env, service, src(lines(LOGIN)))
    v2 = result.snapshot
    texts = by_text(v2)
    assert texts[DELETE].state is S.ORPHANED  # confirmed: kept with provenance
    assert EXPIRE not in texts  # rejected: may disappear
    assert v2.sources[0].raw_text_hash == src(lines(LOGIN)).raw_text_hash
    assert texts[DELETE].origin.source == v2.sources[0]
    trail = env.repo.list_state_changes(env.org_a, v2.snapshot_id, texts[DELETE].id)
    assert [t.new_state for t in trail] == [S.ORPHANED]
    assert trail[0].old_state is S.CONFIRMED
    # The orphan is stable: rebuilding the same inputs makes no new version.
    assert not rebuild(env, service, src(lines(LOGIN)), minutes=2).created
    # Reappearing text needs re-confirmation; the orphan is not duplicated.
    v3 = rebuild(env, service, src(lines(LOGIN, DELETE)), minutes=3)
    assert by_text(v3.snapshot)[DELETE].state is S.NEEDS_RECONFIRMATION
    assert [e.action for e in v3.report.carry_events] == ["restored"]
    assert len(v3.snapshot.criteria) == 2


def test_human_can_dismiss_an_orphan_and_it_then_disappears(env: Env) -> None:
    service = make_service(env)
    v1 = build(env, service, src(lines(LOGIN, DELETE))).snapshot
    confirm(env, v1, DELETE)
    v2 = rebuild(env, service, src(lines(LOGIN))).snapshot
    env.repo.record_state_change(
        env.org_a,
        v2.snapshot_id,
        by_text(v2)[DELETE].id,
        S.REJECTED,
        actor="u1",
        changed_at=at(2),
    )
    v3 = rebuild(env, service, src(lines(LOGIN)), minutes=3).snapshot
    assert [c.text for c in v3.criteria] == [LOGIN]
    with pytest.raises(InvalidStateTransitionError):
        by_text(v2)[DELETE].transition_to(S.CONFIRMED)  # orphan cannot be confirmed


def test_orphaned_when_source_disappears_keeps_old_ref(env: Env) -> None:
    service = make_service(env)
    issue = src(lines(DELETE), IntentSourceKind.ISSUE, "7")
    v1 = build(env, service, src(lines(LOGIN)), issue).snapshot
    confirm(env, v1, DELETE)
    v2 = rebuild(env, service, src(lines(LOGIN))).snapshot
    orphan = by_text(v2)[DELETE]
    assert orphan.state is S.ORPHANED
    assert orphan.origin.source in v2.sources and orphan.origin.source == issue.ref
    assert {r.key for r in v2.sources} == {"pr_body:42", "issue:7"}


def test_confirmed_criterion_moved_between_sources_keeps_its_state(env: Env) -> None:
    service = make_service(env)
    v1 = build(
        env,
        service,
        src(lines(LOGIN)),
        src("Some title here", IntentSourceKind.PR_TITLE, "t"),
    ).snapshot
    confirm(env, v1, LOGIN)
    result = rebuild(
        env,
        service,
        src("", fetched=at(2)),
        src(lines("Some title here", LOGIN), IntentSourceKind.PR_TITLE, "t"),
    )
    moved = by_text(result.snapshot)[LOGIN]
    assert moved.state is S.CONFIRMED
    assert moved.origin.source.kind is IntentSourceKind.PR_TITLE
    assert "moved" in {e.action for e in result.report.carry_events}


def test_same_text_in_two_sources_is_deduplicated_by_priority(env: Env) -> None:
    body = src(lines(LOGIN))
    spec = src(lines(LOGIN), IntentSourceKind.SPEC_FILE, "docs/spec.md")
    result = build(env, make_service(env), body, spec)
    (only,) = result.snapshot.criteria
    assert only.origin.source.kind is IntentSourceKind.SPEC_FILE
    assert [d.code for d in result.report.diagnostics] == ["deduplicated"]


def test_human_authored_criterion_is_never_orphaned(env: Env) -> None:
    human = LineExtractor(
        "human-1", ExtractionMethod.HUMAN, kinds={IntentSourceKind.COMMENT}
    )
    comment = src(lines(EXPIRE), IntentSourceKind.COMMENT, "c1")
    service = make_service(env, human)
    v1 = build(env, service, comment).snapshot
    confirm(env, v1, EXPIRE)
    result = rebuild(env, service)  # comment not passed any more
    v2 = result.snapshot
    assert not result.created and v2.version == 1
    assert by_text(v2)[EXPIRE].state is S.CONFIRMED


# ------------------------------------------------------------------------ diff


def test_diff_reports_added_removed_changed_and_state_changes(env: Env) -> None:
    service = make_service(env)
    v1 = build(env, service, src(lines(LOGIN, DELETE, EXPIRE))).snapshot
    confirm(env, v1, LOGIN)
    confirm(env, v1, DELETE)
    confirm(env, v1, EXPIRE)
    reworded = "Users can log in with email or SSO"
    v2 = rebuild(
        env,
        service,
        src(lines("Preamble line", reworded, EXPIRE, "Brand new requirement")),
    ).snapshot
    diff = service.diff_snapshots(env.org_a, v1.snapshot_id, v2.snapshot_id)
    ids = {t: c.id for t, c in {**by_text(v1), **by_text(v2)}.items()}
    assert {c.text for c in diff.added} == {
        "Preamble line",
        reworded,
        "Brand new requirement",
    }
    assert {c.text for c in diff.removed} == {LOGIN}
    assert [d.criterion_id for d in diff.state_changed] == [
        ids[DELETE]
    ]  # confirmed -> orphaned
    assert diff.state_changed[0].state_before == "confirmed"
    assert diff.state_changed[0].state_after == "orphaned"
    assert diff.changed == ()
    assert ids[EXPIRE] in diff.moved  # same criterion, shifted span
    assert diff.sources_changed == ("pr_body:42",)
    assert not diff.is_empty
    assert (diff.from_version, diff.to_version) == (1, 2)
    again = service.diff_snapshots(env.org_a, v1.snapshot_id, v2.snapshot_id)
    assert json.dumps(diff.to_dict(), sort_keys=True) == json.dumps(
        again.to_dict(), sort_keys=True
    )
    ordered = [c.criterion_id for c in diff.added]
    assert ordered == sorted(ordered)


def test_diff_detects_field_changes_and_empty_diff(env: Env) -> None:
    service = make_service(env)
    v1 = build(env, service, src(lines(LOGIN))).snapshot
    assert diff_snapshot_pair(v1, v1).is_empty
    edited = v1.criteria[0].with_weight(0.5)
    from dataclasses import replace

    other = replace(
        v1,
        snapshot_id=str(uuid4()),
        version=2,
        parent_snapshot_id=v1.snapshot_id,
        criteria=(edited,),
    )
    diff = diff_snapshot_pair(v1, other)
    assert [c.changed_fields for c in diff.changed] == [("weight",)]
    assert diff.moved == ()


def test_diff_missing_snapshot_raises(env: Env) -> None:
    service = make_service(env)
    v1 = build(env, service, src(LOGIN)).snapshot
    with pytest.raises(SnapshotNotFoundError):
        service.diff_snapshots(env.org_a, v1.snapshot_id, str(uuid4()))


def test_latest_and_history(env: Env) -> None:
    service = make_service(env)
    assert service.latest(env.org_a, env.analysis_a) is None
    assert service.history(env.org_a, env.analysis_a) == ()
    v1 = build(env, service, src(LOGIN)).snapshot
    v2 = rebuild(env, service, src(lines(LOGIN, DELETE))).snapshot
    assert service.latest(env.org_a, env.analysis_a) == v2
    assert [s.version for s in service.history(env.org_a, env.analysis_a)] == [1, 2]
    assert service.history(env.org_a, env.analysis_a)[0].snapshot_id == v1.snapshot_id
    assert service.latest(env.org_a, env.analysis_a2) is None


# ----------------------------------------------------------------- tenant isolation


def test_other_organization_sees_nothing_and_cannot_diff(env: Env) -> None:
    service = make_service(env)
    v1 = build(env, service, src(LOGIN)).snapshot
    v2 = rebuild(env, service, src(lines(LOGIN, DELETE))).snapshot
    assert service.latest(env.org_b, env.analysis_a) is None
    assert service.history(env.org_b, env.analysis_a) == ()
    with pytest.raises(SnapshotNotFoundError):
        service.diff_snapshots(env.org_b, v1.snapshot_id, v2.snapshot_id)
    # Organization B's own analysis is unaffected by A's history.
    b = service.build_snapshot(env.analysis_b, env.org_b, [src(LOGIN)], T0)
    assert b.snapshot.version == 1 and b.created


# ------------------------------------------------------------------ concurrency


class StaleReadRepo(InMemoryIntentRepository):
    """Returns a stale 'no snapshot yet' once and runs a hook before the save."""

    def __init__(self, hook):
        super().__init__()
        self.hook = hook
        self.stale = True
        self.saves = 0

    def get_latest_snapshot(self, organization_id, analysis_id):
        if self.stale:
            self.stale = False
            return None
        return super().get_latest_snapshot(organization_id, analysis_id)

    def save_snapshot(self, organization_id, snapshot):
        self.saves += 1
        if self.saves == 1 and self.hook:
            hook, self.hook = self.hook, None
            hook()
        return super().save_snapshot(organization_id, snapshot)


def test_interleaved_identical_build_does_not_duplicate_versions() -> None:
    org, analysis = uuid4(), str(uuid4())
    sources = [src(lines(LOGIN, DELETE))]
    holder: dict = {}

    def competitor():
        holder["other"] = IntentSnapshotService(
            holder["repo"], (LineExtractor(),)
        ).build_snapshot(analysis, org, sources, at(1))

    repo = StaleReadRepo(competitor)
    holder["repo"] = repo
    result = IntentSnapshotService(repo, (LineExtractor(),)).build_snapshot(
        analysis, org, sources, at(1)
    )
    assert not result.created
    assert result.snapshot.snapshot_id == holder["other"].snapshot.snapshot_id
    assert len(repo.list_snapshots(org, analysis)) == 1


def test_interleaved_different_build_retries_to_next_version() -> None:
    org, analysis = uuid4(), str(uuid4())
    holder: dict = {}

    def competitor():
        holder["other"] = IntentSnapshotService(
            holder["repo"], (LineExtractor(),)
        ).build_snapshot(analysis, org, [src(lines(EXPIRE))], at(1))

    repo = StaleReadRepo(competitor)
    holder["repo"] = repo
    result = IntentSnapshotService(repo, (LineExtractor(),)).build_snapshot(
        analysis, org, [src(lines(LOGIN))], at(2)
    )
    assert result.created and result.snapshot.version == 2
    assert result.snapshot.parent_snapshot_id == holder["other"].snapshot.snapshot_id
    assert [s.version for s in repo.list_snapshots(org, analysis)] == [1, 2]


def test_conflicts_exhaust_retries_with_a_clear_error() -> None:
    class AlwaysConflict(InMemoryIntentRepository):
        def save_snapshot(self, organization_id, snapshot):
            raise SnapshotConflictError

    service = IntentSnapshotService(
        AlwaysConflict(), (LineExtractor(),), max_attempts=3
    )
    with pytest.raises(SnapshotBuildConflictError):
        service.build_snapshot(str(uuid4()), uuid4(), [src(LOGIN)], T0)


def test_threads_building_the_same_inputs_create_one_version() -> None:
    repo = InMemoryIntentRepository()
    org, analysis = uuid4(), str(uuid4())
    results, errors = [], []

    def work():
        try:
            service = IntentSnapshotService(repo, (LineExtractor(),))
            results.append(
                service.build_snapshot(analysis, org, [src(lines(LOGIN, DELETE))], T0)
            )
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(repo.list_snapshots(org, analysis)) == 1
    assert sum(r.created for r in results) == 1
    assert len({r.snapshot.snapshot_id for r in results}) == 1


# ------------------------------------------------------------ pure merge rules


def _crit(
    method, kind=IntentSourceKind.PR_BODY, text=LOGIN, source_id="1", version="v"
):
    s = IntentSource.from_text(source_id, kind, text, T0)
    return Criterion.create(
        s,
        Span(source_id, 0, len(text)),
        extraction_method=method,
        extractor_version=version,
    )


def test_priority_order_spec_file_human_deterministic_llm() -> None:
    spec = _crit(ExtractionMethod.LLM, IntentSourceKind.SPEC_FILE)
    human = _crit(ExtractionMethod.HUMAN)
    det = _crit(ExtractionMethod.DETERMINISTIC)
    llm = _crit(ExtractionMethod.LLM)
    assert [priority(c) for c in (spec, human, det, llm)] == [0, 1, 2, 3]


def test_same_id_conflict_resolved_by_method_priority_then_extractor_order() -> None:
    llm = _crit(ExtractionMethod.LLM, version="llm-1")
    det = _crit(ExtractionMethod.DETERMINISTIC, version="det-1")
    human = _crit(ExtractionMethod.HUMAN, version="h-1")
    assert llm.id == det.id == human.id
    for order in ((llm, det, human), (human, det, llm), (det, llm, human)):
        chosen, _ = select_criteria([Candidate(c, i) for i, c in enumerate(order)])
        assert chosen[0].origin.extraction_method is ExtractionMethod.HUMAN
    first, _ = select_criteria(
        [
            Candidate(_crit(ExtractionMethod.DETERMINISTIC, version="b"), 1),
            Candidate(_crit(ExtractionMethod.DETERMINISTIC, version="a"), 0),
        ]
    )
    assert first[0].origin.extractor_version == "a"
    tie, _ = select_criteria(
        [
            Candidate(_crit(ExtractionMethod.DETERMINISTIC, version="z"), 0),
            Candidate(_crit(ExtractionMethod.DETERMINISTIC, version="a"), 0),
        ]
    )
    assert tie[0].origin.extractor_version == "a"


def test_cross_source_dedupe_prefers_higher_priority_else_stable_order() -> None:
    llm_body = _crit(ExtractionMethod.LLM, source_id="1")
    det_issue = _crit(
        ExtractionMethod.DETERMINISTIC, IntentSourceKind.ISSUE, source_id="2"
    )
    kept, notes = select_criteria([Candidate(llm_body, 0), Candidate(det_issue, 1)])
    assert kept == (det_issue,) and notes[0].code == "deduplicated"
    a = _crit(ExtractionMethod.DETERMINISTIC, source_id="1")
    b = _crit(ExtractionMethod.DETERMINISTIC, source_id="2")
    for order in ((a, b), (b, a)):
        kept, _ = select_criteria([Candidate(c, i) for i, c in enumerate(order)])
        assert kept == (a,)


def test_plan_merge_without_previous_is_identity() -> None:
    crit = _crit(ExtractionMethod.DETERMINISTIC)
    plan = plan_merge((crit,), None, {})
    assert plan.final == (crit,) and plan.changes == () and plan.events == ()


def test_reword_matching_is_one_to_one_and_threshold_gated() -> None:
    service_repo = InMemoryIntentRepository()
    org, analysis = uuid4(), str(uuid4())
    service = IntentSnapshotService(service_repo, (LineExtractor(),))
    a, b = "Export reports as PDF files", "Export reports as CSV files"
    v1 = service.build_snapshot(analysis, org, [src(lines(a, b))], T0).snapshot
    for c in v1.criteria:
        service_repo.record_state_change(
            org, v1.snapshot_id, c.id, S.CONFIRMED, actor="u", changed_at=T0
        )
    v2 = service.on_sources_changed(
        analysis, org, [src(lines("Export reports as PDF files quickly"))], at(1)
    ).snapshot
    texts = by_text(v2)
    assert texts["Export reports as PDF files quickly"].state is S.NEEDS_RECONFIRMATION
    assert texts[b].state is S.ORPHANED  # second old criterion has no successor left
    assert len(v2.criteria) == 2


# ---------------------------------------------------------------- architecture


def test_application_layer_depends_only_on_domain_and_ports() -> None:
    root = Path(radius_intent.__file__).parent / "application"
    allowed = (
        "radius_intent.domain",
        "radius_intent.interfaces",
        "radius_intent.application",
    )
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                assert not node.level, f"relative import in {path.name}"
                names = [node.module or ""]
            for name in names:
                top = name.split(".")[0]
                ok = (
                    top in sys.stdlib_module_names
                    or top == "__future__"
                    or any(name == a or name.startswith(a + ".") for a in allowed)
                )
                assert ok, f"{path.name} imports {name}"


def test_orphan_followed_by_reworded_text_needs_reconfirmation(env: Env) -> None:
    service = make_service(env)
    v1 = build(env, service, src(lines(LOGIN, DELETE))).snapshot
    confirm(env, v1, DELETE)
    assert (
        by_text(rebuild(env, service, src(lines(LOGIN))).snapshot)[DELETE].state
        is S.ORPHANED
    )
    reworded = "Admins can delete users permanently"
    result = rebuild(env, service, src(lines(LOGIN, reworded)), minutes=2)
    texts = by_text(result.snapshot)
    assert texts[reworded].state is S.NEEDS_RECONFIRMATION
    assert DELETE not in texts
    json.dumps(result.report.to_dict())
    assert result.report.carry_events[0].to_dict()["action"] == "needs_reconfirmation"
