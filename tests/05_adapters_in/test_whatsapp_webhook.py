"""Igual que test_fastapi_app.py: se recarga adapters.in_.fastapi_app
en cada test para tener un `app` limpio (crear_router() añade rutas
sobre un `app` de módulo compartido), y luego se registran las rutas
de WhatsApp sobre ese mismo `app` con crear_router_whatsapp(). No hay
red real: el envío de la respuesta a la API de Meta se mockea."""
import hashlib
import hmac
import importlib
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from adapters.out.repositorio_sesiones_memoria import RepositorioSesionesMemoria

VERIFY_TOKEN = "verify-123"
ACCESS_TOKEN = "access-123"
PHONE_NUMBER_ID = "1234567890"
APP_SECRET = "shh-secreto"


class FakeOrquestador:
    def __init__(self, respuesta="Hola, ¿en qué puedo ayudarte?"):
        self.respuesta = respuesta
        self.llamadas = []

    def responder(self, sesion, mensaje):
        self.llamadas.append((sesion.usuario_id, mensaje))
        return self.respuesta


def _firmar(cuerpo: bytes, secreto: str = APP_SECRET) -> str:
    return "sha256=" + hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()


def _payload_mensaje(numero: str, texto: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "entry1",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "messages": [{
                        "from": numero,
                        "id": "wamid.1",
                        "timestamp": "1700000000",
                        "type": "text",
                        "text": {"body": texto},
                    }],
                },
            }],
        }],
    }


@pytest.fixture
def modulo():
    import adapters.in_.fastapi_app as fastapi_app
    importlib.reload(fastapi_app)
    return fastapi_app


@pytest.fixture
def contexto(modulo):
    from adapters.in_.whatsapp_webhook import crear_router_whatsapp

    orquestador = FakeOrquestador()
    repositorio_sesiones = RepositorioSesionesMemoria()
    app = modulo.crear_router(orquestador, repositorio_sesiones)
    crear_router_whatsapp(
        app, orquestador, repositorio_sesiones,
        VERIFY_TOKEN, ACCESS_TOKEN, PHONE_NUMBER_ID, APP_SECRET,
    )
    return TestClient(app), orquestador, repositorio_sesiones


def test_handshake_verificacion_correcto_devuelve_el_challenge(contexto):
    client, _, _ = contexto
    respuesta = client.get("/webhook/whatsapp", params={
        "hub.mode": "subscribe",
        "hub.verify_token": VERIFY_TOKEN,
        "hub.challenge": "reto123",
    })
    assert respuesta.status_code == 200
    assert respuesta.text == "reto123"


def test_handshake_verificacion_con_token_incorrecto_devuelve_403(contexto):
    client, _, _ = contexto
    respuesta = client.get("/webhook/whatsapp", params={
        "hub.mode": "subscribe",
        "hub.verify_token": "token-erroneo",
        "hub.challenge": "reto123",
    })
    assert respuesta.status_code == 403


def test_mensaje_de_texto_llama_al_orquestador_y_envia_la_respuesta(contexto):
    client, orquestador, repositorio_sesiones = contexto
    orquestador.respuesta = "¡Hola! ¿En qué te ayudo?"
    cuerpo = json.dumps(_payload_mensaje("34600111222", "hola")).encode()

    with patch("adapters.in_.whatsapp_webhook.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        respuesta = client.post(
            "/webhook/whatsapp",
            content=cuerpo,
            headers={
                "content-type": "application/json",
                "x-hub-signature-256": _firmar(cuerpo),
            },
        )

    assert respuesta.status_code == 200
    assert orquestador.llamadas == [("34600111222", "hola")]
    assert repositorio_sesiones.obtener("whatsapp", "34600111222") is not None

    mock_post.assert_called_once()
    url_llamada, kwargs = mock_post.call_args[0][0], mock_post.call_args[1]
    assert PHONE_NUMBER_ID in url_llamada
    assert kwargs["headers"]["Authorization"] == f"Bearer {ACCESS_TOKEN}"
    assert kwargs["json"]["to"] == "34600111222"
    assert kwargs["json"]["text"]["body"] == "¡Hola! ¿En qué te ayudo?"


