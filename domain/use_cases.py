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
    NotaCliente,
    Pedido,
    PromoBar,
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
    PromoBarNoExiste,
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
    RepositorioContadores,
    RepositorioNotasCliente,
    RepositorioPedidos,
    RepositorioProfesionales,
    RepositorioPromoBar,
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
        contadores: RepositorioContadores,
        calendario: SincronizadorCalendario | None = None,
        notificador: NotificadorMensajes | None = None,
    ):
        self._servicios = servicios
        self._profesionales = profesionales
        self._citas = citas
        self._clientes = clientes
        self._disponibilidad = disponibilidad
        self._contadores = contadores
        self._calendario = calendario
        self._notificador = notificador

    def ejecutar(
        self,
        servicio_id: str,
        profesional_id: str,
        nombre: str,
        telefono: str,
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

        # Antes, el Cliente solo se creaba/actualizaba si telegram_chat_id
        # no era None, así que una reserva por web chat o WhatsApp nunca
        # creaba ningún Cliente — la Cita quedaba con un cliente_id sin
        # fila real detrás (#52, caso B: cliente huérfano). Ahora corre en
        # todos los canales, y el teléfono (obligatorio desde #52, ver
        # application/tools.py) es la clave real para reconocer a un
        # cliente que repite — ya no el string que antes decidía el LLM
        # libremente (cliente_id), que #69 dejó a propósito sin conectar
        # al contador por esto mismo.
        cliente = self._clientes.buscar_por_telefono(telefono)
        if cliente is None:
            nuevo_id_cliente = str(self._contadores.siguiente_valor("cliente"))
            cliente = Cliente(id=nuevo_id_cliente, nombre=nombre, telefono=telefono)
        else:
            cliente.nombre = nombre
        if telegram_chat_id is not None:
            # Registra (o actualiza) el chat_id de Telegram del cliente para
            # poder mandarle notificaciones proactivas sin depender de que
            # haya una sesión de conversación activa (ver más abajo).
            cliente.telegram_chat_id = telegram_chat_id
        self._clientes.guardar(cliente)

        nuevo_id_cita = self._contadores.siguiente_valor("cita")
        cita = Cita.nueva(nuevo_id_cita, servicio_id, profesional_id, cliente.id, inicio, fin)

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
                f"Reserva confirmada ({cita.id_visible}): {servicio.nombre} el "
                f"{cita.inicio:%d/%m/%Y} a las {cita.inicio:%H:%M}.",
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

    def ejecutar(self, cita_id: int) -> None:
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
                f"Tu reserva ({cita.id_visible}) del {cita.inicio:%d/%m/%Y} a las "
                f"{cita.inicio:%H:%M} ha sido cancelada.",
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

    def ejecutar(self, cita_id: int, nuevo_estado: EstadoCita) -> Cita:
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
                f"Tu reserva ({cita.id_visible}) del {cita.inicio:%d/%m/%Y} a las "
                f"{cita.inicio:%H:%M} ha sido confirmada.",
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
    def __init__(self, testimonios: RepositorioTestimonios, contadores: RepositorioContadores):
        self._testimonios = testimonios
        self._contadores = contadores

    def ejecutar(self, nombre: str, descripcion: str, valoracion: int, titulo: str = "") -> Testimonio:
        _validar_valoracion(valoracion)
        nuevo_id = self._contadores.siguiente_valor("testimonio")
        testimonio = Testimonio.nuevo(nuevo_id, nombre, descripcion, valoracion, titulo)
        self._testimonios.guardar(testimonio)
        return testimonio


class EditarTestimonio:
    def __init__(self, testimonios: RepositorioTestimonios):
        self._testimonios = testimonios

    def ejecutar(
        self, testimonio_id: int, nombre: str, descripcion: str, valoracion: int, titulo: str = "",
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

    def ejecutar(self, testimonio_id: int) -> None:
        if self._testimonios.obtener(testimonio_id) is None:
            raise TestimonioNoExiste(testimonio_id)
        self._testimonios.eliminar(testimonio_id)


class ListarTestimoniosRecientes:
    """Lectura pública (issue #61): los testimonios más recientes para
    el carrusel del frontend, sin exponer el CRUD completo del panel."""
    def __init__(self, testimonios: RepositorioTestimonios):
        self._testimonios = testimonios

    def ejecutar(self, limite: int = 5) -> list[Testimonio]:
        return sorted(self._testimonios.listar(), key=lambda t: t.creado_en, reverse=True)[:limite]


class ObtenerPromoBar:
    """Lectura pública: el promobar activo (o None si ninguno lo
    está) para el endpoint del frontend (issue #78)."""
    def __init__(self, promo_bar: RepositorioPromoBar):
        self._promo_bar = promo_bar

    def ejecutar(self) -> PromoBar | None:
        return self._promo_bar.obtener_activo()


class CrearPromoBar:
    """Escritura desde el panel (issue #81) — no hay tool de LLM ni
    otro camino de escritura. Nace inactivo: crear uno nuevo no debe
    desactivar en silencio el que ya estuviera activo, eso requiere
    el paso explícito de ActivarPromoBar."""
    def __init__(self, promo_bar: RepositorioPromoBar, contadores: RepositorioContadores):
        self._promo_bar = promo_bar
        self._contadores = contadores

    def ejecutar(self, nombre: str, contenido_html: str = "") -> PromoBar:
        nuevo_id = self._contadores.siguiente_valor("promo_bar")
        promo_bar = PromoBar.nuevo(nuevo_id, nombre, contenido_html)
        self._promo_bar.guardar(promo_bar)
        return promo_bar


class EditarPromoBar:
    def __init__(self, promo_bar: RepositorioPromoBar):
        self._promo_bar = promo_bar

    def ejecutar(self, promo_bar_id: int, nombre: str, contenido_html: str) -> PromoBar:
        promo_bar = self._promo_bar.obtener(promo_bar_id)
        if promo_bar is None:
            raise PromoBarNoExiste(promo_bar_id)
        promo_bar.nombre = nombre
        promo_bar.contenido_html = contenido_html
        self._promo_bar.guardar(promo_bar)
        return promo_bar


class EliminarPromoBar:
    def __init__(self, promo_bar: RepositorioPromoBar):
        self._promo_bar = promo_bar

    def ejecutar(self, promo_bar_id: int) -> None:
        if self._promo_bar.obtener(promo_bar_id) is None:
            raise PromoBarNoExiste(promo_bar_id)
        self._promo_bar.eliminar(promo_bar_id)


class ListarPromoBars:
    def __init__(self, promo_bar: RepositorioPromoBar):
        self._promo_bar = promo_bar

    def ejecutar(self) -> list[PromoBar]:
        return self._promo_bar.listar()


class ActivarPromoBar:
    """Activa un promobar y desactiva cualquier otro que lo estuviera
    — la invariante "como mucho uno activo a la vez" vive aquí, no en
    el panel ni delegada sin más al repositorio."""
    def __init__(self, promo_bar: RepositorioPromoBar):
        self._promo_bar = promo_bar

    def ejecutar(self, promo_bar_id: int) -> None:
        if self._promo_bar.obtener(promo_bar_id) is None:
            raise PromoBarNoExiste(promo_bar_id)
        self._promo_bar.activar(promo_bar_id)


class CrearCliente:
    """El id no lo decide el llamador: se genera con el contador
    ('cliente'), igual que CrearTestimonio con 'testimonio'. La
    comprobación de colisión se mantiene como salvaguarda para
    clientes ya existentes con id manual (de antes de este cambio, o
    creados vía CrearReserva con el id que decide el LLM) que pudieran
    coincidir con un valor futuro del contador."""

    def __init__(self, clientes: RepositorioClientes, contadores: RepositorioContadores):
        self._clientes = clientes
        self._contadores = contadores

    def ejecutar(
        self, nombre: str,
        telefono: str | None = None, email: str | None = None,
    ) -> Cliente:
        nuevo_id = str(self._contadores.siguiente_valor("cliente"))
        if self._clientes.obtener(nuevo_id) is not None:
            raise ClienteYaExiste(nuevo_id)
        cliente = Cliente(id=nuevo_id, nombre=nombre, telefono=telefono, email=email)
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
        telefono: str | None, email: str | None,
    ) -> Cliente:
        cliente = self._clientes.obtener(cliente_id)
        if cliente is None:
            raise ClienteNoExiste(cliente_id)

        cliente.nombre = nombre
        cliente.telefono = telefono
        cliente.email = email
        self._clientes.guardar(cliente)
        return cliente


class EliminarCliente:
    def __init__(self, clientes: RepositorioClientes):
        self._clientes = clientes

    def ejecutar(self, cliente_id: str) -> None:
        if self._clientes.obtener(cliente_id) is None:
            raise ClienteNoExiste(cliente_id)
        self._clientes.eliminar(cliente_id)


class DetectarClientesDuplicados:
    """Agrupa clientes con el mismo nombre y teléfono (coincidencia
    exacta, no fuzzy matching) — el criterio de duplicidad tal como se
    definió: 'dos clientes con el mismo nombre y teléfono son una
    duplicidad'. Clientes sin teléfono no entran en la comparación
    (un teléfono ausente no es una señal de identidad fiable — dos
    clientes distintos con el mismo nombre pero sin teléfono ninguno
    no deberían fusionarse a ciegas)."""

    def __init__(self, clientes: RepositorioClientes):
        self._clientes = clientes

    def ejecutar(self) -> list[list[Cliente]]:
        grupos: dict[tuple[str, str], list[Cliente]] = {}
        for cliente in self._clientes.listar():
            if not cliente.telefono:
                continue
            clave = (cliente.nombre.strip().lower(), cliente.telefono.strip())
            grupos.setdefault(clave, []).append(cliente)
        return [grupo for grupo in grupos.values() if len(grupo) >= 2]


def _clave_orden_fusion(cliente_id: str) -> tuple[int, str]:
    """El superviviente de una fusión es el id 'más bajo' del grupo,
    asumiendo ids generados por el contador (tras #69/#67): un id
    numérico bajo significa creado antes, sin necesitar ningún campo
    creado_en en Cliente. Ids no numéricos (manuales, de antes de esa
    migración) ordenan después de cualquier id numérico, y entre sí
    alfabéticamente — mejor esfuerzo, ese caso no tiene garantía real
    de orden de creación."""
    if cliente_id.isdigit():
        return (0, cliente_id.zfill(20))
    return (1, cliente_id)


class FusionarClientes:
    """Fusiona un grupo de Cliente duplicados en uno solo: reasigna
    todas sus citas, pedidos y notas (#77) al superviviente, y marca
    los demás como borrado=True (borrado lógico, nunca eliminar()
    físico — ver RepositorioClientes.marcar_borrado)."""

    def __init__(
        self, clientes: RepositorioClientes, citas: RepositorioCitas, pedidos: RepositorioPedidos,
        notas: RepositorioNotasCliente | None = None,
    ):
        self._clientes = clientes
        self._citas = citas
        self._pedidos = pedidos
        self._notas = notas

    def ejecutar(self, ids: list[str]) -> Cliente:
        clientes = []
        for cliente_id in ids:
            cliente = self._clientes.obtener(cliente_id)
            if cliente is None:
                raise ClienteNoExiste(cliente_id)
            clientes.append(cliente)

        superviviente = min(clientes, key=lambda c: _clave_orden_fusion(c.id))

        for cliente in clientes:
            if cliente.id == superviviente.id:
                continue
            self._citas.reasignar_cliente(cliente.id, superviviente.id)
            self._pedidos.reasignar_cliente(cliente.id, superviviente.id)
            if self._notas is not None:
                self._notas.reasignar_cliente(cliente.id, superviviente.id)
            self._clientes.marcar_borrado(cliente.id)

        return superviviente


class AñadirNotaCliente:
    """Pensado para ser llamado tanto desde el panel (formulario manual)
    como desde la tool del LLM guardar_nota_cliente (#77) — misma
    lógica, dos orígenes, sin duplicar la validación de que el cliente
    exista en ninguno de los dos sitios."""

    def __init__(
        self, notas: RepositorioNotasCliente, clientes: RepositorioClientes,
        contadores: RepositorioContadores,
    ):
        self._notas = notas
        self._clientes = clientes
        self._contadores = contadores

    def ejecutar(self, cliente_id: str, texto: str) -> NotaCliente:
        if self._clientes.obtener(cliente_id) is None:
            raise ClienteNoExiste(cliente_id)
        return self._crear_nota(cliente_id, texto)

    def ejecutar_identificando(self, nombre: str, telefono: str, texto: str) -> NotaCliente:
        """Variante para cuando todavía no se conoce el cliente_id (tool
        guardar_nota_cliente del LLM antes de la primera reserva de la
        conversación) — identifica al cliente por teléfono igual que
        CrearReserva (busca por teléfono, crea si no existe, actualiza el
        nombre si ya existía), en vez de exigir un cliente_id que la
        conversación aún no tiene. Evita el mecanismo de notas diferidas
        que existía antes (`notas_pendientes` en `SesionConversacion`),
        que perdía la nota en silencio si la conversación terminaba sin
        llegar a reservar."""
        cliente = self._clientes.buscar_por_telefono(telefono)
        if cliente is None:
            nuevo_id_cliente = str(self._contadores.siguiente_valor("cliente"))
            cliente = Cliente(id=nuevo_id_cliente, nombre=nombre, telefono=telefono)
        else:
            cliente.nombre = nombre
        self._clientes.guardar(cliente)
        return self._crear_nota(cliente.id, texto)

    def _crear_nota(self, cliente_id: str, texto: str) -> NotaCliente:
        nuevo_id = self._contadores.siguiente_valor("nota_cliente")
        nota = NotaCliente.nueva(nuevo_id, cliente_id, texto)
        self._notas.crear(nota)
        return nota


class ListarNotasCliente:
    """Lectura pura para el panel — más reciente primero, igual que
    ListarTestimoniosRecientes."""

    def __init__(self, notas: RepositorioNotasCliente):
        self._notas = notas

    def ejecutar(self, cliente_id: str) -> list[NotaCliente]:
        return sorted(self._notas.listar_de_cliente(cliente_id), key=lambda n: n.creado_en, reverse=True)
