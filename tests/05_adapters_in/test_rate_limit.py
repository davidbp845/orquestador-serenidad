"""LimitadorPeticionesMemoria se prueba controlando el reloj a mano
(monkeypatch de time.monotonic); LimitadorPeticionesRedis mockea
redis.Redis, igual que test_repositorio_sesiones_redis.py, ya que lo
único que le corresponde probar a este adaptador es que traduce el
contrato a incr/expire, no el comportamiento real de Redis."""
from unittest.mock import MagicMock, patch

from adapters.in_.rate_limit import ConsumoClave, LimitadorPeticionesMemoria, LimitadorPeticionesRedis


def test_memoria_permite_hasta_el_limite_y_luego_bloquea():
    limitador = LimitadorPeticionesMemoria()

    for _ in range(3):
        assert limitador.permitir("u1", limite=3, ventana_segundos=60) is True

    assert limitador.permitir("u1", limite=3, ventana_segundos=60) is False


def test_memoria_no_mezcla_contadores_de_distintas_claves():
    limitador = LimitadorPeticionesMemoria()

    for _ in range(3):
        limitador.permitir("u1", limite=3, ventana_segundos=60)

    assert limitador.permitir("u2", limite=3, ventana_segundos=60) is True


def test_memoria_resetea_el_contador_al_pasar_la_ventana(monkeypatch):
    limitador = LimitadorPeticionesMemoria()
    reloj = {"ahora": 1000.0}
    monkeypatch.setattr("adapters.in_.rate_limit.time.monotonic", lambda: reloj["ahora"])

    for _ in range(3):
        limitador.permitir("u1", limite=3, ventana_segundos=60)
    assert limitador.permitir("u1", limite=3, ventana_segundos=60) is False

    reloj["ahora"] += 61
    assert limitador.permitir("u1", limite=3, ventana_segundos=60) is True


def _construir_limitador_redis_falso():
    mock_cliente = MagicMock()
    limitador = LimitadorPeticionesRedis("redis://localhost:6379", cliente=mock_cliente)
    return limitador, mock_cliente


def test_redis_usa_from_url_si_no_se_pasa_cliente():
    with patch("adapters.in_.rate_limit.Redis") as mock_redis_cls:
        LimitadorPeticionesRedis("redis://localhost:6379")
        mock_redis_cls.from_url.assert_called_once_with(
            "redis://localhost:6379", decode_responses=True
        )


def test_redis_permite_por_debajo_del_limite():
    limitador, mock_cliente = _construir_limitador_redis_falso()
    mock_cliente.incr.return_value = 1

    assert limitador.permitir("u1", limite=3, ventana_segundos=60) is True
    mock_cliente.expire.assert_called_once_with("ratelimit:u1", 60)


def test_redis_bloquea_al_superar_el_limite():
    limitador, mock_cliente = _construir_limitador_redis_falso()
    mock_cliente.incr.return_value = 4

    assert limitador.permitir("u1", limite=3, ventana_segundos=60) is False


def test_redis_solo_pone_ttl_en_la_primera_peticion_de_la_ventana():
    limitador, mock_cliente = _construir_limitador_redis_falso()
    mock_cliente.incr.return_value = 2

    limitador.permitir("u1", limite=3, ventana_segundos=60)

    mock_cliente.expire.assert_not_called()


def test_memoria_listar_consumo_vacio_sin_peticiones():
    limitador = LimitadorPeticionesMemoria()
    assert limitador.listar_consumo() == []


def test_memoria_listar_consumo_refleja_las_peticiones_registradas(monkeypatch):
    limitador = LimitadorPeticionesMemoria()
    monkeypatch.setattr("adapters.in_.rate_limit.time.monotonic", lambda: 1000.0)

    limitador.permitir("u1", limite=20, ventana_segundos=60)
    limitador.permitir("u1", limite=20, ventana_segundos=60)

    consumo = limitador.listar_consumo()
    assert len(consumo) == 1
    assert consumo[0].clave == "u1"
    assert consumo[0].peticiones == 2
    assert consumo[0].segundos_restantes == 60


def test_memoria_listar_consumo_omite_ventanas_ya_expiradas(monkeypatch):
    limitador = LimitadorPeticionesMemoria()
    reloj = {"ahora": 1000.0}
    monkeypatch.setattr("adapters.in_.rate_limit.time.monotonic", lambda: reloj["ahora"])

    limitador.permitir("u1", limite=20, ventana_segundos=60)
    reloj["ahora"] += 61

    assert limitador.listar_consumo() == []


def test_redis_listar_consumo_vacio_sin_claves():
    limitador, mock_cliente = _construir_limitador_redis_falso()
    mock_cliente.scan_iter.return_value = iter([])

    assert limitador.listar_consumo() == []


def test_redis_listar_consumo_traduce_claves_contador_y_ttl():
    limitador, mock_cliente = _construir_limitador_redis_falso()
    mock_cliente.scan_iter.return_value = iter(["ratelimit:u1", "ratelimit:u2"])
    mock_cliente.get.side_effect = ["7", "1"]
    mock_cliente.ttl.side_effect = [45, 12]

    consumo = limitador.listar_consumo()

    assert consumo == [
        ConsumoClave(clave="u1", peticiones=7, segundos_restantes=45),
        ConsumoClave(clave="u2", peticiones=1, segundos_restantes=12),
    ]
    mock_cliente.scan_iter.assert_called_once_with(match="ratelimit:*")


def test_redis_listar_consumo_omite_claves_sin_ttl_valido():
    limitador, mock_cliente = _construir_limitador_redis_falso()
    mock_cliente.scan_iter.return_value = iter(["ratelimit:u1"])
    mock_cliente.get.return_value = "3"
    mock_cliente.ttl.return_value = -1

    assert limitador.listar_consumo() == []
