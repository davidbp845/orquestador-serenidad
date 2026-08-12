"""A diferencia de test_vector_store.py (que mockea el cliente
externo), aquí usamos un motor SQLite en memoria real vía SQLModel en
vez de mockear cada sentencia SQL: lo que hay que probar es que el
mapeo fila<->entidad y las queries son correctos, y SQLAlchemy habla
el mismo dialecto core independientemente del backend. No hace falta
red ni credenciales ni un Postgres real."""
from datetime import date, datetime

from sqlmodel import Session, create_engine, select

from adapters.out.db_models import LineaPedidoDB, SQLModel
from adapters.out.repositorios_postgres import (
    RepositorioCitasPostgres,
    RepositorioClientesPostgres,
    RepositorioContadoresPostgres,
    RepositorioPedidosPostgres,
    RepositorioPromoBarPostgres,
    RepositorioTestimoniosPostgres,
)
from domain.entities import Cita, Cliente, EstadoCita, EstadoPedido, LineaPedido, Pedido, PromoBar, Testimonio


def _engine():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return engine


def test_citas_guardar_y_filtrar_por_fecha():
    repo = RepositorioCitasPostgres(_engine())
    cita1 = Cita.nueva(1, "s1", "ana", "c1", datetime(2026, 8, 3, 9, 0), datetime(2026, 8, 3, 10, 0))
    cita2 = Cita.nueva(2, "s1", "ana", "c1", datetime(2026, 8, 4, 9, 0), datetime(2026, 8, 4, 10, 0))
    repo.guardar(cita1)
    repo.guardar(cita2)

    resultado = repo.citas_de_profesional_en_fecha("ana", date(2026, 8, 3))

    assert [c.id for c in resultado] == [cita1.id]
    assert resultado[0].estado == EstadoCita.PENDIENTE


def test_citas_en_fecha_agrega_todos_los_profesionales():
    repo = RepositorioCitasPostgres(_engine())
    cita_ana = Cita.nueva(1, "s1", "ana", "c1", datetime(2026, 8, 3, 9, 0), datetime(2026, 8, 3, 10, 0))
    cita_beatriz = Cita.nueva(2, "s1", "beatriz", "c2", datetime(2026, 8, 3, 11, 0), datetime(2026, 8, 3, 12, 0))
    cita_otro_dia = Cita.nueva(3, "s1", "ana", "c1", datetime(2026, 8, 4, 9, 0), datetime(2026, 8, 4, 10, 0))
    repo.guardar(cita_ana)
    repo.guardar(cita_beatriz)
    repo.guardar(cita_otro_dia)

    resultado = repo.citas_en_fecha(date(2026, 8, 3))

    assert {c.id for c in resultado} == {cita_ana.id, cita_beatriz.id}


def test_citas_en_rango_incluye_los_limites_y_excluye_fuera_de_rango():
    repo = RepositorioCitasPostgres(_engine())
    cita_antes = Cita.nueva(1, "s1", "ana", "c1", datetime(2026, 8, 2, 9, 0), datetime(2026, 8, 2, 10, 0))
    cita_limite_inferior = Cita.nueva(2, "s1", "ana", "c1", datetime(2026, 8, 3, 9, 0), datetime(2026, 8, 3, 10, 0))
    cita_intermedia = Cita.nueva(3, "s1", "beatriz", "c2", datetime(2026, 8, 4, 9, 0), datetime(2026, 8, 4, 10, 0))
    cita_limite_superior = Cita.nueva(4, "s1", "ana", "c1", datetime(2026, 8, 5, 9, 0), datetime(2026, 8, 5, 10, 0))
    cita_despues = Cita.nueva(5, "s1", "ana", "c1", datetime(2026, 8, 6, 9, 0), datetime(2026, 8, 6, 10, 0))
    for cita in (cita_antes, cita_limite_inferior, cita_intermedia, cita_limite_superior, cita_despues):
        repo.guardar(cita)

    resultado = repo.citas_en_rango(date(2026, 8, 3), date(2026, 8, 5))

    assert {c.id for c in resultado} == {
        cita_limite_inferior.id, cita_intermedia.id, cita_limite_superior.id,
    }


def test_citas_en_rango_vacio_si_no_hay_citas_en_ese_rango():
    repo = RepositorioCitasPostgres(_engine())
    repo.guardar(Cita.nueva(1, "s1", "ana", "c1", datetime(2026, 8, 1, 9, 0), datetime(2026, 8, 1, 10, 0)))

    assert repo.citas_en_rango(date(2026, 8, 10), date(2026, 8, 20)) == []


def test_citas_cancelar():
    repo = RepositorioCitasPostgres(_engine())
    cita = Cita.nueva(1, "s1", "ana", "c1", datetime(2026, 8, 3, 9, 0), datetime(2026, 8, 3, 10, 0))
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
    cita = Cita.nueva(1, "s1", "ana", "c1", datetime(2026, 8, 3, 9, 0), datetime(2026, 8, 3, 10, 0))
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


