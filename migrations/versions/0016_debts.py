"""Add debts table

Revision ID: 0016
Revises: 0015
Create Date: 2026-03-25

Tracks money lent/borrowed between household members and external parties.
direction: 'i_owe' (ты должен) / 'they_owe' (тебе должны)
"""
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS hastlefam.debts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            household_id UUID NOT NULL REFERENCES hastlefam.households(id),
            counterparty_name VARCHAR(255) NOT NULL,
            amount NUMERIC(14,2) NOT NULL,
            currency VARCHAR(10) NOT NULL DEFAULT 'RUB',
            direction VARCHAR(20) NOT NULL CHECK (direction IN ('i_owe', 'they_owe')),
            created_at TIMESTAMPTZ DEFAULT now(),
            due_date DATE,
            settled_at TIMESTAMPTZ,
            linked_transaction_id UUID REFERENCES hastlefam.transactions(id) ON DELETE SET NULL,
            notes TEXT
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_debts_household_id
          ON hastlefam.debts(household_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_debts_settled_at
          ON hastlefam.debts(settled_at);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hastlefam.debts;")
