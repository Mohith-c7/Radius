"""Phase 1 SQLAlchemy models."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from radius_shared.database.base import Base, TimestampMixin, UuidPrimaryKeyMixin
from radius_shared.database.enums import (
    AnalysisJobStatus,
    AnalysisStatus,
    ChangedFileType,
    PullRequestStatus,
    RepositoryProvider,
    RepositoryStatus,
    RepositoryVisibility,
    RiskLevel,
    UserRole,
)


def enum_values(enum_cls: type) -> list[str]:
    """Persist StrEnum values instead of Python member names."""

    return [member.value for member in enum_cls]


class Organization(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Customer organization."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    github_installation_id: Mapped[int | None] = mapped_column(
        BigInteger,
        unique=True,
        nullable=True,
    )

    users: Mapped[list["User"]] = relationship(back_populates="organization")
    repositories: Mapped[list["Repository"]] = relationship(
        back_populates="organization"
    )


class User(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Authenticated user."""

    __tablename__ = "users"

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )
    github_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, values_callable=enum_values),
        nullable=False,
    )

    organization: Mapped[Organization] = relationship(back_populates="users")


class Repository(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Connected Git repository."""

    __tablename__ = "repositories"

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=False,
    )
    github_repository_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[RepositoryProvider] = mapped_column(
        Enum(RepositoryProvider, values_callable=enum_values),
        default=RepositoryProvider.GITHUB,
        nullable=False,
    )
    default_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    clone_url: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[RepositoryVisibility] = mapped_column(
        Enum(RepositoryVisibility, values_callable=enum_values),
        nullable=False,
    )
    status: Mapped[RepositoryStatus] = mapped_column(
        Enum(RepositoryStatus, values_callable=enum_values),
        default=RepositoryStatus.CONNECTED,
        nullable=False,
    )

    organization: Mapped[Organization] = relationship(back_populates="repositories")
    branches: Mapped[list["Branch"]] = relationship(back_populates="repository")
    pull_requests: Mapped[list["PullRequest"]] = relationship(
        back_populates="repository"
    )
    analyses: Mapped[list["Analysis"]] = relationship(back_populates="repository")
    graph_snapshots: Mapped[list["GraphSnapshot"]] = relationship(
        back_populates="repository"
    )

    __table_args__ = (
        Index("ix_repositories_github_repository_id", "github_repository_id"),
        Index("ix_repositories_organization_id", "organization_id"),
    )


class Branch(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Repository branch metadata."""

    __tablename__ = "branches"

    repository_id: Mapped[UUID] = mapped_column(
        ForeignKey("repositories.id"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    latest_commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)

    repository: Mapped[Repository] = relationship(back_populates="branches")

    __table_args__ = (
        UniqueConstraint("repository_id", "name", name="uq_branches_repository_name"),
    )


class PullRequest(UuidPrimaryKeyMixin, Base):
    """GitHub pull request."""

    __tablename__ = "pull_requests"

    repository_id: Mapped[UUID] = mapped_column(
        ForeignKey("repositories.id"),
        nullable=False,
    )
    github_pr_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    target_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    author: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[PullRequestStatus] = mapped_column(
        Enum(PullRequestStatus, values_callable=enum_values),
        nullable=False,
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    merged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    repository: Mapped[Repository] = relationship(back_populates="pull_requests")
    analyses: Mapped[list["Analysis"]] = relationship(back_populates="pull_request")

    __table_args__ = (
        UniqueConstraint(
            "repository_id",
            "github_pr_number",
            name="uq_pull_requests_repository_pr_number",
        ),
        Index(
            "ix_pull_requests_repository_id_github_pr_number",
            "repository_id",
            "github_pr_number",
        ),
    )


class Analysis(UuidPrimaryKeyMixin, Base):
    """One Radius verification run."""

    __tablename__ = "analyses"

    repository_id: Mapped[UUID] = mapped_column(
        ForeignKey("repositories.id"),
        nullable=False,
    )
    pull_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("pull_requests.id"),
        nullable=False,
    )
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[AnalysisStatus] = mapped_column(
        Enum(AnalysisStatus, values_callable=enum_values),
        default=AnalysisStatus.PENDING,
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    repository: Mapped[Repository] = relationship(back_populates="analyses")
    pull_request: Mapped[PullRequest] = relationship(back_populates="analyses")
    changed_files: Mapped[list["ChangedFile"]] = relationship(back_populates="analysis")
    blast_radius: Mapped["BlastRadius | None"] = relationship(
        back_populates="analysis",
        uselist=False,
    )
    graph_snapshot: Mapped["GraphSnapshot | None"] = relationship(
        back_populates="analysis",
        uselist=False,
    )
    test_runs: Mapped[list["TestRun"]] = relationship(back_populates="analysis")
    confidence_report: Mapped["ConfidenceReport | None"] = relationship(
        back_populates="analysis",
        uselist=False,
    )
    analysis_job: Mapped["AnalysisJob | None"] = relationship(
        back_populates="analysis",
        uselist=False,
    )

    __table_args__ = (
        Index("ix_analyses_repository_id", "repository_id"),
        Index("ix_analyses_pull_request_id", "pull_request_id"),
        Index("ix_analyses_commit_sha", "commit_sha"),
    )


class ChangedFile(UuidPrimaryKeyMixin, Base):
    """File modified during an analysis."""

    __tablename__ = "changed_files"

    analysis_id: Mapped[UUID] = mapped_column(
        ForeignKey("analyses.id"),
        nullable=False,
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    change_type: Mapped[ChangedFileType] = mapped_column(
        Enum(ChangedFileType, values_callable=enum_values),
        nullable=False,
    )
    additions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deletions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    analysis: Mapped[Analysis] = relationship(back_populates="changed_files")

    __table_args__ = (Index("ix_changed_files_analysis_id", "analysis_id"),)


class GraphSnapshot(UuidPrimaryKeyMixin, Base):
    """Dependency graph metadata generated for an analysis."""

    __tablename__ = "graph_snapshots"

    repository_id: Mapped[UUID] = mapped_column(
        ForeignKey("repositories.id"),
        nullable=False,
    )
    analysis_id: Mapped[UUID] = mapped_column(
        ForeignKey("analyses.id"),
        unique=True,
        nullable=False,
    )
    node_count: Mapped[int] = mapped_column(Integer, nullable=False)
    edge_count: Mapped[int] = mapped_column(Integer, nullable=False)
    graph_version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    repository: Mapped[Repository] = relationship(back_populates="graph_snapshots")
    analysis: Mapped[Analysis] = relationship(back_populates="graph_snapshot")
    nodes: Mapped[list["GraphNode"]] = relationship(back_populates="snapshot")
    edges: Mapped[list["GraphEdge"]] = relationship(back_populates="snapshot")


class GraphNode(UuidPrimaryKeyMixin, Base):
    """Persisted graph node artifact."""

    __tablename__ = "graph_nodes"

    snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("graph_snapshots.id"),
        nullable=False,
    )
    node_key: Mapped[str] = mapped_column(Text, nullable=False)
    node_type: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str | None] = mapped_column(Text, nullable=True)

    snapshot: Mapped[GraphSnapshot] = relationship(back_populates="nodes")

    __table_args__ = (
        UniqueConstraint("snapshot_id", "node_key", name="uq_graph_nodes_snapshot_key"),
        Index("ix_graph_nodes_snapshot_id", "snapshot_id"),
    )


class GraphEdge(UuidPrimaryKeyMixin, Base):
    """Persisted graph edge artifact."""

    __tablename__ = "graph_edges"

    snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("graph_snapshots.id"),
        nullable=False,
    )
    source_key: Mapped[str] = mapped_column(Text, nullable=False)
    target_key: Mapped[str] = mapped_column(Text, nullable=False)
    edge_type: Mapped[str] = mapped_column(String(100), nullable=False)

    snapshot: Mapped[GraphSnapshot] = relationship(back_populates="edges")

    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "source_key",
            "target_key",
            "edge_type",
            name="uq_graph_edges_snapshot_edge",
        ),
        Index("ix_graph_edges_snapshot_id", "snapshot_id"),
    )