def test_clientes_listar():
    repo = RepositorioClientesPostgres(_engine())
    assert repo.listar() == []

    repo.guardar(Cliente(id="c1", nombre="Juan", telefono="600111222"))
    repo.guardar(Cliente(id="c2", nombre="Ana", telefono="600333444"))

    assert {c.id for c in repo.listar()} == {"c1", "c2"}


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


def test_citas_borrar_todo():
    repo = RepositorioCitasPostgres(_engine())
    repo.guardar(Cita.nueva(1, "s1", "ana", "c1", datetime(2026, 8, 3, 9, 0), datetime(2026, 8, 3, 10, 0)))
    repo.guardar(Cita.nueva(2, "s1", "ana", "c1", datetime(2026, 8, 4, 9, 0), datetime(2026, 8, 4, 10, 0)))

    assert repo.borrar_todo() == 2
    assert repo.citas_en_rango(date(2026, 1, 1), date(2026, 12, 31)) == []
    assert repo.borrar_todo() == 0  # repetirlo sobre una tabla vacía no lanza


def test_citas_reasignar_cliente():
    repo = RepositorioCitasPostgres(_engine())
    repo.guardar(Cita.nueva(1, "s1", "ana", "c1", datetime(2026, 8, 3, 9, 0), datetime(2026, 8, 3, 10, 0)))
    repo.guardar(Cita.nueva(2, "s1", "ana", "c2", datetime(2026, 8, 4, 9, 0), datetime(2026, 8, 4, 10, 0)))

    n = repo.reasignar_cliente("c1", "c_final")

    assert n == 1
    assert repo.obtener(1).cliente_id == "c_final"
    assert repo.obtener(2).cliente_id == "c2"


def test_clientes_borrar_todo():
    repo = RepositorioClientesPostgres(_engine())
    repo.guardar(Cliente(id="c1", nombre="Juan"))
    repo.guardar(Cliente(id="c2", nombre="Ana"))

    assert repo.borrar_todo() == 2
    assert repo.listar() == []


def test_clientes_eliminar():
    repo = RepositorioClientesPostgres(_engine())
    repo.guardar(Cliente(id="c1", nombre="Juan"))

    repo.eliminar("c1")

    assert repo.obtener("c1") is None
    repo.eliminar("c1")  # repetirlo sobre uno ya borrado no lanza


def test_clientes_marcar_borrado_no_elimina_la_fila():
    repo = RepositorioClientesPostgres(_engine())
    repo.guardar(Cliente(id="c1", nombre="Juan", telefono="600111222"))

    repo.marcar_borrado("c1")

    assert repo.obtener("c1").borrado is True
    assert repo.listar() == []
    assert repo.buscar_por_telefono("600111222") is None


def test_pedidos_borrar_todo_incluye_las_lineas():
    engine = _engine()
    repo = RepositorioPedidosPostgres(engine)
    repo.guardar(Pedido.nuevo("c1", [LineaPedido(servicio_id="s1", cantidad=2)]))
    repo.guardar(Pedido.nuevo("c1", [LineaPedido(servicio_id="s2", cantidad=1)]))

    borrados = repo.borrar_todo()

    assert borrados == 2
    assert repo.listar_pendientes() == []
    with Session(engine) as sesion:
        assert sesion.exec(select(LineaPedidoDB)).all() == []


def test_pedidos_reasignar_cliente():
    repo = RepositorioPedidosPostgres(_engine())
    pedido1 = Pedido.nuevo("c1", [LineaPedido(servicio_id="s1", cantidad=1)])
    pedido2 = Pedido.nuevo("c2", [LineaPedido(servicio_id="s2", cantidad=1)])
    repo.guardar(pedido1)
    repo.guardar(pedido2)

    n = repo.reasignar_cliente("c1", "c_final")

    assert n == 1
    assert repo.obtener(pedido1.id).cliente_id == "c_final"
    assert repo.obtener(pedido2.id).cliente_id == "c2"


def test_testimonios_guardar_y_obtener():
    repo = RepositorioTestimoniosPostgres(_engine())
    testimonio = Testimonio.nuevo(1, "Juan", "Muy recomendable", 5, titulo="Genial")

    repo.guardar(testimonio)
    obtenido = repo.obtener(testimonio.id)

    assert obtenido.nombre == "Juan"
    assert obtenido.valoracion == 5
    assert repo.obtener(999999) is None


def test_testimonios_listar():
    repo = RepositorioTestimoniosPostgres(_engine())
    t1 = Testimonio.nuevo(1, "Juan", "Muy recomendable", 5, titulo="Genial")
    t2 = Testimonio.nuevo(2, "Ana", "Correcto", 4, titulo="Bien")
    repo.guardar(t1)
    repo.guardar(t2)

    assert {t.id for t in repo.listar()} == {t1.id, t2.id}


