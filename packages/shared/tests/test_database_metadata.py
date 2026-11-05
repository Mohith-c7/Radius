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
    "analysis_jobs",
    "confidence_evidence",
    "graph_edges",
    "graph_nodes",
    "selected_tests",
    "test_cases",
    "test_run_plans",
    "test_selections",
    "idempotency_keys",
    "intent_sources",
    "intent_snapshots",
    "intent_snapshot_sources",
    "intent_criteria",
    "intent_criterion_state_changes",
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
    assert "ix_analysis_jobs_status_created_at" in indexes_by_table["analysis_jobs"]
    assert "ix_graph_nodes_snapshot_id" in indexes_by_table["graph_nodes"]
    assert "ix_graph_edges_snapshot_id" in indexes_by_table["graph_edges"]
    assert "ix_test_selections_analysis_id" in indexes_by_table["test_selections"]
    assert "ix_test_run_plans_analysis_id" in indexes_by_table["test_run_plans"]
    assert (
        "ix_confidence_reports_analysis_id" in indexes_by_table["confidence_reports"]
    )
    assert (
        "ix_confidence_evidence_report_id"
        in indexes_by_table["confidence_evidence"]
    )
    assert (
        "ix_idempotency_keys_organization_id"
        in indexes_by_table["idempotency_keys"]
    )
    assert "ix_intent_sources_analysis_id" in indexes_by_table["intent_sources"]
    assert "ix_intent_snapshots_analysis_id" in indexes_by_table["intent_snapshots"]
    assert "ix_intent_criteria_snapshot_id" in indexes_by_table["intent_criteria"]


def test_intent_tables_are_tenant_scoped() -> None:
    for name, table in metadata.tables.items():
        if name.startswith("intent_"):
            assert "organization_id" in table.c
            assert table.c.organization_id.nullable is False
            assert ["organization_id"] in [
                [c.name for c in i.columns] for i in table.indexes
            ]


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


def test_traceparent_migration_up_and_down() -> None:
    import importlib.util
    from pathlib import Path

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = next(
        p
        for p in Path(__file__).resolve().parents
        if (p / "infra" / "database" / "migrations").is_dir()
    ) / "infra/database/migrations/versions/20261102_0010_analysis_job_traceparent.py"
    spec = importlib.util.spec_from_file_location("mig_0010", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "20261101_0009"

    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(sa.text("create table analysis_jobs (id integer primary key, attempts integer)"))
        conn.execute(sa.text("insert into analysis_jobs (id, attempts) values (1, 0)"))
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
            cols = {c["name"]: c for c in inspect(conn).get_columns("analysis_jobs")}
            assert cols["traceparent"]["nullable"] is True
            assert conn.execute(sa.text("select traceparent from analysis_jobs")).scalar() is None
            module.downgrade()
            cols = {c["name"] for c in inspect(conn).get_columns("analysis_jobs")}
            assert "traceparent" not in cols
            assert conn.execute(sa.text("select count(*) from analysis_jobs")).scalar() == 1
