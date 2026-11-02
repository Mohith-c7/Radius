"""Stage A collector (VS-05): isolation of every producer, budgets and the SQL sources."""

from __future__ import annotations

import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from radius_evidence.domain.inputs import StageAInput
from radius_intent.domain import (
    Criterion,
    ExtractionMethod,
    IntentSnapshot,
    IntentSource,
    IntentSourceKind,
    Span,
    Testability,
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
from radius_testing.domain.entities import ReportedTestCase
from radius_worker.verdict_v2 import collect, sources
from radius_worker.verdict_v2.collect import (
    CollectLimits,
    Producers,
    StageAError,
    VerdictStageACollector,
    guarded,
)
from radius_worker.verdict_v2.sources import IntentFacts, StaticIntent
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

SHA = "c" * 40
SYM_ID = "python:src/a.py::f#function@abc"
TEST_ID = "tests/test_a.py::test_f"


def criterion(cid="C1", **kw):
    base = {
        "id": cid, "text": "f returns one", "state": "confirmed", "weight": 1.0,
        "testability": "behavioral_testable", "hints": NS(paths=(), tests=()),
    }
    return NS(**{**base, **kw})


def changed(symbol_id=SYM_ID, path="src/a.py", qname="f", **kw):
    base = {
        "symbol_id": symbol_id, "path": path, "qualified_name": qname, "kind": "function",
        "language": "python", "change_kind": NS(value="modified_body"), "is_behavioral": True,
        "new_range": None, "old_range": None,
    }
    return NS(**{**base, **kw})


def changeset(*symbols, truncated=False):
    return NS(symbols=symbols or (changed(),), truncated=truncated,
              algo_version="symbol-changes-v1", to_json=lambda: "{}")


def tamper_report(**kw):
    base = {"findings": (), "waived": (), "unanalyzable": (), "truncated": False,
            "rule_errors": (), "catalog_version": "tamper-rules-v1"}
    return NS(**{**base, **kw})


def make_links(*pairs):
    return NS(
        links=tuple(
            NS(symbol_id=s, test_id=t, score=0.9, kind=NS(value="direct_call"), depth=None)
            for s, t in (pairs or ((SYM_ID, TEST_ID),))
        ),
        algo_version="link-combine-v1",
    )


def assertion_set():
    return NS(
        algo_version="assertion-extract-v1",
        to_dict=lambda: {
            "assertions": [{
                "test_id": TEST_ID, "kind": "equality",
                "expected": {"form": "literal", "text": "1"},
                "location": {"line": 3, "path": "tests/test_a.py"},
                "subject": {"text": "f()", "refs": [{"name": "f"}]},
                "strength_features": {},
            }],
            "tests": [{"test_id": TEST_ID, "path": "tests/test_a.py", "line": 2}],
        },
    )


def good_producers(**over):
    base = dict(
        symbol_changes=lambda command: changeset(),
        tamper=lambda cs, command: tamper_report(),
        link_criteria=lambda criteria, cs, command, srcs: NS(
            links=(NS(criterion_id="C1", symbol_id=SYM_ID, linker="combined", score=0.8,
                      rank=1, evidence=()),),
            by_linker=(), algo_version="criterion-symbol-links-v1"),
        link_tests=lambda srcs, targets: make_links(),
        assertions=lambda files, srcs, links, targets: assertion_set(),
        relevance=lambda crit, cl, tl, srcs, aset: [
            {"criterion_id": "C1", "test_id": TEST_ID, "weight": 0.7}
        ],
        read_sources=lambda root: ({"src/a.py": "def f(): return 1\n"}, False),
    )
    base.update(over)
    return Producers(**base)


class Sha:
    def __init__(self, sha=SHA):
        self.sha = sha

    def head_sha(self, analysis_id, command):  # noqa: ARG002
        return self.sha


def collector(producers=None, criteria=None, messages=(), limits=None, sha=SHA, intent=None):
    return VerdictStageACollector(
        intent or StaticIntent(IntentFacts(
            criteria=(criterion(),) if criteria is None else criteria,
            commit_messages=messages)),
        head_sha_port=Sha(sha),
        producers=producers or good_producers(),
        limits=limits,
    )


COMMAND = NS(repository_id=uuid4(), repository_path=Path("."), diff_text="d",
             base_ref=None, head_ref=None)


def collect_once(**kw) -> StageAInput:
    return collector(**kw).collect(uuid4(), COMMAND)


# ------------------------------------------------------------------ happy path


def test_collect_builds_the_stage_a_input() -> None:
    sa = collect_once(messages=("fix\n\nCo-Authored-By: Claude <c@x>",))
    assert sa.head_sha == SHA and len(sa.criteria) == 1
    assert [s.symbol_id for s in sa.symbols] == [SYM_ID]
    assert [(e.criterion_id, e.symbol_id) for e in sa.criterion_symbol] == [("C1", SYM_ID)]
    assert [e.test_id for e in sa.symbol_test] == [TEST_ID]
    assert [e.test_id for e in sa.criterion_test] == [TEST_ID]
    assert sa.criterion_test[0].weight == 0.7
    assert sa.assertions[0].test_id == TEST_ID
    assert sa.agent_signal is True
    assert sa.degraded == ()
    assert sa.algo_versions["tamper"] == "tamper-rules-v1"
    assert sa.algo_versions["symbol_test_links"] == "link-combine-v1"
    assert StageAInput.from_dict(sa.to_dict()) == sa


def test_hints_become_criterion_test_edges_and_win_over_relevance() -> None:
    c = criterion(hints=NS(paths=("src/a.py",), tests=(TEST_ID, "tests/test_a.py::nope")))
    sa = collect_once(criteria=(c,))
    edge = sa.criterion_test[0]
    assert (edge.test_id, edge.weight, edge.method) == (TEST_ID, 1.0, "intent_yml_hint")
    assert "adapter_dropped:hint_unresolved" in sa.degraded


def test_relevance_unavailable_marker_and_no_credit_without_hints() -> None:
    sa = collect_once(producers=good_producers(relevance=None))
    assert sa.criterion_test == ()
    assert "relevance_unavailable" in sa.degraded


def test_no_criteria_skips_linking_and_is_not_an_error() -> None:
    calls = []
    sa = collect_once(
        criteria=(),
        producers=good_producers(link_criteria=lambda *a: calls.append(a)),
    )
    assert sa.criteria == () and sa.criterion_symbol == () and calls == []


def test_dynamic_links_hook_is_used_when_provided() -> None:
    seen = []

    def dyn(srcs, targets, links):
        seen.append(len(targets))
        return make_links((SYM_ID, TEST_ID), (SYM_ID, "tests/test_a.py::test_g"))

    sa = collect_once(producers=good_producers(dynamic_links=dyn))
    assert seen == [1] and len(sa.symbol_test) == 2


def test_changed_tests_and_test_symbols_are_marked() -> None:
    cs = changeset(changed(), changed(symbol_id="t1", path="tests/test_a.py", qname="test_f"))
    sa = collect_once(producers=good_producers(symbol_changes=lambda c: cs))
    assert sa.changed_test_ids == frozenset({TEST_ID})
    assert next(s for s in sa.symbols if s.path == "tests/test_a.py").is_test


# ------------------------------------------------------------------ critical failures


def test_symbol_changes_failure_is_a_stage_error() -> None:
    def boom(command):
        raise RuntimeError("internal text that must not leak")

    with pytest.raises(StageAError) as err:
        collect_once(producers=good_producers(symbol_changes=boom))
    assert err.value.reason_code == "symbol_changes_failed"


def test_tamper_failure_is_a_stage_error() -> None:
    def boom(cs, command):
        raise RuntimeError("x")

    with pytest.raises(StageAError, match="tamper_failed"):
        collect_once(producers=good_producers(tamper=boom))


def test_tamper_rule_errors_are_a_stage_error() -> None:
    with pytest.raises(StageAError, match="tamper_incomplete"):
        collect_once(producers=good_producers(tamper=lambda cs, c: tamper_report(rule_errors=("T001",))))


def test_critical_timeout_is_a_stage_error() -> None:
    def slow(command):
        time.sleep(0.5)
        return changeset()

    with pytest.raises(StageAError, match="symbol_changes_timeout"):
        collect_once(
            producers=good_producers(symbol_changes=slow),
            limits=CollectLimits(step_timeout_s=0.05),
        )


def test_intent_load_failure_is_a_stage_error() -> None:
    class Broken:
        def load(self, analysis_id):
            raise RuntimeError("db")

    with pytest.raises(StageAError, match="intent_load_failed"):
        collect_once(intent=Broken())


def test_unresolved_head_sha_is_a_stage_error(monkeypatch) -> None:
    monkeypatch.setattr(collect, "resolve_head_sha", lambda command: None)
    with pytest.raises(StageAError, match="head_sha_unresolved"):
        collector(sha=None).collect(uuid4(), COMMAND)


# ------------------------------------------------------------------ degradation


@pytest.mark.parametrize(
    ("name", "marker"),
    [
        ("link_criteria", "producer_failed:criterion_symbol_links"),
        ("link_tests", "producer_failed:symbol_test_links"),
        ("assertions", "producer_failed:assertions"),
        ("relevance", "producer_failed:relevance"),
    ],
)
def test_non_critical_failure_degrades_without_raising(name, marker) -> None:
    def boom(*args):
        raise ValueError("x")

    sa = collect_once(producers=good_producers(**{name: boom}))
    assert marker in sa.degraded
    assert sa.head_sha == SHA  # the rest of the analysis is intact


def test_read_sources_failure_degrades() -> None:
    def boom(root):
        raise OSError("x")

    sa = collect_once(producers=good_producers(read_sources=boom))
    assert "producer_failed:read_sources" in sa.degraded


def test_non_critical_timeout_marks_truncated() -> None:
    def slow(srcs, targets):
        time.sleep(0.5)
        return make_links()

    sa = collect_once(
        producers=good_producers(link_tests=slow), limits=CollectLimits(step_timeout_s=0.05)
    )
    assert "producer_timeout:symbol_test_links" in sa.degraded
    assert "truncated" in sa.degraded
    assert sa.symbol_test == ()


def test_exhausted_total_budget_is_a_stage_error() -> None:
    with pytest.raises(StageAError, match="symbol_changes_timeout"):
        collect_once(limits=CollectLimits(timeout_s=0.0))


def test_limits_and_producer_flags_mark_truncated() -> None:
    cs = changeset(changed(), changed(symbol_id="s2", path="src/b.py", qname="g"), truncated=True)
    sa = collect_once(
        producers=good_producers(symbol_changes=lambda c: cs),
        limits=CollectLimits(max_symbols=1),
    )
    assert "truncated" in sa.degraded and len(sa.symbols) == 1


def test_criteria_over_limit_truncates() -> None:
    sa = collect_once(
        criteria=tuple(criterion(cid=f"C{i}") for i in range(3)),
        limits=CollectLimits(max_criteria=2),
    )
    assert len(sa.criteria) == 2 and "truncated" in sa.degraded


def test_tests_over_limit_truncates() -> None:
    links = make_links((SYM_ID, TEST_ID), (SYM_ID, "tests/test_a.py::test_g"))
    sa = collect_once(
        producers=good_producers(link_tests=lambda s, t: links),
        limits=CollectLimits(max_tests=1),
    )
    assert len({e.test_id for e in sa.symbol_test}) == 1 and "truncated" in sa.degraded


def test_tamper_truncation_and_unsupported_language_are_blocking_markers() -> None:
    cs = changeset(changed(), changed(symbol_id="ts1", path="web/a.ts", qname="h", language="typescript"))
    sa = collect_once(
        producers=good_producers(
            symbol_changes=lambda c: cs,
            tamper=lambda c, cmd: tamper_report(truncated=True),
        )
    )
    assert {"truncated", "unsupported_language:typescript"} <= set(sa.degraded)


def test_tamper_findings_and_waived_counts_are_carried() -> None:
    finding = NS(to_dict=lambda: {
        "finding_id": "tf_1", "rule_id": "T001", "check": "c", "severity": "high",
        "confidence": 0.9, "path": "tests/test_a.py", "reason": "r"})
    sa = collect_once(
        producers=good_producers(
            tamper=lambda c, cmd: tamper_report(
                findings=(finding,), waived=(1, 2), unanalyzable=(NS(path="z.py"),))
        )
    )
    assert [f.finding_id for f in sa.tamper] == ["tf_1"]
    assert sa.tamper_waived == 2 and sa.tamper_unanalyzable == ("z.py",)


def test_guarded_runs_and_times_out() -> None:
    assert guarded(lambda: 3, 1.0) == 3
    with pytest.raises(collect.ProducerTimeoutError):
        guarded(lambda: time.sleep(0.5), 0.05)
    with pytest.raises(collect.ProducerTimeoutError):
        guarded(lambda: 1, 0)
    with pytest.raises(ValueError):
        guarded(lambda: (_ for _ in ()).throw(ValueError("x")), 1.0)


# ------------------------------------------------------------------ default producers


def test_default_snapshots_need_a_diff_source() -> None:
    with pytest.raises(StageAError, match="no_diff_source"):
        collect._snapshots(NS(repository_path=Path("."), base_ref=None, head_ref=None, diff_text=None))


def test_default_link_targets_skip_tests_and_files() -> None:
    cs = changeset(
        changed(),
        changed(symbol_id="t", path="tests/test_a.py", qname="test_f"),
        changed(symbol_id="f", path="README.md", qname="<file>", kind="file"),
    )
    syms = collect.adapters.symbol_inputs(cs).items
    targets = VerdictStageACollector._link_targets(cs, syms)
    assert [t.symbol_id for t in targets] == [SYM_ID]


# ------------------------------------------------------------------ sources


def test_read_python_sources_skips_junk(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "b.py").write_text("y = 2\n", encoding="utf-8")
    (tmp_path / "bad.py").write_bytes(b"\xff\xfe\x00bad")
    (tmp_path / "big.py").write_text("z = 3\n" * 10, encoding="utf-8")
    got, truncated = sources.read_python_sources(tmp_path, max_bytes=40)
    assert set(got) == {"pkg/a.py"} and not truncated
    got, truncated = sources.read_python_sources(tmp_path, max_files=1)
    assert len(got) == 1 and truncated


def test_read_python_sources_skips_symlinks(tmp_path: Path) -> None:
    outside = tmp_path / "outside.py"
    outside.write_text("secret = 1\n", encoding="utf-8")
    root = tmp_path / "repo"
    root.mkdir()
    try:
        (root / "link.py").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    assert sources.read_python_sources(root)[0] == {}


def test_resolve_head_sha(monkeypatch, tmp_path: Path) -> None:
    assert sources.resolve_head_sha(NS(head_ref=SHA.upper(), repository_path=tmp_path)) == SHA
    assert sources.resolve_head_sha(NS(head_ref="main", repository_path=None)) is None

    class Done:
        returncode, stdout = 0, SHA + "\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done())
    assert sources.resolve_head_sha(NS(head_ref="main", repository_path=tmp_path)) == SHA

    class Bad:
        returncode, stdout = 1, ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Bad())
    assert sources.resolve_head_sha(NS(head_ref=None, repository_path=tmp_path)) is None

    def oserror(*a, **k):
        raise OSError("no git")

    monkeypatch.setattr(subprocess, "run", oserror)
    assert sources.resolve_head_sha(NS(head_ref=None, repository_path=tmp_path)) is None


