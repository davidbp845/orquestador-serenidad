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
        {"historial": [{"role": "user", "content": "hola"}], "notas_pendientes": []}
    )

    sesion = repo.obtener("web", "u1")

    assert sesion == SesionConversacion(
        canal="web", usuario_id="u1", historial=[{"role": "user", "content": "hola"}]
    )


def test_obtener_deserializa_las_notas_pendientes_guardadas():
    # #77: antes solo se serializaba historial, así que el buffer de
    # guardar_nota_cliente se perdía en cuanto la sesión daba una
    # vuelta por Redis entre dos turnos de la conversación.
    repo, mock_cliente = _construir_con_cliente_falso()
    mock_cliente.get.return_value = json.dumps(
        {"historial": [], "notas_pendientes": ["alérgica al aceite de almendras dulces"]}
    )

    sesion = repo.obtener("web", "u1")

    assert sesion.notas_pendientes == ["alérgica al aceite de almendras dulces"]


def test_guardar_serializa_historial_y_notas_pendientes_como_json():
    repo, mock_cliente = _construir_con_cliente_falso()
    sesion = SesionConversacion(
        canal="telegram", usuario_id="u2",
        historial=[{"role": "user", "content": "hola"}],
        notas_pendientes=["prefiere profesional Ana"],
    )

    repo.guardar(sesion)

    mock_cliente.set.assert_called_once_with(
        "sesion:telegram:u2",
        json.dumps({
            "historial": [{"role": "user", "content": "hola"}],
            "notas_pendientes": ["prefiere profesional Ana"],
        }),
    )


def test_guardar_y_obtener_redondean_las_notas_pendientes_sin_perderlas():
    # Round-trip contra un "Redis" falso de verdad (dict), no solo
    # comprobando las llamadas mockeadas por separado — es la forma
    # más directa de probar que el bug de #77 no vuelve a colarse.
    almacen: dict[str, str] = {}
    mock_cliente = MagicMock()
    mock_cliente.set.side_effect = lambda clave, valor: almacen.__setitem__(clave, valor)
    mock_cliente.get.side_effect = lambda clave: almacen.get(clave)
    repo = RepositorioSesionesRedis("redis://localhost:6379", cliente=mock_cliente)

    sesion = SesionConversacion(canal="web", usuario_id="u1", notas_pendientes=["alergia al aceite"])
    repo.guardar(sesion)
    recuperada = repo.obtener("web", "u1")

    assert recuperada.notas_pendientes == ["alergia al aceite"]
