"""Modelos de tabla SQLModel. Deliberadamente separados de
domain/entities.py: el dominio no debe saber nada de columnas ni de
SQL. Los repositorios de adapters/out/repositorios_postgres.py son los
únicos que traducen entre estas filas y las entidades de dominio."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


class ClienteDB(SQLModel, table=True):
    __tablename__ = "clientes"

    id: str = Field(primary_key=True)
    nombre: str
    telefono: str | None = Field(default=None, index=True)
    email: str | None = None
    notas: str = ""
    telegram_chat_id: str | None = None
    borrado: bool = False


class CitaDB(SQLModel, table=True):
    __tablename__ = "citas"

    id: int = Field(primary_key=True)
    servicio_id: str
    profesional_id: str = Field(index=True)
    cliente_id: str
    inicio: datetime
    fin: datetime
    estado: str
    evento_calendario_id: str | None = None


class PedidoDB(SQLModel, table=True):
    __tablename__ = "pedidos"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    cliente_id: str
    estado: str
    creado_en: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TestimonioDB(SQLModel, table=True):
    __tablename__ = "testimonios"

    id: int = Field(primary_key=True)
    nombre: str
    titulo: str
    descripcion: str
    valoracion: int
    creado_en: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ContadorDB(SQLModel, table=True):
    __tablename__ = "contadores"

    tipo_entidad: str = Field(primary_key=True)
    valor: int = 0


class PromoBarDB(SQLModel, table=True):
    """Colección (issue #81): puede haber varios, como mucho uno con
    activo=True — ver RepositorioPromoBarPostgres.activar()."""
    __tablename__ = "promo_bar"

    id: int = Field(primary_key=True)
    nombre: str
    activo: bool = False
    contenido_html: str = ""
    actualizado_en: datetime = Field(default_factory=lambda: datetime.now(UTC))


class LineaPedidoDB(SQLModel, table=True):
    __tablename__ = "pedido_lineas"

    id: int | None = Field(default=None, primary_key=True)
    pedido_id: UUID = Field(foreign_key="pedidos.id", index=True)
    servicio_id: str
    cantidad: int
    notas: str = ""
