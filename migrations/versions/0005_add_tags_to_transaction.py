"""add primary_tag and extra_tags to transactions

Revision ID: 0005_add_tags_to_transaction
Revises: 0004_money_mvp_slice
Create Date: 2026-03-13
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_add_tags_to_transaction"
down_revision = "0004_money_mvp_slice"
branch_labels = None
depends_on = None
SCHEMA = "hastlefam"


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = :schema
              AND table_name = :table
              AND column_name = :column
            """
        ),
        {"schema": SCHEMA, "table": table, "column": column},
    ).scalar()
    return bool(result)


def upgrade() -> None:
    if not _has_column("transactions", "primary_tag"):
        op.add_column(
            "transactions",
            sa.Column("primary_tag", sa.String(64), nullable=True),
            schema=SCHEMA,
        )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_transactions_primary_tag ON {SCHEMA}.transactions (primary_tag)"
        )

    if not _has_column("transactions", "extra_tags"):
        op.add_column(
            "transactions",
            sa.Column("extra_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default="'[]'::jsonb"),
            schema=SCHEMA,
        )


def downgrade() -> None:
    pass
