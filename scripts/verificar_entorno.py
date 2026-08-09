"""
Comprueba que el entorno de desarrollo está listo para arrancar el stack
completo (backend, frontend, panel interno) sin arrancar nada: dependencias
Python instaladas, la clave del proveedor de LLM activo, el vault indexado
en Chroma, y conectividad real con Postgres/Redis si están configurados vía
DATABASE_URL/REDIS_URL — más avisos (no bloqueantes) sobre Google Calendar y
Telegram cuando están activos, porque arrancar con ellos configurados tiene
efectos reales (sincroniza un calendario real, empieza a hacer polling de
verdad contra Telegram).

Lo usa scripts/dev_up.sh antes de lanzar los tres procesos; también se
puede correr suelto:
    python scripts/verificar_entorno.py

Código de salida 0 si no hay fallos duros (avisos sí se permiten), 1 si hay
algo que impediría arrancar con garantías (p. ej. Postgres configurado pero
inalcanzable).
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv

RAIZ_REPO = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ_REPO / ".env")

_FALLOS = 0
_AVISOS = 0


def _ok(msg: str) -> None:
    print(f"  \033[32m✓\033[0m {msg}")


def _warn(msg: str) -> None:
    global _AVISOS
    _AVISOS += 1
    print(f"  \033[33m!\033[0m {msg}")


def _fail(msg: str) -> None:
    global _FALLOS
    _FALLOS += 1
    print(f"  \033[31m✗\033[0m {msg}")


def _titulo(msg: str) -> None:
    print(f"\n\033[1m{msg}\033[0m")


def _verificar_dependencias() -> None:
    _titulo("Dependencias Python")
    requeridas = [
        "fastapi", "uvicorn", "chromadb", "sentence_transformers",
        "sqlmodel", "redis", "streamlit", "yaml", "dotenv",
    ]
    faltan = [m for m in requeridas if importlib.util.find_spec(m) is None]
    if faltan:
        _fail(f"Faltan paquetes: {', '.join(faltan)} — pip install -r requirements.txt")
    else:
        _ok("Todas las dependencias clave están instaladas")


def _verificar_llm() -> None:
    _titulo("Proveedor de LLM")
    proveedor = os.environ.get("PROVEEDOR_LLM", "anthropic").lower()
    claves = {"anthropic": "ANTHROPIC_API_KEY", "cohere": "COHERE_API_KEY", "openai": "OPENAI_API_KEY"}

    if proveedor == "mock":
        _ok("PROVEEDOR_LLM=mock — sin red ni credenciales, ideal para desarrollar el frontend")
        return

    var = claves.get(proveedor)
    if var is None:
        _fail(f"PROVEEDOR_LLM={proveedor!r} no reconocido (usa anthropic|mock|cohere|openai)")
        return
    if os.environ.get(var):
        _ok(f"PROVEEDOR_LLM={proveedor}, {var} definida")
    else:
        _fail(f"PROVEEDOR_LLM={proveedor} pero falta {var} en .env")


def _verificar_chroma() -> None:
    _titulo("RAG (Chroma)")
    ruta = Path(os.environ.get("CHROMA_PATH", "./chroma_data"))
    if not ruta.exists() or not any(ruta.iterdir()):
        _warn(
            f"{ruta} no existe o está vacío — indexa el vault: "
            "python -m adapters.out.obsidian_ingest --vault ./vault_negocio"
        )
    else:
        _ok(f"{ruta} tiene datos indexados")


def _verificar_postgres() -> None:
    _titulo("Postgres (citas/clientes/pedidos)")
    url = os.environ.get("DATABASE_URL")
    if not url:
        _warn("DATABASE_URL no definida — citas/clientes/pedidos viven en memoria (no sobreviven a un reinicio)")
        return

    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        _ok("Conexión a Postgres OK")
    except Exception as exc:
        _fail(f"No se pudo conectar a Postgres: {exc}")
        return

    try:
        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory

        cfg = Config(str(RAIZ_REPO / "alembic.ini"))
        head = ScriptDirectory.from_config(cfg).get_current_head()
        with engine.connect() as conn:
            actual = MigrationContext.configure(conn).get_current_revision()

        if actual == head:
            _ok(f"Esquema al día (revisión {actual})")
        else:
            _warn(f"Esquema desactualizado (actual={actual}, head={head}) — aplicando 'alembic upgrade head'...")
            resultado = subprocess.run(
                ["alembic", "upgrade", "head"], cwd=RAIZ_REPO, capture_output=True, text=True
            )
            if resultado.returncode == 0:
                _ok("Migraciones aplicadas")
            else:
                _fail(f"alembic upgrade head falló:\n{resultado.stderr}")
    except Exception as exc:
        _warn(f"No se pudo comprobar el estado de las migraciones: {exc}")


def _verificar_redis() -> None:
    _titulo("Redis (sesiones de conversación)")
    url = os.environ.get("REDIS_URL")
    if not url:
        _warn("REDIS_URL no definida — sesiones en memoria del proceso (no sobreviven a un reinicio)")
        return
    try:
        import redis
        redis.Redis.from_url(url, socket_connect_timeout=3).ping()
        _ok("Conexión a Redis OK")
    except Exception as exc:
        _fail(f"No se pudo conectar a Redis: {exc}")


def _verificar_calendar() -> None:
    _titulo("Google Calendar")
    creds = os.environ.get("GOOGLE_CALENDAR_CREDENTIALS_JSON")
    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID")

    if not creds and not calendar_id:
        _warn("No configurado — las reservas no se sincronizan con ningún calendario externo")
        return
    if bool(creds) != bool(calendar_id):
        _fail(
            "GOOGLE_CALENDAR_CREDENTIALS_JSON y GOOGLE_CALENDAR_ID deben definirse juntas "
            "— con solo una, la sincronización queda desactivada en silencio"
        )
        return
    if not Path(creds).exists():
        _fail(f"GOOGLE_CALENDAR_CREDENTIALS_JSON apunta a un fichero que no existe: {creds}")
        return
    _warn(f"ACTIVO — las reservas se sincronizarán con un Google Calendar REAL (calendar_id={calendar_id})")


def _verificar_telegram() -> None:
    _titulo("Telegram")
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        _warn("TELEGRAM_BOT_TOKEN no definido — el bot de Telegram no arrancará")
        return

    import yaml
    config = yaml.safe_load((RAIZ_REPO / "config" / "business.yaml").read_text(encoding="utf-8"))
    if config.get("canales", {}).get("telegram"):
        _warn("ACTIVO — al arrancar main.py empezará polling REAL contra Telegram (interactúa con usuarios reales)")
    else:
        _ok("TELEGRAM_BOT_TOKEN definido, pero canales.telegram=false en business.yaml — el bot no arranca")


def _verificar_frontend() -> None:
    _titulo("Frontend (frontend/)")
    if not (RAIZ_REPO / "frontend" / "node_modules").exists():
        _warn("frontend/node_modules no existe — hace falta 'npm install' en frontend/ antes de 'npm run dev'")
    else:
        _ok("node_modules presente")


def main() -> int:
    _verificar_dependencias()
    _verificar_llm()
    _verificar_chroma()
    _verificar_postgres()
    _verificar_redis()
    _verificar_calendar()
    _verificar_telegram()
    _verificar_frontend()

    print()
    if _FALLOS:
        print(f"\033[31m{_FALLOS} fallo(s)\033[0m, {_AVISOS} aviso(s) — revisa lo de arriba antes de arrancar.")
        return 1
    print(f"Todo listo ({_AVISOS} aviso(s), 0 fallos).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
