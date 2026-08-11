"""
Casos de uso: orquestan entidades y puertos para resolver una acción
de negocio concreta. Esto es lo que el orquestador de agentes va a
invocar como "herramientas" (tools) del LLM.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from uuid import UUID

from .entities import (
    Cita,
    Cliente,
    EstadoCita,
    EstadoPedido,
    LineaPedido,
    Pedido,
    Servicio,
    SlotDisponible,
    Testimonio,
)
from .exceptions import (
    CitaNoExiste,
    ClienteNoExiste,
    ClienteYaExiste,
    PedidoNoExiste,
    ProfesionalNoDisponible,
    ServicioNoExiste,
    TestimonioNoExiste,
    TransicionEstadoInvalida,
    ValoracionInvalida,
)
from .ports import (
    NotificadorMensajes,
    RepositorioCitas,
    RepositorioClientes,
    RepositorioConocimiento,
    RepositorioPedidos,
    RepositorioProfesionales,
    RepositorioServicios,
    RepositorioTestimonios,
    SincronizadorCalendario,
)

logger = logging.getLogger(__name__)

# date.weekday(): 0=lunes ... 6=domingo. No usamos strftime('%A') porque
# depende del locale del sistema operativo y nunca coincidiría de forma
# fiable con los nombres en español usados en config/business.yaml.
_DIAS_SEMANA_ES = [
    "lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo",
]


class ComprobarDisponibilidad:
    """Devuelve huecos libres para un servicio en una fecha dada,
    opcionalmente con un profesional concreto."""

    def __init__(
        self,
        servicios: RepositorioServicios,
        profesionales: RepositorioProfesionales,
        citas: RepositorioCitas,
    ):
        self._servicios = servicios
        self._profesionales = profesionales
        self._citas = citas

    def ejecutar(
        self, servicio_id: str, dia: date, profesional_id: str | None = None
    ) -> list[SlotDisponible]:
        servicio = self._servicios.obtener(servicio_id)
        if servicio is None:
            raise ServicioNoExiste(servicio_id)

        candidatos = (
            [self._profesionales.obtener(profesional_id)]
            if profesional_id
            else self._profesionales.listar_por_servicio(servicio_id)
        )
        candidatos = [p for p in candidatos if p is not None]

        dia_semana = _DIAS_SEMANA_ES[dia.weekday()]
        slots: list[SlotDisponible] = []

        for prof in candidatos:
            horario = prof.horario_semanal.get(dia_semana)
            if not horario:
                continue
            inicio_jornada, fin_jornada = horario
            ocupadas = self._citas.citas_de_profesional_en_fecha(prof.id, dia)

            cursor = datetime.combine(dia, inicio_jornada)
            fin_jornada_dt = datetime.combine(dia, fin_jornada)
            duracion = timedelta(minutes=servicio.duracion_minutos)

            while cursor + duracion <= fin_jornada_dt:
                solapa = any(
                    cursor < c.fin and (cursor + duracion) > c.inicio
                    for c in ocupadas
                )
                if not solapa:
                    slots.append(SlotDisponible(
                        profesional_id=prof.id,
                        inicio=cursor,
                        fin=cursor + duracion,
                    ))
                cursor += timedelta(minutes=15)  # granularidad de búsqueda

        return slots


class CrearReserva:
    def __init__(
        self,
        servicios: RepositorioServicios,
        profesionales: RepositorioProfesionales,
        citas: RepositorioCitas,
        clientes: RepositorioClientes,
        disponibilidad: ComprobarDisponibilidad,
        calendario: SincronizadorCalendario | None = None,
        notificador: NotificadorMensajes | None = None,
    ):
        self._servicios = servicios
        self._profesionales = profesionales
        self._citas = citas
        self._clientes = clientes
        self._disponibilidad = disponibilidad
        self._calendario = calendario
        self._notificador = notificador

    def ejecutar(
        self,
        servicio_id: str,
        profesional_id: str,
        cliente_id: str,
        inicio: datetime,
        telegram_chat_id: str | None = None,
    ) -> Cita:
        servicio = self._servicios.obtener(servicio_id)
        if servicio is None:
            raise ServicioNoExiste(servicio_id)

        fin = inicio + timedelta(minutes=servicio.duracion_minutos)

        libres = self._disponibilidad.ejecutar(
            servicio_id, inicio.date(), profesional_id
        )
        cabe = any(s.inicio <= inicio and s.fin >= fin for s in libres)
        if not cabe:
            raise ProfesionalNoDisponible(profesional_id, inicio)

        if telegram_chat_id is not None:
            # Registra (o actualiza) el chat_id de Telegram del cliente para
            # poder mandarle notificaciones proactivas sin depender de que
            # haya una sesión de conversación activa (ver más abajo).
            cliente = self._clientes.obtener(cliente_id)
            if cliente is None:
                cliente = Cliente(id=cliente_id, nombre=cliente_id)
            cliente.telegram_chat_id = telegram_chat_id
            self._clientes.guardar(cliente)

        cita = Cita.nueva(servicio_id, profesional_id, cliente_id, inicio, fin)

        if self._calendario is not None:
            # Best-effort: un fallo al sincronizar con el calendario externo
            # no debe impedir crear la reserva en el sistema.
            try:
                profesional = self._profesionales.obtener(profesional_id)
                if profesional is not None:
                    cita.evento_calendario_id = self._calendario.crear_evento(
                        cita, servicio, profesional
                    )
            except Exception:
                logger.exception(
                    "No se pudo sincronizar la cita %s con el calendario externo",
                    cita.id,
                )

        self._citas.guardar(cita)

        if self._notificador is not None:
            self._notificar_confirmacion(cita, servicio)

        return cita

    def _notificar_confirmacion(self, cita: Cita, servicio: Servicio) -> None:
        # Best-effort, igual que la sincronización con el calendario: un
        # fallo al notificar no debe deshacer ni bloquear la reserva ya
        # creada.
        assert self._notificador is not None  # solo se llama tras comprobarlo
        cliente = self._clientes.obtener(cita.cliente_id)
        if cliente is None or not cliente.telegram_chat_id:
            return
        try:
            self._notificador.enviar(
                cliente.telegram_chat_id,
                f"Reserva confirmada: {servicio.nombre} el {cita.inicio:%d/%m/%Y} "
                f"a las {cita.inicio:%H:%M}.",
            )
        except Exception:
            logger.exception(
                "No se pudo notificar la confirmación de la cita %s", cita.id
            )


class CancelarReserva:
    def __init__(
        self,
        citas: RepositorioCitas,
        calendario: SincronizadorCalendario | None = None,
        clientes: RepositorioClientes | None = None,
        notificador: NotificadorMensajes | None = None,
    ):
        self._citas = citas
        self._calendario = calendario
        self._clientes = clientes
        self._notificador = notificador

    def ejecutar(self, cita_id: UUID) -> None:
        cita = None
        if self._calendario is not None or self._notificador is not None:
            cita = self._citas.obtener(cita_id)

        if self._calendario is not None and cita is not None and cita.evento_calendario_id:
            try:
                self._calendario.cancelar_evento(cita.evento_calendario_id)
            except Exception:
                logger.exception(
                    "No se pudo cancelar en el calendario externo el "
                    "evento de la cita %s",
                    cita_id,
                )

        if self._notificador is not None and cita is not None:
            self._notificar_cancelacion(cita)

        self._citas.cancelar(cita_id)

    def _notificar_cancelacion(self, cita: Cita) -> None:
        assert self._notificador is not None  # solo se llama tras comprobarlo
        if self._clientes is None:
            return
        cliente = self._clientes.obtener(cita.cliente_id)
        if cliente is None or not cliente.telegram_chat_id:
            return
        try:
            self._notificador.enviar(
                cliente.telegram_chat_id,
                f"Tu reserva del {cita.inicio:%d/%m/%Y} a las {cita.inicio:%H:%M} "
                f"ha sido cancelada.",
            )
        except Exception:
            logger.exception(
                "No se pudo notificar la cancelación de la cita %s", cita.id
            )


# Transiciones válidas del ciclo de vida de una cita. Confirmar, marcar
# en curso, finalizar y marcar no-show se disparan manualmente desde el
# panel interno — el LLM nunca las invoca. Cancelar sigue siendo
# CancelarReserva, sin relación con esta tabla (por eso CANCELADA no
# aparece aquí como destino: ese camino no pasa por CambiarEstadoCita).
_TRANSICIONES_CITA_VALIDAS: dict[EstadoCita, set[EstadoCita]] = {
    EstadoCita.PENDIENTE: {EstadoCita.CONFIRMADA, EstadoCita.NO_SHOW},
    EstadoCita.CONFIRMADA: {EstadoCita.EN_CURSO, EstadoCita.FINALIZADA, EstadoCita.NO_SHOW},
    EstadoCita.EN_CURSO: {EstadoCita.FINALIZADA},
    EstadoCita.FINALIZADA: set(),
    EstadoCita.CANCELADA: set(),
    EstadoCita.NO_SHOW: set(),
}


class CambiarEstadoCita:
    """Transiciona el estado de una cita (confirmar, marcar en curso,
    finalizar, marcar no-show), usado por el panel interno. Valida la
    transición antes de delegar en el repo. No toca el calendario
    externo (a diferencia de CrearReserva/CancelarReserva) — estas
    transiciones son puramente internas al sistema."""

    def __init__(
        self,
        citas: RepositorioCitas,
        clientes: RepositorioClientes | None = None,
        notificador: NotificadorMensajes | None = None,
    ):
        self._citas = citas
        self._clientes = clientes
        self._notificador = notificador

    def ejecutar(self, cita_id: UUID, nuevo_estado: EstadoCita) -> Cita:
        cita = self._citas.obtener(cita_id)
        if cita is None:
            raise CitaNoExiste(cita_id)

        if nuevo_estado not in _TRANSICIONES_CITA_VALIDAS[cita.estado]:
            raise TransicionEstadoInvalida(cita.estado, nuevo_estado)

        cita.estado = nuevo_estado
        self._citas.guardar(cita)

        if nuevo_estado == EstadoCita.CONFIRMADA and self._notificador is not None:
            self._notificar_confirmacion(cita)

        return cita

    def _notificar_confirmacion(self, cita: Cita) -> None:
        # Best-effort, igual que las notificaciones de CrearReserva/
        # CancelarReserva: un fallo aquí no debe deshacer la transición
        # ya aplicada.
        assert self._notificador is not None  # solo se llama tras comprobarlo
        if self._clientes is None:
            return
        cliente = self._clientes.obtener(cita.cliente_id)
        if cliente is None or not cliente.telegram_chat_id:
            return
        try:
            self._notificador.enviar(
                cliente.telegram_chat_id,
                f"Tu reserva del {cita.inicio:%d/%m/%Y} a las {cita.inicio:%H:%M} "
                f"ha sido confirmada.",
            )
        except Exception:
            logger.exception(
                "No se pudo notificar la confirmación de la cita %s", cita.id
            )


class RegistrarPedido:
    def __init__(self, pedidos: RepositorioPedidos, servicios: RepositorioServicios):
        self._pedidos = pedidos
        self._servicios = servicios

    def ejecutar(self, cliente_id: str, lineas: list[LineaPedido]) -> Pedido:
        for linea in lineas:
            if self._servicios.obtener(linea.servicio_id) is None:
                raise ServicioNoExiste(linea.servicio_id)
        pedido = Pedido.nuevo(cliente_id, lineas)
        self._pedidos.guardar(pedido)
        return pedido


# Transiciones válidas del ciclo de vida de un pedido. Un estado
# terminal (entregado/cancelado) no admite transición: {} en el mapa.
_TRANSICIONES_PEDIDO_VALIDAS: dict[EstadoPedido, set[EstadoPedido]] = {
    EstadoPedido.RECIBIDO: {EstadoPedido.EN_PREPARACION, EstadoPedido.CANCELADO},
    EstadoPedido.EN_PREPARACION: {EstadoPedido.LISTO, EstadoPedido.CANCELADO},
    EstadoPedido.LISTO: {EstadoPedido.ENTREGADO, EstadoPedido.CANCELADO},
    EstadoPedido.ENTREGADO: set(),
    EstadoPedido.CANCELADO: set(),
}


class CambiarEstadoPedido:
    """Transiciona el estado de un pedido (ej. 'recibido' -> 'en
    preparación'), usado por el panel interno para gestionar pedidos
    pendientes. Valida la transición antes de delegar en el repo."""

    def __init__(self, pedidos: RepositorioPedidos):
        self._pedidos = pedidos

    def ejecutar(self, pedido_id: UUID, nuevo_estado: EstadoPedido) -> Pedido:
        pedido = self._pedidos.obtener(pedido_id)
        if pedido is None:
            raise PedidoNoExiste(pedido_id)

        if nuevo_estado not in _TRANSICIONES_PEDIDO_VALIDAS[pedido.estado]:
            raise TransicionEstadoInvalida(pedido.estado, nuevo_estado)

        pedido.estado = nuevo_estado
        self._pedidos.guardar(pedido)
        return pedido


class ConsultarConocimientoNegocio:
    """Caso de uso puente hacia el RAG: dado que la respuesta depende
    de contenido documental (precios, políticas, horarios generales),
    delega en el puerto de conocimiento."""

    def __init__(self, conocimiento: RepositorioConocimiento):
        self._conocimiento = conocimiento

    def ejecutar(self, consulta: str) -> dict:
        resultados = self._conocimiento.buscar_con_fuentes(consulta)
        fragmentos = [r["texto"] for r in resultados]

        # Las fuentes solo se exponen si la nota de origen está marcada
        # como pública: el RAG puede seguir usando fragmentos de notas
        # internas para responder en texto, pero su fichero nunca sale
        # como "fuente" resaltable si no es publicar_web: true.
        fuentes = []
        vistas = set()
        for r in resultados:
            fuente = r.get("fuente")
            if fuente and r.get("publicar_web") is True and fuente not in vistas:
                vistas.add(fuente)
                fuentes.append({"fuente": fuente, "categoria": r.get("categoria")})

        return {"fragmentos": fragmentos, "fuentes": fuentes}


def _validar_valoracion(valoracion: int) -> None:
    if not 1 <= valoracion <= 5:
        raise ValoracionInvalida(valoracion)


class CrearTestimonio:
    def __init__(self, testimonios: RepositorioTestimonios):
        self._testimonios = testimonios

    def ejecutar(self, nombre: str, descripcion: str, valoracion: int, titulo: str = "") -> Testimonio:
        _validar_valoracion(valoracion)
        testimonio = Testimonio.nuevo(nombre, descripcion, valoracion, titulo)
        self._testimonios.guardar(testimonio)
        return testimonio


class EditarTestimonio:
    def __init__(self, testimonios: RepositorioTestimonios):
        self._testimonios = testimonios

    def ejecutar(
        self, testimonio_id: UUID, nombre: str, descripcion: str, valoracion: int, titulo: str = "",
    ) -> Testimonio:
        testimonio = self._testimonios.obtener(testimonio_id)
        if testimonio is None:
            raise TestimonioNoExiste(testimonio_id)
        _validar_valoracion(valoracion)

        testimonio.nombre = nombre
        testimonio.titulo = titulo
        testimonio.descripcion = descripcion
        testimonio.valoracion = valoracion
        self._testimonios.guardar(testimonio)
        return testimonio


class EliminarTestimonio:
    def __init__(self, testimonios: RepositorioTestimonios):
        self._testimonios = testimonios

    def ejecutar(self, testimonio_id: UUID) -> None:
        if self._testimonios.obtener(testimonio_id) is None:
            raise TestimonioNoExiste(testimonio_id)
        self._testimonios.eliminar(testimonio_id)


class CrearCliente:
    def __init__(self, clientes: RepositorioClientes):
        self._clientes = clientes

    def ejecutar(
        self, cliente_id: str, nombre: str,
        telefono: str | None = None, email: str | None = None, notas: str = "",
    ) -> Cliente:
        if self._clientes.obtener(cliente_id) is not None:
            raise ClienteYaExiste(cliente_id)
        cliente = Cliente(id=cliente_id, nombre=nombre, telefono=telefono, email=email, notas=notas)
        self._clientes.guardar(cliente)
        return cliente


class EditarCliente:
    """El id no se toca: es la clave del cliente, inmutable una vez
    asignada. telegram_chat_id tampoco: se rellena solo vía el flujo de
    reservas por Telegram (#38), no es un campo de este formulario."""

    def __init__(self, clientes: RepositorioClientes):
        self._clientes = clientes

    def ejecutar(
        self, cliente_id: str, nombre: str,
        telefono: str | None, email: str | None, notas: str,
    ) -> Cliente:
        cliente = self._clientes.obtener(cliente_id)
        if cliente is None:
            raise ClienteNoExiste(cliente_id)

        cliente.nombre = nombre
        cliente.telefono = telefono
        cliente.email = email
        cliente.notas = notas
        self._clientes.guardar(cliente)
        return cliente


class EliminarCliente:
    def __init__(self, clientes: RepositorioClientes):
        self._clientes = clientes

    def ejecutar(self, cliente_id: str) -> None:
        if self._clientes.obtener(cliente_id) is None:
            raise ClienteNoExiste(cliente_id)
        self._clientes.eliminar(cliente_id)
