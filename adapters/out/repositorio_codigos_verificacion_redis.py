"""Implementación de RepositorioCodigosVerificacion sobre Redis (#84):
TTL nativo vía SETEX, así una entrada nunca usada desaparece sola en
vez de acumularse para siempre (a diferencia de la alternativa en
memoria). Seleccionada en main.py cuando hay REDIS_URL configurada,
mismo patrón que RepositorioSesionesRedis."""
from __future__ import annotations

import json
from datetime import UTC, datetime

from redis import Redis

from domain.entities import CodigoVerificacion
from domain.ports import RepositorioCodigosVerificacion


class RepositorioCodigosVerificacionRedis(RepositorioCodigosVerificacion):
    def __init__(self, redis_url: str, cliente: Redis | None = None):
        self._cliente = cliente or Redis.from_url(redis_url, decode_responses=True)

    def guardar(self, codigo: CodigoVerificacion) -> None:
        ttl_segundos = max(1, int((codigo.expira_en - datetime.now(UTC)).total_seconds()))
        self._cliente.setex(
            self._clave(codigo.telefono),
            ttl_segundos,
            json.dumps({"codigo": codigo.codigo, "expira_en": codigo.expira_en.isoformat()}),
        )

    def obtener(self, telefono: str) -> CodigoVerificacion | None:
        bruto = self._cliente.get(self._clave(telefono))
        if bruto is None:
            return None
        datos = json.loads(bruto)
        return CodigoVerificacion(
            telefono=telefono,
            codigo=datos["codigo"],
            expira_en=datetime.fromisoformat(datos["expira_en"]),
        )

    def eliminar(self, telefono: str) -> None:
        self._cliente.delete(self._clave(telefono))

    @staticmethod
    def _clave(telefono: str) -> str:
        return f"codigo_verificacion:{telefono}"