class BlastRadius(UuidPrimaryKeyMixin, Base):
    """Impact analysis summary."""

    __tablename__ = "blast_radius"

    analysis_id: Mapped[UUID] = mapped_column(
        ForeignKey("analyses.id"),
        unique=True,
        nullable=False,
    )
    affected_files: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    affected_symbols: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    affected_modules: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    affected_tests: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    dependency_depth: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    analysis: Mapped[Analysis] = relationship(back_populates="blast_radius")


class TestRun(UuidPrimaryKeyMixin, Base):
    """Executed test run summary."""

    __tablename__ = "test_runs"

    analysis_id: Mapped[UUID] = mapped_column(
        ForeignKey("analyses.id"),
        nullable=False,
    )
    framework: Mapped[str] = mapped_column(String(100), nullable=False)
    total_tests: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    passed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    coverage_percent: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)

    analysis: Mapped[Analysis] = relationship(back_populates="test_runs")

    __table_args__ = (Index("ix_test_runs_analysis_id", "analysis_id"),)


class TestCase(UuidPrimaryKeyMixin, Base):
    """Discovered test case artifact."""

    __tablename__ = "test_cases"

    path: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    framework: Mapped[str] = mapped_column(String(100), nullable=False)
    test_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    selections: Mapped[list["SelectedTest"]] = relationship(back_populates="test_case")

    __table_args__ = (Index("ix_test_cases_path", "path"),)


