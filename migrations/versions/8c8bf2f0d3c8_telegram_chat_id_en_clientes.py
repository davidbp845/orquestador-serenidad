"""telegram_chat_id en clientes

Revision ID: 8c8bf2f0d3c8
Revises: 4794f8eeb103
Create Date: 2026-08-08 15:04:58.585926

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '8c8bf2f0d3c8'
down_revision: Union[str, Sequence[str], None] = '4794f8eeb103'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'clientes',
        sa.Column('telegram_chat_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('clientes', 'telegram_chat_id')
