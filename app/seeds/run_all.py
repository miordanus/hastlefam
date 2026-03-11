import uuid
from sqlalchemy import text
from app.infrastructure.db.session import SessionLocal
from app.infrastructure.db.base import DB_SCHEMA
from app.seeds import seed_areas, seed_finance_categories


def main():
    db = SessionLocal()
    try:
        household_id = db.execute(text(f'SELECT id FROM {DB_SCHEMA}.households ORDER BY created_at LIMIT 1')).scalar()
        if household_id is None:
            household_id = uuid.uuid4()
            db.execute(text(
                f"INSERT INTO {DB_SCHEMA}.households (id, name, created_at, updated_at) VALUES (:id, 'Default Household', now(), now())"
            ), {'id': household_id})
            db.commit()
        seed_areas.run(db, household_id)
        seed_finance_categories.run(db, household_id)
    finally:
        db.close()


if __name__ == '__main__':
    main()
