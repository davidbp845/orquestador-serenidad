"""No golpea una instancia Redis real: se mockea redis.Redis, ya que
lo único que le corresponde probar a este adaptador es que traduce
correctamente el puerto RepositorioSesiones (serialización JSON del
historial, construcción de la clave) a llamadas de get/set."""
import json
from unittest.mock import MagicMock, patch

from adapters.out.repositorio_sesiones_redis import RepositorioSesionesRedis
from application.orchestrator import SesionConversacion


def _construir_con_cliente_falso():
    mock_cliente = MagicMock()
    repo = RepositorioSesionesRedis("redis://localhost:6379", cliente=mock_cliente)
    return repo, mock_cliente


def test_usa_redis_from_url_si_no_se_pasa_cliente():
    with patch("adapters.out.repositorio_sesiones_redis.Redis") as mock_redis_cls:
        RepositorioSesionesRedis("redis://localhost:6379")
        mock_redis_cls.from_url.assert_called_once_with(
            "redis://localhost:6379", decode_responses=True
        )


def test_obtener_devuelve_none_si_no_existe():
    repo, mock_cliente = _construir_con_cliente_falso()
    mock_cliente.get.return_value = None

    assert repo.obtener("web", "u1") is None
    mock_cliente.get.assert_called_once_with("sesion:web:u1")


def test_obtener_deserializa_el_historial_guardado():
    repo, mock_cliente = _construir_con_cliente_falso()
    mock_cliente.get.return_value = json.dumps(
        {"historial": [{"role": "user", "content": "hola"}], "cliente_id_conocido": None}
    )

    sesion = repo.obtener("web", "u1")

    assert sesion == SesionConversacion(
        canal="web", usuario_id="u1", historial=[{"role": "user", "content": "hola"}]
    )


def test_obtener_deserializa_el_cliente_id_conocido_guardado():
    # Si crear_reserva ya resolvió un cliente_id en un turno anterior,
    # tiene que sobrevivir a la vuelta por Redis para que
    # guardar_nota_cliente pueda reutilizarlo en un turno posterior de
    # la misma conversación (#77).
    repo, mock_cliente = _construir_con_cliente_falso()
    mock_cliente.get.return_value = json.dumps({"historial": [], "cliente_id_conocido": "c1"})

    sesion = repo.obtener("web", "u1")

    assert sesion.cliente_id_conocido == "c1"


def test_obtener_tolera_una_sesion_guardada_sin_cliente_id_conocido():
    # Sesión guardada por una versión anterior del código, antes de
    # añadir cliente_id_conocido (#77) — no debe romper con KeyError,
    # solo faltarle ese campo concreto (vuelve a None).
    repo, mock_cliente = _construir_con_cliente_falso()
    mock_cliente.get.return_value = json.dumps({"historial": []})

    sesion = repo.obtener("web", "u1")

    assert sesion.cliente_id_conocido is None


def test_guardar_serializa_historial_cliente_id_conocido_y_telefonos_verificados():
    repo, mock_cliente = _construir_con_cliente_falso()
    sesion = SesionConversacion(
        canal="telegram", usuario_id="u2",
        historial=[{"role": "user", "content": "hola"}],
        cliente_id_conocido="c1",
        telefonos_verificados={"600111222"},
    )

    repo.guardar(sesion)

    mock_cliente.set.assert_called_once_with(
        "sesion:telegram:u2",
        json.dumps({
            "historial": [{"role": "user", "content": "hola"}],
            "cliente_id_conocido": "c1",
            "telefonos_verificados": ["600111222"],
        }),
    )


def test_obtener_deserializa_los_telefonos_verificados_guardados():
    repo, mock_cliente = _construir_con_cliente_falso()
    mock_cliente.get.return_value = json.dumps({
        "historial": [], "cliente_id_conocido": None,
        "telefonos_verificados": ["600111222"],
    })

    sesion = repo.obtener("web", "u1")

    assert sesion.telefonos_verificados == {"600111222"}


def test_obtener_tolera_una_sesion_guardada_sin_telefonos_verificados():
    repo, mock_cliente = _construir_con_cliente_falso()
    mock_cliente.get.return_value = json.dumps({"historial": [], "cliente_id_conocido": "c1"})

    sesion = repo.obtener("web", "u1")

    assert sesion.telefonos_verificados == set()


def test_guardar_y_obtener_redondean_el_cliente_id_conocido_sin_perderlo():
    # Round-trip contra un "Redis" falso de verdad (dict), no solo
    # comprobando las llamadas mockeadas por separado — es la forma
    # más directa de probar que el bug de #77 no vuelve a colarse.
    almacen: dict[str, str] = {}
    mock_cliente = MagicMock()
    mock_cliente.set.side_effect = lambda clave, valor: almacen.__setitem__(clave, valor)
    mock_cliente.get.side_effect = lambda clave: almacen.get(clave)
    repo = RepositorioSesionesRedis("redis://localhost:6379", cliente=mock_cliente)

    sesion = SesionConversacion(
        canal="web", usuario_id="u1", cliente_id_conocido="c1",
        telefonos_verificados={"600111222"},
    )
    repo.guardar(sesion)
    recuperada = repo.obtener("web", "u1")

    assert recuperada.cliente_id_conocido == "c1"
    assert recuperada.telefonos_verificados == {"600111222"}
