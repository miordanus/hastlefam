"""Add rollover fields to category_budgets

Revision ID: 0018
Revises: 0017
Create Date: 2026-03-28

rollover_enabled: whether unused budget carries over to the next month.
rollover_amount: the carried-over amount (set by apply_rollover logic).
"""
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE hastlefam.category_budgets
          ADD COLUMN IF NOT EXISTS rollover_enabled BOOLEAN NOT NULL DEFAULT FALSE;
    """)
    op.execute("""
        ALTER TABLE hastlefam.category_budgets
          ADD COLUMN IF NOT EXISTS rollover_amount NUMERIC(14,2) NOT NULL DEFAULT 0;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE hastlefam.category_budgets DROP COLUMN IF EXISTS rollover_amount;")
    op.execute("ALTER TABLE hastlefam.category_budgets DROP COLUMN IF EXISTS rollover_enabled;")
