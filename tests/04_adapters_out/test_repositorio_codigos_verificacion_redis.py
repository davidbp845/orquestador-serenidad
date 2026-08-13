"""No golpea una instancia Redis real: se mockea redis.Redis."""
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from adapters.out.repositorio_codigos_verificacion_redis import (
    RepositorioCodigosVerificacionRedis,
)
from domain.entities import CodigoVerificacion


def _construir_con_cliente_falso():
    mock_cliente = MagicMock()
    repo = RepositorioCodigosVerificacionRedis("redis://localhost:6379", cliente=mock_cliente)
    return repo, mock_cliente


def test_guardar_llama_a_setex_con_el_ttl_calculado_desde_expira_en():
    repo, mock_cliente = _construir_con_cliente_falso()
    expira_en = datetime.now(UTC) + timedelta(minutes=10)
    codigo = CodigoVerificacion(telefono="600111222", codigo="123456", expira_en=expira_en)

    repo.guardar(codigo)

    clave, ttl, valor = mock_cliente.setex.call_args[0]
    assert clave == "codigo_verificacion:600111222"
    assert 590 <= ttl <= 600
    assert json.loads(valor) == {"codigo": "123456", "expira_en": expira_en.isoformat()}


def test_guardar_usa_ttl_minimo_de_un_segundo_si_ya_ha_expirado():
    repo, mock_cliente = _construir_con_cliente_falso()
    codigo = CodigoVerificacion(
        telefono="600111222", codigo="123456", expira_en=datetime.now(UTC) - timedelta(minutes=1),
    )

    repo.guardar(codigo)

    _, ttl, _ = mock_cliente.setex.call_args[0]
    assert ttl == 1


def test_obtener_devuelve_none_si_no_existe():
    repo, mock_cliente = _construir_con_cliente_falso()
    mock_cliente.get.return_value = None

    assert repo.obtener("600111222") is None
    mock_cliente.get.assert_called_once_with("codigo_verificacion:600111222")


def test_obtener_deserializa_el_codigo_guardado():
    repo, mock_cliente = _construir_con_cliente_falso()
    expira_en = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    mock_cliente.get.return_value = json.dumps({"codigo": "123456", "expira_en": expira_en.isoformat()})

    codigo = repo.obtener("600111222")

    assert codigo == CodigoVerificacion(telefono="600111222", codigo="123456", expira_en=expira_en)


def test_eliminar_llama_a_delete_con_la_clave():
    repo, mock_cliente = _construir_con_cliente_falso()

    repo.eliminar("600111222")

    mock_cliente.delete.assert_called_once_with("codigo_verificacion:600111222")


def test_guardar_y_obtener_redondean_sin_perder_datos():
    almacen: dict[str, tuple[int, str]] = {}
    mock_cliente = MagicMock()
    mock_cliente.setex.side_effect = lambda clave, ttl, valor: almacen.__setitem__(clave, (ttl, valor))
    mock_cliente.get.side_effect = lambda clave: almacen.get(clave, (None, None))[1]
    repo = RepositorioCodigosVerificacionRedis("redis://localhost:6379", cliente=mock_cliente)

    expira_en = datetime.now(UTC) + timedelta(minutes=10)
    codigo = CodigoVerificacion(telefono="600111222", codigo="123456", expira_en=expira_en)
    repo.guardar(codigo)
    recuperado = repo.obtener("600111222")

    assert recuperado == codigo
