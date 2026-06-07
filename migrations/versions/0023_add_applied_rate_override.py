"""Add applied_rate_override to transactions

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-07

Operator-set real RUB-per-unit rate for a specific transaction. When set, it
takes precedence over the real applied exchange rate and the CBR rate when
valuing the transaction to RUB (see fx_service.valuation_rate_to_rub). NULL
keeps the existing real-rate / CBR fallback.
"""
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE hastlefam.transactions
          ADD COLUMN IF NOT EXISTS applied_rate_override NUMERIC(18, 6);
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE hastlefam.transactions
          DROP COLUMN IF EXISTS applied_rate_override;
    """)
