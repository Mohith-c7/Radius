from radius_shared.database import models as db_models
from radius_shared.database.base import metadata
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import configure_mappers

EXPECTED_TABLES = {
    "organizations",
    "users",
    "repositories",
    "branches",
    "pull_requests",
    "analyses",
    "changed_files",
    "graph_snapshots",
    "blast_radius",
    "test_runs",
    "confidence_reports",
}


def test_phase1_tables_are_registered() -> None:
    assert EXPECTED_TABLES.issubset(set(metadata.tables))


def test_required_indexes_exist() -> None:
    indexes_by_table = {
        table_name: {index.name for index in table.indexes}
        for table_name, table in metadata.tables.items()
    }

    assert "ix_repositories_github_repository_id" in indexes_by_table["repositories"]
    assert "ix_repositories_organization_id" in indexes_by_table["repositories"]
    assert (
        "ix_pull_requests_repository_id_github_pr_number"
        in indexes_by_table["pull_requests"]
    )
    assert "ix_analyses_repository_id" in indexes_by_table["analyses"]
    assert "ix_analyses_pull_request_id" in indexes_by_table["analyses"]
    assert "ix_analyses_commit_sha" in indexes_by_table["analyses"]
    assert "ix_changed_files_analysis_id" in indexes_by_table["changed_files"]
    assert "ix_test_runs_analysis_id" in indexes_by_table["test_runs"]
    assert (
        "ix_confidence_reports_analysis_id" in indexes_by_table["confidence_reports"]
    )


def test_one_to_one_analysis_tables_have_unique_analysis_id() -> None:
    for table_name in ("blast_radius", "confidence_reports", "graph_snapshots"):
        table = metadata.tables[table_name]
        assert table.c.analysis_id.unique is True


def test_database_enums_use_domain_values() -> None:
    repositories = metadata.tables["repositories"]
    analyses = metadata.tables["analyses"]
    confidence_reports = metadata.tables["confidence_reports"]

    assert repositories.c.status.type.enums == [
        "connected",
        "synchronizing",
        "failed",
        "disconnected",
    ]
    assert analyses.c.status.type.enums == [
        "pending",
        "running",
        "completed",
        "failed",
        "cancelled",
    ]
    assert confidence_reports.c.risk_level.type.enums == [
        "low",
        "medium",
        "high",
        "critical",
    ]


def test_mapper_relationships_configure_cleanly() -> None:
    configure_mappers()

    assert (
        db_models.Organization.repositories.property.mapper.class_
        is db_models.Repository
    )
    assert (
        db_models.Analysis.blast_radius.property.mapper.class_
        is db_models.BlastRadius
    )
    assert (
        db_models.Analysis.graph_snapshot.property.mapper.class_
        is db_models.GraphSnapshot
    )
    assert (
        db_models.Analysis.confidence_report.property.mapper.class_
        is db_models.ConfidenceReport
    )
    assert db_models.Analysis.test_runs.property.mapper.class_ is db_models.TestRun


def test_metadata_can_create_tables_in_sqlite() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    metadata.create_all(engine)

    inspector = inspect(engine)
    assert EXPECTED_TABLES.issubset(set(inspector.get_table_names()))
