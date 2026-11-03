"""Human confirm / edit / reject refreshes the stored verdict inputs (DEC-033).

* ``refresh_stage_a_intent``: the stored Stage A takes the current criterion states;
  provenance is derived from the stored state only, never from anything else.
* ``StageBRecomputer`` with a real SQL session: a state change made through the intent
  repository (what the authenticated API does) changes the next stored revision.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from radius_evidence.domain.config import LinkMapping, VerdictV2Config
from radius_evidence.domain.inputs import (
    CriterionInput,
    CriterionSymbolEdgeInput,
    CriterionTestEdgeInput,
    StageAInput,
)
from radius_intent.domain import (
    CriterionState,
    IntentSnapshot,
    IntentSource,
    IntentSourceKind,
)
from radius_intent.infrastructure.extraction import (
    DeterministicCriterionExtractor,
    ExtractionConfig,
)
from radius_intent.infrastructure.sqlalchemy_repository import (
    SqlAlchemyIntentRepository,
)
from radius_shared.database import enums as db_enums
from radius_shared.database.base import Base
from radius_shared.database.models import (
    Analysis,
    Organization,
    PullRequest,
    Repository,
)
from radius_shared.verdict_v2_flag import VerdictV2Mode
from radius_worker.verdict_v2 import adapters
from radius_worker.verdict_v2.intent_refresh import refresh_stage_a_intent
from radius_worker.verdict_v2.scoring import (
    HINT_METHOD,
    ScoringPipeline,
    StageBRecomputer,
    build_stage_b,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "docs" / "research" / "design").is_dir()
)
MARKER = adapters.UNCONFIRMED_INFERRED_MARKER
NOW = datetime(2026, 11, 3, tzinfo=UTC)
SHA = "c" * 40


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "verdict_v2_run_intent_refresh", ROOT / "scripts" / "verdict_v2_run.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RUN = _load_script()
F01 = next(p for p in RUN.fixture_dirs([]) if p.name == "01_correct_strong_tests")


def db(cid: str, state: str, *, text: str = "t", version: str = "det-1", **extra):
    return NS(
        id=cid, text=text, state=NS(value=state), origin=NS(extractor_version=version), **extra
    )


# ------------------------------------------------------- the fixture, scored for real


def _score(stage_a: StageAInput) -> dict:
    expected = json.loads((F01 / "expected.json").read_text(encoding="utf-8"))
    cases = RUN.cases_for(expected)
    stage_b = build_stage_b(stage_a, cases=RUN.adapters.case_inputs(cases).items, uploads=1)
    scored = ScoringPipeline(
        config=VerdictV2Config(link=LinkMapping()), mode="shadow", clock=RUN._fixed_clock
    ).score_full(stage_b)
    return scored.payload


@pytest.fixture(scope="module")
def capped_stage_a() -> StageAInput:
    """Fixture 01 whose hints and criteria came from the PR author (capped at 0.7)."""

    return RUN.collect_stage_a(F01, "gold", "static", "author_head_spec")


def _ids(stage_a: StageAInput) -> list[str]:
    return [c.criterion_id for c in stage_a.criteria]


def test_baseline_author_hints_are_capped_and_the_verdict_is_not_verified(capped_stage_a) -> None:
    payload = _score(capped_stage_a)
    assert payload["verdict"] == "insufficient_evidence"
    assert payload["summary"]["author_hint_criteria"] == 2


def test_still_proposed_criteria_stay_capped(capped_stage_a) -> None:
    current = [db(cid, "proposed") for cid in _ids(capped_stage_a)]
    payload = _score(refresh_stage_a_intent(capped_stage_a, current))
    assert payload["verdict"] == "insufficient_evidence"
    assert payload["summary"]["author_hint_criteria"] == 2


def test_confirming_every_criterion_lifts_the_author_hint_cap(capped_stage_a) -> None:
    current = [db(cid, "confirmed") for cid in _ids(capped_stage_a)]

    refreshed = refresh_stage_a_intent(capped_stage_a, current)
    payload = _score(refreshed)

    assert payload["verdict"] == "verified"
    assert payload["summary"]["author_hint_criteria"] == 0
    assert {c["provenance"] for c in payload["criteria"]} == {"human_confirmed"}
    assert all("author_supplied_hint" not in c["flags"] for c in payload["criteria"])
    assert {
        e.provenance for e in refreshed.criterion_test if e.method == HINT_METHOD
    } == {"human_confirmed"}


def test_confirming_one_criterion_lifts_only_that_cap(capped_stage_a) -> None:
    first, second = _ids(capped_stage_a)[:2]
    current = [db(first, "confirmed"), db(second, "proposed")]

    payload = _score(refresh_stage_a_intent(capped_stage_a, current))

    by_id = {c["criterion_id"]: c for c in payload["criteria"]}
    assert "author_supplied_hint" not in by_id[first]["flags"]
    assert "author_supplied_hint" in by_id[second]["flags"]
    assert payload["summary"]["author_hint_criteria"] == 1
    assert payload["verdict"] != "verified"


def test_rejecting_a_criterion_excludes_it_and_its_edges(capped_stage_a) -> None:
    first, second = _ids(capped_stage_a)[:2]
    current = [db(first, "rejected"), db(second, "confirmed")]

    refreshed = refresh_stage_a_intent(capped_stage_a, current)

    assert _ids(refreshed) == [second]
    assert all(e.criterion_id == second for e in refreshed.criterion_test)
    assert all(e.criterion_id == second for e in refreshed.criterion_symbol)
    payload = _score(refreshed)
    assert [c["criterion_id"] for c in payload["criteria"]] == [second]


def test_edit_updates_the_text_and_counts_as_human_confirmed(capped_stage_a) -> None:
    first = _ids(capped_stage_a)[0]

    refreshed = refresh_stage_a_intent(
        capped_stage_a, [db(first, "edited", text="A reworded criterion")]
    )

    item = next(c for c in refreshed.criteria if c.criterion_id == first)
    assert (item.lifecycle, item.text) == ("edited", "A reworded criterion")
    assert item.provenance == item.hints_provenance == "human_confirmed"


def test_refresh_is_idempotent_and_a_no_op_without_changes(capped_stage_a) -> None:
    current = [db(cid, "confirmed") for cid in _ids(capped_stage_a)]
    once = refresh_stage_a_intent(capped_stage_a, current)
    assert refresh_stage_a_intent(once, current) == once
    # an empty list and unknown dropped ids change nothing
    assert refresh_stage_a_intent(capped_stage_a, []) == capped_stage_a
    assert refresh_stage_a_intent(capped_stage_a, [db("nope", "rejected")]) == capped_stage_a
    # B-09: an unknown LIVE criterion is not scored, but no longer silently: it is marked
    marked = refresh_stage_a_intent(capped_stage_a, [db("nope", "confirmed")])
    assert marked.degraded == (*capped_stage_a.degraded, "intent_not_in_analysis:1")
    assert replace(marked, degraded=capped_stage_a.degraded) == capped_stage_a


def test_reopening_demotes_human_confirmed_provenance_to_the_capped_default() -> None:
    sa = _stage_a_with_hint(provenance="human_confirmed", hint_provenance="human_confirmed")

    refreshed = refresh_stage_a_intent(sa, [db("C1", "proposed")])

    item = refreshed.criteria[0]
    assert item.lifecycle == "proposed"
    assert item.provenance == item.hints_provenance == "author_pr_body"
    assert refreshed.criterion_test[0].provenance == "author_pr_body"
    # a base-branch spec hint is not touched by a state change
    base = _stage_a_with_hint(provenance="base_spec", hint_provenance="base_spec")
    assert refresh_stage_a_intent(base, [db("C1", "proposed")]).criterion_test[0].provenance == (
        "base_spec"
    )


def test_provenance_comes_only_from_the_stored_state_not_from_attributes() -> None:
    sa = _stage_a_with_hint(provenance="author_pr_body", hint_provenance="author_pr_body")
    # a look-alike carrying its own provenance tag must not be believed
    liar = db("C1", "proposed", provenance="human_confirmed", hints_provenance="human_confirmed")

    refreshed = refresh_stage_a_intent(sa, [liar])

    assert refreshed.criteria[0].provenance == "author_pr_body"
    assert refreshed.criterion_test[0].provenance == "author_pr_body"


def _stage_a_with_hint(*, provenance: str, hint_provenance: str) -> StageAInput:
    return StageAInput(
        analysis_id="a", repository_id="r", head_sha="0" * 40, changeset_ref="x",
        criteria=(
            CriterionInput(
                "C1", "t", 1.0, "behavioral_testable", "confirmed",
                provenance=provenance, hints_provenance=hint_provenance,
            ),
        ),
        symbols=(),
        criterion_symbol=(CriterionSymbolEdgeInput("C1", "s", 0.5, 1),),
        symbol_test=(), assertions=(), tamper=(),
        criterion_test=(
            CriterionTestEdgeInput("C1", "t.py::t", 1.0, HINT_METHOD, provenance=provenance),
        ),
    )


# ------------------------------------- unconfirmed_inferred_intent (DEC-032) is lifted


def _summary_criteria():
    body = (
        "## Summary\n- Rejects uploads larger than 5 MB with a 413\n"
        "- Users no longer see the banner\n"
    )
    source = IntentSource.from_text("pr-body", IntentSourceKind.PR_BODY, body, NOW)
    return source, DeterministicCriterionExtractor(ExtractionConfig(mode="summary")).extract(
        source
    )


def _inferred_stage_a(criteria) -> StageAInput:
    items = adapters.criterion_inputs(criteria).items
    return StageAInput(
        analysis_id="a", repository_id="r", head_sha="0" * 40, changeset_ref="x",
        criteria=items, symbols=(), criterion_symbol=(), symbol_test=(),
        criterion_test=(), assertions=(), tamper=(), degraded=("truncated", MARKER),
    )


def test_unconfirmed_inferred_intent_lifts_only_when_all_are_confirmed() -> None:
    _, (first, second) = _summary_criteria()
    sa = _inferred_stage_a((first, second))
    assert MARKER in sa.degraded

    one = refresh_stage_a_intent(sa, [first.confirm(), second])
    assert MARKER in one.degraded

    both = refresh_stage_a_intent(sa, [first.confirm(), second.edit("Users never see the banner")])
    assert MARKER not in both.degraded
    assert both.degraded == ("truncated",)  # other degraded reasons are kept

    rejected = refresh_stage_a_intent(sa, [first.confirm(), second.reject()])
    assert MARKER not in rejected.degraded
    assert [c.criterion_id for c in rejected.criteria] == [first.id]


def test_reopening_a_confirmed_inferred_criterion_restores_the_block() -> None:
    _, (first, second) = _summary_criteria()
    sa = _inferred_stage_a((first, second))
    lifted = refresh_stage_a_intent(sa, [first.confirm(), second.confirm()])
    assert MARKER not in lifted.degraded

    again = refresh_stage_a_intent(lifted, [first.confirm(), second])

    assert MARKER in again.degraded


# ---------------------------------------------------- the recomputer on a real SQL session


def _sql_env():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        org = Organization(name="Acme", github_installation_id=1, github_installation_status="active")
        repo = Repository(
            organization=org, github_repository_id=2, name="r", owner="o",
            default_branch="main", clone_url="https://example.invalid/o/r.git",
            visibility=db_enums.RepositoryVisibility.PRIVATE,
            status=db_enums.RepositoryStatus.CONNECTED)
        pr = PullRequest(repository=repo, github_pr_number=1, title="t",
                         source_branch="f", target_branch="main", author="a",
                         status=db_enums.PullRequestStatus.OPEN, opened_at=NOW)
        analysis = Analysis(repository=repo, pull_request=pr, commit_sha=SHA,
                            status=db_enums.AnalysisStatus.PENDING, started_at=NOW,
                            created_at=NOW)
        session.add_all([org, repo, pr, analysis])
        session.flush()
        ids = (analysis.id, org.id)
        session.commit()
    return factory, ids


class MemoryStore:
    """Mimics ``SqlVerdictStore``: the newest bundle's Stage A is what is re-scored."""

    def __init__(self, stage_a: StageAInput) -> None:
        self.bundles: list[dict] = []
        self._first = stage_a

    def latest_stage_a(self, organization_id, analysis_id):  # noqa: ARG002
        for bundle in reversed(self.bundles):  # error rows carry no Stage A (like the SQL repo)
            if bundle.get("stage_a"):
                return StageAInput.from_dict(bundle["stage_a"])
        return self._first

    def latest_head(self, organization_id, analysis_id):  # noqa: ARG002
        return SHA

    def save(self, organization_id, analysis_id, bundle):  # noqa: ARG002
        if self.bundles and self.bundles[-1]["inputs_digest"] == bundle["inputs_digest"]:
            return False
        self.bundles.append(bundle)
        return True


