import os
import uuid

from sqlalchemy import text

from app.infrastructure.db.base import DB_SCHEMA

# Configure via environment variables or edit defaults below.
# Each entry: (telegram_id, display_name)
_DEFAULT_USERS = [
    (os.environ.get("TELEGRAM_ID_MINE", ""), "Mine"),
    (os.environ.get("TELEGRAM_ID_WIFE", ""), "Wife"),
]


def run(db, household_id):
    for telegram_id, name in _DEFAULT_USERS:
        if not telegram_id:
            continue
        exists = db.execute(
            text(f"SELECT 1 FROM {DB_SCHEMA}.users WHERE telegram_id = :tid LIMIT 1"),
            {"tid": telegram_id},
        ).scalar()
        if exists:
            continue
        db.execute(
            text(
                f"INSERT INTO {DB_SCHEMA}.users (id, household_id, telegram_id, name, is_active, created_at, updated_at) "
                "VALUES (:id, :hid, :tid, :name, true, now(), now())"
            ),
            {"id": uuid.uuid4(), "hid": household_id, "tid": telegram_id, "name": name},
        )
    db.commit()
