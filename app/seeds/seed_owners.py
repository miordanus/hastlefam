import uuid

from sqlalchemy import text

from app.infrastructure.db.base import DB_SCHEMA

OWNERS = [
    ("mine", "Mine"),
    ("wife", "Wife"),
    ("shared", "Shared"),
]


def run(db, household_id):
    for slug, name in OWNERS:
        exists = db.execute(
            text(f"SELECT 1 FROM {DB_SCHEMA}.owners WHERE household_id = :hid AND slug = :slug LIMIT 1"),
            {"hid": household_id, "slug": slug},
        ).scalar()
        if exists:
            continue
        db.execute(
            text(
                f"INSERT INTO {DB_SCHEMA}.owners (id, household_id, name, slug, is_active, created_at, updated_at) "
                "VALUES (:id, :hid, :name, :slug, true, now(), now())"
            ),
            {"id": uuid.uuid4(), "hid": household_id, "name": name, "slug": slug},
        )
    db.commit()
