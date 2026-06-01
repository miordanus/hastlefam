"""Add month_lock table (approve & lock a month)

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-01

Snapshots approved actual income/expense (RUB) for a month and freezes that
month's transactions from edits while is_locked. Unique per (household, month).
"""
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS hastlefam.month_lock (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          household_id UUID NOT NULL REFERENCES hastlefam.households(id),
          month_key VARCHAR(7) NOT NULL,
          is_locked BOOLEAN NOT NULL DEFAULT TRUE,
          income_rub NUMERIC(14,2) NOT NULL DEFAULT 0,
          expense_rub NUMERIC(14,2) NOT NULL DEFAULT 0,
          locked_at TIMESTAMPTZ DEFAULT now(),
          locked_by_user_id UUID REFERENCES hastlefam.users(id),
          unlocked_at TIMESTAMPTZ,
          CONSTRAINT uq_month_lock_household_month UNIQUE (household_id, month_key)
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hastlefam.month_lock;")
