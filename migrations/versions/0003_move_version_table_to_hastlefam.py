"""move alembic version table to hastlefam schema

Revision ID: 0003_move_version_table_to_hastlefam
Revises: 0002_seed_defaults
Create Date: 2026-03-11
"""

from alembic import op
import sqlalchemy as sa

from app.infrastructure.db.base import DB_SCHEMA

revision = '0003_move_version_table_to_hastlefam'
down_revision = '0002_seed_defaults'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text(f'CREATE SCHEMA IF NOT EXISTS {DB_SCHEMA}'))
    conn.execute(
        sa.text(
            f'CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.hf_alembic_version '
            '(version_num VARCHAR(32) NOT NULL PRIMARY KEY)'
        )
    )

    source_exists = conn.execute(
        sa.text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
    ).scalar()
    target_empty = conn.execute(
        sa.text(f'SELECT NOT EXISTS (SELECT 1 FROM {DB_SCHEMA}.hf_alembic_version)')
    ).scalar()

    if source_exists and target_empty:
        conn.execute(
            sa.text(
                f'INSERT INTO {DB_SCHEMA}.hf_alembic_version (version_num) '
                'SELECT version_num FROM public.alembic_version'
            )
        )


def downgrade() -> None:
    pass
