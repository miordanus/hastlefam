import uuid
from sqlalchemy import text

EXPENSES = [
    'Housing', 'Utilities', 'Internet & Mobile', 'Groceries', 'Eating Out / Delivery', 'Transport',
    'Health / Medicine', 'Pets', 'Household Goods', 'Subscriptions', 'Shopping / Personal', 'Travel',
    'Gifts', 'Education', 'Taxes / Fees', 'Debt / Loan Payments', 'Savings / Investments', 'Other'
]
INCOMES = [
    'Salary', 'Freelance / Consulting', 'Business Income', 'Transfers In',
    'Investment Income', 'Cashback / Refunds', 'Other'
]


def run(db, household_id):
    for name in EXPENSES:
        db.execute(text(
            "INSERT INTO finance_categories (id, household_id, name, kind, is_default, created_at) "
            "VALUES (:id, :household_id, :name, 'expense', true, now())"
        ), {'id': uuid.uuid4(), 'household_id': household_id, 'name': name})

    for name in INCOMES:
        db.execute(text(
            "INSERT INTO finance_categories (id, household_id, name, kind, is_default, created_at) "
            "VALUES (:id, :household_id, :name, 'income', true, now())"
        ), {'id': uuid.uuid4(), 'household_id': household_id, 'name': name})
    db.commit()
