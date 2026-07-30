"""SQLAlchemy confidence store tests."""

from datetime import UTC, datetime
from uuid import uuid4

from radius_confidence.application import ConfidenceApplicationService
from radius_confidence.domain import CoveragePercent, ImpactEvidence
from radius_confidence.domain import TestEvidence as ConfidenceTestEvidence
from radius_confidence.dto import GenerateConfidenceReportCommand
from radius_confidence.infrastructure import (
    DeterministicConfidenceScorer,
    SqlAlchemyConfidenceStore,
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


def test_sqlalchemy_confidence_store_persists_evidence_and_recommendations() -> None:
    with _session() as session:
        analysis_id = _create_context(session)
        service = ConfidenceApplicationService(
            scorer=DeterministicConfidenceScorer(),
            store=SqlAlchemyConfidenceStore(session),
        )

        report = service.generate_report(
            GenerateConfidenceReportCommand(
                analysis_id=analysis_id,
                impact=ImpactEvidence(1, 1, 1, 1, 1),
                tests=ConfidenceTestEvidence(
                    total_tests=1,
                    passed=1,
                    failed=0,
                    skipped=0,
                    coverage_percent=CoveragePercent(90),
                ),
            )
        )
        loaded = service.get_report(analysis_id)

        assert loaded.id == report.id
        assert loaded.evidence
        assert loaded.recommendations == ("Proceed with standard review.",)


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _create_context(session: Session):
    organization = Organization(name="Acme")
    repository = Repository(
        organization=organization,
        github_repository_id=uuid4().int % 100000,
        name="radius",
        owner="acme",
        default_branch="main",
        clone_url="https://github.com/acme/radius.git",
        visibility=RepositoryVisibility.PRIVATE,
    )
    pull_request = PullRequest(
        repository=repository,
        github_pr_number=42,
        title="Confidence",
        source_branch="feature",
        target_branch="main",
        author="mohith",
        status=PullRequestStatus.OPEN,
        opened_at=datetime.now(UTC),
    )
    analysis = Analysis(
        repository=repository,
        pull_request=pull_request,
        commit_sha="a" * 40,
        status=AnalysisStatus.PENDING,
        started_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    session.add_all([organization, repository, pull_request, analysis])
    session.flush()
    return analysis.id
