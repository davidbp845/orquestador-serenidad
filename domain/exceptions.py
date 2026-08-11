from datetime import datetime
from uuid import UUID

from .entities import EstadoCita, EstadoPedido


class DominioError(Exception):
    """Excepción base de dominio."""


class ServicioNoExiste(DominioError):
    def __init__(self, servicio_id: str) -> None:
        super().__init__(f"El servicio '{servicio_id}' no existe.")
        self.servicio_id = servicio_id


class ProfesionalNoDisponible(DominioError):
    def __init__(self, profesional_id: str, inicio: datetime) -> None:
        super().__init__(
            f"El profesional '{profesional_id}' no tiene hueco a las {inicio}."
        )
        self.profesional_id = profesional_id
        self.inicio = inicio


class PedidoNoExiste(DominioError):
    def __init__(self, pedido_id: UUID) -> None:
        super().__init__(f"El pedido '{pedido_id}' no existe.")
        self.pedido_id = pedido_id


class CitaNoExiste(DominioError):
    def __init__(self, cita_id: int) -> None:
        super().__init__(f"La cita '{cita_id}' no existe.")
        self.cita_id = cita_id


class ClienteNoExiste(DominioError):
    def __init__(self, cliente_id: str) -> None:
        super().__init__(f"El cliente '{cliente_id}' no existe.")
        self.cliente_id = cliente_id


class ClienteYaExiste(DominioError):
    def __init__(self, cliente_id: str) -> None:
        super().__init__(f"Ya existe un cliente con id '{cliente_id}'.")
        self.cliente_id = cliente_id


class TestimonioNoExiste(DominioError):
    def __init__(self, testimonio_id: int) -> None:
        super().__init__(f"El testimonio '{testimonio_id}' no existe.")
        self.testimonio_id = testimonio_id


class ValoracionInvalida(DominioError):
    def __init__(self, valoracion: int) -> None:
        super().__init__(
            f"La valoración debe estar entre 1 y 5 (recibido: {valoracion})."
        )
        self.valoracion = valoracion


class TransicionEstadoInvalida(DominioError):
    """Genérica para cualquier entidad con máquina de estados (Pedido,
    Cita...) — el mensaje no asume cuál, solo reporta los estados."""

    def __init__(
        self,
        estado_actual: EstadoPedido | EstadoCita,
        estado_nuevo: EstadoPedido | EstadoCita,
    ) -> None:
        super().__init__(
            f"No se puede pasar de '{estado_actual}' a '{estado_nuevo}'."
        )
        self.estado_actual = estado_actual
        self.estado_nuevo = estado_nuevo
