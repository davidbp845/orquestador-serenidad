"""
Composition root: aquí, y solo aquí, se conocen todas las
implementaciones concretas. Se instancian los adaptadores y se
inyectan en los casos de uso y en el orquestador. Si mañana cambias
Chroma por Qdrant, o Telegram por WhatsApp, este es el único fichero
que toca saberlo.
"""
from __future__ import annotations

import logging
import os
import threading

from dotenv import load_dotenv

load_dotenv()  # lee .env si existe; si las variables ya están exportadas
                # en el entorno (ej. en producción), esas tienen prioridad
                # y load_dotenv() no las sobreescribe por defecto.

import uvicorn

from adapters.in_.fastapi_app import crear_router
from adapters.in_.rate_limit import (
    LIMITE_PETICIONES_DEFECTO,
    VENTANA_SEGUNDOS_DEFECTO,
    LimitadorPeticiones,
    LimitadorPeticionesMemoria,
    LimitadorPeticionesRedis,
)
from adapters.in_.telegram_bot import crear_bot
from adapters.in_.whatsapp_webhook import crear_router_whatsapp
from adapters.out.llm_anthropic import ProveedorLLMAnthropic
from adapters.out.llm_cohere import ProveedorLLMCohere
from adapters.out.llm_mock import ProveedorLLMMock
from adapters.out.llm_openai import ProveedorLLMOpenAI
from adapters.out.repositorio_sesiones_memoria import RepositorioSesionesMemoria
from adapters.out.repositorios_memoria import (
    RepositorioCitasMemoria,
    RepositorioClientesMemoria,
    RepositorioContadoresMemoria,
    RepositorioPedidosMemoria,
    RepositorioProfesionalesMemoria,
    RepositorioServiciosMemoria,
)
from adapters.out.vector_store import RepositorioConocimientoChroma
from application.orchestrator import OrquestadorAgente
from application.ports import RepositorioSesiones
from application.prompts import construir_system_prompt
from application.tools import EjecutorHerramientas
from config.loader import cargar_config, construir_profesionales, construir_servicios
from domain.use_cases import (
    CancelarReserva,
    ComprobarDisponibilidad,
    ConsultarConocimientoNegocio,
    CrearReserva,
    RegistrarPedido,
)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# A nivel INFO, las librerías HTTP que usan chromadb/sentence-transformers
# por debajo (httpx, httpcore, huggingface_hub) registran una línea por
# cada petición de red al descargar el modelo de embeddings — ruido que
# tapa los logs de la propia app. Se silencian a WARNING; nuestro logger
# (más abajo) sigue respetando LOG_LEVEL.
for _nombre_ruidoso in ("httpx", "httpcore", "urllib3", "huggingface_hub"):
    logging.getLogger(_nombre_ruidoso).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def construir_sistema(ruta_config: str = "config/business.yaml") -> OrquestadorAgente:
    config = cargar_config(ruta_config)

    # --- Repositorios (adaptadores de salida) ---
    # Servicios y profesionales son catálogo: siempre se derivan del
    # yaml, no necesitan sobrevivir a un reinicio.
    repo_servicios = RepositorioServiciosMemoria(construir_servicios(config))
    repo_profesionales = RepositorioProfesionalesMemoria(construir_profesionales(config))

    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        # El esquema lo gestiona Alembic (`alembic upgrade head`), no
        # el arranque de la app — evita que varias instancias
        # compitan por crear/alterar tablas a la vez.
        from adapters.out.repositorios_postgres import (
            RepositorioCitasPostgres,
            RepositorioClientesPostgres,
            RepositorioContadoresPostgres,
            RepositorioPedidosPostgres,
            crear_engine,
        )
        engine = crear_engine(database_url)
        repo_citas = RepositorioCitasPostgres(engine)
        repo_clientes = RepositorioClientesPostgres(engine)
        repo_pedidos = RepositorioPedidosPostgres(engine)
        repo_contadores = RepositorioContadoresPostgres(engine)
    else:
        repo_citas = RepositorioCitasMemoria()
        repo_clientes = RepositorioClientesMemoria()
        repo_pedidos = RepositorioPedidosMemoria()
        repo_contadores = RepositorioContadoresMemoria()

    conocimiento = RepositorioConocimientoChroma()

    credenciales_calendario = os.environ.get("GOOGLE_CALENDAR_CREDENTIALS_JSON")
    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID")
    if credenciales_calendario and calendar_id:
        from adapters.out.calendario_google import SincronizadorCalendarioGoogle
        zona_horaria_calendario = os.environ.get("GOOGLE_CALENDAR_TIMEZONE", "Europe/Madrid")
        calendario = SincronizadorCalendarioGoogle(
            credenciales_calendario, calendar_id, zona_horaria_calendario
        )
    else:
        calendario = None

    telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if telegram_bot_token:
        from adapters.out.notificador_telegram import NotificadorMensajesTelegram
        notificador = NotificadorMensajesTelegram(telegram_bot_token)
    else:
        notificador = None

    proveedor_llm = os.environ.get("PROVEEDOR_LLM", "anthropic").lower()
    if proveedor_llm == "mock":
        llm = ProveedorLLMMock()
    elif proveedor_llm == "cohere":
        llm = ProveedorLLMCohere()
    elif proveedor_llm == "openai":
        llm = ProveedorLLMOpenAI()
    else:
        llm = ProveedorLLMAnthropic()

    # --- Casos de uso (dominio) ---
    disponibilidad = ComprobarDisponibilidad(repo_servicios, repo_profesionales, repo_citas)
    crear_reserva = CrearReserva(
        repo_servicios, repo_profesionales, repo_citas, repo_clientes,
        disponibilidad, repo_contadores, calendario, notificador,
    )
    cancelar_reserva = CancelarReserva(repo_citas, calendario, repo_clientes, notificador)
    registrar_pedido = RegistrarPedido(repo_pedidos, repo_servicios)
    consultar_conocimiento = ConsultarConocimientoNegocio(conocimiento)

    ejecutor = EjecutorHerramientas({
        "comprobar_disponibilidad": disponibilidad,
        "crear_reserva": crear_reserva,
        "cancelar_reserva": cancelar_reserva,
        "registrar_pedido": registrar_pedido,
        "consultar_conocimiento": consultar_conocimiento,
    })

    system_prompt = construir_system_prompt(config)

    return OrquestadorAgente(llm=llm, ejecutor_herramientas=ejecutor, system_prompt=system_prompt), config


