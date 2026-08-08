from datetime import date, datetime

from adapters.out.repositorios_memoria import (
    RepositorioCitasMemoria,
    RepositorioClientesMemoria,
    RepositorioPedidosMemoria,
    RepositorioProfesionalesMemoria,
    RepositorioServiciosMemoria,
)
from domain.entities import Cita, Cliente, EstadoCita, EstadoPedido, LineaPedido, Pedido, Profesional, Servicio


def test_repositorio_servicios_obtener_y_listar():
    servicio = Servicio(id="s1", nombre="Masaje", duracion_minutos=60, precio=50.0)
    repo = RepositorioServiciosMemoria([servicio])

    assert repo.obtener("s1") is servicio
    assert repo.obtener("no_existe") is None
    assert repo.listar() == [servicio]


def test_repositorio_servicios_vacio_por_defecto():
    assert RepositorioServiciosMemoria().listar() == []


def test_repositorio_profesionales_listar_por_servicio():
    ana = Profesional(id="ana", nombre="Ana", servicios_ids=["s1", "s2"])
    beatriz = Profesional(id="beatriz", nombre="Beatriz", servicios_ids=["s2"])
    repo = RepositorioProfesionalesMemoria([ana, beatriz])

    assert repo.obtener("ana") is ana
    assert repo.listar_por_servicio("s1") == [ana]
    assert set(p.id for p in repo.listar_por_servicio("s2")) == {"ana", "beatriz"}


def test_repositorio_citas_guardar_y_filtrar_por_fecha():
    repo = RepositorioCitasMemoria()
    cita1 = Cita.nueva("s1", "ana", "c1", datetime(2026, 8, 3, 9, 0), datetime(2026, 8, 3, 10, 0))
    cita2 = Cita.nueva("s1", "ana", "c1", datetime(2026, 8, 4, 9, 0), datetime(2026, 8, 4, 10, 0))
    repo.guardar(cita1)
    repo.guardar(cita2)

    resultado = repo.citas_de_profesional_en_fecha("ana", date(2026, 8, 3))

    assert resultado == [cita1]


def test_repositorio_citas_en_fecha_agrega_todos_los_profesionales():
    repo = RepositorioCitasMemoria()
    cita_ana = Cita.nueva("s1", "ana", "c1", datetime(2026, 8, 3, 9, 0), datetime(2026, 8, 3, 10, 0))
    cita_beatriz = Cita.nueva("s1", "beatriz", "c2", datetime(2026, 8, 3, 11, 0), datetime(2026, 8, 3, 12, 0))
    cita_otro_dia = Cita.nueva("s1", "ana", "c1", datetime(2026, 8, 4, 9, 0), datetime(2026, 8, 4, 10, 0))
    repo.guardar(cita_ana)
    repo.guardar(cita_beatriz)
    repo.guardar(cita_otro_dia)

    resultado = repo.citas_en_fecha(date(2026, 8, 3))

    assert set(c.id for c in resultado) == {cita_ana.id, cita_beatriz.id}


def test_repositorio_citas_cancelar():
    repo = RepositorioCitasMemoria()
    cita = Cita.nueva("s1", "ana", "c1", datetime(2026, 8, 3, 9, 0), datetime(2026, 8, 3, 10, 0))
    repo.guardar(cita)

    repo.cancelar(cita.id)

    assert repo._data[cita.id].estado == EstadoCita.CANCELADA


def test_repositorio_citas_cancelar_id_inexistente_no_lanza():
    repo = RepositorioCitasMemoria()
    repo.cancelar("no_existe")  # no debe lanzar


def test_repositorio_citas_obtener():
    repo = RepositorioCitasMemoria()
    cita = Cita.nueva("s1", "ana", "c1", datetime(2026, 8, 3, 9, 0), datetime(2026, 8, 3, 10, 0))
    repo.guardar(cita)

    assert repo.obtener(cita.id) is cita
    assert repo.obtener("no_existe") is None


def test_repositorio_clientes():
    repo = RepositorioClientesMemoria()
    cliente = Cliente(id="c1", nombre="Juan", telefono="600111222")
    repo.guardar(cliente)

    assert repo.obtener("c1") is cliente
    assert repo.buscar_por_telefono("600111222") is cliente
    assert repo.buscar_por_telefono("no_existe") is None


def test_repositorio_clientes_telegram_chat_id():
    repo = RepositorioClientesMemoria()
    cliente = Cliente(id="c1", nombre="Juan", telegram_chat_id="chat123")
    repo.guardar(cliente)

    assert repo.obtener("c1").telegram_chat_id == "chat123"


def test_repositorio_pedidos():
    repo = RepositorioPedidosMemoria()
    pedido = Pedido.nuevo("c1", [LineaPedido(servicio_id="s1", cantidad=1)])
    repo.guardar(pedido)

    assert repo.obtener(pedido.id) is pedido
    assert repo.obtener("no_existe") is None


def test_repositorio_pedidos_listar_pendientes_excluye_estados_terminales():
    repo = RepositorioPedidosMemoria()
    pendiente = Pedido.nuevo("c1", [LineaPedido(servicio_id="s1", cantidad=1)])
    entregado = Pedido.nuevo("c1", [LineaPedido(servicio_id="s1", cantidad=1)])
    entregado.estado = EstadoPedido.ENTREGADO
    cancelado = Pedido.nuevo("c1", [LineaPedido(servicio_id="s1", cantidad=1)])
    cancelado.estado = EstadoPedido.CANCELADO
    repo.guardar(pendiente)
    repo.guardar(entregado)
    repo.guardar(cancelado)

    assert repo.listar_pendientes() == [pendiente]
