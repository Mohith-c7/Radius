"""SQL coverage persistence and evidence retrieval tests."""

from datetime import UTC, datetime
from uuid import uuid4

from radius_confidence.infrastructure import SqlAlchemyCoverageStore
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
    TestCase,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_sql_store_persists_and_returns_test_to_symbol_evidence() -> None:
    session = Session(create_engine("sqlite+pysqlite:///:memory:"))
    Base.metadata.create_all(session.bind)
    analysis, test_case = _context(session)
    store = SqlAlchemyCoverageStore(session)

    store.ingest_coverage(
        analysis.id, "pytest", 100.0,
        [{"test_path": test_case.path, "path": "src/payment.py", "covered": True, "count": 1}],
        [{"test_path": test_case.path, "file_path": "src/payment.py", "symbol": "process_payment", "executed": True, "count": 2}],
    )
    session.commit()

    report = store.get_report(analysis.id)
    evidence = store.get_selection_evidence(analysis.id, ("src/payment.py",), ("process_payment",))
    assert report is not None
    assert len(report["artifacts"]) == 2
    assert evidence[test_case.path] == ("Runtime coverage covers src/payment.py.", "Runtime coverage executes process_payment in src/payment.py.")


def test_coverage_ingestion_resolves_test_within_analysis_repository() -> None:
    session = Session(create_engine("sqlite+pysqlite:///:memory:"))
    Base.metadata.create_all(session.bind)

    analysis, original_test = _context(session)

    # Move the original test into another repository.
    other_repo = Repository(
        organization=analysis.repository.organization,
        github_repository_id=2,
        name="another-radius",
        owner="acme",
        default_branch="main",
        clone_url="https://example.test/another-radius.git",
        visibility=RepositoryVisibility.PRIVATE,
    )
    session.add(other_repo)
    session.flush()

    original_test.repository_id = other_repo.id

    # Create a test with the same path in the analysis repository.
    correct_test = TestCase(
        id=uuid4(),
        repository_id=analysis.repository_id,
        name="test_payment",
        path="tests/test_payment.py",
        framework="pytest",
        test_type="unit",
    )
    session.add(correct_test)
    session.flush()

    store = SqlAlchemyCoverageStore(session)

    store.ingest_coverage(
        analysis.id,
        "pytest",
        100.0,
        [
            {
                "test_path": "tests/test_payment.py",
                "path": "src/payment.py",
                "covered": True,
                "count": 1,
            }
        ],
        [],
    )
    session.commit()

    report = store.get_report(analysis.id)

    assert report is not None
    assert len(report["artifacts"]) == 1
    assert report["artifacts"][0]["test_id"] == correct_test.id

def _context(session: Session):
    org = Organization(name="Acme")
    repo = Repository(
        organization=org,
        github_repository_id=1,
        name="radius",
        owner="acme",
        default_branch="main",
        clone_url="https://example.test/radius.git",
        visibility=RepositoryVisibility.PRIVATE,
    )

    session.add_all([org, repo])
    session.flush()

    pr = PullRequest(
        repository=repo,
        github_pr_number=1,
        title="Coverage",
        source_branch="feature",
        target_branch="main",
        author="radius",
        status=PullRequestStatus.OPEN,
        opened_at=datetime.now(UTC),
    )

    analysis = Analysis(
        repository=repo,
        pull_request=pr,
        commit_sha="a" * 40,
        status=AnalysisStatus.PENDING,
        started_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )

    test_case = TestCase(
        id=uuid4(),
        repository_id=repo.id,
        name="test_payment",
        path="tests/test_payment.py",
        framework="pytest",
        test_type="unit",
    )

    session.add_all([pr, analysis, test_case])
    session.flush()

    return analysis, test_case
