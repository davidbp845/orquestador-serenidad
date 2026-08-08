"""main.py es el composition root: aquí solo verificamos que
construir_sistema() conecta correctamente adaptadores, casos de uso y
orquestador. Se mockean los adaptadores que hablan con servicios
externos reales (Anthropic, Chroma) para que el test sea rápido y no
dependa de red ni de credenciales."""
from unittest.mock import MagicMock, patch

from adapters.out.repositorios_postgres import (
    RepositorioCitasPostgres,
    RepositorioClientesPostgres,
    RepositorioPedidosPostgres,
)
from application.orchestrator import OrquestadorAgente


def test_construir_sistema_conecta_las_piezas():
    with patch("main.ProveedorLLMAnthropic") as mock_llm_cls, \
         patch("main.RepositorioConocimientoChroma") as mock_chroma_cls:
        mock_llm_cls.return_value = MagicMock()
        mock_chroma_cls.return_value = MagicMock()

        import main
        orquestador, config = main.construir_sistema("config/business.yaml")

    assert isinstance(orquestador, OrquestadorAgente)
    assert config["nombre"] == "Centro de Masajes Serenidad"

    herramientas_esperadas = {
        "comprobar_disponibilidad", "crear_reserva", "cancelar_reserva",
        "registrar_pedido", "consultar_conocimiento",
    }
    assert set(orquestador._ejecutor._casos.keys()) == herramientas_esperadas
    assert "Centro de Masajes Serenidad" in orquestador._system_prompt


def test_construir_sistema_carga_servicios_y_profesionales_del_yaml():
    with patch("main.ProveedorLLMAnthropic") as mock_llm_cls, \
         patch("main.RepositorioConocimientoChroma") as mock_chroma_cls:
        mock_llm_cls.return_value = MagicMock()
        mock_chroma_cls.return_value = MagicMock()

        import main
        orquestador, _ = main.construir_sistema("config/business.yaml")

    disponibilidad = orquestador._ejecutor._casos["comprobar_disponibilidad"]
    servicios = disponibilidad._servicios.listar()
    ids_servicios = {s.id for s in servicios}

    assert "masaje_relajante_60" in ids_servicios
    assert "masaje_descontracturante_45" in ids_servicios


def test_construir_sistema_usa_llm_real_por_defecto(monkeypatch):
    monkeypatch.delenv("PROVEEDOR_LLM", raising=False)
    with patch("main.ProveedorLLMAnthropic") as mock_llm_cls, \
         patch("main.RepositorioConocimientoChroma") as mock_chroma_cls:
        mock_llm_cls.return_value = MagicMock()
        mock_chroma_cls.return_value = MagicMock()

        import main
        orquestador, _ = main.construir_sistema("config/business.yaml")

    assert orquestador._llm is mock_llm_cls.return_value


def test_construir_sistema_usa_llm_mock_si_proveedor_llm_es_mock(monkeypatch):
    monkeypatch.setenv("PROVEEDOR_LLM", "mock")
    with patch("main.RepositorioConocimientoChroma") as mock_chroma_cls:
        mock_chroma_cls.return_value = MagicMock()

        import main
        orquestador, _ = main.construir_sistema("config/business.yaml")

    from adapters.out.llm_mock import ProveedorLLMMock
    assert isinstance(orquestador._llm, ProveedorLLMMock)


def test_construir_sistema_usa_llm_real_si_proveedor_llm_es_anthropic(monkeypatch):
    monkeypatch.setenv("PROVEEDOR_LLM", "anthropic")
    with patch("main.ProveedorLLMAnthropic") as mock_llm_cls, \
         patch("main.RepositorioConocimientoChroma") as mock_chroma_cls:
        mock_llm_cls.return_value = MagicMock()
        mock_chroma_cls.return_value = MagicMock()

        import main
        orquestador, _ = main.construir_sistema("config/business.yaml")

    assert orquestador._llm is mock_llm_cls.return_value


def test_construir_sistema_usa_llm_cohere_si_proveedor_llm_es_cohere(monkeypatch):
    monkeypatch.setenv("PROVEEDOR_LLM", "cohere")
    with patch("main.ProveedorLLMCohere") as mock_llm_cls, \
         patch("main.RepositorioConocimientoChroma") as mock_chroma_cls:
        mock_llm_cls.return_value = MagicMock()
        mock_chroma_cls.return_value = MagicMock()

        import main
        orquestador, _ = main.construir_sistema("config/business.yaml")

    assert orquestador._llm is mock_llm_cls.return_value


def test_construir_sistema_usa_repos_en_memoria_sin_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with patch("main.ProveedorLLMAnthropic") as mock_llm_cls, \
         patch("main.RepositorioConocimientoChroma") as mock_chroma_cls:
        mock_llm_cls.return_value = MagicMock()
        mock_chroma_cls.return_value = MagicMock()

        import main
        orquestador, _ = main.construir_sistema("config/business.yaml")

    from adapters.out.repositorios_memoria import RepositorioCitasMemoria
    crear_reserva = orquestador._ejecutor._casos["crear_reserva"]
    assert isinstance(crear_reserva._citas, RepositorioCitasMemoria)


