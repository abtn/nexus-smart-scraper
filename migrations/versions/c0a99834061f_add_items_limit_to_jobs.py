"""add_items_limit_to_jobs

Revision ID: c0a99834061f
Revises: b90af958b767
Create Date: 2026-01-05 13:58:37.003971

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c0a99834061f'
down_revision: Union[str, Sequence[str], None] = 'b90af958b767'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add column with default value of 10 to prevent errors on existing rows
    op.add_column('scheduled_jobs', sa.Column('items_limit', sa.Integer(), nullable=False, 
        server_default='10'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('scheduled_jobs', 'items_limit')
