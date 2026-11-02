"""Placeholder for the verdict_v2 table (Verdict v2 alpha).

Created empty by VS-00 so the revision chain exists before any task starts.
VD-03 fills ``upgrade``/``downgrade`` (table ``verdict_v2``, design 4.2) and
edits only this file.

Revision ID: 20261102_0013
Revises: 20261102_0012
Create Date: 2026-11-02
"""

from collections.abc import Sequence

revision: str = "20261102_0013"
down_revision: str | None = "20261102_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op until VD-03 creates the ``verdict_v2`` table."""


def downgrade() -> None:
    """No-op until VD-03 drops the ``verdict_v2`` table."""