def upload(commit, *cases, flaky=()):
    return NS(commit_sha=commit, cases=cases, result=NS(flaky_tests=flaky))


def test_outcomes_from_uploads_bind_to_head_and_merge() -> None:
    sa = StageAInput(
        analysis_id="a", repository_id="r", head_sha=SHA, changeset_ref="x",
        criteria=(), symbols=(), criterion_symbol=(), symbol_test=(),
        criterion_test=(), assertions=(), tamper=(),
        changed_test_ids=frozenset({TEST_ID}),
    )
    uploads = [
        upload(SHA, ReportedTestCase("tests/test_a.py", None, "test_f", "passed"),
               flaky=("tests/test_a.py::test_f",)),
        upload(SHA.upper(), ReportedTestCase("tests/test_a.py", None, "test_f", "failed")),
        upload("d" * 40, ReportedTestCase("tests/test_a.py", None, "test_zz", "failed")),
    ]
    facts = sources.outcomes_from_uploads(uploads, sa)
    assert facts.uploads == 2
    assert [c.outcome.value for c in facts.cases] == ["failed"]  # failed beats passed
    assert facts.flaky_test_ids == frozenset({TEST_ID})
    assert sources.NoOutcomes().load(uuid4(), sa) == sources.OutcomeFacts()
    assert sources.StaticIntent().load(uuid4()) == IntentFacts()


