"""money mvp vertical slice

Revision ID: 0004_money_mvp_slice
Revises: 0003_legacy_public_to_hastlefam
Create Date: 2026-03-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_money_mvp_slice"
down_revision = "0003_legacy_public_to_hastlefam"
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
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.owners (
            id uuid PRIMARY KEY,
            household_id uuid NOT NULL REFERENCES {SCHEMA}.households(id),
            name varchar(255) NOT NULL,
            slug varchar(32) NOT NULL,
            is_active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_owners_household_id ON {SCHEMA}.owners (household_id)")

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.raw_import_transactions (
            id uuid PRIMARY KEY,
            household_id uuid NOT NULL REFERENCES {SCHEMA}.households(id),
            import_batch_id varchar(128) NOT NULL,
            source_name varchar(64) NOT NULL,
            imported_at timestamptz NOT NULL DEFAULT now(),
            raw_payload json NOT NULL,
            raw_occurred_at timestamptz NULL,
            raw_amount numeric(14,2) NULL,
            raw_currency varchar(8) NULL,
            raw_merchant varchar(255) NULL,
            raw_description text NULL,
            normalization_status varchar(32) NOT NULL DEFAULT 'pending',
            normalization_error text NULL
        )
        """
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_raw_import_status_imported_at ON {SCHEMA}.raw_import_transactions (normalization_status, imported_at)"
    )

    if not _has_column("accounts", "owner_id"):
        op.add_column(
            "accounts",
            sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.owners.id"), nullable=True),
            schema=SCHEMA,
        )
    if not _has_column("accounts", "is_active"):
        op.add_column("accounts", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")), schema=SCHEMA)

    if _has_column("transactions", "account_id"):
        op.alter_column("transactions", "account_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True, schema=SCHEMA)
    if _has_column("transactions", "category_id"):
        op.alter_column("transactions", "category_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True, schema=SCHEMA)

    new_tx_columns = [
        ("owner_id", sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.owners.id"), nullable=True)),
        ("merchant_raw", sa.Column("merchant_raw", sa.String(length=255), nullable=True)),
        ("description_raw", sa.Column("description_raw", sa.Text(), nullable=True)),
        ("source", sa.Column("source", sa.String(length=64), nullable=False, server_default="manual")),
        ("raw_import_id", sa.Column("raw_import_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.raw_import_transactions.id"), nullable=True)),
        ("parse_status", sa.Column("parse_status", sa.String(length=32), nullable=True)),
        ("parse_confidence", sa.Column("parse_confidence", sa.Numeric(4, 3), nullable=True)),
        ("dedup_fingerprint", sa.Column("dedup_fingerprint", sa.String(length=128), nullable=True)),
        ("updated_at", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))),
    ]
    for col_name, column in new_tx_columns:
        if not _has_column("transactions", col_name):
            op.add_column("transactions", column, schema=SCHEMA)

    op.execute(f"CREATE INDEX IF NOT EXISTS ix_transactions_dedup_fingerprint ON {SCHEMA}.transactions (dedup_fingerprint)")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_transactions_owner_id ON {SCHEMA}.transactions (owner_id)")

    recurring_cols = [
        ("owner_id", sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.owners.id"), nullable=True)),
        ("title", sa.Column("title", sa.String(length=255), nullable=True)),
        ("amount_expected", sa.Column("amount_expected", sa.Numeric(14, 2), nullable=True)),
        ("cadence", sa.Column("cadence", sa.String(length=16), nullable=True)),
        ("day_of_month", sa.Column("day_of_month", sa.Integer(), nullable=True)),
    ]
    for col_name, column in recurring_cols:
        if not _has_column("recurring_payments", col_name):
            op.add_column("recurring_payments", column, schema=SCHEMA)

    if _has_column("recurring_payments", "account_id"):
        op.alter_column("recurring_payments", "account_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True, schema=SCHEMA)
    if _has_column("recurring_payments", "category_id"):
        op.alter_column("recurring_payments", "category_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True, schema=SCHEMA)

    op.execute(f"UPDATE {SCHEMA}.recurring_payments SET title = COALESCE(title, name)")
    op.execute(f"UPDATE {SCHEMA}.recurring_payments SET amount_expected = COALESCE(amount_expected, amount)")
    op.execute(f"UPDATE {SCHEMA}.recurring_payments SET cadence = COALESCE(cadence, period, 'monthly')")
    op.execute(f"UPDATE {SCHEMA}.recurring_payments SET day_of_month = COALESCE(day_of_month, EXTRACT(DAY FROM next_due_date)::int)")
    op.execute(f"ALTER TABLE {SCHEMA}.recurring_payments ALTER COLUMN title SET NOT NULL")
    op.execute(f"ALTER TABLE {SCHEMA}.recurring_payments ALTER COLUMN cadence SET NOT NULL")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_recurring_due_active ON {SCHEMA}.recurring_payments (next_due_date, is_active)")


def downgrade() -> None:
    # intentionally lightweight; schema evolution is forward-focused for MVP.
    pass
