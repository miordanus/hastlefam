from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

DB_SCHEMA = 'hastlefam'


class Base(DeclarativeBase):
    metadata = MetaData(schema=DB_SCHEMA)
