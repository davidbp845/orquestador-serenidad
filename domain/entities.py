"""
Entidades del dominio. Puro Python, sin dependencias de frameworks,
LLMs, bases de datos ni canales de mensajería. Esto es lo único que
cambia de verdad entre negocios (masajes, restaurante, peluquería...).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from enum import StrEnum
from uuid import UUID, uuid4


class EstadoCita(StrEnum):
    PENDIENTE = "pendiente"
    CONFIRMADA = "confirmada"
    CANCELADA = "cancelada"
    COMPLETADA = "completada"


@dataclass
class Servicio:
    """Ej: 'Masaje relajante 60 min'. Genérico: podría ser 'Mesa 4 personas'."""
    id: str
    nombre: str
    duracion_minutos: int
    precio: float
    descripcion: str = ""


@dataclass
class Profesional:
    """Ej: terapeuta. Genérico: camarero, estilista, técnico..."""
    id: str
    nombre: str
    servicios_ids: list[str] = field(default_factory=list)
    horario_semanal: dict[str, tuple[time, time]] = field(default_factory=dict)
    # horario_semanal: {"lunes": (time(9,0), time(18,0)), ...}


@dataclass
class Cliente:
    id: str
    nombre: str
    telefono: str | None = None
    email: str | None = None
    notas: str = ""
    # Chat id de Telegram del cliente, si ha reservado alguna vez por ese
    # canal — lo que permite mandarle una notificación proactiva (ver
    # NotificadorMensajes) sin depender de una sesión de conversación activa.
    telegram_chat_id: str | None = None


@dataclass
class Cita:
    id: UUID
    servicio_id: str
    profesional_id: str
    cliente_id: str
    inicio: datetime
    fin: datetime
    estado: EstadoCita = EstadoCita.PENDIENTE
    evento_calendario_id: str | None = None

    @staticmethod
    def nueva(servicio_id: str, profesional_id: str, cliente_id: str,
              inicio: datetime, fin: datetime) -> Cita:
        return Cita(
            id=uuid4(),
            servicio_id=servicio_id,
            profesional_id=profesional_id,
            cliente_id=cliente_id,
            inicio=inicio,
            fin=fin,
        )


@dataclass
class SlotDisponible:
    """Hueco libre que se puede ofrecer al cliente."""
    profesional_id: str
    inicio: datetime
    fin: datetime


class EstadoPedido(StrEnum):
    RECIBIDO = "recibido"
    EN_PREPARACION = "en_preparacion"
    LISTO = "listo"
    ENTREGADO = "entregado"
    CANCELADO = "cancelado"


@dataclass
class LineaPedido:
    servicio_id: str
    cantidad: int
    notas: str = ""


@dataclass
class Pedido:
    """Genérico: pedido de productos/servicios adicionales (ej. venta de
    productos de cosmética en el centro de masajes, o comida en un restaurante)."""
    id: UUID
    cliente_id: str
    lineas: list[LineaPedido]
    estado: EstadoPedido = EstadoPedido.RECIBIDO
    creado_en: datetime = field(default_factory=lambda: datetime.now(UTC))

    @staticmethod
    def nuevo(cliente_id: str, lineas: list[LineaPedido]) -> Pedido:
        return Pedido(id=uuid4(), cliente_id=cliente_id, lineas=lineas)