class TestSelection(UuidPrimaryKeyMixin, Base):
    """Selected tests for one analysis."""

    __tablename__ = "test_selections"

    analysis_id: Mapped[UUID] = mapped_column(
        ForeignKey("analyses.id"),
        unique=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    selected_tests: Mapped[list["SelectedTest"]] = relationship(
        back_populates="selection"
    )

    __table_args__ = (Index("ix_test_selections_analysis_id", "analysis_id"),)


class SelectedTest(UuidPrimaryKeyMixin, Base):
    """One selected test and reason."""

    __tablename__ = "selected_tests"

    selection_id: Mapped[UUID] = mapped_column(
        ForeignKey("test_selections.id"),
        nullable=False,
    )
    test_case_id: Mapped[UUID] = mapped_column(
        ForeignKey("test_cases.id"),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(String(100), nullable=False)

    selection: Mapped[TestSelection] = relationship(back_populates="selected_tests")
    test_case: Mapped[TestCase] = relationship(back_populates="selections")

    __table_args__ = (
        UniqueConstraint(
            "selection_id",
            "test_case_id",
            name="uq_selected_tests_selection_case",
        ),
        Index("ix_selected_tests_selection_id", "selection_id"),
    )


class TestRunPlan(UuidPrimaryKeyMixin, Base):
    """Structured test command plan."""

    __tablename__ = "test_run_plans"

    analysis_id: Mapped[UUID] = mapped_column(
        ForeignKey("analyses.id"),
        unique=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(100), nullable=False)
    selected_test_paths: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    command_plan: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    __table_args__ = (Index("ix_test_run_plans_analysis_id", "analysis_id"),)


class ConfidenceReport(UuidPrimaryKeyMixin, Base):
    """Final verification confidence report."""

    __tablename__ = "confidence_reports"

    analysis_id: Mapped[UUID] = mapped_column(
        ForeignKey("analyses.id"),
        unique=True,
        nullable=False,
    )
    confidence_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    risk_level: Mapped[RiskLevel] = mapped_column(
        Enum(RiskLevel, values_callable=enum_values),
        nullable=False,
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    recommendations: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    analysis: Mapped[Analysis] = relationship(back_populates="confidence_report")
    evidence_items: Mapped[list["ConfidenceEvidence"]] = relationship(
        back_populates="report"
    )

    __table_args__ = (Index("ix_confidence_reports_analysis_id", "analysis_id"),)


class ConfidenceEvidence(UuidPrimaryKeyMixin, Base):
    """Persisted confidence evidence item."""

    __tablename__ = "confidence_evidence"

    report_id: Mapped[UUID] = mapped_column(
        ForeignKey("confidence_reports.id"),
        nullable=False,
    )
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    impact: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)

    report: Mapped[ConfidenceReport] = relationship(back_populates="evidence_items")

    __table_args__ = (Index("ix_confidence_evidence_report_id", "report_id"),)


class AnalysisJob(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Durable queue entry for one analysis execution."""

    __tablename__ = "analysis_jobs"

    analysis_id: Mapped[UUID] = mapped_column(
        ForeignKey("analyses.id"),
        unique=True,
        nullable=False,
    )
    status: Mapped[AnalysisJobStatus] = mapped_column(
        Enum(AnalysisJobStatus, values_callable=enum_values),
        default=AnalysisJobStatus.PENDING,
        nullable=False,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    analysis: Mapped[Analysis] = relationship(back_populates="analysis_job")

    __table_args__ = (
        Index("ix_analysis_jobs_status_created_at", "status", "created_at"),
        Index("ix_analysis_jobs_analysis_id", "analysis_id"),
    )