# ------------------------------------------------------------------ SQL sources (SQLite)


def sql_env():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime(2026, 11, 2, 12, tzinfo=UTC)
    with factory() as session:
        org = Organization(name="Acme", github_installation_id=1,
                           github_installation_status="active")
        repo = Repository(
            organization=org, github_repository_id=2, name="r", owner="o",
            default_branch="main", clone_url="https://example.invalid/o/r.git",
            visibility=db_enums.RepositoryVisibility.PRIVATE,
            status=db_enums.RepositoryStatus.CONNECTED)
        pr = PullRequest(repository=repo, github_pr_number=1, title="t",
                         source_branch="f", target_branch="main", author="a",
                         status=db_enums.PullRequestStatus.OPEN, opened_at=now)
        analysis = Analysis(repository=repo, pull_request=pr, commit_sha=SHA,
                            status=db_enums.AnalysisStatus.PENDING, started_at=now,
                            created_at=now)
        session.add_all([org, repo, pr, analysis])
        session.flush()
        ids = (analysis.id, org.id)
        session.commit()
    return factory, ids


def test_sql_intent_source_reads_snapshot_commit_messages_and_head() -> None:
    factory, (analysis_id, org_id) = sql_env()
    src = sources.SqlIntentSource(factory)
    assert src.head_sha(analysis_id, None) == SHA
    assert src.organization_id(analysis_id) == org_id
    assert src.load(analysis_id) == IntentFacts()  # no snapshot yet
    assert src.load(uuid4()) == IntentFacts()  # unknown analysis
    assert src.organization_id(uuid4()) is None

    t0 = datetime(2026, 11, 2, tzinfo=UTC)
    body = IntentSource.from_text("1", IntentSourceKind.PR_BODY, "f returns one", t0)
    commit = IntentSource.from_text(
        "abc", IntentSourceKind.COMMIT_MESSAGE, "fix\n\nCo-Authored-By: Claude <c@x>", t0)
    crit = Criterion.create(
        body, Span("1", 0, len(body.text)),
        extraction_method=ExtractionMethod.DETERMINISTIC, extractor_version="det-1",
    ).with_testability(Testability.TESTABLE, "clear")
    with factory() as session:
        repo = SqlAlchemyIntentRepository(session)
        repo.save_sources(org_id, str(analysis_id), (body, commit))
        repo.save_snapshot(org_id, IntentSnapshot(
            snapshot_id=str(uuid4()), analysis_id=str(analysis_id), version=1,
            created_at=t0, criteria=(crit,), sources=(body.ref, commit.ref)))
        session.commit()
    facts = src.load(analysis_id)
    assert [c.text for c in facts.criteria] == ["f returns one"]
    assert facts.commit_messages == ("fix\n\nCo-Authored-By: Claude <c@x>",)
    # IN-01 criteria flow through the adapter unchanged
    assert collect.adapters.criterion_inputs(facts.criteria).items[0].testability == (
        "behavioral_testable")
    # and the full collector accepts the SQL source
    sa = VerdictStageACollector(src, producers=good_producers()).collect(analysis_id, COMMAND)
    assert sa.head_sha == SHA and sa.agent_signal and len(sa.criteria) == 1


