"""update the primary TV catalogue

Revision ID: f7a8b9c0d1e2
Revises: e7b3c9d1a5f2
Create Date: 2026-08-20 22:45:00
"""

import sqlalchemy as sa
from alembic import op


revision = "f7a8b9c0d1e2"
down_revision = "e7b3c9d1a5f2"
branch_labels = None
depends_on = None


OLD_REPOSITORY = "mesbahikarim63-commits/hot-dodo"
NEW_REPOSITORY = "Dragon0WaTTyler/Dragon-IPTV-Clean"


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE tv_sources
            SET locator = :new_repository,
                branch = 'main',
                status = 'untested',
                last_error = ''
            WHERE protected = 1
              AND source_type = 'github_repository'
              AND lower(trim(locator)) = :old_repository
            """
        ).bindparams(new_repository=NEW_REPOSITORY, old_repository=OLD_REPOSITORY)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE tv_sources
            SET locator = :old_repository,
                status = 'untested',
                last_error = ''
            WHERE protected = 1
              AND source_type = 'github_repository'
              AND locator = :new_repository
            """
        ).bindparams(new_repository=NEW_REPOSITORY, old_repository=OLD_REPOSITORY)
    )
