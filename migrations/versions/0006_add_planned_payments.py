"""add planned_payments table

Revision ID: 0006_add_planned_payments
Revises: 0005_add_tags_to_transaction
Create Date: 2026-03-13
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_add_planned_payments"
down_revision = "0005_add_tags_to_transaction"
branch_labels = None
depends_on = None
SCHEMA = "hastlefam"


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = :schema
              AND table_name = :table
            """
        ),
        {"schema": SCHEMA, "table": table},
    ).scalar()
    return bool(result)


def upgrade() -> None:
    if not _has_table("planned_payments"):
        op.execute(
            f"""
            CREATE TABLE {SCHEMA}.planned_payments (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                household_id uuid NOT NULL REFERENCES {SCHEMA}.households(id),
                owner_id uuid REFERENCES {SCHEMA}.owners(id),
                title varchar(255) NOT NULL,
                amount numeric(14,2) NOT NULL,
                currency varchar(10) NOT NULL,
                due_date date NOT NULL,
                primary_tag varchar(64),
                extra_tags jsonb NOT NULL DEFAULT '[]'::jsonb,
                status varchar(20) NOT NULL DEFAULT 'planned',
                note text,
                created_at timestamptz NOT NULL DEFAULT now(),
                linked_transaction_id uuid REFERENCES {SCHEMA}.transactions(id)
            )
            """
        )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_planned_payments_household_due ON {SCHEMA}.planned_payments (household_id, due_date)"
        )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_planned_payments_status ON {SCHEMA}.planned_payments (status)"
        )


def downgrade() -> None:
    pass