def test_sql_outcome_source_reads_uploads_of_the_analysis() -> None:
    factory, (analysis_id, _) = sql_env()
    sa = StageAInput(
        analysis_id=str(analysis_id), repository_id="r", head_sha=SHA, changeset_ref="x",
        criteria=(), symbols=(), criterion_symbol=(), symbol_test=(),
        criterion_test=(), assertions=(), tamper=(),
    )
    assert sources.SqlOutcomeSource(factory).load(analysis_id, sa).uploads == 0


def test_stage_b_recomputer_rescoring_from_the_stored_stage_a() -> None:
    from radius_shared.verdict_v2_flag import VerdictV2Mode
    from radius_worker.verdict_v2.scoring import StageBRecomputer

    factory, (analysis_id, org_id) = sql_env()
    stage_a = VerdictStageACollector(
        StaticIntent(IntentFacts(criteria=(criterion(),))),
        head_sha_port=Sha(), producers=good_producers(),
    ).collect(analysis_id, COMMAND)

    class Store:
        def __init__(self, stored):
            self.stored, self.saved = stored, []

        def latest_stage_a(self, organization_id, aid):
            return self.stored

        def save(self, organization_id, aid, bundle):
            self.saved.append(bundle)
            return True

    store = Store(stage_a)
    rec = StageBRecomputer(store, VerdictV2Mode.ON, clock=lambda: datetime(2026, 11, 2, tzinfo=UTC))
    with factory() as session:
        assert rec.recompute(session, org_id, analysis_id) is True
        assert Store(None) and StageBRecomputer(Store(None), VerdictV2Mode.ON).recompute(
            session, org_id, analysis_id) is False
    bundle = store.saved[0]
    # no CI upload yet: pending (R2p), computed without any clone or producer
    assert bundle["verdict"]["pending"] is True
    assert bundle["verdict"]["justification"]["decided_by"] == "R2p"