def test_recomputer_stores_a_new_revision_after_a_confirm_and_none_when_repeated() -> None:
    factory, (analysis_id, org_id) = _sql_env()
    source, (first, second) = _summary_criteria()
    snapshot_id = str(uuid4())
    with factory() as session:
        repo = SqlAlchemyIntentRepository(session)
        repo.save_sources(org_id, str(analysis_id), (source,))
        repo.save_snapshot(org_id, IntentSnapshot(
            snapshot_id=snapshot_id, analysis_id=str(analysis_id), version=1,
            created_at=NOW, criteria=(first, second), sources=(source.ref,)))
        session.commit()
    store = MemoryStore(replace(_inferred_stage_a((first, second)), head_sha=SHA))
    rec = StageBRecomputer(store, VerdictV2Mode.ON, clock=lambda: NOW)

    def recompute() -> bool:
        with factory() as session:
            return rec.recompute(session, org_id, analysis_id)

    def confirm(criterion) -> None:
        with factory() as session:
            SqlAlchemyIntentRepository(session).record_state_change(
                org_id, snapshot_id, criterion.id, CriterionState.CONFIRMED,
                actor="org:test", changed_at=NOW,
            )
            session.commit()

    # nothing changed in the database: the first run only re-scores the stored Stage A
    assert recompute() is True
    assert MARKER in store.bundles[-1]["degraded"]
    assert recompute() is False  # identical inputs: no new revision

    confirm(first)
    assert recompute() is True
    assert MARKER in store.bundles[-1]["degraded"]  # one criterion is still unconfirmed
    assert recompute() is False

    confirm(second)
    assert recompute() is True
    last = store.bundles[-1]
    assert MARKER not in last["degraded"]
    assert {c["provenance"] for c in last["verdict"]["criteria"]} == {"human_confirmed"}
    assert recompute() is False
    assert len(store.bundles) == 3


