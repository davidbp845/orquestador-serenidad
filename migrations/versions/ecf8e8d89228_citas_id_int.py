"""citas_id_int

Revision ID: ecf8e8d89228
Revises: 7d58456d923f
Create Date: 2026-08-11 10:37:31.776534

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'ecf8e8d89228'
down_revision: Union[str, Sequence[str], None] = '7d58456d923f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Ajustado a mano, mismo motivo que 7d58456d923f_testimonios_id_int:
    el autogenerate proponía un `ALTER COLUMN ... TYPE Integer` directo
    sobre una columna UUID, que Postgres rechaza sin un `USING`
    explícito. Se asume la tabla vacía en el momento de aplicar esta
    migración (id: int pasa a generarse vía RepositorioContadores, ver
    #69) — dropear y recrear la tabla evita inventar un USING para
    datos que no hace falta preservar."""
    op.drop_table('citas')
    op.create_table(
        'citas',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('servicio_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('profesional_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('cliente_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('inicio', sa.DateTime(), nullable=False),
        sa.Column('fin', sa.DateTime(), nullable=False),
        sa.Column('estado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('evento_calendario_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_citas_profesional_id'), 'citas', ['profesional_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema. Misma lógica que upgrade(): recrea la tabla en
    vez de un ALTER COLUMN, asumiendo que tampoco hace falta preservar
    datos al revertir."""
    op.drop_table('citas')
    op.create_table(
        'citas',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('servicio_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('profesional_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('cliente_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('inicio', sa.DateTime(), nullable=False),
        sa.Column('fin', sa.DateTime(), nullable=False),
        sa.Column('estado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('evento_calendario_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_citas_profesional_id'), 'citas', ['profesional_id'], unique=False)
