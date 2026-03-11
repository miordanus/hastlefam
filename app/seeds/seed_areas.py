import uuid
from sqlalchemy import text
from app.infrastructure.db.base import DB_SCHEMA

AREAS = [
    'Finances', 'Home', 'Relationship', 'Health', 'Admin', 'Purchases', 'Travel', 'Work / Side Projects'
]


def run(db, household_id):
    for name in AREAS:
        db.execute(text(
            f"INSERT INTO {DB_SCHEMA}.areas (id, household_id, name, is_default, created_at, updated_at) "
            "VALUES (:id, :household_id, :name, true, now(), now())"
        ), {'id': uuid.uuid4(), 'household_id': household_id, 'name': name})
    db.commit()
