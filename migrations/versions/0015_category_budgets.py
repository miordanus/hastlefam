"""Add category_budgets table

Revision ID: 0015
Revises: 0014
Create Date: 2026-03-25

Per-household monthly budget limits per finance category.
"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS hastlefam.category_budgets (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            household_id UUID NOT NULL REFERENCES hastlefam.households(id),
            month_key VARCHAR(7) NOT NULL,
            category_id UUID REFERENCES hastlefam.finance_categories(id),
            limit_amount NUMERIC(14,2) NOT NULL,
            currency VARCHAR(10) NOT NULL DEFAULT 'RUB',
            created_at TIMESTAMPTZ DEFAULT now(),
            UNIQUE(household_id, month_key, category_id)
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_category_budgets_household_month
          ON hastlefam.category_budgets(household_id, month_key);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hastlefam.category_budgets;")
