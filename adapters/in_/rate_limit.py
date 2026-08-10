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

`listar_consumo()` (#50) es lo que consume el panel interno para
mostrar el consumo en vivo por usuario_id — solo tiene datos reales
cuando el backend usa LimitadorPeticionesRedis, ya que el panel es un
proceso distinto sin memoria compartida con main.py.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from redis import Redis

# Límites por defecto si no se define RATE_LIMIT_CHAT_MAX_PETICIONES/
# RATE_LIMIT_CHAT_VENTANA_SEGUNDOS (main.py) — centralizados aquí para
# que fastapi_app.py, main.py y el panel interno usen siempre el mismo
# valor por defecto sin duplicarlo.
LIMITE_PETICIONES_DEFECTO = 20
VENTANA_SEGUNDOS_DEFECTO = 60


@dataclass
class ConsumoClave:
    clave: str
    peticiones: int
    segundos_restantes: int


class LimitadorPeticiones(ABC):
    @abstractmethod
    def permitir(self, clave: str, limite: int, ventana_segundos: int) -> bool:
        """True si la petición identificada por `clave` puede pasar sin
        superar `limite` peticiones en los últimos `ventana_segundos`."""
        ...

    @abstractmethod
    def listar_consumo(self) -> list[ConsumoClave]:
        """Consumo actual de todas las claves con alguna petición
        registrada en la ventana activa — para observabilidad (#50),
        no se usa en el camino de comprobar el límite."""
        ...


class LimitadorPeticionesMemoria(LimitadorPeticiones):
    def __init__(self):
        self._contadores: dict[str, tuple[int, float, int]] = {}

    def permitir(self, clave: str, limite: int, ventana_segundos: int) -> bool:
        ahora = time.monotonic()
        contador, inicio_ventana, _ = self._contadores.get(clave, (0, ahora, ventana_segundos))
        if ahora - inicio_ventana >= ventana_segundos:
            contador, inicio_ventana = 0, ahora
        if contador >= limite:
            self._contadores[clave] = (contador, inicio_ventana, ventana_segundos)
            return False
        self._contadores[clave] = (contador + 1, inicio_ventana, ventana_segundos)
        return True

    def listar_consumo(self) -> list[ConsumoClave]:
        ahora = time.monotonic()
        resultado = []
        for clave, (contador, inicio_ventana, ventana_segundos) in self._contadores.items():
            restante = ventana_segundos - (ahora - inicio_ventana)
            if restante <= 0:
                continue  # ventana ya expirada, no queda consumo que mostrar
            resultado.append(ConsumoClave(clave=clave, peticiones=contador, segundos_restantes=int(restante)))
        return resultado


class LimitadorPeticionesRedis(LimitadorPeticiones):
    _PREFIJO_CLAVE = "ratelimit:"

    def __init__(self, redis_url: str, cliente: Redis | None = None):
        self._cliente = cliente or Redis.from_url(redis_url, decode_responses=True)

    def permitir(self, clave: str, limite: int, ventana_segundos: int) -> bool:
        clave_redis = f"{self._PREFIJO_CLAVE}{clave}"
        # INCR crea la clave a 1 si no existía; solo se le pone TTL la
        # primera vez (contador == 1) para no alargar la ventana en
        # cada petición sucesiva dentro del mismo periodo.
        contador = self._cliente.incr(clave_redis)
        if contador == 1:
            self._cliente.expire(clave_redis, ventana_segundos)
        return contador <= limite

    def listar_consumo(self) -> list[ConsumoClave]:
        resultado = []
        for clave_redis in self._cliente.scan_iter(match=f"{self._PREFIJO_CLAVE}*"):
            contador = int(self._cliente.get(clave_redis) or 0)
            ttl = self._cliente.ttl(clave_redis)
            if ttl <= 0:
                continue  # sin TTL (no debería pasar) o ya expirada
            clave = clave_redis.removeprefix(self._PREFIJO_CLAVE)
            resultado.append(ConsumoClave(clave=clave, peticiones=contador, segundos_restantes=ttl))
        return resultado
