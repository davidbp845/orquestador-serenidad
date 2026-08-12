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
    EN_CURSO = "en_curso"
    FINALIZADA = "finalizada"
    CANCELADA = "cancelada"
    NO_SHOW = "no_show"


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
    # Borrado lógico: True tras fusionar este cliente en otro (ver
    # FusionarClientes) — nunca se borra físicamente en ese caso, para
    # no perder el rastro de qué cliente absorbió sus citas/pedidos.
    borrado: bool = False


@dataclass
class Cita:
    """id: int generado por RepositorioContadores ('cita') — igual que
    Testimonio, no se genera aquí con uuid4(), lo decide quien
    construye el caso de uso CrearReserva."""
    id: int
    servicio_id: str
    profesional_id: str
    cliente_id: str
    inicio: datetime
    fin: datetime
    estado: EstadoCita = EstadoCita.PENDIENTE
    evento_calendario_id: str | None = None

    @staticmethod
    def nueva(id: int, servicio_id: str, profesional_id: str, cliente_id: str,
              inicio: datetime, fin: datetime) -> Cita:
        return Cita(
            id=id,
            servicio_id=servicio_id,
            profesional_id=profesional_id,
            cliente_id=cliente_id,
            inicio=inicio,
            fin=fin,
        )

    @property
    def id_visible(self) -> str:
        """Formato de visualización AAAA-00000X: año de la cita (no el
        de creación, Cita no tiene ese campo) + id con ceros a la
        izquierda hasta 6 dígitos. No cambia el id real, solo cómo se
        muestra (ej. en la confirmación que ve el cliente)."""
        return f"{self.inicio.year}-{self.id:06d}"


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


@dataclass
class Testimonio:
    """Reseña/valoración del negocio, gestionada manualmente desde el
    panel interno (sin integración con ningún proveedor externo de
    reseñas). id: int generado por RepositorioContadores
    ('testimonio') — a diferencia de Cita/Pedido, no se genera aquí
    con uuid4(), lo decide quien construye el caso de uso CrearTestimonio."""
    id: int
    nombre: str
    descripcion: str
    valoracion: int
    titulo: str = ""
    creado_en: datetime = field(default_factory=lambda: datetime.now(UTC))

    @staticmethod
    def nuevo(id: int, nombre: str, descripcion: str, valoracion: int, titulo: str = "") -> Testimonio:
        return Testimonio(
            id=id, nombre=nombre, descripcion=descripcion,
            valoracion=valoracion, titulo=titulo,
        )


@dataclass
class PromoBar:
    """Aviso/oferta editable desde el panel, mostrado en la cabecera
    del frontend público (issue #78). Colección (issue #81): puede
    haber varios preparados, pero como mucho uno con activo=True a la
    vez — esa invariante la garantiza el caso de uso ActivarPromoBar,
    no esta entidad. id: int generado por RepositorioContadores
    ('promo_bar'), igual que Testimonio."""
    id: int
    nombre: str
    activo: bool = False
    contenido_html: str = ""
    actualizado_en: datetime = field(default_factory=lambda: datetime.now(UTC))

    @staticmethod
    def nuevo(id: int, nombre: str, contenido_html: str = "") -> PromoBar:
        return PromoBar(id=id, nombre=nombre, contenido_html=contenido_html)
