"""
Limitador de peticiones para /chat y /chat/stream (#49): evita que un
único usuario_id agote la cuota del proveedor de LLM configurado. No
es un puerto de domain/application — es un detalle puramente de este
adaptador HTTP, ningún caso de uso necesita saber que existe.

Ventana fija (no sliding window): simple y suficiente para frenar
abuso, no pensado como control de tráfico fino.

Dos implementaciones, elegidas en main.py según haya REDIS_URL o no —
mismo patrón "opcional, comparte estado si hay Redis" que ya usa
RepositorioSesiones (adapters/out/repositorio_sesiones_redis.py): sin
Redis, cada proceso lleva su propio contador en memoria, así que con
varios workers/procesos el límite real es N veces el configurado (la
misma limitación conocida que ya tienen las sesiones en memoria).
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod

from redis import Redis


class LimitadorPeticiones(ABC):
    @abstractmethod
    def permitir(self, clave: str, limite: int, ventana_segundos: int) -> bool:
        """True si la petición identificada por `clave` puede pasar sin
        superar `limite` peticiones en los últimos `ventana_segundos`."""
        ...


class LimitadorPeticionesMemoria(LimitadorPeticiones):
    def __init__(self):
        self._contadores: dict[str, tuple[int, float]] = {}

    def permitir(self, clave: str, limite: int, ventana_segundos: int) -> bool:
        ahora = time.monotonic()
        contador, inicio_ventana = self._contadores.get(clave, (0, ahora))
        if ahora - inicio_ventana >= ventana_segundos:
            contador, inicio_ventana = 0, ahora
        if contador >= limite:
            self._contadores[clave] = (contador, inicio_ventana)
            return False
        self._contadores[clave] = (contador + 1, inicio_ventana)
        return True


class LimitadorPeticionesRedis(LimitadorPeticiones):
    def __init__(self, redis_url: str, cliente: Redis | None = None):
        self._cliente = cliente or Redis.from_url(redis_url, decode_responses=True)

    def permitir(self, clave: str, limite: int, ventana_segundos: int) -> bool:
        clave_redis = f"ratelimit:{clave}"
        # INCR crea la clave a 1 si no existía; solo se le pone TTL la
        # primera vez (contador == 1) para no alargar la ventana en
        # cada petición sucesiva dentro del mismo periodo.
        contador = self._cliente.incr(clave_redis)
        if contador == 1:
            self._cliente.expire(clave_redis, ventana_segundos)
        return contador <= limite
