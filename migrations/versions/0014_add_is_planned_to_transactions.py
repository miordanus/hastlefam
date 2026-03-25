"""Add is_planned column to transactions

Revision ID: 0014
Revises: 0013
Create Date: 2026-03-25

is_planned=True marks a transaction as a future/planned expense or income.
ЗАКОН: is_planned=True НИКОГДА не входит в расходы/доходы (actual).
       Нарушать нельзя нигде: finance_service, month, ask, insights.
"""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE hastlefam.transactions
          ADD COLUMN IF NOT EXISTS is_planned BOOLEAN NOT NULL DEFAULT FALSE;
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_transactions_is_planned
          ON hastlefam.transactions(is_planned);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS hastlefam.ix_transactions_is_planned;")
    op.execute("ALTER TABLE hastlefam.transactions DROP COLUMN IF EXISTS is_planned;")
