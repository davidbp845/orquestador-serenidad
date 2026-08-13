"""
Adaptador de entrada: webhook de WhatsApp (Meta Cloud API). Igual que
fastapi_app.py/telegram_bot.py, solo traduce WhatsApp <-> orquestador,
sin lógica de negocio propia.

A diferencia de Telegram (polling: el proceso local pregunta a
Telegram si hay mensajes nuevos), WhatsApp funciona por webhook: Meta
llama a esta URL cuando llega un mensaje, así que hace falta una URL
pública (túnel en desarrollo, dominio real en producción) apuntando al
mismo puerto/app que ya sirve /chat — por eso las rutas se registran
sobre el `app` de FastAPI que main.py ya construye con crear_router(),
en vez de levantar un servidor aparte.

Dos rutas, ambas parte del protocolo de Meta:
- GET  /webhook/whatsapp: handshake de verificación al suscribir el
  webhook en el panel de Meta (hub.mode/hub.verify_token/hub.challenge).
- POST /webhook/whatsapp: mensajes entrantes. Cada mensaje de texto se
  responde llamando a OrquestadorAgente.responder() y enviando la
  respuesta de vuelta con el mismo NotificadorMensajesWhatsApp (#86)
  que el resto del sistema usa para notificar de forma proactiva (Meta
  no acepta la respuesta como el propio cuerpo del webhook, hay que
  hacer una llamada HTTP aparte).
"""
from __future__ import annotations

import hashlib
import hmac
import logging

import httpx
from fastapi import FastAPI, Request, Response

from adapters.out.notificador_whatsapp import NotificadorMensajesWhatsApp
from application.orchestrator import OrquestadorAgente, SesionConversacion
from application.ports import RepositorioSesiones

logger = logging.getLogger(__name__)


def crear_router_whatsapp(
    app: FastAPI,
    orquestador: OrquestadorAgente,
    repositorio_sesiones: RepositorioSesiones,
    verify_token: str,
    notificador: NotificadorMensajesWhatsApp,
    app_secret: str,
) -> FastAPI:
    @app.get("/webhook/whatsapp")
    def verificar(request: Request):
        if (
            request.query_params.get("hub.mode") == "subscribe"
            and request.query_params.get("hub.verify_token") == verify_token
        ):
            return Response(
                content=request.query_params.get("hub.challenge", ""),
                media_type="text/plain",
            )
        return Response(status_code=403)

    @app.post("/webhook/whatsapp")
    async def recibir(request: Request):
        cuerpo = await request.body()
        if not _firma_valida(cuerpo, request.headers.get("x-hub-signature-256"), app_secret):
            return Response(status_code=403)

        payload = await request.json()
        for entrada in payload.get("entry", []):
            for cambio in entrada.get("changes", []):
                for mensaje in cambio.get("value", {}).get("messages", []):
                    _procesar_mensaje(mensaje, orquestador, repositorio_sesiones, notificador)
        # Meta reintenta el webhook si no recibe 200 — hay que devolverlo
        # aunque el mensaje no fuera de un tipo soportado (ver más abajo).
        return {"status": "ok"}

    return app


def _procesar_mensaje(
    mensaje: dict,
    orquestador: OrquestadorAgente,
    repositorio_sesiones: RepositorioSesiones,
    notificador: NotificadorMensajesWhatsApp,
) -> None:
    # Fuera de alcance de #17: solo texto plano (botones interactivos,
    # imágenes, ubicaciones... quedan fuera, ver "Fuera de alcance").
    if mensaje.get("type") != "text":
        return

    numero = mensaje["from"]
    texto = mensaje["text"]["body"]

    sesion = repositorio_sesiones.obtener("whatsapp", numero) or SesionConversacion(
        canal="whatsapp", usuario_id=numero
    )
    respuesta = orquestador.responder(sesion, texto)
    repositorio_sesiones.guardar(sesion)
    try:
        notificador.enviar(numero, respuesta)
    except httpx.HTTPError as exc:
        # Igual que EjecutorHerramientas: un fallo de red/API no debe
        # tumbar el manejo del webhook, solo queda registrado.
        logger.warning("Fallo al enviar respuesta de WhatsApp a %s: %s", numero, exc)


def _firma_valida(cuerpo: bytes, firma_recibida: str | None, app_secret: str) -> bool:
    if not firma_recibida or not firma_recibida.startswith("sha256="):
        return False
    esperada = hmac.new(app_secret.encode(), cuerpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={esperada}", firma_recibida)
