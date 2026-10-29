"""Tests for coverage SQLAlchemy models."""

from radius_shared.database import coverage as coverage_models
from radius_shared.database.base import metadata
from sqlalchemy import create_engine, inspect


def test_coverage_tables_are_registered() -> None:
    expected = {
        "coverage_artifacts",
        "coverage_reports",
        "coverage_report_test_association",
    }
    assert expected.issubset(set(metadata.tables))


def test_coverage_indexes_exist() -> None:
    indexes_by_table = {
        table_name: {index.name for index in table.indexes}
        for table_name, table in metadata.tables.items()
    }

    assert "ix_coverage_artifacts_test_id" in indexes_by_table["coverage_artifacts"]
    assert "ix_coverage_artifacts_path" in indexes_by_table["coverage_artifacts"]
    assert (
        "ix_coverage_reports_analysis_id" in indexes_by_table["coverage_reports"]
    )
    assert (
        "ix_coverage_report_test_association_test_id"
        in indexes_by_table["coverage_report_test_association"]
    )


def test_one_to_one_coverage_report_table_has_unique_analysis_id() -> None:
    table = metadata.tables["coverage_reports"]
    assert table.c.analysis_id.unique is True


def test_metadata_can_create_tables_in_sqlite() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    inspector = inspect(engine)
    assert set(inspector.get_table_names()) >= {
        "coverage_artifacts",
        "coverage_reports",
        "coverage_report_test_association",
    }
