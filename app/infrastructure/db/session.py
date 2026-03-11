from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.infrastructure.config.settings import get_settings

settings = get_settings()
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={'options': '-csearch_path=hastlefam'},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
