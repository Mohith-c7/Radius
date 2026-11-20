"""Persist Radius test manifests, report slots, and provenance history.

Revision ID: 20261115_0024
Revises: 20261105_0023
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261115_0024"
down_revision: str | None = "20261105_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "test_evidence_manifests",
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("head_sha", sa.String(64), nullable=False),
        sa.Column("manifest_version", sa.Integer(), nullable=False),
        sa.Column("canonical_manifest", sa.JSON(), nullable=False),
        sa.Column("digest_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"]),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_id"),
        sa.UniqueConstraint("digest_sha256"),
    )
    op.create_index(
        "ix_test_evidence_manifests_analysis_id",
        "test_evidence_manifests",
        ["analysis_id"],
    )
    op.create_index(
        "ix_test_evidence_manifests_repository_id",
        "test_evidence_manifests",
        ["repository_id"],
    )

    op.add_column(
        "test_result_uploads",
        sa.Column("repository_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "test_result_uploads",
        sa.Column(
            "report_slot_id", sa.String(128), server_default="legacy", nullable=False
        ),
    )
    op.add_column("test_result_uploads", sa.Column("run_id", sa.String(32)))
    op.add_column("test_result_uploads", sa.Column("run_attempt", sa.Integer()))
    op.add_column("test_result_uploads", sa.Column("manifest_id", sa.Uuid()))
    op.add_column("test_result_uploads", sa.Column("manifest_digest", sa.String(64)))
    op.add_column("test_result_uploads", sa.Column("artifact_bytes", sa.LargeBinary()))
    op.add_column("test_result_uploads", sa.Column("attestation_bundle", sa.LargeBinary()))
    op.add_column("test_result_uploads", sa.Column("attestation_digest", sa.String(64)))
    op.add_column(
        "test_result_uploads",
        sa.Column(
            "provenance_status",
            sa.String(32),
            server_default="untrusted",
            nullable=False,
        ),
    )
    op.add_column(
        "test_result_uploads", sa.Column("provenance_reason_code", sa.String(64))
    )
    op.execute(
        "UPDATE test_result_uploads "
        "SET repository_id = (SELECT repository_id FROM analyses "
        "WHERE analyses.id = test_result_uploads.analysis_id)"
    )
    with op.batch_alter_table("test_result_uploads") as batch:
        batch.drop_constraint(
            "uq_test_result_uploads_analysis_id_body_sha256", type_="unique"
        )
        batch.create_foreign_key(
            "fk_test_result_uploads_repository_id_repositories",
            "repositories", ["repository_id"], ["id"],
        )
        batch.create_foreign_key(
            "fk_test_result_uploads_manifest_id_test_evidence_manifests",
            "test_evidence_manifests", ["manifest_id"], ["id"],
        )
        batch.create_unique_constraint(
            "uq_test_result_uploads_analysis_slot_body",
            ["analysis_id", "report_slot_id", "run_id", "run_attempt", "body_sha256"],
        )
        batch.create_unique_constraint(
            "uq_test_result_uploads_repo_run_attempt_slot",
            ["repository_id", "run_id", "run_attempt", "report_slot_id"],
        )
        batch.create_unique_constraint(
            "uq_test_result_uploads_repo_attestation_digest",
            ["repository_id", "attestation_digest"],
        )
    op.create_index(
        "ix_test_result_uploads_manifest_id", "test_result_uploads", ["manifest_id"]
    )
    op.execute(
        "UPDATE test_result_uploads SET provenance_status = 'untrusted'"
    )

    op.create_table(
        "test_evidence_verification_events",
        sa.Column("upload_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(64)),
        sa.Column("verifier_version", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("attestation_digest", sa.String(64)),
        sa.Column("attestation_bundle", sa.LargeBinary()),
        sa.Column("details", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["upload_id"], ["test_result_uploads.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_test_evidence_verification_upload",
        "test_evidence_verification_events",
        ["upload_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM test_evidence_manifests LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade while immutable evidence manifests exist.")
    if bind.execute(sa.text("SELECT 1 FROM test_evidence_verification_events LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade while provenance verification history exists.")
    op.drop_index(
        "ix_test_evidence_verification_upload",
        table_name="test_evidence_verification_events",
    )
    op.drop_table("test_evidence_verification_events")
    op.drop_index("ix_test_result_uploads_manifest_id", table_name="test_result_uploads")
    with op.batch_alter_table("test_result_uploads") as batch:
        batch.drop_constraint("uq_test_result_uploads_repo_attestation_digest", type_="unique")
        batch.drop_constraint("uq_test_result_uploads_repo_run_attempt_slot", type_="unique")
        batch.drop_constraint("uq_test_result_uploads_analysis_slot_body", type_="unique")
        batch.create_unique_constraint(
            "uq_test_result_uploads_analysis_id_body_sha256", ["analysis_id", "body_sha256"]
        )
        batch.drop_constraint(
            "fk_test_result_uploads_manifest_id_test_evidence_manifests", type_="foreignkey"
        )
        batch.drop_constraint(
            "fk_test_result_uploads_repository_id_repositories", type_="foreignkey"
        )
        for name in (
            "provenance_reason_code", "provenance_status", "attestation_digest",
            "artifact_bytes", "attestation_bundle", "manifest_digest", "manifest_id",
            "run_attempt", "run_id", "report_slot_id", "repository_id",
        ):
            batch.drop_column(name)
    op.drop_index(
        "ix_test_evidence_manifests_repository_id", table_name="test_evidence_manifests"
    )
    op.drop_index(
        "ix_test_evidence_manifests_analysis_id", table_name="test_evidence_manifests"
    )
    op.drop_table("test_evidence_manifests")
