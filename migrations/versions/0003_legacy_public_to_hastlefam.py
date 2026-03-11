"""legacy public-to-hastlefam migration

Revision ID: 0003_legacy_public_to_hastlefam
Revises: 0002_seed_defaults
Create Date: 2026-03-11
"""
from alembic import op

revision = "0003_legacy_public_to_hastlefam"
down_revision = "0002_seed_defaults"
branch_labels = None
depends_on = None


TABLES = [
    "households",
    "users",
    "areas",
    "sprints",
    "tasks",
    "decisions",
    "notes",
    "meetings",
    "transactions",
    "finance_categories",
    "accounts",
    "recurring_payments",
    "savings_goals",
    "reminders",
    "digests",
    "llm_drafts",
    "event_log",
]


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS hastlefam")

    for table_name in TABLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF to_regclass('public.{table_name}') IS NOT NULL
                   AND to_regclass('hastlefam.{table_name}') IS NULL THEN
                    EXECUTE 'ALTER TABLE public.{table_name} SET SCHEMA hastlefam';
                END IF;
            END $$;
            """
        )


def downgrade() -> None:
    # Intentionally no-op: this migration safely moves legacy tables into the app schema.
    pass
