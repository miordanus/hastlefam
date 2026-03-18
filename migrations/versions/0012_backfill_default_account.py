"""backfill default Наличные RUB account per household

Revision ID: 0012
Revises: 0011
Create Date: 2026-03-18

1. Creates a "Наличные" RUB account for every household that doesn't have one.
2. Sets account_id on all transactions that still have account_id IS NULL,
   pointing to the default "Наличные" RUB account of that household.
"""
from __future__ import annotations

from alembic import op


revision = "0012_backfill_default_account"
down_revision = "0011_fx_rates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO accounts (id, household_id, name, currency, is_shared, is_active, created_at)
        SELECT gen_random_uuid(), h.id, 'Наличные', 'RUB', true, true, now()
        FROM households h
        WHERE NOT EXISTS (
            SELECT 1 FROM accounts a
            WHERE a.household_id = h.id
              AND a.name = 'Наличные'
              AND a.currency = 'RUB'
        );
    """)
    op.execute("""
        UPDATE transactions t
        SET account_id = (
            SELECT a.id FROM accounts a
            WHERE a.household_id = t.household_id
              AND a.name = 'Наличные'
              AND a.currency = 'RUB'
            LIMIT 1
        )
        WHERE t.account_id IS NULL;
    """)


def downgrade() -> None:
    # Not reversible — account_id backfill cannot be safely undone.
    pass
