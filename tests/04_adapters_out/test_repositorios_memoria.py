import threading
from datetime import date, datetime

from adapters.out.repositorios_memoria import (
    RepositorioCitasMemoria,
    RepositorioClientesMemoria,
    RepositorioContadoresMemoria,
    RepositorioPedidosMemoria,
    RepositorioProfesionalesMemoria,
    RepositorioServiciosMemoria,
    RepositorioTestimoniosMemoria,
)
from domain.entities import (
    Cita,
    Cliente,
    EstadoCita,
    EstadoPedido,
    LineaPedido,
    Pedido,
    Profesional,
    Servicio,
    Testimonio,
)


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


def test_repositorio_citas_en_rango_incluye_los_limites_y_excluye_fuera_de_rango():
    repo = RepositorioCitasMemoria()
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


def test_repositorio_citas_en_rango_vacio_si_no_hay_citas_en_ese_rango():
    repo = RepositorioCitasMemoria()
    repo.guardar(Cita.nueva("s1", "ana", "c1", datetime(2026, 8, 1, 9, 0), datetime(2026, 8, 1, 10, 0)))

    assert repo.citas_en_rango(date(2026, 8, 10), date(2026, 8, 20)) == []


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


def test_repositorio_clientes_listar():
    repo = RepositorioClientesMemoria()
    assert repo.listar() == []

    cliente1 = Cliente(id="c1", nombre="Juan", telefono="600111222")
    cliente2 = Cliente(id="c2", nombre="Ana", telefono="600333444")
    repo.guardar(cliente1)
    repo.guardar(cliente2)

    assert {c.id for c in repo.listar()} == {"c1", "c2"}


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


def test_repositorio_citas_borrar_todo():
    repo = RepositorioCitasMemoria()
    repo.guardar(Cita.nueva("s1", "ana", "c1", datetime(2026, 8, 3, 9, 0), datetime(2026, 8, 3, 10, 0)))
    repo.guardar(Cita.nueva("s1", "ana", "c1", datetime(2026, 8, 4, 9, 0), datetime(2026, 8, 4, 10, 0)))

    assert repo.borrar_todo() == 2
    assert repo.citas_en_rango(date(2026, 1, 1), date(2026, 12, 31)) == []
    assert repo.borrar_todo() == 0


def test_repositorio_clientes_borrar_todo():
    repo = RepositorioClientesMemoria()
    repo.guardar(Cliente(id="c1", nombre="Juan"))
    repo.guardar(Cliente(id="c2", nombre="Ana"))

    assert repo.borrar_todo() == 2
    assert repo.listar() == []


def test_repositorio_pedidos_borrar_todo():
    repo = RepositorioPedidosMemoria()
    repo.guardar(Pedido.nuevo("c1", [LineaPedido(servicio_id="s1", cantidad=1)]))
    repo.guardar(Pedido.nuevo("c1", [LineaPedido(servicio_id="s2", cantidad=1)]))

    assert repo.borrar_todo() == 2
    assert repo.listar_pendientes() == []


def test_repositorio_testimonios_guardar_obtener_listar():
    repo = RepositorioTestimoniosMemoria()
    t1 = Testimonio.nuevo("Juan", "Genial", "Muy recomendable", 5)
    t2 = Testimonio.nuevo("Ana", "Bien", "Correcto", 4)
    repo.guardar(t1)
    repo.guardar(t2)

    assert repo.obtener(t1.id) is t1
    assert repo.obtener("no_existe") is None
    assert {t.id for t in repo.listar()} == {t1.id, t2.id}


def test_repositorio_testimonios_eliminar():
    repo = RepositorioTestimoniosMemoria()
    t1 = Testimonio.nuevo("Juan", "Genial", "Muy recomendable", 5)
    repo.guardar(t1)

    repo.eliminar(t1.id)

    assert repo.obtener(t1.id) is None
    repo.eliminar(t1.id)  # repetirlo sobre uno ya borrado no lanza


def test_repositorio_testimonios_borrar_todo():
    repo = RepositorioTestimoniosMemoria()
    repo.guardar(Testimonio.nuevo("Juan", "Genial", "Muy recomendable", 5))
    repo.guardar(Testimonio.nuevo("Ana", "Bien", "Correcto", 4))

    assert repo.borrar_todo() == 2
    assert repo.listar() == []


def test_repositorio_contadores_empieza_en_uno_e_incrementa():
    repo = RepositorioContadoresMemoria()

    assert repo.siguiente_valor("testimonio") == 1
    assert repo.siguiente_valor("testimonio") == 2
    assert repo.siguiente_valor("testimonio") == 3


def test_repositorio_contadores_es_independiente_por_tipo_entidad():
    repo = RepositorioContadoresMemoria()

    assert repo.siguiente_valor("testimonio") == 1
    assert repo.siguiente_valor("cliente") == 1
    assert repo.siguiente_valor("testimonio") == 2


def test_repositorio_contadores_borrar_todo():
    repo = RepositorioContadoresMemoria()
    repo.siguiente_valor("testimonio")
    repo.siguiente_valor("cliente")

    assert repo.borrar_todo() == 2
    assert repo.siguiente_valor("testimonio") == 1


def test_repositorio_contadores_es_imposible_repetir_valor_bajo_concurrencia():
    """La garantía real que pide el issue: N hilos pidiendo
    siguiente_valor("testimonio") a la vez nunca devuelven el mismo
    número — sin huecos ni repeticiones."""
    repo = RepositorioContadoresMemoria()
    n = 200
    resultados: list[int] = []
    lock_resultados = threading.Lock()

    def pedir_valor():
        valor = repo.siguiente_valor("testimonio")
        with lock_resultados:
            resultados.append(valor)

    hilos = [threading.Thread(target=pedir_valor) for _ in range(n)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()

    assert sorted(resultados) == list(range(1, n + 1))
