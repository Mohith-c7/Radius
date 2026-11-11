"""runtime coverage persistence (tables created in 20261101_0009_coverage_tables)

Revision ID: 20261029_0005
Revises: 20261101_0009
"""

from collections.abc import Sequence

revision: str = "20261029_0005"
down_revision: str | None = "20261101_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Coverage tables (coverage_reports, coverage_report_test_association,
    # coverage_artifacts) are created in 20261101_0009_coverage_tables.py.
    pass


def downgrade() -> None:
    pass
