"""add exchange fields to transactions table

Revision ID: 0008_add_exchange_fields_to_transaction
Revises: 0007_add_exchange_direction
Create Date: 2026-03-13
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_add_exchange_fields_to_transaction"
down_revision = "0007_add_exchange_direction"
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
    exchange_cols = [
        ("from_amount", sa.Column("from_amount", sa.Numeric(14, 2), nullable=True)),
        ("from_currency", sa.Column("from_currency", sa.String(10), nullable=True)),
        ("to_amount", sa.Column("to_amount", sa.Numeric(14, 2), nullable=True)),
        ("to_currency", sa.Column("to_currency", sa.String(10), nullable=True)),
        ("exchange_rate", sa.Column("exchange_rate", sa.Numeric(18, 6), nullable=True)),
    ]
    for col_name, column in exchange_cols:
        if not _has_column("transactions", col_name):
            op.add_column("transactions", column, schema=SCHEMA)


def downgrade() -> None:
    pass