def test_testimonios_eliminar():
    engine = _engine()
    repo = RepositorioTestimoniosPostgres(engine)
    testimonio = Testimonio.nuevo(1, "Juan", "Muy recomendable", 5, titulo="Genial")
    repo.guardar(testimonio)

    repo.eliminar(testimonio.id)

    assert repo.obtener(testimonio.id) is None
    repo.eliminar(testimonio.id)  # repetirlo sobre uno ya borrado no lanza


def test_testimonios_borrar_todo():
    repo = RepositorioTestimoniosPostgres(_engine())
    repo.guardar(Testimonio.nuevo(1, "Juan", "Muy recomendable", 5, titulo="Genial"))
    repo.guardar(Testimonio.nuevo(2, "Ana", "Correcto", 4, titulo="Bien"))

    assert repo.borrar_todo() == 2
    assert repo.listar() == []


def test_promo_bar_obtener_devuelve_none_si_no_existe():
    repo = RepositorioPromoBarPostgres(_engine())
    assert repo.obtener(999) is None


def test_promo_bar_guardar_y_obtener():
    repo = RepositorioPromoBarPostgres(_engine())

    repo.guardar(PromoBar(id=1, nombre="Lanzamiento", activo=True, contenido_html="<p>2x1</p>"))
    leido = repo.obtener(1)

    assert leido.nombre == "Lanzamiento"
    assert leido.activo is True
    assert leido.contenido_html == "<p>2x1</p>"


def test_promo_bar_listar_y_eliminar():
    repo = RepositorioPromoBarPostgres(_engine())
    repo.guardar(PromoBar(id=1, nombre="Uno"))
    repo.guardar(PromoBar(id=2, nombre="Dos"))

    assert {p.id for p in repo.listar()} == {1, 2}

    repo.eliminar(1)

    assert {p.id for p in repo.listar()} == {2}
    repo.eliminar(1)  # repetirlo sobre uno ya borrado no lanza


def test_promo_bar_obtener_activo():
    repo = RepositorioPromoBarPostgres(_engine())
    assert repo.obtener_activo() is None

    repo.guardar(PromoBar(id=1, nombre="Uno", activo=False))
    repo.guardar(PromoBar(id=2, nombre="Dos", activo=True))

    assert repo.obtener_activo().id == 2


def test_promo_bar_activar_desactiva_el_anterior():
    repo = RepositorioPromoBarPostgres(_engine())
    repo.guardar(PromoBar(id=1, nombre="Uno", activo=True))
    repo.guardar(PromoBar(id=2, nombre="Dos", activo=False))

    repo.activar(2)

    assert repo.obtener(1).activo is False
    assert repo.obtener(2).activo is True


def test_contadores_empieza_en_uno_e_incrementa():
    repo = RepositorioContadoresPostgres(_engine())

    assert repo.siguiente_valor("testimonio") == 1
    assert repo.siguiente_valor("testimonio") == 2
    assert repo.siguiente_valor("testimonio") == 3


def test_contadores_es_independiente_por_tipo_entidad():
    repo = RepositorioContadoresPostgres(_engine())

    assert repo.siguiente_valor("testimonio") == 1
    assert repo.siguiente_valor("cliente") == 1
    assert repo.siguiente_valor("testimonio") == 2


def test_contadores_listar_no_incrementa():
    repo = RepositorioContadoresPostgres(_engine())
    repo.siguiente_valor("testimonio")
    repo.siguiente_valor("testimonio")
    repo.siguiente_valor("cliente")

    assert repo.listar() == {"testimonio": 2, "cliente": 1}
    assert repo.listar() == {"testimonio": 2, "cliente": 1}  # llamarlo dos veces no cambia nada


def test_contadores_listar_vacio_por_defecto():
    assert RepositorioContadoresPostgres(_engine()).listar() == {}


def test_contadores_borrar_todo():
    repo = RepositorioContadoresPostgres(_engine())
    repo.siguiente_valor("testimonio")
    repo.siguiente_valor("cliente")

    assert repo.borrar_todo() == 2
    assert repo.siguiente_valor("testimonio") == 1


# No hay test de concurrencia real aquí (a diferencia de
# RepositorioContadoresMemoria en test_repositorios_memoria.py):
# probado con un motor SQLite en memoria compartido entre hilos
# (StaticPool + check_same_thread=False), varias llamadas concurrentes
# a siguiente_valor() fallaban con NoResultFound — un artefacto del
# propio modelo de concurrencia de SQLite (una única conexión de
# verdad reutilizada por todos los hilos), no de la lógica del
# adaptador. La garantía real que pide el issue (unicidad entre
# procesos) depende del bloqueo de fila de Postgres sobre la sentencia
# atómica INSERT ... ON CONFLICT ... RETURNING, que SQLite no puede
# reproducir de forma fiel — de ahí que este repo, a diferencia del
# resto de RepositorioXPostgres de este fichero, no tenga forma barata
# de comprobar su promesa central sin un Postgres real (fuera del
# alcance de esta suite, ver la cabecera del fichero).
