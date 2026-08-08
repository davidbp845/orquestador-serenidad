from datetime import date
from unittest.mock import patch

from application.orchestrator import OrquestadorAgente, SesionConversacion
from domain.ports import ProveedorLLM


def _bloque_texto(texto):
    return {"type": "text", "text": texto}


def _bloque_tool_use(id_, name, input_):
    return {"type": "tool_use", "id": id_, "name": name, "input": input_}


class FakeLLM(ProveedorLLM):
    """Devuelve, en orden, las respuestas indicadas al construirlo."""

    def __init__(self, respuestas):
        self._respuestas = list(respuestas)
        self.llamadas = []

    def generar_respuesta(self, mensajes, herramientas=None, system=None):
        self.llamadas.append({"mensajes": list(mensajes), "herramientas": herramientas, "system": system})
        return self._respuestas.pop(0)

    def generar_respuesta_stream(self, mensajes, herramientas=None, system=None):
        self.llamadas.append({"mensajes": list(mensajes), "herramientas": herramientas, "system": system})
        respuesta = self._respuestas.pop(0)
        for bloque in respuesta["content"]:
            if bloque["type"] == "text":
                yield {"tipo": "delta_texto", "texto": bloque["text"]}
        yield {"tipo": "final", "content": respuesta["content"]}


class FakeEjecutor:
    def __init__(self, resultado=None):
        self.resultado = resultado if resultado is not None else {"ok": True}
        self.llamadas = []
        self.canal_recibido = None
        self.usuario_id_recibido = None

    def ejecutar(self, nombre_tool, entrada, canal=None, usuario_id=None):
        self.llamadas.append((nombre_tool, entrada))
        self.canal_recibido = canal
        self.usuario_id_recibido = usuario_id
        return self.resultado


def test_responde_directamente_con_texto_si_no_hay_tool_use():
    llm = FakeLLM([{"content": [_bloque_texto("Hola, ¿en qué puedo ayudarte?")]}])
    orquestador = OrquestadorAgente(llm=llm, ejecutor_herramientas=FakeEjecutor(), system_prompt="system")
    sesion = SesionConversacion(canal="web", usuario_id="u1")

    respuesta = orquestador.responder(sesion, "hola")

    assert respuesta == "Hola, ¿en qué puedo ayudarte?"
    assert sesion.historial[0] == {"role": "user", "content": "hola"}
    assert llm.llamadas[0]["system"].startswith("system")
    assert "Hoy es" in llm.llamadas[0]["system"]


def test_incluye_la_fecha_de_hoy_en_el_system_prompt_y_se_recalcula_cada_turno():
    llm = FakeLLM([
        {"content": [_bloque_texto("Respuesta 1")]},
        {"content": [_bloque_texto("Respuesta 2")]},
    ])
    orquestador = OrquestadorAgente(llm=llm, ejecutor_herramientas=FakeEjecutor(), system_prompt="system")
    sesion = SesionConversacion(canal="web", usuario_id="u1")

    with patch("application.orchestrator.date") as mock_date:
        mock_date.today.return_value = date(2026, 8, 7)
        orquestador.responder(sesion, "primer mensaje")

    with patch("application.orchestrator.date") as mock_date:
        mock_date.today.return_value = date(2026, 8, 10)
        orquestador.responder(sesion, "segundo mensaje")

    assert "Hoy es viernes 7 de agosto de 2026." in llm.llamadas[0]["system"]
    assert "Hoy es lunes 10 de agosto de 2026." in llm.llamadas[1]["system"]


def test_ejecuta_tool_y_responde_con_el_siguiente_texto():
    llm = FakeLLM([
        {"content": [_bloque_tool_use("call1", "consultar_conocimiento_negocio", {"consulta": "precios"})]},
        {"content": [_bloque_texto("El masaje cuesta 55€.")]},
    ])
    ejecutor = FakeEjecutor(resultado={"fragmentos": ["55€"]})
    orquestador = OrquestadorAgente(llm=llm, ejecutor_herramientas=ejecutor, system_prompt="system")
    sesion = SesionConversacion(canal="web", usuario_id="u1")

    respuesta = orquestador.responder(sesion, "¿cuánto cuesta el masaje?")

    assert respuesta == "El masaje cuesta 55€."
    assert ejecutor.llamadas == [("consultar_conocimiento_negocio", {"consulta": "precios"})]

    mensajes_tool_result = sesion.historial[2]["content"]
    assert mensajes_tool_result[0]["type"] == "tool_result"
    assert mensajes_tool_result[0]["tool_use_id"] == "call1"
    assert "55" in mensajes_tool_result[0]["content"]


def test_pasa_canal_y_usuario_id_de_la_sesion_al_ejecutor():
    llm = FakeLLM([
        {"content": [_bloque_tool_use("call1", "crear_reserva", {})]},
        {"content": [_bloque_texto("Listo.")]},
    ])
    ejecutor = FakeEjecutor()
    orquestador = OrquestadorAgente(llm=llm, ejecutor_herramientas=ejecutor, system_prompt="system")
    sesion = SesionConversacion(canal="telegram", usuario_id="chat123")

    orquestador.responder(sesion, "resérvame un masaje")

    assert ejecutor.canal_recibido == "telegram"
    assert ejecutor.usuario_id_recibido == "chat123"


