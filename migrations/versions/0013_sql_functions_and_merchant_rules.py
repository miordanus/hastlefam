"""Add SQL aggregation functions + merchant_tag_rules table

Revision ID: 0013
Revises: 0012
Create Date: 2026-03-21

1. SQL function: hf_month_summary(household_uuid, year, month) — returns
   spend/income by currency, top tags, untagged count.  All in one query.
2. SQL function: hf_balance_deltas(household_uuid, year, month) — returns
   per-account current balance, month-start balance, and delta.
3. New table: merchant_tag_rules — auto-categorization rules per household.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "0013_sql_functions_and_merchant_rules"
down_revision = "0012_backfill_default_account"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─── merchant_tag_rules table ───────────────────────────────────────────
    op.create_table(
        "merchant_tag_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("household_id", UUID(as_uuid=True), sa.ForeignKey("households.id"), nullable=False),
        sa.Column("merchant_pattern", sa.String(255), nullable=False),
        sa.Column("tag", sa.String(64), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="auto"),
        sa.Column("hit_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_merchant_tag_rules_household_merchant",
        "merchant_tag_rules",
        ["household_id", "merchant_pattern"],
        unique=True,
    )

    # ─── SQL function: hf_month_summary ─────────────────────────────────────
    op.execute("""
    CREATE OR REPLACE FUNCTION hf_month_summary(
        p_household_id UUID,
        p_year INT,
        p_month INT
    )
    RETURNS TABLE (
        direction TEXT,
        currency TEXT,
        primary_tag TEXT,
        total_amount NUMERIC(14,2),
        tx_count BIGINT
    )
    LANGUAGE sql STABLE
    AS $$
        SELECT
            t.direction::text,
            t.currency::text,
            t.primary_tag,
            SUM(t.amount)::numeric(14,2) AS total_amount,
            COUNT(*)                      AS tx_count
        FROM transactions t
        WHERE t.household_id = p_household_id
          AND t.occurred_at >= make_timestamptz(p_year, p_month, 1, 0, 0, 0, 'UTC')
          AND t.occurred_at <  make_timestamptz(p_year, p_month, 1, 0, 0, 0, 'UTC')
                                + interval '1 month'
          AND t.direction NOT IN ('transfer', 'exchange')
        GROUP BY t.direction, t.currency, t.primary_tag
    $$;
    """)

    # ─── SQL function: hf_balance_deltas ────────────────────────────────────
    op.execute("""
    CREATE OR REPLACE FUNCTION hf_balance_deltas(
        p_household_id UUID,
        p_year INT,
        p_month INT
    )
    RETURNS TABLE (
        account_id UUID,
        account_name TEXT,
        currency TEXT,
        current_balance NUMERIC(14,2),
        month_start_balance NUMERIC(14,2),
        delta NUMERIC(14,2)
    )
    LANGUAGE sql STABLE
    AS $$
        WITH month_start AS (
            SELECT make_timestamptz(p_year, p_month, 1, 0, 0, 0, 'UTC') AS ts
        ),
        latest_snap AS (
            SELECT DISTINCT ON (bs.account_id)
                bs.account_id,
                bs.actual_balance
            FROM balance_snapshots bs
            WHERE bs.household_id = p_household_id
            ORDER BY bs.account_id, bs.created_at DESC
        ),
        start_snap AS (
            SELECT DISTINCT ON (bs.account_id)
                bs.account_id,
                bs.actual_balance
            FROM balance_snapshots bs, month_start ms
            WHERE bs.household_id = p_household_id
              AND bs.created_at < ms.ts
            ORDER BY bs.account_id, bs.created_at DESC
        )
        SELECT
            a.id                         AS account_id,
            a.name::text                 AS account_name,
            a.currency::text             AS currency,
            ls.actual_balance            AS current_balance,
            ss.actual_balance            AS month_start_balance,
            (ls.actual_balance - COALESCE(ss.actual_balance, ls.actual_balance))
                                         AS delta
        FROM accounts a
        LEFT JOIN latest_snap ls ON ls.account_id = a.id
        LEFT JOIN start_snap  ss ON ss.account_id = a.id
        WHERE a.household_id = p_household_id
          AND a.is_active = true
          AND ls.actual_balance IS NOT NULL
        ORDER BY a.created_at ASC;
    $$;
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS hf_balance_deltas(UUID, INT, INT);")
    op.execute("DROP FUNCTION IF EXISTS hf_month_summary(UUID, INT, INT);")
    op.drop_index("ix_merchant_tag_rules_household_merchant")
    op.drop_table("merchant_tag_rules")
