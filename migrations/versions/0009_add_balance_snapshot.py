"""add balance_snapshots table

Revision ID: 0009
Revises: 0008
Create Date: 2026-03-14

Manual balance checkpoint feature.
"""
from __future__ import annotations

import uuid
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009_add_balance_snapshot"
down_revision = "0008_add_exchange_fields_to_transaction"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "balance_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("household_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("households.id"), nullable=False),
        sa.Column("actual_balance", sa.Numeric(14, 2), nullable=False),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_balance_snapshots_account_id", "balance_snapshots", ["account_id"])
    op.create_index("ix_balance_snapshots_household_id", "balance_snapshots", ["household_id"])


def downgrade() -> None:
    op.drop_index("ix_balance_snapshots_household_id", table_name="balance_snapshots")
    op.drop_index("ix_balance_snapshots_account_id", table_name="balance_snapshots")
    op.drop_table("balance_snapshots")