def test_recomputer_fails_loudly_when_the_intent_cannot_be_read() -> None:
    factory, (analysis_id, org_id) = _sql_env()
    _, (first, second) = _summary_criteria()
    store = MemoryStore(replace(_inferred_stage_a((first, second)), head_sha=SHA))
    rec = StageBRecomputer(store, VerdictV2Mode.ON, clock=lambda: NOW)

    class Broken:
        def execute(self, *args, **kwargs):
            raise RuntimeError("database unavailable")

        def __getattr__(self, name):
            raise RuntimeError("database unavailable")

    with pytest.raises(RuntimeError):
        rec.recompute(Broken(), org_id, analysis_id)
    # B-01/B-04: the failure is recorded as the newest revision so an older (possibly
    # verified) verdict is not current any more; the outbox still retries
    assert [b["status"] for b in store.bundles] == ["error"]
    assert store.bundles[0]["verdict"] is None
    assert store.bundles[0]["reason_code"].startswith("recompute_failed:")


def test_recompute_failure_after_a_stored_verdict_replaces_it_with_an_error_row() -> None:
    from radius_worker.verdict_v2 import scoring

    factory, (analysis_id, org_id) = _sql_env()
    _, (first, second) = _summary_criteria()
    store = MemoryStore(replace(_inferred_stage_a((first, second)), head_sha=SHA))
    rec = StageBRecomputer(store, VerdictV2Mode.ON, clock=lambda: NOW)
    with factory() as session:
        assert rec.recompute(session, org_id, analysis_id) is True
    assert store.bundles[-1]["status"] == "ok"

    original = scoring.compute_pipeline

    def boom(*args, **kwargs):
        raise ValueError("invariant")

    scoring.compute_pipeline = boom
    try:
        with factory() as session, pytest.raises(ValueError):
            rec.recompute(session, org_id, analysis_id)
    finally:
        scoring.compute_pipeline = original
    assert store.bundles[-1]["status"] == "error"
    assert store.bundles[-1]["reason_code"] == "recompute_failed:ValueError"
    # and the next successful run replaces the error row again
    with factory() as session:
        assert rec.recompute(session, org_id, analysis_id) is True
    assert store.bundles[-1]["status"] == "ok"


