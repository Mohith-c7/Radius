"""Unit tests for FlakyDetectionService and FlakyClassification."""

from datetime import UTC, datetime
from uuid import uuid4

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
    TestCase,
    TestExecutionHistory,
)
from radius_testing.application.services import FlakyDetectionService
from radius_testing.domain.models import FlakyStatus
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture()
def db_session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    return session_factory


def _seed_context(session):
    org = Organization(name="Acme")
    repo = Repository(
        organization=org,
        github_repository_id=10,
        name="repo",
        owner="acme",
        default_branch="main",
        clone_url="https://example.test/repo.git",
        visibility=RepositoryVisibility.PRIVATE,
    )
    session.add_all([org, repo])
    session.flush()

    pr = PullRequest(
        repository=repo,
        github_pr_number=1,
        title="PR",
        source_branch="feature",
        target_branch="main",
        author="user",
        status=PullRequestStatus.OPEN,
        opened_at=datetime.now(UTC),
    )
    analysis = Analysis(
        repository=repo,
        pull_request=pr,
        commit_sha="a" * 40,
        status=AnalysisStatus.COMPLETED,
        started_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    test_case = TestCase(
        id=uuid4(),
        repository_id=repo.id,
        name="test_foo",
        path="tests/test_foo.py",
        framework="pytest",
        test_type="unit",
    )
    session.add_all([pr, analysis, test_case])
    session.flush()
    return repo, pr, analysis, test_case


def test_flaky_detection_insufficient_data(db_session_factory):
    with db_session_factory() as session:
        repo, pr, analysis, test_case = _seed_context(session)

        # Only 2 executions (min_runs defaults to 5)
        for i in range(2):
            session.add(
                TestExecutionHistory(
                    id=uuid4(),
                    test_name=test_case.name,
                    test_path=f"tests/test_foo_{i}.py",  # unique analysis_id + test_path constraint
                    repository_id=repo.id,
                    analysis_id=analysis.id,
                    commit_sha="a" * 40,
                    status="passed",
                    duration_ms=100,
                    timestamp=datetime.now(UTC),
                )
            )
        # Update test_case to match one of the paths
        test_case.path = "tests/test_foo_0.py"
        session.commit()
        test_id = test_case.id

    service = FlakyDetectionService(session_factory=db_session_factory)
    service.min_runs = 5
    result = service.classify(test_id)

    assert result.status == FlakyStatus.INSUFFICIENT_DATA
    assert result.total_runs == 1
    assert result.fail_runs == 0


def test_flaky_detection_potentially_flaky(db_session_factory):
    with db_session_factory() as session:
        repo, pr, analysis, test_case = _seed_context(session)

        # 5 executions across 5 analyses
        for i in range(5):
            a = Analysis(
                repository=repo,
                pull_request=pr,
                commit_sha="b" * 40,
                status=AnalysisStatus.COMPLETED,
                started_at=datetime.now(UTC),
                created_at=datetime.now(UTC),
            )
            session.add(a)
            session.flush()
            status = "failed" if i < 2 else "passed"
            session.add(
                TestExecutionHistory(
                    id=uuid4(),
                    test_name=test_case.name,
                    test_path=test_case.path,
                    repository_id=repo.id,
                    analysis_id=a.id,
                    commit_sha="b" * 40,
                    status=status,
                    duration_ms=100,
                    timestamp=datetime.now(UTC),
                )
            )
        session.commit()
        test_id = test_case.id

    service = FlakyDetectionService(session_factory=db_session_factory)
    service.min_runs = 5
    service.threshold = 0.30
    result = service.classify(test_id)

    assert result.status == FlakyStatus.POTENTIALLY_FLAKY
    assert result.total_runs == 5
    assert result.fail_runs == 2
    assert round(result.score, 2) == 0.40
