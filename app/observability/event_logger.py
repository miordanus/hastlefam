import json
import uuid
from sqlalchemy import text
from app.infrastructure.db.base import DB_SCHEMA


def log_event(db, *, event_type: str, payload: dict, household_id=None, user_id=None, severity='info'):
    db.execute(text(
        f"INSERT INTO {DB_SCHEMA}.event_log (id, household_id, user_id, event_type, payload, severity, created_at) "
        "VALUES (:id, :household_id, :user_id, :event_type, :payload::json, :severity, now())"
    ), {
        'id': uuid.uuid4(),
        'household_id': household_id,
        'user_id': user_id,
        'event_type': event_type,
        'payload': json.dumps(payload),
        'severity': severity,
    })
    db.commit()
