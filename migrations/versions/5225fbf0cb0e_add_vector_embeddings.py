"""add_vector_embeddings

Revision ID: 5225fbf0cb0e
Revises: c0a99834061f
Create Date: 2026-01-07 08:59:27.593023

"""
from typing import Sequence, Union

from alembic import op # pyright: ignore[reportMissingImports]
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector # pyright: ignore[reportMissingImports] # New: Import Vector type from pgvector extension


# revision identifiers, used by Alembic.
revision: str = '5225fbf0cb0e'
down_revision: Union[str, Sequence[str], None] = 'c0a99834061f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    op.add_column('scraped_data', sa.Column('embedding', Vector(768), nullable=True))

def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('scraped_data', 'embedding')
    op.execute('DROP EXTENSION IF EXISTS vector')