# ------------------------------------------------------- B-07 separation of duties


def test_b07_confirmation_by_someone_else_lifts_the_cap_and_records_who(capped_stage_a) -> None:
    current = [db(cid, "confirmed") for cid in _ids(capped_stage_a)]
    actors = {cid: "org:1234/reviewer-bob" for cid in _ids(capped_stage_a)}

    refreshed = refresh_stage_a_intent(capped_stage_a, current, actors=actors, pr_author="alice")
    payload = _score(refreshed)

    assert payload["verdict"] == "verified"
    assert {c["confirmed_by"] for c in payload["criteria"]} == {"reviewer-bob"}


def test_b07_the_pr_author_confirming_their_own_criteria_does_not_lift_anything(
    capped_stage_a,
) -> None:
    current = [db(cid, "confirmed") for cid in _ids(capped_stage_a)]
    actors = {cid: "org:1234/Alice" for cid in _ids(capped_stage_a)}  # case-insensitive

    refreshed = refresh_stage_a_intent(capped_stage_a, current, actors=actors, pr_author="alice")
    payload = _score(refreshed)

    assert payload["verdict"] == "insufficient_evidence"
    assert payload["summary"]["author_hint_criteria"] == 2  # the cap stays
    assert all(c["provenance"] != "human_confirmed" for c in payload["criteria"])
    assert all("not counted" in c["confirmed_by"] for c in payload["criteria"])


