"""Add tag_budgets table

Revision ID: 0019
Revises: 0018
Create Date: 2026-03-28

Replaces category-based budgets with tag-based budgets.
category_budgets is kept but no longer used by the application.
"""
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS hastlefam.tag_budgets (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          household_id UUID NOT NULL REFERENCES hastlefam.households(id),
          month_key VARCHAR(7) NOT NULL,
          tag VARCHAR(255) NOT NULL,
          limit_amount NUMERIC(14,2) NOT NULL,
          currency VARCHAR(10) NOT NULL DEFAULT 'RUB',
          rollover_enabled BOOLEAN NOT NULL DEFAULT FALSE,
          rollover_amount NUMERIC(14,2) NOT NULL DEFAULT 0,
          created_at TIMESTAMPTZ DEFAULT now(),
          UNIQUE(household_id, month_key, tag)
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_tag_budgets_household_month
          ON hastlefam.tag_budgets(household_id, month_key);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS hastlefam.ix_tag_budgets_household_month;")
    op.execute("DROP TABLE IF EXISTS hastlefam.tag_budgets;")
