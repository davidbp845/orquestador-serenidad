"""testimonios_id_int

Revision ID: 7d58456d923f
Revises: ab726cec1d63
Create Date: 2026-08-11 09:44:53.138512

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '7d58456d923f'
down_revision: Union[str, Sequence[str], None] = 'ab726cec1d63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Ajustado a mano: el autogenerate proponía un `ALTER COLUMN ... TYPE
    Integer` directo sobre una columna UUID, que Postgres rechaza sin un
    `USING` explícito (no hay cast implícito uuid->integer, y un cast de
    texto tampoco serviría). Se asume la tabla vacía en el momento de
    aplicar esta migración (id: int pasa a generarse vía
    RepositorioContadores, ver #68) — dropear y recrear la tabla es más
    simple y sin ambigüedad que inventar un USING para datos que no hace
    falta preservar."""
    op.drop_table('testimonios')
    op.create_table(
        'testimonios',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('titulo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('descripcion', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('valoracion', sa.Integer(), nullable=False),
        sa.Column('creado_en', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema. Misma lógica que upgrade(): recrea la tabla en
    vez de un ALTER COLUMN, asumiendo que tampoco hace falta preservar
    datos al revertir."""
    op.drop_table('testimonios')
    op.create_table(
        'testimonios',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('titulo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('descripcion', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('valoracion', sa.Integer(), nullable=False),
        sa.Column('creado_en', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
