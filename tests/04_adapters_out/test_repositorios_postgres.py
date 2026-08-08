"""A diferencia de test_vector_store.py (que mockea el cliente
externo), aquí usamos un motor SQLite en memoria real vía SQLModel en
vez de mockear cada sentencia SQL: lo que hay que probar es que el
mapeo fila<->entidad y las queries son correctos, y SQLAlchemy habla
el mismo dialecto core independientemente del backend. No hace falta
red ni credenciales ni un Postgres real."""
from datetime import date, datetime

from sqlmodel import create_engine

from adapters.out.db_models import SQLModel
from adapters.out.repositorios_postgres import (
    RepositorioCitasPostgres,
    RepositorioClientesPostgres,
    RepositorioPedidosPostgres,
)
from domain.entities import Cita, Cliente, EstadoCita, EstadoPedido, LineaPedido, Pedido


def _engine():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return engine


def test_citas_guardar_y_filtrar_por_fecha():
    repo = RepositorioCitasPostgres(_engine())
    cita1 = Cita.nueva("s1", "ana", "c1", datetime(2026, 8, 3, 9, 0), datetime(2026, 8, 3, 10, 0))
    cita2 = Cita.nueva("s1", "ana", "c1", datetime(2026, 8, 4, 9, 0), datetime(2026, 8, 4, 10, 0))
    repo.guardar(cita1)
    repo.guardar(cita2)

    resultado = repo.citas_de_profesional_en_fecha("ana", date(2026, 8, 3))

    assert [c.id for c in resultado] == [cita1.id]
    assert resultado[0].estado == EstadoCita.PENDIENTE


def test_citas_en_fecha_agrega_todos_los_profesionales():
    repo = RepositorioCitasPostgres(_engine())
    cita_ana = Cita.nueva("s1", "ana", "c1", datetime(2026, 8, 3, 9, 0), datetime(2026, 8, 3, 10, 0))
    cita_beatriz = Cita.nueva("s1", "beatriz", "c2", datetime(2026, 8, 3, 11, 0), datetime(2026, 8, 3, 12, 0))
    cita_otro_dia = Cita.nueva("s1", "ana", "c1", datetime(2026, 8, 4, 9, 0), datetime(2026, 8, 4, 10, 0))
    repo.guardar(cita_ana)
    repo.guardar(cita_beatriz)
    repo.guardar(cita_otro_dia)

    resultado = repo.citas_en_fecha(date(2026, 8, 3))

    assert {c.id for c in resultado} == {cita_ana.id, cita_beatriz.id}


def test_citas_en_rango_incluye_los_limites_y_excluye_fuera_de_rango():
    repo = RepositorioCitasPostgres(_engine())
    cita_antes = Cita.nueva("s1", "ana", "c1", datetime(2026, 8, 2, 9, 0), datetime(2026, 8, 2, 10, 0))
    cita_limite_inferior = Cita.nueva("s1", "ana", "c1", datetime(2026, 8, 3, 9, 0), datetime(2026, 8, 3, 10, 0))
    cita_intermedia = Cita.nueva("s1", "beatriz", "c2", datetime(2026, 8, 4, 9, 0), datetime(2026, 8, 4, 10, 0))
    cita_limite_superior = Cita.nueva("s1", "ana", "c1", datetime(2026, 8, 5, 9, 0), datetime(2026, 8, 5, 10, 0))
    cita_despues = Cita.nueva("s1", "ana", "c1", datetime(2026, 8, 6, 9, 0), datetime(2026, 8, 6, 10, 0))
    for cita in (cita_antes, cita_limite_inferior, cita_intermedia, cita_limite_superior, cita_despues):
        repo.guardar(cita)

    resultado = repo.citas_en_rango(date(2026, 8, 3), date(2026, 8, 5))

    assert {c.id for c in resultado} == {
        cita_limite_inferior.id, cita_intermedia.id, cita_limite_superior.id,
    }


def test_citas_en_rango_vacio_si_no_hay_citas_en_ese_rango():
    repo = RepositorioCitasPostgres(_engine())
    repo.guardar(Cita.nueva("s1", "ana", "c1", datetime(2026, 8, 1, 9, 0), datetime(2026, 8, 1, 10, 0)))

    assert repo.citas_en_rango(date(2026, 8, 10), date(2026, 8, 20)) == []


