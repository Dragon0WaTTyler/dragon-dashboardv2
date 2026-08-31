"""add Google personal workspace foundation

Revision ID: c1a4d9e7b2f6
Revises: c2f7a1d9e4b6
Create Date: 2026-08-31 02:20:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c1a4d9e7b2f6"
down_revision = "c2f7a1d9e4b6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "external_identities",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False, server_default=""),
        sa.Column("display_name", sa.String(length=240), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "subject", name="uq_identity_provider_subject"),
    )
    op.create_index("ix_external_identities_user_id", "external_identities", ["user_id"])

    op.create_table(
        "personal_workspaces",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "storage_provider",
            sa.String(length=40),
            nullable=False,
            server_default="google_drive",
        ),
        sa.Column("remote_locator", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("state", sa.String(length=40), nullable=False, server_default="provisioning"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_user_id"),
    )
    op.create_index(
        "ix_personal_workspaces_owner_user_id",
        "personal_workspaces",
        ["owner_user_id"],
    )

    op.create_table(
        "workspace_connections",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("workspace_id", sa.String(length=40), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("credential_ciphertext", sa.Text(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["personal_workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "provider", name="uq_workspace_connection"),
    )
    op.create_index(
        "ix_workspace_connections_workspace_id",
        "workspace_connections",
        ["workspace_id"],
    )


def downgrade():
    op.drop_index("ix_workspace_connections_workspace_id", table_name="workspace_connections")
    op.drop_table("workspace_connections")
    op.drop_index("ix_personal_workspaces_owner_user_id", table_name="personal_workspaces")
    op.drop_table("personal_workspaces")
    op.drop_index("ix_external_identities_user_id", table_name="external_identities")
    op.drop_table("external_identities")
