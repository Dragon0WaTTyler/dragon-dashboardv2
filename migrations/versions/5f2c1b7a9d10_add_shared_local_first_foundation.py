"""add shared local-first foundation

Revision ID: 5f2c1b7a9d10
Revises: b86bbec3d904
Create Date: 2026-07-14 01:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "5f2c1b7a9d10"
down_revision = "b86bbec3d904"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "operations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("domain", sa.String(length=40), nullable=False),
        sa.Column("scope", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("safe_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_operations_domain_created", "operations", ["domain", "created_at"], unique=False
    )
    op.create_table(
        "snapshot_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("domain", sa.String(length=40), nullable=False),
        sa.Column("schema_version", sa.String(length=80), nullable=False),
        sa.Column("relative_path", sa.String(length=255), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("message", sa.String(length=300), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_snapshot_records_domain", "snapshot_records", ["domain"], unique=True)
    op.create_table(
        "legacy_id_map",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_system", sa.String(length=60), nullable=False),
        sa.Column("entity_type", sa.String(length=60), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=False),
        sa.Column("source_checksum", sa.String(length=64), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_system",
            "entity_type",
            "source_id",
            name="uq_legacy_id_source_entity",
        ),
    )
    op.create_table(
        "migration_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("mode", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("source_root", sa.String(length=1024), nullable=False),
        sa.Column("manifest_path", sa.String(length=1024), nullable=True),
        sa.Column("report_path", sa.String(length=1024), nullable=True),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("migration_runs")
    op.drop_table("legacy_id_map")
    op.drop_index("ix_snapshot_records_domain", table_name="snapshot_records")
    op.drop_table("snapshot_records")
    op.drop_index("ix_operations_domain_created", table_name="operations")
    op.drop_table("operations")