def test_citas_cancelar():
    repo = RepositorioCitasPostgres(_engine())
    cita = Cita.nueva("s1", "ana", "c1", datetime(2026, 8, 3, 9, 0), datetime(2026, 8, 3, 10, 0))
    repo.guardar(cita)

    repo.cancelar(cita.id)

    resultado = repo.citas_de_profesional_en_fecha("ana", date(2026, 8, 3))
    assert resultado[0].estado == EstadoCita.CANCELADA


def test_citas_cancelar_id_inexistente_no_lanza():
    repo = RepositorioCitasPostgres(_engine())
    repo.cancelar("no_existe")  # no debe lanzar
    repo.cancelar(None)  # no debe lanzar


def test_citas_obtener():
    repo = RepositorioCitasPostgres(_engine())
    cita = Cita.nueva("s1", "ana", "c1", datetime(2026, 8, 3, 9, 0), datetime(2026, 8, 3, 10, 0))
    cita.evento_calendario_id = "evento-abc"
    repo.guardar(cita)

    resultado = repo.obtener(cita.id)

    assert resultado.id == cita.id
    assert resultado.evento_calendario_id == "evento-abc"
    assert repo.obtener("no_existe") is None


def test_clientes():
    repo = RepositorioClientesPostgres(_engine())
    cliente = Cliente(id="c1", nombre="Juan", telefono="600111222")
    repo.guardar(cliente)

    obtenido = repo.obtener("c1")

    assert obtenido == cliente
    assert repo.buscar_por_telefono("600111222") == cliente
    assert repo.buscar_por_telefono("no_existe") is None
    assert repo.obtener("no_existe") is None


def test_clientes_guardar_es_upsert():
    repo = RepositorioClientesPostgres(_engine())
    repo.guardar(Cliente(id="c1", nombre="Juan"))
    repo.guardar(Cliente(id="c1", nombre="Juan Actualizado"))

    assert repo.obtener("c1").nombre == "Juan Actualizado"


def test_clientes_telegram_chat_id():
    repo = RepositorioClientesPostgres(_engine())
    repo.guardar(Cliente(id="c1", nombre="Juan", telegram_chat_id="chat123"))

    assert repo.obtener("c1").telegram_chat_id == "chat123"


def test_pedidos_guardar_y_obtener_con_lineas():
    repo = RepositorioPedidosPostgres(_engine())
    pedido = Pedido.nuevo("c1", [
        LineaPedido(servicio_id="s1", cantidad=2, notas="sin azúcar"),
        LineaPedido(servicio_id="s2", cantidad=1),
    ])
    repo.guardar(pedido)

    obtenido = repo.obtener(pedido.id)

    assert obtenido.id == pedido.id
    assert obtenido.cliente_id == "c1"
    assert obtenido.estado == EstadoPedido.RECIBIDO
    assert {(linea.servicio_id, linea.cantidad, linea.notas) for linea in obtenido.lineas} == {
        ("s1", 2, "sin azúcar"), ("s2", 1, ""),
    }


def test_pedidos_guardar_de_nuevo_sustituye_las_lineas():
    repo = RepositorioPedidosPostgres(_engine())
    pedido = Pedido.nuevo("c1", [LineaPedido(servicio_id="s1", cantidad=1)])
    repo.guardar(pedido)

    pedido.lineas = [LineaPedido(servicio_id="s2", cantidad=5)]
    repo.guardar(pedido)

    obtenido = repo.obtener(pedido.id)
    assert [(linea.servicio_id, linea.cantidad) for linea in obtenido.lineas] == [("s2", 5)]


def test_pedidos_obtener_inexistente_devuelve_none():
    repo = RepositorioPedidosPostgres(_engine())
    assert repo.obtener("no_existe") is None


def test_pedidos_listar_pendientes_excluye_estados_terminales():
    repo = RepositorioPedidosPostgres(_engine())
    pendiente = Pedido.nuevo("c1", [LineaPedido(servicio_id="s1", cantidad=1)])
    entregado = Pedido.nuevo("c1", [LineaPedido(servicio_id="s1", cantidad=1)])
    entregado.estado = EstadoPedido.ENTREGADO
    cancelado = Pedido.nuevo("c1", [LineaPedido(servicio_id="s1", cantidad=1)])
    cancelado.estado = EstadoPedido.CANCELADO
    repo.guardar(pendiente)
    repo.guardar(entregado)
    repo.guardar(cancelado)

    resultado = repo.listar_pendientes()

    assert {p.id for p in resultado} == {pendiente.id}
