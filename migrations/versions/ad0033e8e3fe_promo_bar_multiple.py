"""promo_bar_multiple

Revision ID: ad0033e8e3fe
Revises: aa41676e205f
Create Date: 2026-08-12 17:18:58.622484

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'ad0033e8e3fe'
down_revision: Union[str, Sequence[str], None] = 'aa41676e205f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Añadida nullable primero: la tabla ya puede tener la fila única
    # del modelo anterior (issue #78, antes de #81) y una columna NOT
    # NULL sin default fallaría al añadirla sobre una fila existente.
    # Se rellena con un nombre genérico y luego se cierra a NOT NULL.
    op.add_column('promo_bar', sa.Column('nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.execute("UPDATE promo_bar SET nombre = 'Promobar' WHERE nombre IS NULL")
    op.alter_column('promo_bar', 'nombre', nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('promo_bar', 'nombre')
