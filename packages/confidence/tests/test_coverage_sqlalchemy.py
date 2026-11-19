"""SQL coverage store: persists what it is given, round-trips like the in-memory store."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from radius_confidence.infrastructure.coverage_in_memory import InMemoryCoverageStore
from radius_confidence.infrastructure.coverage_sqlalchemy import SqlAlchemyCoverageStore
from radius_shared.database import (
    coverage as coverage_models,  # noqa: F401  (registers tables)
)
from radius_shared.database import models as db
from radius_shared.database.base import Base
from radius_shared.database.enums import AnalysisStatus, RepositoryVisibility
from radius_shared.errors import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

NOW = datetime(2026, 11, 19, tzinfo=UTC)


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _analysis_with_test(session: Session, owner: str, test_path: str):
    org = db.Organization(id=uuid4(), name=owner)
    repo = db.Repository(
        id=uuid4(), organization_id=org.id, github_repository_id=len(owner) * 1000 + ord(owner[0]),
        name="app", owner=owner, default_branch="main",
        clone_url=f"https://github.com/{owner}/app.git", visibility=RepositoryVisibility.PRIVATE,
    )
    analysis = db.Analysis(
        id=uuid4(), repository_id=repo.id, pull_request_id=uuid4(), commit_sha="a" * 40,
        status=AnalysisStatus.COMPLETED, started_at=NOW, created_at=NOW,
    )
    case = db.TestCase(
        id=uuid4(), repository_id=repo.id, path=test_path, name="test_core",
        framework="pytest", test_type="unit",
    )
    session.add_all([org, repo, analysis, case])
    session.flush()
    return analysis, case


def _payload(test_id, test_path="tests/test_core.py"):
    files = [{"test_id": test_id, "test_path": test_path, "path": "src/core.py", "covered": True, "count": 3}]
    symbols = [{"test_id": test_id, "file_path": "src/core.py", "symbol": "pay", "executed": True, "count": 2}]
    return files, symbols


def test_ingest_persists_and_round_trips(session) -> None:
    store = SqlAlchemyCoverageStore(session)
    analysis, case = _analysis_with_test(session, "acme", "tests/test_core.py")
    files, symbols = _payload(case.id)

    store.ingest_coverage(analysis.id, "pytest", 88.5, files, symbols)

    summary = store.get_summary(analysis.id)
    assert summary == {
        "covered_lines": 2, "total_lines": 2, "coverage_percent": 88.5,
        "artifact_count": 2, "available": True,
    }
    artifact = store.get_coverage_for_artifact(analysis.id, "src/core.py")
    assert artifact["report"]["framework"] == "pytest"
    assert artifact["artifacts"] == [{
        "test_id": case.id, "test_path": "tests/test_core.py", "file_path": "src/core.py",
        "symbol": None, "executed": True, "count": 3, "covered": True,
    }]
    assert store.get_tests_for_symbol(analysis.id, "src/core.py", "pay")["tests"] == [case.id]
    assert store.get_tests_for_symbol(analysis.id, "src/core.py", "other") is None
    report = store.get_report(analysis.id)
    assert [f["file_path"] for f in report["files"]] == ["src/core.py"]
    assert [a["symbol"] for a in report["artifacts"]] == ["pay"]


def test_same_shapes_as_the_in_memory_store(session) -> None:
    sql = SqlAlchemyCoverageStore(session)
    memory = InMemoryCoverageStore()
    analysis, case = _analysis_with_test(session, "acme", "tests/test_core.py")
    files, symbols = _payload(case.id)
    for store in (sql, memory):
        store.ingest_coverage(analysis.id, "pytest", 50.0, files, symbols)
    assert sql.get_summary(analysis.id) == memory.get_summary(analysis.id)
    assert (
        sql.get_coverage_for_artifact(analysis.id, "src/core.py")["artifacts"]
        == memory.get_coverage_for_artifact(analysis.id, "src/core.py")["artifacts"]
    )
    assert (
        sql.get_tests_for_symbol(analysis.id, "src/core.py", "pay")["tests"]
        == memory.get_tests_for_symbol(analysis.id, "src/core.py", "pay")["tests"]
    )


def test_reingest_replaces_and_test_path_resolves_the_test_case(session) -> None:
    store = SqlAlchemyCoverageStore(session)
    analysis, case = _analysis_with_test(session, "acme", "tests/test_core.py")
    store.ingest_coverage(analysis.id, "pytest", 10.0, *_payload(case.id))
    files, symbols = _payload(None, test_path="./tests/test_core.py")
    store.ingest_coverage(analysis.id, "pytest", 20.0, files, [])

    assert store.get_summary(analysis.id)["artifact_count"] == 1
    assert store.get_summary(analysis.id)["coverage_percent"] == 20.0
    assert store.get_tests_for_symbol(analysis.id, "src/core.py", "pay") is None
    total = session.scalar(select(func.count()).select_from(coverage_models.CoverageArtifact))
    assert total == 1


def test_another_tenants_test_case_is_refused(session) -> None:
    store = SqlAlchemyCoverageStore(session)
    analysis, _case = _analysis_with_test(session, "acme", "tests/test_core.py")
    _other, foreign_case = _analysis_with_test(session, "globex", "tests/test_secret.py")

    with pytest.raises(ValidationError):
        store.ingest_coverage(analysis.id, "pytest", 1.0, *_payload(foreign_case.id, "tests/test_secret.py"))
    with pytest.raises(ValidationError):
        store.ingest_coverage(analysis.id, "pytest", 1.0, *_payload(uuid4(), "tests/nope.py"))


def test_unknown_analysis_has_no_coverage(session) -> None:
    store = SqlAlchemyCoverageStore(session)
    assert store.get_summary(uuid4()) is None
    assert store.get_report(uuid4()) is None
    assert store.get_coverage_for_artifact(uuid4(), "src/core.py") is None
    with pytest.raises(ValidationError):
        store.ingest_coverage(uuid4(), "pytest", None, [], [])


def test_in_memory_store_never_returns_another_analysis_report() -> None:
    store = InMemoryCoverageStore()
    case_id = uuid4()
    store.ingest_coverage(uuid4(), "pytest", 88.5, *_payload(case_id))
    other = uuid4()
    assert store.get_summary(other) is None
    assert store.get_report(other) is None
    assert store.get_coverage_for_artifact(other, "src/core.py") is None
