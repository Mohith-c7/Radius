"""Placeholder for the verdict_v2_requests outbox table (Verdict v2 alpha).

Created empty by VS-00 so the revision chain exists before any task starts.
VS-07 fills ``upgrade``/``downgrade`` (table ``verdict_v2_requests``, design 4.2)
and edits only this file.

Revision ID: 20261102_0014
Revises: 20261102_0013
Create Date: 2026-11-02
"""

from collections.abc import Sequence

revision: str = "20261102_0014"
down_revision: str | None = "20261102_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op until VS-07 creates the ``verdict_v2_requests`` table."""


def downgrade() -> None:
    """No-op until VS-07 drops the ``verdict_v2_requests`` table."""
