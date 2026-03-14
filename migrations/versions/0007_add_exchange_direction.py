"""add exchange value to transaction_direction_enum

Revision ID: 0007_add_exchange_direction
Revises: 0006_add_planned_payments
Create Date: 2026-03-13

NOTE: ALTER TYPE ADD VALUE cannot run inside a transaction in PostgreSQL.
Alembic runs this migration with transaction_per_migration=False.
This migration has no downgrade — ADD VALUE is irreversible without
dropping the type. Add to manual_apply.sql instead if Alembic can't connect.
"""

from alembic import op

revision = "0007_add_exchange_direction"
down_revision = "0006_add_planned_payments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE hastlefam.transaction_direction_enum ADD VALUE IF NOT EXISTS 'exchange'")


def downgrade() -> None:
    # Cannot remove an enum value in PostgreSQL without recreating the type.
    pass
