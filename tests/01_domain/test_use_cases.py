"""Tests de casos de uso de dominio usando fakes en memoria que
implementan los puertos de domain/ports.py — sin mocks pesados, tal
y como sugiere el README."""
from datetime import UTC, date, datetime, time

import pytest

from domain.entities import (
    Cita,
    Cliente,
    EstadoCita,
    EstadoPedido,
    LineaPedido,
    Pedido,
    Profesional,
    PromoBar,
    Servicio,
    Testimonio,
)
from domain.exceptions import (
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
from domain.use_cases import (
    _DIAS_SEMANA_ES,
    ActualizarPromoBar,
    CambiarEstadoCita,
    CambiarEstadoPedido,
    CancelarReserva,
    ComprobarDisponibilidad,
    ConsultarConocimientoNegocio,
    CrearCliente,
    CrearReserva,
    CrearTestimonio,
    DetectarClientesDuplicados,
    EditarCliente,
    EditarTestimonio,
    EliminarCliente,
    EliminarTestimonio,
    FusionarClientes,
    ListarTestimoniosRecientes,
    ObtenerPromoBar,
    RegistrarPedido,
)

# pytest recolecta por defecto cualquier clase de nivel superior cuyo
# nombre empiece por "Test" — Testimonio (entidad) y TestimonioNoExiste
# (excepción) caen en ese patrón por casualidad de nombre, no porque
# sean clases de test. __test__ = False es la forma estándar de decirle
# a pytest que las ignore sin tocar domain/ (que no debe saber nada de
# pytest) ni ampliar python_classes en pytest.ini (afectaría a todo el
# resto de la suite).
Testimonio.__test__ = False
TestimonioNoExiste.__test__ = False


class FakeSincronizadorCalendario:
    def __init__(self, id_evento="evento-externo-1", lanza_en_crear=False, lanza_en_cancelar=False):
        self._id_evento = id_evento
        self._lanza_en_crear = lanza_en_crear
        self._lanza_en_cancelar = lanza_en_cancelar
        self.eventos_creados = []
        self.eventos_cancelados = []

    def crear_evento(self, cita, servicio, profesional):
        if self._lanza_en_crear:
            raise RuntimeError("fallo simulado de Google Calendar")
        self.eventos_creados.append((cita, servicio, profesional))
        return self._id_evento

    def cancelar_evento(self, evento_id):
        if self._lanza_en_cancelar:
            raise RuntimeError("fallo simulado de Google Calendar")
        self.eventos_cancelados.append(evento_id)


class FakeNotificadorMensajes:
    def __init__(self, lanza=False):
        self._lanza = lanza
        self.enviados = []

    def enviar(self, destinatario_id, texto):
        if self._lanza:
            raise RuntimeError("fallo simulado del notificador")
        self.enviados.append((destinatario_id, texto))


class FakeRepoServicios:
    def __init__(self, servicios=None):
        self._data = {s.id: s for s in (servicios or [])}

    def obtener(self, servicio_id):
        return self._data.get(servicio_id)

    def listar(self):
        return list(self._data.values())


class FakeRepoProfesionales:
    def __init__(self, profesionales=None):
        self._data = {p.id: p for p in (profesionales or [])}

    def obtener(self, profesional_id):
        return self._data.get(profesional_id)

    def listar_por_servicio(self, servicio_id):
        return [p for p in self._data.values() if servicio_id in p.servicios_ids]


class FakeRepoCitas:
    def __init__(self, citas=None):
        self._data = {c.id: c for c in (citas or [])}
        self.canceladas = []

    def guardar(self, cita):
        self._data[cita.id] = cita

    def obtener(self, cita_id):
        return self._data.get(cita_id)

    def citas_de_profesional_en_fecha(self, profesional_id, dia):
        return [
            c for c in self._data.values()
            if c.profesional_id == profesional_id and c.inicio.date() == dia
        ]

    def cancelar(self, cita_id):
        self.canceladas.append(cita_id)

    def reasignar_cliente(self, id_antiguo, id_nuevo):
        n = 0
        for cita in self._data.values():
            if cita.cliente_id == id_antiguo:
                cita.cliente_id = id_nuevo
                n += 1
        return n


class FakeRepoClientes:
    def __init__(self, clientes=None):
        self._data = {c.id: c for c in (clientes or [])}

    def obtener(self, cliente_id):
        return self._data.get(cliente_id)

    def guardar(self, cliente):
        self._data[cliente.id] = cliente

    def buscar_por_telefono(self, telefono):
        return next(
            (c for c in self._data.values() if c.telefono == telefono and not c.borrado), None
        )

    def listar(self):
        return [c for c in self._data.values() if not c.borrado]

    def eliminar(self, cliente_id):
        self._data.pop(cliente_id, None)

    def marcar_borrado(self, cliente_id):
        if cliente_id in self._data:
            self._data[cliente_id].borrado = True


class FakeRepoPedidos:
    def __init__(self, pedidos=None):
        self._data = {p.id: p for p in (pedidos or [])}

    def guardar(self, pedido):
        self._data[pedido.id] = pedido

    def obtener(self, pedido_id):
        return self._data.get(pedido_id)

    def listar_pendientes(self):
        return [
            p for p in self._data.values()
            if p.estado not in (EstadoPedido.ENTREGADO, EstadoPedido.CANCELADO)
        ]

    def reasignar_cliente(self, id_antiguo, id_nuevo):
        n = 0
        for pedido in self._data.values():
            if pedido.cliente_id == id_antiguo:
                pedido.cliente_id = id_nuevo
                n += 1
        return n


class FakeRepoTestimonios:
    def __init__(self, testimonios=None):
        self._data = {t.id: t for t in (testimonios or [])}

    def obtener(self, testimonio_id):
        return self._data.get(testimonio_id)

    def guardar(self, testimonio):
        self._data[testimonio.id] = testimonio

    def listar(self):
        return list(self._data.values())

    def eliminar(self, testimonio_id):
        self._data.pop(testimonio_id, None)

    def borrar_todo(self):
        n = len(self._data)
        self._data.clear()
        return n


class FakeRepoPromoBar:
    def __init__(self, promo_bar=None):
        self._promo_bar = promo_bar or PromoBar()

    def obtener(self):
        return self._promo_bar

    def guardar(self, promo_bar):
        self._promo_bar = promo_bar


class FakeRepoContadores:
    def __init__(self):
        self._data = {}

    def siguiente_valor(self, tipo_entidad):
        nuevo_valor = self._data.get(tipo_entidad, 0) + 1
        self._data[tipo_entidad] = nuevo_valor
        return nuevo_valor

    def listar(self):
        return dict(self._data)

    def borrar_todo(self):
        n = len(self._data)
        self._data.clear()
        return n


class FakeRepoConocimiento:
    def __init__(self, resultados=None):
        self._resultados = resultados or []
        self.ultima_consulta = None

    def buscar(self, consulta, top_k=5):
        self.ultima_consulta = consulta
        return [r["texto"] for r in self._resultados]

    def buscar_con_fuentes(self, consulta, top_k=5):
        self.ultima_consulta = consulta
        return self._resultados


# Lunes cualquiera, para tener el nombre de día controlado.
_LUNES = date(2026, 8, 3)
assert _DIAS_SEMANA_ES[_LUNES.weekday()] == "lunes"


def _servicio(duracion=60):
    return Servicio(id="masaje", nombre="Masaje", duracion_minutos=duracion, precio=50.0)


def _profesional(horario=None):
    return Profesional(
        id="ana",
        nombre="Ana",
        servicios_ids=["masaje"],
        horario_semanal=horario or {"lunes": (time(9, 0), time(10, 0))},
    )


class TestComprobarDisponibilidad:
    def test_lanza_si_servicio_no_existe(self):
        caso = ComprobarDisponibilidad(
            FakeRepoServicios(), FakeRepoProfesionales(), FakeRepoCitas()
        )
        with pytest.raises(ServicioNoExiste):
            caso.ejecutar("no_existe", _LUNES)

    def test_genera_slots_segun_duracion_y_horario(self):
        caso = ComprobarDisponibilidad(
            FakeRepoServicios([_servicio(duracion=30)]),
            FakeRepoProfesionales([_profesional()]),
            FakeRepoCitas(),
        )
        slots = caso.ejecutar("masaje", _LUNES)

        inicios = [s.inicio.time() for s in slots]
        assert inicios == [time(9, 0), time(9, 15), time(9, 30)]
        assert all(s.profesional_id == "ana" for s in slots)

    def test_sin_horario_ese_dia_no_hay_slots(self):
        sin_horario = Profesional(id="ana", nombre="Ana", servicios_ids=["masaje"])
        caso = ComprobarDisponibilidad(
            FakeRepoServicios([_servicio(duracion=30)]),
            FakeRepoProfesionales([sin_horario]),
            FakeRepoCitas(),
        )
        assert caso.ejecutar("masaje", _LUNES) == []

    def test_respeta_citas_existentes(self):
        cita_existente = Cita.nueva(
            1, "masaje", "ana", "cliente1",
            datetime.combine(_LUNES, time(9, 30)),
            datetime.combine(_LUNES, time(10, 0)),
        )
        caso = ComprobarDisponibilidad(
            FakeRepoServicios([_servicio(duracion=30)]),
            FakeRepoProfesionales([_profesional()]),
            FakeRepoCitas([cita_existente]),
        )
        slots = caso.ejecutar("masaje", _LUNES)
        assert [s.inicio.time() for s in slots] == [time(9, 0)]

    def test_filtra_por_profesional_id_si_se_indica(self):
        otro = Profesional(
            id="beatriz", nombre="Beatriz", servicios_ids=["masaje"],
            horario_semanal={"lunes": (time(9, 0), time(10, 0))},
        )
        caso = ComprobarDisponibilidad(
            FakeRepoServicios([_servicio(duracion=30)]),
            FakeRepoProfesionales([_profesional(), otro]),
            FakeRepoCitas(),
        )
        slots = caso.ejecutar("masaje", _LUNES, profesional_id="beatriz")
        assert all(s.profesional_id == "beatriz" for s in slots)
        assert len(slots) == 3


class TestCrearReserva:
    def _construir(self, citas=None, calendario=None):
        repo_servicios = FakeRepoServicios([_servicio(duracion=30)])
        repo_profesionales = FakeRepoProfesionales([_profesional()])
        repo_citas = FakeRepoCitas(citas)
        repo_clientes = FakeRepoClientes()
        disponibilidad = ComprobarDisponibilidad(
            repo_servicios, repo_profesionales, repo_citas
        )
        caso = CrearReserva(
            repo_servicios, repo_profesionales, repo_citas, repo_clientes,
            disponibilidad, FakeRepoContadores(), calendario,
        )
        return caso, repo_citas

    def test_lanza_si_servicio_no_existe(self):
        caso, _ = self._construir()
        with pytest.raises(ServicioNoExiste):
            caso.ejecutar("no_existe", "ana", "Juan", "600111222", datetime.combine(_LUNES, time(9, 0)))

    def test_crea_reserva_en_hueco_libre(self):
        caso, repo_citas = self._construir()
        inicio = datetime.combine(_LUNES, time(9, 0))

        cita = caso.ejecutar("masaje", "ana", "Juan", "600111222", inicio)

        assert cita.inicio == inicio
        assert cita.fin == datetime.combine(_LUNES, time(9, 30))
        assert repo_citas._data[cita.id] is cita

    def test_lanza_si_no_cabe_en_hueco(self):
        caso, _ = self._construir()
        # Fuera del horario laboral (09:00-10:00).
        inicio = datetime.combine(_LUNES, time(11, 0))
        with pytest.raises(ProfesionalNoDisponible):
            caso.ejecutar("masaje", "ana", "Juan", "600111222", inicio)

    def test_lanza_si_solapa_con_cita_existente(self):
        cita_existente = Cita.nueva(
            1, "masaje", "ana", "cliente0",
            datetime.combine(_LUNES, time(9, 0)),
            datetime.combine(_LUNES, time(9, 30)),
        )
        caso, _ = self._construir(citas=[cita_existente])
        with pytest.raises(ProfesionalNoDisponible):
            caso.ejecutar("masaje", "ana", "Juan", "600111222", datetime.combine(_LUNES, time(9, 0)))

    def test_sincroniza_con_el_calendario_si_esta_configurado(self):
        calendario = FakeSincronizadorCalendario(id_evento="evento-abc")
        caso, _ = self._construir(calendario=calendario)
        inicio = datetime.combine(_LUNES, time(9, 0))

        cita = caso.ejecutar("masaje", "ana", "Juan", "600111222", inicio)

        assert cita.evento_calendario_id == "evento-abc"
        assert len(calendario.eventos_creados) == 1

    def test_no_falla_si_el_calendario_lanza_excepcion(self):
        calendario = FakeSincronizadorCalendario(lanza_en_crear=True)
        caso, repo_citas = self._construir(calendario=calendario)
        inicio = datetime.combine(_LUNES, time(9, 0))

        cita = caso.ejecutar("masaje", "ana", "Juan", "600111222", inicio)

        assert cita.evento_calendario_id is None
        assert repo_citas._data[cita.id] is cita

    def test_sin_telegram_chat_id_tambien_crea_cliente(self):
        # Antes del fix de #69/#52 (caso B: cliente huérfano), esto NO
        # creaba ningún Cliente — la Cita quedaba con un cliente_id sin
        # fila real detrás. Ahora se crea en cualquier canal.
        repo_servicios = FakeRepoServicios([_servicio(duracion=30)])
        repo_profesionales = FakeRepoProfesionales([_profesional()])
        repo_citas = FakeRepoCitas()
        repo_clientes = FakeRepoClientes()
        disponibilidad = ComprobarDisponibilidad(repo_servicios, repo_profesionales, repo_citas)
        caso = CrearReserva(
            repo_servicios, repo_profesionales, repo_citas, repo_clientes, disponibilidad,
            FakeRepoContadores(),
        )

        cita = caso.ejecutar(
            "masaje", "ana", "Juan", "600111222", datetime.combine(_LUNES, time(9, 0)),
        )

        cliente = repo_clientes.obtener(cita.cliente_id)
        assert cliente is not None
        assert cliente.nombre == "Juan"
        assert cliente.telefono == "600111222"
        assert cliente.telegram_chat_id is None

    def test_con_telegram_chat_id_crea_cliente_nuevo(self):
        repo_servicios = FakeRepoServicios([_servicio(duracion=30)])
        repo_profesionales = FakeRepoProfesionales([_profesional()])
        repo_citas = FakeRepoCitas()
        repo_clientes = FakeRepoClientes()
        disponibilidad = ComprobarDisponibilidad(repo_servicios, repo_profesionales, repo_citas)
        caso = CrearReserva(
            repo_servicios, repo_profesionales, repo_citas, repo_clientes, disponibilidad,
            FakeRepoContadores(),
        )

        cita = caso.ejecutar(
            "masaje", "ana", "Juan", "600111222", datetime.combine(_LUNES, time(9, 0)),
            telegram_chat_id="chat123",
        )

        cliente = repo_clientes.obtener(cita.cliente_id)
        assert cliente is not None
        assert cliente.telegram_chat_id == "chat123"

    def test_con_telegram_chat_id_actualiza_cliente_existente(self):
        # El teléfono es la clave de búsqueda (no un cliente_id libre):
        # un cliente ya existente con ese teléfono se reutiliza, no se
        # duplica.
        repo_servicios = FakeRepoServicios([_servicio(duracion=30)])
        repo_profesionales = FakeRepoProfesionales([_profesional()])
        repo_citas = FakeRepoCitas()
        repo_clientes = FakeRepoClientes()
        repo_clientes.guardar(Cliente(id="cliente1", nombre="Juan", telefono="600111222"))
        disponibilidad = ComprobarDisponibilidad(repo_servicios, repo_profesionales, repo_citas)
        caso = CrearReserva(
            repo_servicios, repo_profesionales, repo_citas, repo_clientes, disponibilidad,
            FakeRepoContadores(),
        )

        caso.ejecutar(
            "masaje", "ana", "Juan", "600111222", datetime.combine(_LUNES, time(9, 0)),
            telegram_chat_id="chat123",
        )

        cliente = repo_clientes.obtener("cliente1")
        assert cliente.nombre == "Juan"
        assert cliente.telefono == "600111222"
        assert cliente.telegram_chat_id == "chat123"
        assert len(repo_clientes.listar()) == 1  # no se duplicó

    def test_actualiza_el_nombre_si_cambia_para_un_telefono_ya_conocido(self):
        repo_servicios = FakeRepoServicios([_servicio(duracion=30)])
        repo_profesionales = FakeRepoProfesionales([_profesional()])
        repo_citas = FakeRepoCitas()
        repo_clientes = FakeRepoClientes()
        repo_clientes.guardar(Cliente(id="cliente1", nombre="Juan", telefono="600111222"))
        disponibilidad = ComprobarDisponibilidad(repo_servicios, repo_profesionales, repo_citas)
        caso = CrearReserva(
            repo_servicios, repo_profesionales, repo_citas, repo_clientes, disponibilidad,
            FakeRepoContadores(),
        )

        caso.ejecutar("masaje", "ana", "Juan Pérez", "600111222", datetime.combine(_LUNES, time(9, 0)))

        assert repo_clientes.obtener("cliente1").nombre == "Juan Pérez"

    def test_sin_calendario_configurado_no_intenta_sincronizar(self):
        caso, _ = self._construir(calendario=None)
        cita = caso.ejecutar("masaje", "ana", "Juan", "600111222", datetime.combine(_LUNES, time(9, 0)))
        assert cita.evento_calendario_id is None

    def test_notifica_confirmacion_si_el_cliente_tiene_telegram_chat_id(self):
        repo_servicios = FakeRepoServicios([_servicio(duracion=30)])
        repo_profesionales = FakeRepoProfesionales([_profesional()])
        repo_citas = FakeRepoCitas()
        repo_clientes = FakeRepoClientes()
        repo_clientes.guardar(
            Cliente(id="cliente1", nombre="Juan", telefono="600111222", telegram_chat_id="chat123")
        )
        notificador = FakeNotificadorMensajes()
        disponibilidad = ComprobarDisponibilidad(repo_servicios, repo_profesionales, repo_citas)
        caso = CrearReserva(
            repo_servicios, repo_profesionales, repo_citas, repo_clientes, disponibilidad,
            FakeRepoContadores(), notificador=notificador,
        )

        caso.ejecutar("masaje", "ana", "Juan", "600111222", datetime.combine(_LUNES, time(9, 0)))

        assert len(notificador.enviados) == 1
        destinatario, texto = notificador.enviados[0]
        assert destinatario == "chat123"
        assert "Masaje" in texto

    def test_notifica_usando_el_telegram_chat_id_persistido_en_la_misma_llamada(self):
        repo_servicios = FakeRepoServicios([_servicio(duracion=30)])
        repo_profesionales = FakeRepoProfesionales([_profesional()])
        repo_citas = FakeRepoCitas()
        repo_clientes = FakeRepoClientes()
        notificador = FakeNotificadorMensajes()
        disponibilidad = ComprobarDisponibilidad(repo_servicios, repo_profesionales, repo_citas)
        caso = CrearReserva(
            repo_servicios, repo_profesionales, repo_citas, repo_clientes, disponibilidad,
            FakeRepoContadores(), notificador=notificador,
        )

        caso.ejecutar(
            "masaje", "ana", "Juan", "600111222", datetime.combine(_LUNES, time(9, 0)),
            telegram_chat_id="chat123",
        )

        assert len(notificador.enviados) == 1
        assert notificador.enviados[0][0] == "chat123"

    def test_no_notifica_si_el_cliente_no_tiene_telegram_chat_id(self):
        repo_servicios = FakeRepoServicios([_servicio(duracion=30)])
        repo_profesionales = FakeRepoProfesionales([_profesional()])
        repo_citas = FakeRepoCitas()
        repo_clientes = FakeRepoClientes()
        repo_clientes.guardar(Cliente(id="cliente1", nombre="Juan", telefono="600111222"))
        notificador = FakeNotificadorMensajes()
        disponibilidad = ComprobarDisponibilidad(repo_servicios, repo_profesionales, repo_citas)
        caso = CrearReserva(
            repo_servicios, repo_profesionales, repo_citas, repo_clientes, disponibilidad,
            FakeRepoContadores(), notificador=notificador,
        )

        caso.ejecutar("masaje", "ana", "Juan", "600111222", datetime.combine(_LUNES, time(9, 0)))

        assert notificador.enviados == []

    def test_no_falla_si_el_notificador_lanza_excepcion(self):
        repo_servicios = FakeRepoServicios([_servicio(duracion=30)])
        repo_profesionales = FakeRepoProfesionales([_profesional()])
        repo_citas = FakeRepoCitas()
        repo_clientes = FakeRepoClientes()
        repo_clientes.guardar(
            Cliente(id="cliente1", nombre="Juan", telefono="600111222", telegram_chat_id="chat123")
        )
        notificador = FakeNotificadorMensajes(lanza=True)
        disponibilidad = ComprobarDisponibilidad(repo_servicios, repo_profesionales, repo_citas)
        caso = CrearReserva(
            repo_servicios, repo_profesionales, repo_citas, repo_clientes, disponibilidad,
            FakeRepoContadores(), notificador=notificador,
        )

        cita = caso.ejecutar("masaje", "ana", "Juan", "600111222", datetime.combine(_LUNES, time(9, 0)))

        assert repo_citas._data[cita.id] is cita


class TestCancelarReserva:
    def test_delega_en_el_repositorio(self):
        repo_citas = FakeRepoCitas()
        caso = CancelarReserva(repo_citas)
        caso.ejecutar("cita-123")
        assert repo_citas.canceladas == ["cita-123"]

    def test_cancela_el_evento_de_calendario_si_la_cita_tiene_uno(self):
        cita = Cita.nueva(
            1, "masaje", "ana", "cliente1",
            datetime.combine(_LUNES, time(9, 0)), datetime.combine(_LUNES, time(9, 30)),
        )
        cita.evento_calendario_id = "evento-abc"
        repo_citas = FakeRepoCitas([cita])
        calendario = FakeSincronizadorCalendario()

        caso = CancelarReserva(repo_citas, calendario)
        caso.ejecutar(cita.id)

        assert calendario.eventos_cancelados == ["evento-abc"]
        assert repo_citas.canceladas == [cita.id]

    def test_no_cancela_evento_si_la_cita_no_tiene_evento_calendario(self):
        cita = Cita.nueva(
            1, "masaje", "ana", "cliente1",
            datetime.combine(_LUNES, time(9, 0)), datetime.combine(_LUNES, time(9, 30)),
        )
        repo_citas = FakeRepoCitas([cita])
        calendario = FakeSincronizadorCalendario()

        CancelarReserva(repo_citas, calendario).ejecutar(cita.id)

        assert calendario.eventos_cancelados == []

    def test_no_falla_si_cancelar_evento_de_calendario_lanza_excepcion(self):
        cita = Cita.nueva(
            1, "masaje", "ana", "cliente1",
            datetime.combine(_LUNES, time(9, 0)), datetime.combine(_LUNES, time(9, 30)),
        )
        cita.evento_calendario_id = "evento-abc"
        repo_citas = FakeRepoCitas([cita])
        calendario = FakeSincronizadorCalendario(lanza_en_cancelar=True)

        CancelarReserva(repo_citas, calendario).ejecutar(cita.id)

        assert repo_citas.canceladas == [cita.id]

    def test_notifica_cancelacion_si_el_cliente_tiene_telegram_chat_id(self):
        cita = Cita.nueva(
            1, "masaje", "ana", "cliente1",
            datetime.combine(_LUNES, time(9, 0)), datetime.combine(_LUNES, time(9, 30)),
        )
        repo_citas = FakeRepoCitas([cita])
        repo_clientes = FakeRepoClientes()
        repo_clientes.guardar(Cliente(id="cliente1", nombre="Juan", telegram_chat_id="chat123"))
        notificador = FakeNotificadorMensajes()

        CancelarReserva(repo_citas, clientes=repo_clientes, notificador=notificador).ejecutar(cita.id)

        assert len(notificador.enviados) == 1
        assert notificador.enviados[0][0] == "chat123"

    def test_no_notifica_si_el_cliente_no_tiene_telegram_chat_id(self):
        cita = Cita.nueva(
            1, "masaje", "ana", "cliente1",
            datetime.combine(_LUNES, time(9, 0)), datetime.combine(_LUNES, time(9, 30)),
        )
        repo_citas = FakeRepoCitas([cita])
        repo_clientes = FakeRepoClientes()
        repo_clientes.guardar(Cliente(id="cliente1", nombre="Juan"))
        notificador = FakeNotificadorMensajes()

        CancelarReserva(repo_citas, clientes=repo_clientes, notificador=notificador).ejecutar(cita.id)

        assert notificador.enviados == []

    def test_no_notifica_sin_repositorio_de_clientes_aunque_haya_notificador(self):
        cita = Cita.nueva(
            1, "masaje", "ana", "cliente1",
            datetime.combine(_LUNES, time(9, 0)), datetime.combine(_LUNES, time(9, 30)),
        )
        repo_citas = FakeRepoCitas([cita])
        notificador = FakeNotificadorMensajes()

        CancelarReserva(repo_citas, notificador=notificador).ejecutar(cita.id)

        assert notificador.enviados == []
        assert repo_citas.canceladas == [cita.id]

    def test_no_falla_si_el_notificador_lanza_excepcion(self):
        cita = Cita.nueva(
            1, "masaje", "ana", "cliente1",
            datetime.combine(_LUNES, time(9, 0)), datetime.combine(_LUNES, time(9, 30)),
        )
        repo_citas = FakeRepoCitas([cita])
        repo_clientes = FakeRepoClientes()
        repo_clientes.guardar(Cliente(id="cliente1", nombre="Juan", telegram_chat_id="chat123"))
        notificador = FakeNotificadorMensajes(lanza=True)

        CancelarReserva(repo_citas, clientes=repo_clientes, notificador=notificador).ejecutar(cita.id)

        assert repo_citas.canceladas == [cita.id]


class TestCambiarEstadoCita:
    @staticmethod
    def _cita_pendiente():
        return Cita.nueva(
            1, "masaje", "ana", "cliente1",
            datetime.combine(_LUNES, time(9, 0)), datetime.combine(_LUNES, time(9, 30)),
        )

    def test_lanza_si_cita_no_existe(self):
        caso = CambiarEstadoCita(FakeRepoCitas())
        with pytest.raises(CitaNoExiste):
            caso.ejecutar("no_existe", EstadoCita.CONFIRMADA)

    def test_transicion_valida_actualiza_y_guarda(self):
        cita = self._cita_pendiente()
        repo = FakeRepoCitas([cita])
        caso = CambiarEstadoCita(repo)

        actualizada = caso.ejecutar(cita.id, EstadoCita.CONFIRMADA)

        assert actualizada.estado == EstadoCita.CONFIRMADA
        assert repo.obtener(cita.id).estado == EstadoCita.CONFIRMADA

    def test_lanza_si_transicion_invalida(self):
        cita = self._cita_pendiente()  # PENDIENTE no puede saltar directo a FINALIZADA
        repo = FakeRepoCitas([cita])
        caso = CambiarEstadoCita(repo)

        with pytest.raises(TransicionEstadoInvalida):
            caso.ejecutar(cita.id, EstadoCita.FINALIZADA)

    def test_estado_terminal_no_admite_transicion(self):
        cita = self._cita_pendiente()
        cita.estado = EstadoCita.FINALIZADA
        repo = FakeRepoCitas([cita])
        caso = CambiarEstadoCita(repo)

        with pytest.raises(TransicionEstadoInvalida):
            caso.ejecutar(cita.id, EstadoCita.CONFIRMADA)

    def test_cancelada_no_es_destino_valido_desde_ningun_estado(self):
        # CANCELADA se gestiona vía CancelarReserva, no a través de esta
        # transición — por diseño (ver issue #43).
        cita = self._cita_pendiente()
        repo = FakeRepoCitas([cita])
        caso = CambiarEstadoCita(repo)

        with pytest.raises(TransicionEstadoInvalida):
            caso.ejecutar(cita.id, EstadoCita.CANCELADA)

    def test_confirmada_permite_saltar_directo_a_finalizada(self):
        cita = self._cita_pendiente()
        cita.estado = EstadoCita.CONFIRMADA
        repo = FakeRepoCitas([cita])
        caso = CambiarEstadoCita(repo)

        actualizada = caso.ejecutar(cita.id, EstadoCita.FINALIZADA)

        assert actualizada.estado == EstadoCita.FINALIZADA

    def test_en_curso_solo_permite_finalizar(self):
        cita = self._cita_pendiente()
        cita.estado = EstadoCita.EN_CURSO
        repo = FakeRepoCitas([cita])
        caso = CambiarEstadoCita(repo)

        with pytest.raises(TransicionEstadoInvalida):
            caso.ejecutar(cita.id, EstadoCita.NO_SHOW)

    def test_notifica_al_confirmar_si_el_cliente_tiene_telegram_chat_id(self):
        cita = self._cita_pendiente()
        repo_citas = FakeRepoCitas([cita])
        repo_clientes = FakeRepoClientes()
        repo_clientes.guardar(Cliente(id="cliente1", nombre="Juan", telegram_chat_id="chat123"))
        notificador = FakeNotificadorMensajes()

        CambiarEstadoCita(repo_citas, repo_clientes, notificador).ejecutar(cita.id, EstadoCita.CONFIRMADA)

        assert len(notificador.enviados) == 1
        assert notificador.enviados[0][0] == "chat123"

    def test_no_notifica_si_el_cliente_no_tiene_telegram_chat_id(self):
        cita = self._cita_pendiente()
        repo_citas = FakeRepoCitas([cita])
        repo_clientes = FakeRepoClientes()
        repo_clientes.guardar(Cliente(id="cliente1", nombre="Juan"))
        notificador = FakeNotificadorMensajes()

        CambiarEstadoCita(repo_citas, repo_clientes, notificador).ejecutar(cita.id, EstadoCita.CONFIRMADA)

        assert notificador.enviados == []

    def test_no_notifica_sin_repositorio_de_clientes_aunque_haya_notificador(self):
        cita = self._cita_pendiente()
        repo_citas = FakeRepoCitas([cita])
        notificador = FakeNotificadorMensajes()

        actualizada = CambiarEstadoCita(repo_citas, notificador=notificador).ejecutar(
            cita.id, EstadoCita.CONFIRMADA
        )

        assert actualizada.estado == EstadoCita.CONFIRMADA
        assert notificador.enviados == []

    def test_no_notifica_en_transiciones_distintas_de_confirmada(self):
        cita = self._cita_pendiente()
        cita.estado = EstadoCita.CONFIRMADA
        repo_citas = FakeRepoCitas([cita])
        repo_clientes = FakeRepoClientes()
        repo_clientes.guardar(Cliente(id="cliente1", nombre="Juan", telegram_chat_id="chat123"))
        notificador = FakeNotificadorMensajes()

        CambiarEstadoCita(repo_citas, repo_clientes, notificador).ejecutar(cita.id, EstadoCita.EN_CURSO)

        assert notificador.enviados == []

    def test_no_falla_si_el_notificador_lanza_excepcion(self):
        cita = self._cita_pendiente()
        repo_citas = FakeRepoCitas([cita])
        repo_clientes = FakeRepoClientes()
        repo_clientes.guardar(Cliente(id="cliente1", nombre="Juan", telegram_chat_id="chat123"))
        notificador = FakeNotificadorMensajes(lanza=True)

        actualizada = CambiarEstadoCita(repo_citas, repo_clientes, notificador).ejecutar(
            cita.id, EstadoCita.CONFIRMADA
        )

        assert actualizada.estado == EstadoCita.CONFIRMADA


class TestRegistrarPedido:
    def test_registra_pedido_valido(self):
        repo_servicios = FakeRepoServicios([_servicio()])
        repo_pedidos = FakeRepoPedidos()
        caso = RegistrarPedido(repo_pedidos, repo_servicios)

        lineas = [LineaPedido(servicio_id="masaje", cantidad=2)]
        pedido = caso.ejecutar("cliente1", lineas)

        assert pedido.cliente_id == "cliente1"
        assert repo_pedidos._data[pedido.id] is pedido

    def test_lanza_si_alguna_linea_tiene_servicio_inexistente(self):
        repo_servicios = FakeRepoServicios([_servicio()])
        repo_pedidos = FakeRepoPedidos()
        caso = RegistrarPedido(repo_pedidos, repo_servicios)

        lineas = [LineaPedido(servicio_id="no_existe", cantidad=1)]
        with pytest.raises(ServicioNoExiste):
            caso.ejecutar("cliente1", lineas)


class TestCambiarEstadoPedido:
    def test_lanza_si_pedido_no_existe(self):
        caso = CambiarEstadoPedido(FakeRepoPedidos())
        with pytest.raises(PedidoNoExiste):
            caso.ejecutar("no_existe", EstadoPedido.EN_PREPARACION)

    def test_transicion_valida_actualiza_y_guarda(self):
        pedido = Pedido.nuevo("cliente1", [LineaPedido(servicio_id="masaje", cantidad=1)])
        repo = FakeRepoPedidos([pedido])
        caso = CambiarEstadoPedido(repo)

        actualizado = caso.ejecutar(pedido.id, EstadoPedido.EN_PREPARACION)

        assert actualizado.estado == EstadoPedido.EN_PREPARACION
        assert repo.obtener(pedido.id).estado == EstadoPedido.EN_PREPARACION

    def test_lanza_si_transicion_invalida(self):
        pedido = Pedido.nuevo("cliente1", [LineaPedido(servicio_id="masaje", cantidad=1)])
        repo = FakeRepoPedidos([pedido])
        caso = CambiarEstadoPedido(repo)

        with pytest.raises(TransicionEstadoInvalida):
            caso.ejecutar(pedido.id, EstadoPedido.ENTREGADO)

    def test_estado_terminal_no_admite_transicion(self):
        pedido = Pedido.nuevo("cliente1", [LineaPedido(servicio_id="masaje", cantidad=1)])
        pedido.estado = EstadoPedido.ENTREGADO
        repo = FakeRepoPedidos([pedido])
        caso = CambiarEstadoPedido(repo)

        with pytest.raises(TransicionEstadoInvalida):
            caso.ejecutar(pedido.id, EstadoPedido.CANCELADO)


class TestConsultarConocimientoNegocio:
    def test_delega_la_busqueda_en_el_puerto(self):
        conocimiento = FakeRepoConocimiento(resultados=[
            {"texto": "fragmento 1", "fuente": "horarios.md", "categoria": "horarios", "publicar_web": True},
            {"texto": "fragmento 2", "fuente": "horarios.md", "categoria": "horarios", "publicar_web": True},
        ])
        caso = ConsultarConocimientoNegocio(conocimiento)

        resultado = caso.ejecutar("¿cuáles son los horarios?")

        assert resultado == {
            "fragmentos": ["fragmento 1", "fragmento 2"],
            "fuentes": [{"fuente": "horarios.md", "categoria": "horarios"}],
        }
        assert conocimiento.ultima_consulta == "¿cuáles son los horarios?"

    def test_no_expone_fuentes_de_notas_no_publicas(self):
        conocimiento = FakeRepoConocimiento(resultados=[
            {"texto": "fragmento interno", "fuente": "interno.md", "categoria": "interno", "publicar_web": False},
        ])
        caso = ConsultarConocimientoNegocio(conocimiento)

        resultado = caso.ejecutar("consulta interna")

        assert resultado["fragmentos"] == ["fragmento interno"]
        assert resultado["fuentes"] == []


class TestCrearTestimonio:
    def test_crea_y_guarda_testimonio_valido(self):
        repo = FakeRepoTestimonios()
        caso = CrearTestimonio(repo, FakeRepoContadores())

        testimonio = caso.ejecutar("Juan", "Repetiré seguro", 5, titulo="Muy buena experiencia")

        assert testimonio.nombre == "Juan"
        assert testimonio.valoracion == 5
        assert repo.obtener(testimonio.id) is testimonio

    def test_genera_ids_crecientes_vía_contador(self):
        repo = FakeRepoTestimonios()
        caso = CrearTestimonio(repo, FakeRepoContadores())

        t1 = caso.ejecutar("Juan", "Uno", 5)
        t2 = caso.ejecutar("Ana", "Dos", 4)

        assert (t1.id, t2.id) == (1, 2)

    @pytest.mark.parametrize("valoracion", [0, 6, -1])
    def test_lanza_si_valoracion_fuera_de_rango(self, valoracion):
        caso = CrearTestimonio(FakeRepoTestimonios(), FakeRepoContadores())
        with pytest.raises(ValoracionInvalida):
            caso.ejecutar("Juan", "Descripción", valoracion, titulo="Título")

    def test_titulo_es_opcional(self):
        repo = FakeRepoTestimonios()
        caso = CrearTestimonio(repo, FakeRepoContadores())

        testimonio = caso.ejecutar("Juan", "Repetiré seguro", 5)

        assert testimonio.titulo == ""
        assert repo.obtener(testimonio.id) is testimonio


class TestEditarTestimonio:
    def test_lanza_si_testimonio_no_existe(self):
        caso = EditarTestimonio(FakeRepoTestimonios())
        with pytest.raises(TestimonioNoExiste):
            caso.ejecutar("no_existe", "Juan", "Desc", 4, titulo="Título")

    def test_edita_campos_y_guarda(self):
        testimonio = Testimonio.nuevo(1, "Juan", "Desc vieja", 3, titulo="Título viejo")
        repo = FakeRepoTestimonios([testimonio])
        caso = EditarTestimonio(repo)

        actualizado = caso.ejecutar(testimonio.id, "Juana", "Desc nueva", 5, titulo="Título nuevo")

        assert actualizado.nombre == "Juana"
        assert actualizado.titulo == "Título nuevo"
        assert actualizado.valoracion == 5
        assert repo.obtener(testimonio.id).nombre == "Juana"

    def test_lanza_si_nueva_valoracion_fuera_de_rango(self):
        testimonio = Testimonio.nuevo(1, "Juan", "Desc", 3, titulo="Título")
        repo = FakeRepoTestimonios([testimonio])
        caso = EditarTestimonio(repo)

        with pytest.raises(ValoracionInvalida):
            caso.ejecutar(testimonio.id, "Juan", "Desc", 7, titulo="Título")


class TestEliminarTestimonio:
    def test_lanza_si_testimonio_no_existe(self):
        caso = EliminarTestimonio(FakeRepoTestimonios())
        with pytest.raises(TestimonioNoExiste):
            caso.ejecutar("no_existe")

    def test_elimina_testimonio_existente(self):
        testimonio = Testimonio.nuevo(1, "Juan", "Desc", 4, titulo="Título")
        repo = FakeRepoTestimonios([testimonio])
        caso = EliminarTestimonio(repo)

        caso.ejecutar(testimonio.id)

        assert repo.obtener(testimonio.id) is None


class TestListarTestimoniosRecientes:
    def _testimonio(self, id_, dia):
        return Testimonio(
            id=id_, nombre=f"Cliente {id_}", descripcion="Desc", valoracion=5,
            creado_en=datetime(2026, 1, dia, tzinfo=UTC),
        )

    def test_devuelve_los_mas_recientes_primero(self):
        antiguo = self._testimonio(1, 1)
        reciente = self._testimonio(2, 10)
        repo = FakeRepoTestimonios([antiguo, reciente])
        caso = ListarTestimoniosRecientes(repo)

        resultado = caso.ejecutar()

        assert [t.id for t in resultado] == [2, 1]

    def test_limita_al_numero_indicado(self):
        testimonios = [self._testimonio(i, i) for i in range(1, 8)]
        repo = FakeRepoTestimonios(testimonios)
        caso = ListarTestimoniosRecientes(repo)

        resultado = caso.ejecutar(limite=5)

        assert len(resultado) == 5
        assert [t.id for t in resultado] == [7, 6, 5, 4, 3]

    def test_lista_vacia_si_no_hay_testimonios(self):
        caso = ListarTestimoniosRecientes(FakeRepoTestimonios())
        assert caso.ejecutar() == []


class TestObtenerPromoBar:
    def test_devuelve_valores_por_defecto_si_nunca_se_guardo_nada(self):
        caso = ObtenerPromoBar(FakeRepoPromoBar())

        resultado = caso.ejecutar()

        assert resultado.activo is False
        assert resultado.contenido_html == ""

    def test_devuelve_lo_guardado(self):
        repo = FakeRepoPromoBar(PromoBar(activo=True, contenido_html="<p>Oferta</p>"))
        caso = ObtenerPromoBar(repo)

        resultado = caso.ejecutar()

        assert resultado.activo is True
        assert resultado.contenido_html == "<p>Oferta</p>"


class TestActualizarPromoBar:
    def test_guarda_activo_y_contenido(self):
        repo = FakeRepoPromoBar()
        caso = ActualizarPromoBar(repo)

        resultado = caso.ejecutar(activo=True, contenido_html="<a href='/x'>Oferta</a>")

        assert resultado.activo is True
        assert resultado.contenido_html == "<a href='/x'>Oferta</a>"
        assert repo.obtener() == resultado

    def test_sobrescribe_lo_anterior(self):
        repo = FakeRepoPromoBar(PromoBar(activo=True, contenido_html="Viejo"))
        caso = ActualizarPromoBar(repo)

        caso.ejecutar(activo=False, contenido_html="Nuevo")

        actual = repo.obtener()
        assert actual.activo is False
        assert actual.contenido_html == "Nuevo"


class TestCrearCliente:
    def test_crea_y_guarda_cliente_con_id_generado_por_contador(self):
        repo = FakeRepoClientes()
        caso = CrearCliente(repo, FakeRepoContadores())

        cliente = caso.ejecutar("Juan", telefono="600111222")

        assert cliente.id == "1"
        assert cliente.nombre == "Juan"
        assert cliente.telefono == "600111222"
        assert repo.obtener("1") is cliente

    def test_genera_ids_crecientes_vía_contador(self):
        repo = FakeRepoClientes()
        caso = CrearCliente(repo, FakeRepoContadores())

        c1 = caso.ejecutar("Juan")
        c2 = caso.ejecutar("Ana")

        assert (c1.id, c2.id) == ("1", "2")

    def test_lanza_si_el_id_generado_ya_existe(self):
        # Salvaguarda para clientes ya existentes con id manual (de
        # antes de este cambio, o vía CrearReserva) que coincidan con
        # un valor futuro del contador.
        repo = FakeRepoClientes()
        repo.guardar(Cliente(id="1", nombre="Cliente antiguo"))
        caso = CrearCliente(repo, FakeRepoContadores())

        with pytest.raises(ClienteYaExiste):
            caso.ejecutar("Juan")


class TestEditarCliente:
    def test_lanza_si_cliente_no_existe(self):
        caso = EditarCliente(FakeRepoClientes())
        with pytest.raises(ClienteNoExiste):
            caso.ejecutar("no_existe", "Juan", None, None, "")

    def test_edita_campos_pero_no_el_id(self):
        cliente = Cliente(id="c1", nombre="Juan", telefono="600111222")
        repo = FakeRepoClientes()
        repo.guardar(cliente)
        caso = EditarCliente(repo)

        actualizado = caso.ejecutar("c1", "Juana", "600999888", "juana@example.com", "vip")

        assert actualizado.id == "c1"
        assert actualizado.nombre == "Juana"
        assert actualizado.telefono == "600999888"
        assert actualizado.email == "juana@example.com"
        assert actualizado.notas == "vip"

    def test_no_toca_telegram_chat_id(self):
        cliente = Cliente(id="c1", nombre="Juan", telegram_chat_id="tg-123")
        repo = FakeRepoClientes()
        repo.guardar(cliente)
        caso = EditarCliente(repo)

        actualizado = caso.ejecutar("c1", "Juana", None, None, "")

        assert actualizado.telegram_chat_id == "tg-123"


class TestEliminarCliente:
    def test_lanza_si_cliente_no_existe(self):
        caso = EliminarCliente(FakeRepoClientes())
        with pytest.raises(ClienteNoExiste):
            caso.ejecutar("no_existe")

    def test_elimina_cliente_existente(self):
        repo = FakeRepoClientes()
        repo.guardar(Cliente(id="c1", nombre="Juan"))
        caso = EliminarCliente(repo)

        caso.ejecutar("c1")

        assert repo.obtener("c1") is None


class TestDetectarClientesDuplicados:
    def test_agrupa_clientes_con_mismo_nombre_y_telefono(self):
        repo = FakeRepoClientes()
        repo.guardar(Cliente(id="1", nombre="Juan Pérez", telefono="600111222"))
        repo.guardar(Cliente(id="2", nombre="juan pérez", telefono="600111222"))
        repo.guardar(Cliente(id="3", nombre="Ana", telefono="600999888"))
        caso = DetectarClientesDuplicados(repo)

        grupos = caso.ejecutar()

        assert len(grupos) == 1
        assert {c.id for c in grupos[0]} == {"1", "2"}

    def test_ignora_clientes_sin_telefono(self):
        repo = FakeRepoClientes()
        repo.guardar(Cliente(id="1", nombre="Juan", telefono=None))
        repo.guardar(Cliente(id="2", nombre="Juan", telefono=None))
        caso = DetectarClientesDuplicados(repo)

        assert caso.ejecutar() == []

    def test_no_agrupa_si_no_hay_duplicados(self):
        repo = FakeRepoClientes()
        repo.guardar(Cliente(id="1", nombre="Juan", telefono="600111222"))
        repo.guardar(Cliente(id="2", nombre="Ana", telefono="600999888"))
        caso = DetectarClientesDuplicados(repo)

        assert caso.ejecutar() == []


class TestFusionarClientes:
    def test_lanza_si_algun_id_no_existe(self):
        repo = FakeRepoClientes()
        repo.guardar(Cliente(id="1", nombre="Juan", telefono="600111222"))
        caso = FusionarClientes(repo, FakeRepoCitas(), FakeRepoPedidos())

        with pytest.raises(ClienteNoExiste):
            caso.ejecutar(["1", "no_existe"])

    def test_el_superviviente_es_el_id_mas_bajo(self):
        repo = FakeRepoClientes()
        repo.guardar(Cliente(id="5", nombre="Juan", telefono="600111222"))
        repo.guardar(Cliente(id="2", nombre="Juan", telefono="600111222"))
        repo.guardar(Cliente(id="9", nombre="Juan", telefono="600111222"))
        caso = FusionarClientes(repo, FakeRepoCitas(), FakeRepoPedidos())

        superviviente = caso.ejecutar(["5", "2", "9"])

        assert superviviente.id == "2"

    def test_marca_borrado_a_los_no_supervivientes_sin_eliminarlos(self):
        repo = FakeRepoClientes()
        repo.guardar(Cliente(id="1", nombre="Juan", telefono="600111222"))
        repo.guardar(Cliente(id="2", nombre="Juan", telefono="600111222"))
        caso = FusionarClientes(repo, FakeRepoCitas(), FakeRepoPedidos())

        caso.ejecutar(["1", "2"])

        # marcar_borrado, no eliminar(): la fila sigue estando en el
        # repo (obtener la sigue encontrando), pero listar() ya no la
        # devuelve.
        fusionado = repo.obtener("2")
        assert fusionado is not None
        assert fusionado.borrado is True
        assert repo.obtener("1").borrado is False
        assert [c.id for c in repo.listar()] == ["1"]

    def test_reasigna_citas_y_pedidos_al_superviviente(self):
        repo_clientes = FakeRepoClientes()
        repo_clientes.guardar(Cliente(id="1", nombre="Juan", telefono="600111222"))
        repo_clientes.guardar(Cliente(id="2", nombre="Juan", telefono="600111222"))
        cita = Cita.nueva(1, "masaje", "ana", "2", datetime(2026, 8, 3, 9, 0), datetime(2026, 8, 3, 10, 0))
        repo_citas = FakeRepoCitas([cita])
        pedido = Pedido.nuevo("2", [LineaPedido(servicio_id="masaje", cantidad=1)])
        repo_pedidos = FakeRepoPedidos([pedido])
        caso = FusionarClientes(repo_clientes, repo_citas, repo_pedidos)

        caso.ejecutar(["1", "2"])

        assert repo_citas.obtener(cita.id).cliente_id == "1"
        assert repo_pedidos.obtener(pedido.id).cliente_id == "1"
