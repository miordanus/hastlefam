"""seed defaults

Revision ID: 0002_seed_defaults
Revises: 0001_initial_schema
Create Date: 2026-03-10
"""
import uuid
from alembic import op
import sqlalchemy as sa

revision = '0002_seed_defaults'
down_revision = '0001_initial_schema'
branch_labels = None
depends_on = None

AREAS = [
    'Finances', 'Home', 'Relationship', 'Health', 'Admin', 'Purchases', 'Travel', 'Work / Side Projects'
]
EXPENSES = [
    'Housing', 'Utilities', 'Internet & Mobile', 'Groceries', 'Eating Out / Delivery', 'Transport',
    'Health / Medicine', 'Pets', 'Household Goods', 'Subscriptions', 'Shopping / Personal', 'Travel',
    'Gifts', 'Education', 'Taxes / Fees', 'Debt / Loan Payments', 'Savings / Investments', 'Other'
]
INCOMES = [
    'Salary', 'Freelance / Consulting', 'Business Income', 'Transfers In',
    'Investment Income', 'Cashback / Refunds', 'Other'
]


def upgrade() -> None:
    conn = op.get_bind()
    household_id = conn.execute(sa.text("SELECT id FROM households ORDER BY created_at LIMIT 1")).scalar()
    if household_id is None:
        household_id = uuid.uuid4()
        conn.execute(sa.text(
            "INSERT INTO households (id,name,created_at,updated_at) VALUES (:id,'Default Household',now(),now())"
        ), {'id': household_id})

    for name in AREAS:
        conn.execute(sa.text(
            "INSERT INTO areas (id, household_id, name, is_default, created_at, updated_at) "
            "VALUES (:id, :hid, :name, true, now(), now())"
        ), {'id': uuid.uuid4(), 'hid': household_id, 'name': name})

    for name in EXPENSES:
        conn.execute(sa.text(
            "INSERT INTO finance_categories (id, household_id, name, kind, is_default, created_at) "
            "VALUES (:id, :hid, :name, 'expense', true, now())"
        ), {'id': uuid.uuid4(), 'hid': household_id, 'name': name})

    for name in INCOMES:
        conn.execute(sa.text(
            "INSERT INTO finance_categories (id, household_id, name, kind, is_default, created_at) "
            "VALUES (:id, :hid, :name, 'income', true, now())"
        ), {'id': uuid.uuid4(), 'hid': household_id, 'name': name})


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM finance_categories WHERE is_default = true"))
    conn.execute(sa.text("DELETE FROM areas WHERE is_default = true"))
