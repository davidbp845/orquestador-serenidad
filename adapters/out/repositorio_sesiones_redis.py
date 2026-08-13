"""Implementación de RepositorioSesiones sobre Redis: persiste el
historial de conversación como JSON, para que sobreviva a un reinicio
del proceso y se comparta entre varios workers/procesos. Alternativa
a RepositorioSesionesMemoria, seleccionada en main.py cuando hay
REDIS_URL configurada."""
from __future__ import annotations

import json

from redis import Redis

from application.orchestrator import SesionConversacion
from application.ports import RepositorioSesiones


class RepositorioSesionesRedis(RepositorioSesiones):
    def __init__(self, redis_url: str, cliente: Redis | None = None):
        self._cliente = cliente or Redis.from_url(redis_url, decode_responses=True)

    def obtener(self, canal: str, usuario_id: str) -> SesionConversacion | None:
        bruto = self._cliente.get(self._clave(canal, usuario_id))
        if bruto is None:
            return None
        datos = json.loads(bruto)
        # .get() con default, no indexado directo: una sesión guardada
        # con una versión anterior del código (un campo de
        # SesionConversacion menos) no debe romper el chat con un
        # KeyError — solo pierde ese campo concreto, igual que si nunca
        # se hubiera rellenado.
        return SesionConversacion(
            canal=canal, usuario_id=usuario_id,
            historial=datos.get("historial", []),
            cliente_id_conocido=datos.get("cliente_id_conocido"),
        )

    def guardar(self, sesion: SesionConversacion) -> None:
        # cliente_id_conocido (#77) también tiene que sobrevivir entre
        # peticiones: antes solo se serializaba historial, así que se
        # perdía en cuanto la sesión daba una vuelta por Redis (el
        # siguiente obtener() la reconstruía sin ese campo) —
        # silenciosamente, sin error, con REDIS_URL configurada.
        self._cliente.set(
            self._clave(sesion.canal, sesion.usuario_id),
            json.dumps({
                "historial": sesion.historial,
                "cliente_id_conocido": sesion.cliente_id_conocido,
            }),
        )

    @staticmethod
    def _clave(canal: str, usuario_id: str) -> str:
        return f"sesion:{canal}:{usuario_id}"
