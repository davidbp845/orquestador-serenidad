"""Adaptador de NotificadorMensajes contra WhatsApp (Meta Cloud API).

Misma llamada a la Graph API que antes vivía embebida en
`adapters/in_/whatsapp_webhook.py` (`_enviar_mensaje`), extraída aquí
para poder usarse también como notificación proactiva (confirmación/
cancelación de reserva, código de verificación) y no solo como
respuesta dentro del propio ciclo del webhook (#86)."""
from __future__ import annotations

import httpx

from domain.ports import NotificadorMensajes

_GRAPH_API_VERSION = "v21.0"


class NotificadorMensajesWhatsApp(NotificadorMensajes):
    def __init__(self, access_token: str, phone_number_id: str):
        self._access_token = access_token
        self._phone_number_id = phone_number_id

    def enviar(self, destinatario_id: str, texto: str) -> None:
        url = f"https://graph.facebook.com/{_GRAPH_API_VERSION}/{self._phone_number_id}/messages"
        respuesta = httpx.post(
            url,
            headers={"Authorization": f"Bearer {self._access_token}"},
            json={
                "messaging_product": "whatsapp",
                "to": destinatario_id,
                "type": "text",
                "text": {"body": texto},
            },
            timeout=10,
        )
        respuesta.raise_for_status()