def test_mensaje_con_firma_invalida_se_rechaza_y_no_llama_al_orquestador(contexto):
    client, orquestador, _ = contexto
    cuerpo = json.dumps(_payload_mensaje("34600111222", "hola")).encode()

    respuesta = client.post(
        "/webhook/whatsapp",
        content=cuerpo,
        headers={
            "content-type": "application/json",
            "x-hub-signature-256": "sha256=firmaquenocuadra",
        },
    )

    assert respuesta.status_code == 403
    assert orquestador.llamadas == []


def test_mensaje_sin_cabecera_de_firma_se_rechaza(contexto):
    client, orquestador, _ = contexto
    cuerpo = json.dumps(_payload_mensaje("34600111222", "hola")).encode()

    respuesta = client.post("/webhook/whatsapp", content=cuerpo, headers={"content-type": "application/json"})

    assert respuesta.status_code == 403
    assert orquestador.llamadas == []


def test_mensaje_de_tipo_no_soportado_se_ignora_sin_error(contexto):
    client, orquestador, _ = contexto
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "entry1",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "messages": [{
                        "from": "34600111222",
                        "id": "wamid.2",
                        "timestamp": "1700000000",
                        "type": "image",
                        "image": {"id": "media123"},
                    }],
                },
            }],
        }],
    }
    cuerpo = json.dumps(payload).encode()

    respuesta = client.post(
        "/webhook/whatsapp",
        content=cuerpo,
        headers={"content-type": "application/json", "x-hub-signature-256": _firmar(cuerpo)},
    )

    assert respuesta.status_code == 200
    assert orquestador.llamadas == []


def test_notificacion_de_estado_sin_mensajes_se_ignora_sin_error(contexto):
    client, orquestador, _ = contexto
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "entry1",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "statuses": [{"id": "wamid.1", "status": "delivered"}],
                },
            }],
        }],
    }
    cuerpo = json.dumps(payload).encode()

    respuesta = client.post(
        "/webhook/whatsapp",
        content=cuerpo,
        headers={"content-type": "application/json", "x-hub-signature-256": _firmar(cuerpo)},
    )

    assert respuesta.status_code == 200
    assert orquestador.llamadas == []


def test_reutiliza_la_sesion_del_mismo_numero(contexto):
    client, orquestador, repositorio_sesiones = contexto

    for texto in ("primero", "segundo"):
        cuerpo = json.dumps(_payload_mensaje("34600111222", texto)).encode()
        with patch("adapters.in_.whatsapp_webhook.httpx.post"):
            client.post(
                "/webhook/whatsapp",
                content=cuerpo,
                headers={"content-type": "application/json", "x-hub-signature-256": _firmar(cuerpo)},
            )

    sesion = repositorio_sesiones.obtener("whatsapp", "34600111222")
    assert sesion is not None
    assert sesion.canal == "whatsapp"
    assert [m for _, m in orquestador.llamadas] == ["primero", "segundo"]


def test_fallo_de_red_al_enviar_no_rompe_el_webhook(contexto):
    client, orquestador, _ = contexto
    import httpx as httpx_module

    cuerpo = json.dumps(_payload_mensaje("34600111222", "hola")).encode()

    with patch("adapters.in_.whatsapp_webhook.httpx.post", side_effect=httpx_module.ConnectError("caído")):
        respuesta = client.post(
            "/webhook/whatsapp",
            content=cuerpo,
            headers={"content-type": "application/json", "x-hub-signature-256": _firmar(cuerpo)},
        )

    assert respuesta.status_code == 200
    assert orquestador.llamadas == [("34600111222", "hola")]
