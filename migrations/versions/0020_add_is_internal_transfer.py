"""Add is_internal_transfer to transactions

Revision ID: 0020
Revises: 0019
Create Date: 2026-04-01

Adds a boolean flag to mark intra-household fund movements (e.g. ATM
top-ups that are credit-card replenishments) so they are excluded from
income/expense aggregations.
"""
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE hastlefam.transactions
          ADD COLUMN IF NOT EXISTS is_internal_transfer BOOLEAN NOT NULL DEFAULT FALSE;
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE hastlefam.transactions
          DROP COLUMN IF EXISTS is_internal_transfer;
    """)