def test_b07_self_confirmation_keeps_the_unconfirmed_inferred_block() -> None:
    sa = _inferred_stage_a(_summary_criteria()[1])
    current = [db("C1", "confirmed", version="det-extract-summary-1")]
    me = refresh_stage_a_intent(sa, current, actors={"C1": "org:1/me"}, pr_author="me")
    assert MARKER in me.degraded
    other = refresh_stage_a_intent(sa, current, actors={"C1": "org:1/you"}, pr_author="me")
    assert MARKER not in other.degraded


def test_b07_unknown_author_or_missing_label_cannot_be_compared_and_confirms_as_before(
    capped_stage_a,
) -> None:
    current = [db(cid, "confirmed") for cid in _ids(capped_stage_a)]
    for actors, author in (({}, "alice"), ({c: "org:1/alice" for c in _ids(capped_stage_a)}, None)):
        refreshed = refresh_stage_a_intent(capped_stage_a, current, actors=actors, pr_author=author)
        assert _score(refreshed)["verdict"] == "verified"  # documented residual risk


def test_b07_policy_hook_can_be_replaced() -> None:
    sa = _stage_a_with_hint(provenance="author_pr_body", hint_provenance="author_pr_body")
    refreshed = refresh_stage_a_intent(
        sa, [db("C1", "confirmed")], actors={"C1": "org:1/anyone"}, pr_author="x",
        confirm_policy=lambda label, author: True,  # "nobody may confirm" (strict deployments)
    )
    assert refreshed.criteria[0].provenance == "author_pr_body"
    assert refreshed.criteria[0].lifecycle == "proposed"


def test_b09_a_criterion_added_after_the_analysis_blocks_verified_visibly(capped_stage_a) -> None:
    from radius_confidence.verdict_v2.domain.rules import is_blocking_degraded

    current = [db(cid, "confirmed") for cid in _ids(capped_stage_a)]
    assert not any(
        d.startswith("intent_not_in_analysis:")
        for d in refresh_stage_a_intent(capped_stage_a, current).degraded
    )
    manual = db("manual-1", "confirmed", text="a human added this")
    refreshed = refresh_stage_a_intent(capped_stage_a, [*current, manual])
    assert "intent_not_in_analysis:1" in refreshed.degraded
    assert is_blocking_degraded("intent_not_in_analysis:1")
    assert _score(refreshed)["verdict"] == "insufficient_evidence"
    # rejected criteria the analysis never saw do not count; the marker is not duplicated
    again = refresh_stage_a_intent(refreshed, [*current, manual, db("gone", "rejected")])
    assert [d for d in again.degraded if d.startswith("intent_not_in_analysis:")] == [
        "intent_not_in_analysis:1"
    ]
