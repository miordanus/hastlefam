"""create fx_rates table

Revision ID: 0011
Revises: 0010
Create Date: 2026-03-18

Stores daily FX rates fetched from exchangerate-api.com.
Used by fx_service to convert multi-currency amounts to RUB totals.
"""
from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0011_fx_rates"
down_revision = "0010_account_id_on_transactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS fx_rates (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            date          DATE NOT NULL,
            from_currency VARCHAR(10) NOT NULL,
            to_currency   VARCHAR(10) NOT NULL,
            rate          NUMERIC(18, 6) NOT NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (date, from_currency, to_currency)
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_fx_rates_date
            ON fx_rates (date);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_fx_rates_date;")
    op.execute("DROP TABLE IF EXISTS fx_rates;")