def test_concatena_varios_bloques_de_texto():
    llm = FakeLLM([{"content": [_bloque_texto("Primera parte."), _bloque_texto("Segunda parte.")]}])
    orquestador = OrquestadorAgente(llm=llm, ejecutor_herramientas=FakeEjecutor(), system_prompt="system")
    sesion = SesionConversacion(canal="web", usuario_id="u1")

    respuesta = orquestador.responder(sesion, "hola")

    assert respuesta == "Primera parte.\nSegunda parte."


def test_da_mensaje_de_fallback_tras_agotar_iteraciones():
    respuestas = [
        {"content": [_bloque_tool_use(f"call{i}", "comprobar_disponibilidad", {})]}
        for i in range(4)
    ]
    llm = FakeLLM(respuestas)
    orquestador = OrquestadorAgente(
        llm=llm, ejecutor_herramientas=FakeEjecutor(), system_prompt="system",
        max_iteraciones_tool=4,
    )
    sesion = SesionConversacion(canal="web", usuario_id="u1")

    respuesta = orquestador.responder(sesion, "resérvame algo")

    assert "no he podido completar" in respuesta
    assert len(llm.llamadas) == 4


def test_historial_se_mantiene_entre_llamadas_a_responder():
    llm = FakeLLM([
        {"content": [_bloque_texto("Respuesta 1")]},
        {"content": [_bloque_texto("Respuesta 2")]},
    ])
    orquestador = OrquestadorAgente(llm=llm, ejecutor_herramientas=FakeEjecutor(), system_prompt="system")
    sesion = SesionConversacion(canal="web", usuario_id="u1")

    orquestador.responder(sesion, "primer mensaje")
    orquestador.responder(sesion, "segundo mensaje")

    roles_y_contenido = [m["content"] for m in sesion.historial if m["role"] == "user"]
    assert roles_y_contenido[0] == "primer mensaje"
    assert roles_y_contenido[1] == "segundo mensaje"


def test_stream_responde_con_deltas_y_un_evento_done():
    llm = FakeLLM([{"content": [_bloque_texto("Hola, ¿en qué puedo ayudarte?")]}])
    orquestador = OrquestadorAgente(llm=llm, ejecutor_herramientas=FakeEjecutor(), system_prompt="system")
    sesion = SesionConversacion(canal="web", usuario_id="u1")

    eventos = list(orquestador.responder_stream(sesion, "hola"))

    assert eventos[0] == {"tipo": "delta", "texto": "Hola, ¿en qué puedo ayudarte?"}
    assert eventos[-1] == {
        "tipo": "done",
        "respuesta": "Hola, ¿en qué puedo ayudarte?",
        "fuentes": [],
    }


def test_stream_ejecuta_tool_y_acumula_fuentes_deduplicadas():
    llm = FakeLLM([
        {"content": [_bloque_tool_use("call1", "consultar_conocimiento_negocio", {"consulta": "precios"})]},
        {"content": [_bloque_texto("El masaje cuesta 55€.")]},
    ])
    resultado_tool = {
        "fragmentos": ["55€"],
        "fuentes": [
            {"fuente": "servicios.md", "categoria": "servicios"},
            {"fuente": "servicios.md", "categoria": "servicios"},
        ],
    }
    ejecutor = FakeEjecutor(resultado=resultado_tool)
    orquestador = OrquestadorAgente(llm=llm, ejecutor_herramientas=ejecutor, system_prompt="system")
    sesion = SesionConversacion(canal="web", usuario_id="u1")

    eventos = list(orquestador.responder_stream(sesion, "¿cuánto cuesta el masaje?"))

    evento_done = eventos[-1]
    assert evento_done["tipo"] == "done"
    assert evento_done["respuesta"] == "El masaje cuesta 55€."
    assert evento_done["fuentes"] == [{"fuente": "servicios.md", "categoria": "servicios"}]


def test_stream_pasa_canal_y_usuario_id_de_la_sesion_al_ejecutor():
    llm = FakeLLM([
        {"content": [_bloque_tool_use("call1", "crear_reserva", {})]},
        {"content": [_bloque_texto("Listo.")]},
    ])
    ejecutor = FakeEjecutor()
    orquestador = OrquestadorAgente(llm=llm, ejecutor_herramientas=ejecutor, system_prompt="system")
    sesion = SesionConversacion(canal="telegram", usuario_id="chat123")

    list(orquestador.responder_stream(sesion, "resérvame un masaje"))

    assert ejecutor.canal_recibido == "telegram"
    assert ejecutor.usuario_id_recibido == "chat123"


def test_stream_da_mensaje_de_fallback_tras_agotar_iteraciones():
    respuestas = [
        {"content": [_bloque_tool_use(f"call{i}", "comprobar_disponibilidad", {})]}
        for i in range(4)
    ]
    llm = FakeLLM(respuestas)
    orquestador = OrquestadorAgente(
        llm=llm, ejecutor_herramientas=FakeEjecutor(), system_prompt="system",
        max_iteraciones_tool=4,
    )
    sesion = SesionConversacion(canal="web", usuario_id="u1")

    eventos = list(orquestador.responder_stream(sesion, "resérvame algo"))

    evento_done = eventos[-1]
    assert evento_done["tipo"] == "done"
    assert "no he podido completar" in evento_done["respuesta"]
    assert len(llm.llamadas) == 4
