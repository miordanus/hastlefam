from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.infrastructure.config.settings import get_settings


@lru_cache
def get_engine():
    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={'options': '-csearch_path=hastlefam'},
    )


def SessionLocal() -> Session:
    engine = get_engine()
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return factory()