def test_construir_sistema_usa_repos_postgres_si_hay_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    with patch("main.ProveedorLLMAnthropic") as mock_llm_cls, \
         patch("main.RepositorioConocimientoChroma") as mock_chroma_cls:
        mock_llm_cls.return_value = MagicMock()
        mock_chroma_cls.return_value = MagicMock()

        import main
        orquestador, _ = main.construir_sistema("config/business.yaml")

    crear_reserva = orquestador._ejecutor._casos["crear_reserva"]
    cancelar_reserva = orquestador._ejecutor._casos["cancelar_reserva"]
    registrar_pedido = orquestador._ejecutor._casos["registrar_pedido"]

    assert isinstance(crear_reserva._citas, RepositorioCitasPostgres)
    assert isinstance(crear_reserva._clientes, RepositorioClientesPostgres)
    assert isinstance(cancelar_reserva._citas, RepositorioCitasPostgres)
    assert isinstance(registrar_pedido._pedidos, RepositorioPedidosPostgres)


def test_construir_sistema_sin_calendario_configurado(monkeypatch):
    monkeypatch.delenv("GOOGLE_CALENDAR_CREDENTIALS_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_CALENDAR_ID", raising=False)
    with patch("main.ProveedorLLMAnthropic") as mock_llm_cls, \
         patch("main.RepositorioConocimientoChroma") as mock_chroma_cls:
        mock_llm_cls.return_value = MagicMock()
        mock_chroma_cls.return_value = MagicMock()

        import main
        orquestador, _ = main.construir_sistema("config/business.yaml")

    crear_reserva = orquestador._ejecutor._casos["crear_reserva"]
    cancelar_reserva = orquestador._ejecutor._casos["cancelar_reserva"]
    assert crear_reserva._calendario is None
    assert cancelar_reserva._calendario is None


def test_construir_sistema_usa_google_calendar_si_hay_credenciales(monkeypatch):
    monkeypatch.setenv("GOOGLE_CALENDAR_CREDENTIALS_JSON", "/ruta/falsa/credenciales.json")
    monkeypatch.setenv("GOOGLE_CALENDAR_ID", "negocio@group.calendar.google.com")
    with patch("main.ProveedorLLMAnthropic") as mock_llm_cls, \
         patch("main.RepositorioConocimientoChroma") as mock_chroma_cls, \
         patch("adapters.out.calendario_google.SincronizadorCalendarioGoogle") as mock_calendario_cls:
        mock_llm_cls.return_value = MagicMock()
        mock_chroma_cls.return_value = MagicMock()
        mock_calendario_cls.return_value = MagicMock()

        import main
        orquestador, _ = main.construir_sistema("config/business.yaml")

    crear_reserva = orquestador._ejecutor._casos["crear_reserva"]
    cancelar_reserva = orquestador._ejecutor._casos["cancelar_reserva"]

    mock_calendario_cls.assert_called_once_with(
        "/ruta/falsa/credenciales.json", "negocio@group.calendar.google.com", "Europe/Madrid"
    )
    assert crear_reserva._calendario is mock_calendario_cls.return_value
    assert cancelar_reserva._calendario is mock_calendario_cls.return_value


def test_construir_sistema_sin_token_telegram_no_instancia_notificador(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with patch("main.ProveedorLLMAnthropic") as mock_llm_cls, \
         patch("main.RepositorioConocimientoChroma") as mock_chroma_cls:
        mock_llm_cls.return_value = MagicMock()
        mock_chroma_cls.return_value = MagicMock()

        import main
        orquestador, _ = main.construir_sistema("config/business.yaml")

    crear_reserva = orquestador._ejecutor._casos["crear_reserva"]
    cancelar_reserva = orquestador._ejecutor._casos["cancelar_reserva"]
    assert crear_reserva._notificador is None
    assert cancelar_reserva._notificador is None


def test_construir_sistema_usa_notificador_telegram_si_hay_token(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-falso")
    with patch("main.ProveedorLLMAnthropic") as mock_llm_cls, \
         patch("main.RepositorioConocimientoChroma") as mock_chroma_cls, \
         patch("adapters.out.notificador_telegram.NotificadorMensajesTelegram") as mock_notificador_cls:
        mock_llm_cls.return_value = MagicMock()
        mock_chroma_cls.return_value = MagicMock()
        mock_notificador_cls.return_value = MagicMock()

        import main
        orquestador, _ = main.construir_sistema("config/business.yaml")

    crear_reserva = orquestador._ejecutor._casos["crear_reserva"]
    cancelar_reserva = orquestador._ejecutor._casos["cancelar_reserva"]

    mock_notificador_cls.assert_called_once_with("token-falso")
    assert crear_reserva._notificador is mock_notificador_cls.return_value
    assert cancelar_reserva._notificador is mock_notificador_cls.return_value


def test_construir_repositorio_sesiones_usa_memoria_sin_redis_url(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)

    import main
    from adapters.out.repositorio_sesiones_memoria import RepositorioSesionesMemoria

    assert isinstance(main.construir_repositorio_sesiones(), RepositorioSesionesMemoria)


def test_construir_repositorio_sesiones_usa_redis_si_hay_redis_url(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    with patch("adapters.out.repositorio_sesiones_redis.Redis") as mock_redis_cls:
        mock_redis_cls.from_url.return_value = MagicMock()

        import main
        from adapters.out.repositorio_sesiones_redis import RepositorioSesionesRedis

        repo = main.construir_repositorio_sesiones()

    assert isinstance(repo, RepositorioSesionesRedis)
