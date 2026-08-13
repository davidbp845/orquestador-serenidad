"""Adaptador de NotificadorMensajes contra SMS (Twilio).

Cliente inyectable (`cliente: Client | None = None`) para poder
testear sin red real — mismo patrón que `RepositorioSesionesRedis`."""
from __future__ import annotations

from twilio.rest import Client

from domain.ports import NotificadorMensajes


class NotificadorMensajesSMS(NotificadorMensajes):
    def __init__(
        self, account_sid: str, auth_token: str, numero_remitente: str,
        cliente: Client | None = None,
    ):
        self._cliente = cliente or Client(account_sid, auth_token)
        self._numero_remitente = numero_remitente

    def enviar(self, destinatario_id: str, texto: str) -> None:
        self._cliente.messages.create(
            body=texto, from_=self._numero_remitente, to=destinatario_id
        )
