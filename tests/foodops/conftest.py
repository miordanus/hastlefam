import uuid

import pytest

from app.infrastructure.db.models import Household, User


@pytest.fixture()
def household(db):
    """A household + user on the in-memory DB (reuses root `db` fixture)."""
    hid = uuid.uuid4()
    uid = uuid.uuid4()
    db.add(Household(id=hid, name="FoodOps Test Fam"))
    db.add(User(id=uid, household_id=hid, telegram_id="tg-food-1", name="Max"))
    db.flush()
    return hid, uid
