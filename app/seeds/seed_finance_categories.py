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


def _insert_default_category(db, household_id, name, kind):
    db.execute(text(
        "INSERT INTO finance_categories (id, household_id, name, kind, is_default, created_at) "
        "SELECT :id, :household_id, :name, :kind, true, now() "
        "WHERE NOT EXISTS ("
        "SELECT 1 FROM finance_categories "
        "WHERE household_id = :household_id AND name = :name AND kind = :kind AND is_default = true"
        ")"
    ), {'id': uuid.uuid4(), 'household_id': household_id, 'name': name, 'kind': kind})


def run(db, household_id):
    for name in EXPENSES:
        _insert_default_category(db, household_id, name, 'expense')

    for name in INCOMES:
        _insert_default_category(db, household_id, name, 'income')
    db.commit()
