from datetime import date, datetime
from unittest.mock import Mock

from application.orchestrator import SesionConversacion
from application.tools import TOOLS_SCHEMA, EjecutorHerramientas
from domain.entities import Cita, EstadoCita, EstadoPedido, LineaPedido, NotaCliente, Pedido, SlotDisponible


def test_tools_schema_declara_las_cinco_herramientas():
    nombres = {t["name"] for t in TOOLS_SCHEMA}
    assert nombres == {
        "comprobar_disponibilidad",
        "crear_reserva",
        "registrar_pedido",
        "consultar_conocimiento_negocio",
        "guardar_nota_cliente",
    }
    for tool in TOOLS_SCHEMA:
        assert "description" in tool
        assert tool["input_schema"]["type"] == "object"


def test_comprobar_disponibilidad_serializa_slots():
    slot = SlotDisponible(
        profesional_id="ana",
        inicio=datetime(2026, 8, 3, 9, 0),
        fin=datetime(2026, 8, 3, 10, 0),
    )
    caso = Mock()
    caso.ejecutar.return_value = [slot]
    ejecutor = EjecutorHerramientas({"comprobar_disponibilidad": caso})

    resultado = ejecutor.ejecutar(
        "comprobar_disponibilidad",
        {"servicio_id": "masaje", "fecha": "2026-08-03", "profesional_id": "ana"},
    )

    caso.ejecutar.assert_called_once_with(
        servicio_id="masaje", dia=date(2026, 8, 3), profesional_id="ana"
    )
    assert resultado == {
        "slots": [{
            "profesional_id": "ana",
            "inicio": "2026-08-03T09:00:00",
            "fin": "2026-08-03T10:00:00",
        }]
    }


def test_comprobar_disponibilidad_sin_profesional_id():
    caso = Mock()
    caso.ejecutar.return_value = []
    ejecutor = EjecutorHerramientas({"comprobar_disponibilidad": caso})

    ejecutor.ejecutar("comprobar_disponibilidad", {"servicio_id": "masaje", "fecha": "2026-08-03"})

    caso.ejecutar.assert_called_once_with(
        servicio_id="masaje", dia=date(2026, 8, 3), profesional_id=None
    )


def test_crear_reserva_devuelve_cita_id_cliente_id_y_estado():
    cita = Cita.nueva(1, "masaje", "ana", "cliente1", datetime(2026, 8, 3, 9, 0), datetime(2026, 8, 3, 10, 0))
    caso = Mock()
    caso.ejecutar.return_value = cita
    ejecutor = EjecutorHerramientas({"crear_reserva": caso})

    resultado = ejecutor.ejecutar("crear_reserva", {
        "servicio_id": "masaje",
        "profesional_id": "ana",
        "nombre": "Juan",
        "telefono": "600111222",
        "inicio": "2026-08-03T09:00:00",
    })

    caso.ejecutar.assert_called_once_with(
        servicio_id="masaje", profesional_id="ana", nombre="Juan", telefono="600111222",
        inicio=datetime(2026, 8, 3, 9, 0),
    )
    assert resultado == {
        "cita_id": cita.id_visible, "cliente_id": cita.cliente_id, "estado": EstadoCita.PENDIENTE.value,
    }


def test_crear_reserva_por_telegram_pasa_telegram_chat_id():
    cita = Cita.nueva(1, "masaje", "ana", "cliente1", datetime(2026, 8, 3, 9, 0), datetime(2026, 8, 3, 10, 0))
    caso = Mock()
    caso.ejecutar.return_value = cita
    ejecutor = EjecutorHerramientas({"crear_reserva": caso})

    ejecutor.ejecutar(
        "crear_reserva",
        {
            "servicio_id": "masaje",
            "profesional_id": "ana",
            "nombre": "Juan",
            "telefono": "600111222",
            "inicio": "2026-08-03T09:00:00",
        },
        canal="telegram",
        usuario_id="chat123",
    )

    caso.ejecutar.assert_called_once_with(
        servicio_id="masaje", profesional_id="ana", nombre="Juan", telefono="600111222",
        inicio=datetime(2026, 8, 3, 9, 0), telegram_chat_id="chat123",
    )


