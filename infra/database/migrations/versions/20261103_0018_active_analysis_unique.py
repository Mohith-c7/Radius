"""At most one active (pending/running) analysis per pull request head commit.

Revision ID: 20261103_0018
Revises: 20261103_0017
Create Date: 2026-11-03

C-12: ``find_active`` followed by an insert is check-then-insert; concurrent webhooks, polls
and syncs could create two analyses and two jobs for one head commit. A partial unique index
on ``(pull_request_id, commit_sha) WHERE status IN ('pending', 'running')`` closes the race.
Finished analyses (reruns) are unaffected.

Existing duplicate active rows are resolved first, keeping the oldest: the others are set to
``cancelled`` and their jobs ``completed`` with ``Cancelled: duplicate`` (nothing is deleted).
The revision number may be renumbered at merge time.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261103_0018"
down_revision: str | None = "20261103_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "uq_analyses_active_pr_commit"
ACTIVE = "status IN ('pending', 'running')"


def _dedupe(conn: sa.Connection) -> None:
    rows = conn.execute(
        sa.text(
            "SELECT id, pull_request_id, commit_sha FROM analyses "
            f"WHERE {ACTIVE} ORDER BY created_at, id"
        )
    ).all()
    seen: set[tuple[str, str]] = set()
    losers: list[object] = []
    for row in rows:
        key = (str(row.pull_request_id), row.commit_sha)
        if key in seen:
            losers.append(row.id)
        else:
            seen.add(key)
    for analysis_id in losers:
        conn.execute(
            sa.text(
                "UPDATE analyses SET status = 'cancelled', completed_at = CURRENT_TIMESTAMP "
                "WHERE id = :id"
            ),
            {"id": analysis_id},
        )
        conn.execute(
            sa.text(
                "UPDATE analysis_jobs SET status = 'completed', locked_at = NULL, "
                "last_error = 'Cancelled: duplicate analysis for the same commit' "
                "WHERE analysis_id = :id AND status IN ('pending', 'running')"
            ),
            {"id": analysis_id},
        )


def upgrade() -> None:
    conn = op.get_bind()
    indexes = {i["name"] for i in sa.inspect(conn).get_indexes("analyses")}
    if INDEX in indexes:
        return
    _dedupe(conn)
    where = sa.text(ACTIVE)
    op.create_index(
        INDEX,
        "analyses",
        ["pull_request_id", "commit_sha"],
        unique=True,
        postgresql_where=where,
        sqlite_where=where,
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name="analyses")
