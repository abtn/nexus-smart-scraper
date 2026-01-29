"""add_generated_content_table

Revision ID: 1a71200c3f9e
Revises: 5225fbf0cb0e
Create Date: 2026-01-29 12:49:17.442105

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1a71200c3f9e'
down_revision: Union[str, Sequence[str], None] = '5225fbf0cb0e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'generated_content',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_id', sa.String(length=64), nullable=False),
        sa.Column('user_prompt', sa.Text(), nullable=False),
        sa.Column('generated_text', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='processing'),
        sa.Column('search_queries', sa.JSON(), nullable=True),
        sa.Column('used_article_ids', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_generated_content_task_id'), 'generated_content', ['task_id'], unique=True)
    op.create_index(op.f('ix_generated_content_status'), 'generated_content', ['status'], unique=False)



def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_generated_content_status'), table_name='generated_content')
    op.drop_index(op.f('ix_generated_content_task_id'), table_name='generated_content')
    op.drop_table('generated_content')
