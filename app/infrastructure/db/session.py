from contextlib import contextmanager
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
        pool_size=10,
        max_overflow=20,
        pool_timeout=10,          # fail fast instead of hanging forever
        connect_args={'options': '-csearch_path=hastlefam'},
    )


@lru_cache
def get_session_factory():
    return sessionmaker(autocommit=False, autoflush=False, bind=get_engine())


@contextmanager
def SessionLocal():
    """Yield a SQLAlchemy session, always closing it on exit."""
    session: Session = get_session_factory()()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