def test_crear_reserva_por_web_no_pasa_telegram_chat_id():
    cita = Cita.nueva(1, "masaje", "ana", "cliente1", datetime(2026, 8, 3, 9, 0), datetime(2026, 8, 3, 10, 0))
    caso = Mock()
    caso.ejecutar.return_value = cita
    ejecutor = EjecutorHerramientas({"crear_reserva": caso})

    ejecutor.ejecutar(
        "crear_reserva",
        {
            "servicio_id": "masaje",
            "profesional_id": "ana",
            "nombre": "Juan",
            "telefono": "600111222",
            "inicio": "2026-08-03T09:00:00",
        },
        canal="web",
        usuario_id="u1",
    )

    caso.ejecutar.assert_called_once_with(
        servicio_id="masaje", profesional_id="ana", nombre="Juan", telefono="600111222",
        inicio=datetime(2026, 8, 3, 9, 0),
    )


def test_registrar_pedido_construye_lineas_pedido():
    pedido = Pedido.nuevo("cliente1", [LineaPedido(servicio_id="masaje", cantidad=1)])
    caso = Mock()
    caso.ejecutar.return_value = pedido
    ejecutor = EjecutorHerramientas({"registrar_pedido": caso})

    resultado = ejecutor.ejecutar("registrar_pedido", {
        "cliente_id": "cliente1",
        "lineas": [{"servicio_id": "masaje", "cantidad": 2, "notas": "sin aceite"}],
    })

    args, kwargs = caso.ejecutar.call_args
    assert kwargs["cliente_id"] == "cliente1"
    assert kwargs["lineas"] == [LineaPedido(servicio_id="masaje", cantidad=2, notas="sin aceite")]
    assert resultado == {"pedido_id": str(pedido.id), "estado": EstadoPedido.RECIBIDO.value}


def test_registrar_pedido_notas_por_defecto():
    pedido = Pedido.nuevo("cliente1", [])
    caso = Mock()
    caso.ejecutar.return_value = pedido
    ejecutor = EjecutorHerramientas({"registrar_pedido": caso})

    ejecutor.ejecutar("registrar_pedido", {
        "cliente_id": "cliente1",
        "lineas": [{"servicio_id": "masaje", "cantidad": 1}],
    })

    _, kwargs = caso.ejecutar.call_args
    assert kwargs["lineas"][0].notas == ""


def test_guardar_nota_cliente_con_cliente_id_escribe_directamente():
    nota = NotaCliente.nueva(1, "cliente1", "Alérgica al aceite de almendras")
    caso = Mock()
    caso.ejecutar.return_value = nota
    ejecutor = EjecutorHerramientas({"anadir_nota_cliente": caso})

    resultado = ejecutor.ejecutar(
        "guardar_nota_cliente", {"texto": "Alérgica al aceite de almendras", "cliente_id": "cliente1"},
    )

    caso.ejecutar.assert_called_once_with(cliente_id="cliente1", texto="Alérgica al aceite de almendras")
    assert resultado == {"nota_id": nota.id, "cliente_id": nota.cliente_id}


def test_guardar_nota_cliente_sin_cliente_id_con_nombre_y_telefono_identifica_al_cliente():
    nota = NotaCliente.nueva(1, "cliente1", "prefiere profesional Ana")
    caso = Mock()
    caso.ejecutar_identificando.return_value = nota
    ejecutor = EjecutorHerramientas({"anadir_nota_cliente": caso})
    sesion = SesionConversacion(canal="web", usuario_id="u1")

    resultado = ejecutor.ejecutar(
        "guardar_nota_cliente",
        {"texto": "prefiere profesional Ana", "nombre": "Juan", "telefono": "600111222"},
        sesion=sesion,
    )

    caso.ejecutar_identificando.assert_called_once_with(
        nombre="Juan", telefono="600111222", texto="prefiere profesional Ana",
    )
    assert sesion.cliente_id_conocido == "cliente1"
    assert resultado == {"nota_id": nota.id, "cliente_id": nota.cliente_id}


def test_guardar_nota_cliente_sin_identificacion_devuelve_error():
    # Igual que crear_reserva: sin cliente_id ni nombre+telefono, no hay
    # forma de saber a quién pertenece la nota — se pide identificación
    # en vez de guardarla a ciegas o diferirla silenciosamente.
    caso = Mock()
    ejecutor = EjecutorHerramientas({"anadir_nota_cliente": caso})

    resultado = ejecutor.ejecutar("guardar_nota_cliente", {"texto": "algo"})

    caso.ejecutar.assert_not_called()
    caso.ejecutar_identificando.assert_not_called()
    assert "error" in resultado


