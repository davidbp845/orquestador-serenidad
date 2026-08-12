"""notas_cliente

Revision ID: e1a2b3c4d5f6
Revises: ad0033e8e3fe
Create Date: 2026-08-12 21:00:00.000000

"""
from datetime import UTC, datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'e1a2b3c4d5f6'
down_revision: Union[str, Sequence[str], None] = 'ad0033e8e3fe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    A mano, no autogenerate puro: además de crear la tabla, hay que
    migrar los datos existentes de clientes.notas (texto libre) a la
    tabla nueva antes de dropear esa columna (#77) — el autogenerate no
    sabe generar esa parte, solo el cambio de esquema."""
    op.create_table(
        'notas_cliente',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cliente_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('texto', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('creado_en', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_notas_cliente_cliente_id'), 'notas_cliente', ['cliente_id'])

    conexion = op.get_bind()
    filas = conexion.execute(
        sa.text("SELECT id, notas FROM clientes WHERE notas IS NOT NULL AND notas != ''")
    ).fetchall()

    ahora = datetime.now(UTC)
    siguiente_id = 1
    for cliente_id, notas in filas:
        conexion.execute(
            sa.text(
                "INSERT INTO notas_cliente (id, cliente_id, texto, creado_en) "
                "VALUES (:id, :cliente_id, :texto, :creado_en)"
            ),
            {"id": siguiente_id, "cliente_id": cliente_id, "texto": f"[Importada] {notas}", "creado_en": ahora},
        )
        siguiente_id += 1

    if siguiente_id > 1:
        # Deja el contador 'nota_cliente' en sync con los ids ya usados
        # por la importación, para que RepositorioContadores.siguiente_valor
        # continúe justo después en vez de colisionar con ellos — mismo
        # motivo que ya resuelve cf201bd8f855 para cliente/testimonio/cita.
        conexion.execute(
            sa.text(
                "INSERT INTO contadores (tipo_entidad, valor) VALUES ('nota_cliente', :valor) "
                "ON CONFLICT (tipo_entidad) DO UPDATE SET valor = :valor"
            ),
            {"valor": siguiente_id - 1},
        )

    op.drop_column('clientes', 'notas')


def downgrade() -> None:
    """Downgrade schema. Los textos migrados a notas_cliente no vuelven
    a fundirse en clientes.notas (irían con el prefijo [Importada] y se
    perdería el resto del historial de notas posteriores) — se limitan
    a quedar huérfanos en la tabla que se dropea aquí, igual que ya
    asume 7d58456d923f para datos que no hace falta preservar al
    revertir."""
    op.add_column(
        'clientes',
        sa.Column('notas', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''),
    )
    op.drop_index(op.f('ix_notas_cliente_cliente_id'), table_name='notas_cliente')
    op.drop_table('notas_cliente')
