"""add_job_type_enum

Revision ID: b90af958b767
Revises: 2314b1fc27cf
Create Date: 2026-01-05 13:16:28.615960

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b90af958b767'
down_revision: Union[str, Sequence[str], None] = '2314b1fc27cf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
     # 1. Create the Enum type in Postgres
    # We use sync logic to handle the Enum creation safely
    job_type_enum = sa.Enum('RSS', 'DISCOVERY', 'SINGLE', name='jobtype')
    job_type_enum.create(op.get_bind(), checkfirst=True)

    # 2. Add the column. We use a default string 'SINGLE' to backfill existing rows.
    op.add_column('scheduled_jobs', 
        sa.Column('job_type', job_type_enum, nullable=False, server_default='SINGLE')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('scheduled_jobs', 'job_type')
    sa.Enum(name='jobtype').drop(op.get_bind(), checkfirst=False)
