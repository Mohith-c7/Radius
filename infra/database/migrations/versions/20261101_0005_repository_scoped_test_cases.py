"""Scope discovered test cases to a repository

Before this revision ``test_cases.path`` was globally unique, so two
repositories that both contain ``tests/test_app.py`` shared (and overwrote)
one row.

Revision ID: 20261101_0005
Revises: 20261002_0004
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261101_0005"
down_revision: str | None = "20261002_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("test_cases") as batch:
        batch.add_column(sa.Column("repository_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_test_cases_repository_id_repositories",
            "repositories",
            ["repository_id"],
            ["id"],
        )
        batch.drop_constraint("uq_test_cases_path", type_="unique")
        batch.create_unique_constraint(
            "uq_test_cases_repository_id_path",
            ["repository_id", "path"],
        )


def downgrade() -> None:
    # Rows that only differ by repository cannot satisfy a global unique path.
    # Downgrading therefore drops all but one row per path (and its selections).
    op.execute(
        """
        DELETE FROM selected_tests WHERE test_case_id IN (
            SELECT id FROM test_cases t
            WHERE EXISTS (
                SELECT 1 FROM test_cases o WHERE o.path = t.path AND o.id < t.id
            )
        )
        """
    )
    op.execute(
        """
        DELETE FROM test_cases
        WHERE EXISTS (
            SELECT 1 FROM test_cases o
            WHERE o.path = test_cases.path AND o.id < test_cases.id
        )
        """
    )
    with op.batch_alter_table("test_cases") as batch:
        batch.drop_constraint("uq_test_cases_repository_id_path", type_="unique")
        batch.create_unique_constraint("uq_test_cases_path", ["path"])
        batch.drop_constraint(
            "fk_test_cases_repository_id_repositories",
            type_="foreignkey",
        )
        batch.drop_column("repository_id")