def test_guardar_nota_cliente_con_solo_nombre_sin_telefono_devuelve_error():
    caso = Mock()
    ejecutor = EjecutorHerramientas({"anadir_nota_cliente": caso})

    resultado = ejecutor.ejecutar("guardar_nota_cliente", {"texto": "algo", "nombre": "Juan"})

    caso.ejecutar_identificando.assert_not_called()
    assert "error" in resultado


def test_guardar_nota_cliente_sin_cliente_id_reutiliza_el_de_una_reserva_anterior():
    # Caso real reportado en #77: la reserva se hizo antes en la misma
    # conversación y luego el cliente comenta algo (una alergia) — si el
    # LLM omite cliente_id en guardar_nota_cliente (siguiendo al pie de
    # la letra la instrucción de omitirlo "si todavía no lo conoce"), se
    # reutiliza el cliente_id_conocido de la sesión en vez de exigir
    # nombre+telefono otra vez.
    nota = NotaCliente.nueva(1, "cliente1", "Alérgica al aceite de almendras dulces")
    caso = Mock()
    caso.ejecutar.return_value = nota
    ejecutor = EjecutorHerramientas({"anadir_nota_cliente": caso})
    sesion = SesionConversacion(canal="web", usuario_id="u1", cliente_id_conocido="cliente1")

    resultado = ejecutor.ejecutar(
        "guardar_nota_cliente", {"texto": "Alérgica al aceite de almendras dulces"}, sesion=sesion,
    )

    caso.ejecutar.assert_called_once_with(cliente_id="cliente1", texto="Alérgica al aceite de almendras dulces")
    assert resultado == {"nota_id": nota.id, "cliente_id": nota.cliente_id}


def test_guardar_nota_cliente_cliente_id_explicito_gana_al_conocido_de_la_sesion():
    nota = NotaCliente.nueva(1, "cliente2", "texto")
    caso = Mock()
    caso.ejecutar.return_value = nota
    ejecutor = EjecutorHerramientas({"anadir_nota_cliente": caso})
    sesion = SesionConversacion(canal="web", usuario_id="u1", cliente_id_conocido="cliente1")

    ejecutor.ejecutar("guardar_nota_cliente", {"texto": "texto", "cliente_id": "cliente2"}, sesion=sesion)

    caso.ejecutar.assert_called_once_with(cliente_id="cliente2", texto="texto")


def test_crear_reserva_deja_el_cliente_id_conocido_en_la_sesion():
    cita = Cita.nueva(1, "masaje", "ana", "cliente1", datetime(2026, 8, 3, 9, 0), datetime(2026, 8, 3, 10, 0))
    caso_reserva = Mock()
    caso_reserva.ejecutar.return_value = cita
    ejecutor = EjecutorHerramientas({"crear_reserva": caso_reserva})
    sesion = SesionConversacion(canal="web", usuario_id="u1")

    ejecutor.ejecutar(
        "crear_reserva",
        {
            "servicio_id": "masaje", "profesional_id": "ana", "nombre": "Juan",
            "telefono": "600111222", "inicio": "2026-08-03T09:00:00",
        },
        sesion=sesion,
    )

    assert sesion.cliente_id_conocido == "cliente1"


def test_consultar_conocimiento_negocio():
    caso = Mock()
    caso.ejecutar.return_value = {"fragmentos": ["fragmento 1"], "fuentes": []}
    ejecutor = EjecutorHerramientas({"consultar_conocimiento": caso})

    resultado = ejecutor.ejecutar("consultar_conocimiento_negocio", {"consulta": "precios"})

    caso.ejecutar.assert_called_once_with("precios")
    assert resultado == {"fragmentos": ["fragmento 1"], "fuentes": []}


def test_herramienta_desconocida():
    ejecutor = EjecutorHerramientas({})
    resultado = ejecutor.ejecutar("no_existe", {})
    assert resultado == {"error": "Herramienta desconocida: no_existe"}


def test_excepcion_del_caso_de_uso_se_traduce_a_error():
    caso = Mock()
    caso.ejecutar.side_effect = ValueError("boom")
    ejecutor = EjecutorHerramientas({"consultar_conocimiento": caso})

    resultado = ejecutor.ejecutar("consultar_conocimiento_negocio", {"consulta": "x"})

    assert resultado == {"error": "boom"}
