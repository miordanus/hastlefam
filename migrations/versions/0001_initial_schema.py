"""initial schema

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-03-10
"""
from alembic import op

revision = '0001_initial_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.infrastructure.db.base import Base
    import app.infrastructure.db.models  # noqa: F401
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    from app.infrastructure.db.base import Base
    import app.infrastructure.db.models  # noqa: F401
    Base.metadata.drop_all(bind=op.get_bind())
