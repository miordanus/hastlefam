"""Shared helpers for FoodOps bot handlers."""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.infrastructure.db.models import User
from app.infrastructure.db.session import SessionLocal


@dataclass
class UserRef:
    id: uuid.UUID
    household_id: uuid.UUID


def find_user(telegram_id: str) -> UserRef | None:
    """Resolve a Telegram id to a detached (id, household_id) ref.

    Returns a plain dataclass so callers can use it after the session closes.
    """
    with SessionLocal() as db:
        user = (
            db.query(User)
            .filter(User.telegram_id == telegram_id, User.is_active.is_(True))
            .first()
        )
        if user is None:
            return None
        return UserRef(id=user.id, household_id=user.household_id)
