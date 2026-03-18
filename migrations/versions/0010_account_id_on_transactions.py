"""add index on transactions.account_id

Revision ID: 0010
Revises: 0009
Create Date: 2026-03-18

account_id column already exists (added in 0001/0004).
This migration adds the missing index and ensures the column
definition matches the ORM model (nullable FK to accounts).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0010_account_id_on_transactions"
down_revision = "0009_add_balance_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Column already exists from migration 0001/0004.
    # Add IF NOT EXISTS guard via raw SQL so re-running is safe.
    op.execute("""
        ALTER TABLE transactions
            ADD COLUMN IF NOT EXISTS account_id UUID
            REFERENCES accounts(id) ON DELETE SET NULL;
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_transactions_account_id
            ON transactions(account_id);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_transactions_account_id;")
