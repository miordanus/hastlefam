from collections.abc import Generator
from app.infrastructure.db.session import SessionLocal


def get_db() -> Generator:
    with SessionLocal() as db:
        yield db
