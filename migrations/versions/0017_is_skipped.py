"""Add is_skipped to transactions

Revision ID: 0017
Revises: 0016
Create Date: 2026-03-28

Allows upcoming planned transactions to be skipped without deletion.
is_skipped=True → hidden from /upcoming, kept in DB for history.
"""
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE hastlefam.transactions
          ADD COLUMN IF NOT EXISTS is_skipped BOOLEAN NOT NULL DEFAULT FALSE;
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_transactions_is_skipped
          ON hastlefam.transactions(is_skipped);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS hastlefam.ix_transactions_is_skipped;")
    op.execute("ALTER TABLE hastlefam.transactions DROP COLUMN IF EXISTS is_skipped;")