def construir_repositorio_sesiones() -> RepositorioSesiones:
    # Igual que DATABASE_URL/GOOGLE_CALENDAR_*: opcional, y sin ella el
    # sistema sigue funcionando exactamente como hasta ahora (sesiones
    # en memoria del proceso, no sobreviven a un reinicio).
    redis_url = os.environ.get("REDIS_URL")
    if redis_url:
        from adapters.out.repositorio_sesiones_redis import RepositorioSesionesRedis
        return RepositorioSesionesRedis(redis_url)
    return RepositorioSesionesMemoria()


def construir_limitador_peticiones() -> LimitadorPeticiones:
    # Mismo condicional que construir_repositorio_sesiones() (#49): sin
    # REDIS_URL, cada proceso lleva su propio contador en memoria — un
    # límite compartido entre varios workers/procesos necesita Redis,
    # igual que las sesiones necesitan Redis para sobrevivir/compartirse.
    redis_url = os.environ.get("REDIS_URL")
    if redis_url:
        return LimitadorPeticionesRedis(redis_url)
    return LimitadorPeticionesMemoria()


def main():
    orquestador, config = construir_sistema()
    repositorio_sesiones = construir_repositorio_sesiones()
    limitador_peticiones = construir_limitador_peticiones()
    # `or` en vez de un default en .get(): si .env define la variable
    # vacía (RATE_LIMIT_CHAT_MAX_PETICIONES=, como queda tras copiar
    # .env.example sin rellenarla), .get() devuelve "" en vez del
    # default, y int("") lanzaría ValueError.
    limite_chat = int(os.environ.get("RATE_LIMIT_CHAT_MAX_PETICIONES") or LIMITE_PETICIONES_DEFECTO)
    ventana_chat = int(os.environ.get("RATE_LIMIT_CHAT_VENTANA_SEGUNDOS") or VENTANA_SEGUNDOS_DEFECTO)

    app = crear_router(
        orquestador, repositorio_sesiones,
        limitador=limitador_peticiones,
        limite_peticiones=limite_chat,
        ventana_segundos=ventana_chat,
    )

    if config.get("canales", {}).get("whatsapp"):
        verify_token = os.environ.get("WHATSAPP_VERIFY_TOKEN")
        access_token = os.environ.get("WHATSAPP_ACCESS_TOKEN")
        phone_number_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
        app_secret = os.environ.get("WHATSAPP_APP_SECRET")
        if verify_token and access_token and phone_number_id and app_secret:
            crear_router_whatsapp(
                app, orquestador, repositorio_sesiones,
                verify_token, access_token, phone_number_id, app_secret,
            )
            logger.info("Webhook de WhatsApp registrado en /webhook/whatsapp.")
        else:
            logger.warning(
                "canales.whatsapp activado pero faltan variables WHATSAPP_* "
                "(VERIFY_TOKEN, ACCESS_TOKEN, PHONE_NUMBER_ID, APP_SECRET): "
                "webhook de WhatsApp no registrado."
            )

    hilo_web = threading.Thread(
        target=lambda: uvicorn.run(app, host="0.0.0.0", port=8000),
        daemon=True,
    )
    hilo_web.start()
    logger.info("Chat web disponible en http://localhost:8000/chat")

    if config.get("canales", {}).get("telegram"):
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if token:
            bot = crear_bot(token, orquestador, repositorio_sesiones)
            logger.info("Bot de Telegram iniciado.")
            bot.run_polling()
        else:
            logger.warning("TELEGRAM_BOT_TOKEN no definido: bot de Telegram no arrancado.")
            hilo_web.join()
    else:
        hilo_web.join()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Apagando...")
