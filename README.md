# Orquestador agéntico — esqueleto hexagonal

Esqueleto funcional de un orquestador de agentes con arquitectura 
hexagonal (puertos y adaptadores), pensado para negocios "AI-first", 
donde el producto es el conocimiento del negocio y la capacidad de 
actuar sobre él vía agentes, expuesto sobre todo a través de canales 
conversacionales (chat, Telegram), mientras la web actúa como 
escaparate estático generado desde la misma fuente de conocimiento.

[Documentación](doc/001-intro.md) — narrativa más profunda que este README:
arquitectura, RAG, cómo extender a otro negocio, despliegue y referencia de
la API del chat.

## Estructura

```
domain/           → entidades, puertos (interfaces) y casos de uso.
                     Sin dependencias externas. Esto es lo único que
                     cambia de verdad entre negocios.
application/      → orquestador de agentes (síncrono y en streaming),
                     definición de tools, construcción del system
                     prompt.
adapters/in_/     → adaptadores de entrada: FastAPI (chat web, con
                     variante en streaming vía SSE), Telegram.
adapters/out/     → adaptadores de salida: LLM (Anthropic, Cohere o
                     un mock heurístico — intercambiables por
                     variable de entorno), vector store (Chroma) +
                     ingesta de Obsidian, repositorios en memoria
                     (sustituibles por Postgres sin tocar el dominio).
config/           → configuración declarativa por negocio (YAML)
                     + loader.
main.py           → composition root: conecta todas las piezas.
frontend/         → proyecto hermano (Astro + Preact), web pública +
                     chat en streaming; solo habla con el backend por
                     HTTP (ver "Frontend cliente" en CLAUDE.md).
```

## Puesta en marcha

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Copia .env.example a .env y rellena tus claves reales:
#   ANTHROPIC_API_KEY=sk-...          # si PROVEEDOR_LLM=anthropic (por defecto)
#   COHERE_API_KEY=...                # si PROVEEDOR_LLM=cohere (vale una trial key gratuita)
#   PROVEEDOR_LLM=anthropic|mock|cohere
#   TELEGRAM_BOT_TOKEN=...            # opcional, solo si quieres el canal Telegram
#   LOG_LEVEL=INFO                    # opcional, DEBUG|INFO|WARNING|ERROR
cp .env.example .env

# 1. Prepara tu vault de Obsidian con el conocimiento del negocio
#    (precios, políticas, horarios, FAQs) en ./vault_negocio/*.md

# 2. Indexa el vault en el RAG
python -m adapters.out.obsidian_ingest --vault ./vault_negocio

# 3. Ajusta config/business.yaml con tus servicios y profesionales

# 4. Arranca el backend
python main.py

# Verifica que arrancó bien, en otra terminal:
curl http://localhost:8000/health   # {"status": "ok"}

# 5. (opcional) Arranca la web pública + chat, en otra terminal
cd frontend && npm install && npm run dev   # http://localhost:4321
```

Alternativa a los pasos 4-5 (+ el panel interno): `./scripts/dev_up.sh`
verifica el entorno (dependencias, LLM, Chroma, Postgres/Redis si están
configurados) y arranca backend, frontend y panel en un solo comando —
ver `scripts/verificar_entorno.py` para correr solo la verificación.

El chat web queda disponible en `POST http://localhost:8000/chat`
(respuesta completa en JSON) y en `POST http://localhost:8000/chat/stream`
(streaming vía Server-Sent Events, el que usa `frontend/`), ambos con
body `{"usuario_id": "...", "mensaje": "..."}`.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Los tests viven en `tests/`, organizados en carpetas numeradas que
siguen el mismo orden de dependencia que la arquitectura hexagonal
(dominio → config → aplicación → adaptadores de salida →
adaptadores de entrada → composition root), de forma que se ejecutan
de dentro hacia afuera. No requieren ninguna API key, red ni
servicios externos: los adaptadores de salida se prueban mockeando
el SDK/cliente correspondiente (Anthropic, Cohere, Chroma).

## Lint

```bash
pip install -r requirements-dev.txt
ruff check .
```

Configurado en `pyproject.toml` (`[tool.ruff]`). `.github/workflows/ci.yml`
corre tanto `ruff check .` como `pytest` (jobs `lint` y `test`) en cada
push/PR a `main`.

## Cómo extender a otro negocio

1. Duplica `config/business.yaml` y ajusta servicios/profesionales/tono.
2. Crea un nuevo vault de Obsidian con el conocimiento de ese negocio
   e indícalo en `vault_obsidian`.
3. Vuelve a correr la ingesta contra ese vault.
4. Si el negocio necesita un caso de uso distinto (p. ej. "reservar
   mesa" en vez de "reservar cita"), añádelo en `domain/use_cases.py`
   y expón su tool en `application/tools.py` — el resto del sistema
   no cambia.

## Validación de la configuración

`config/business.yaml` se valida contra un schema (`config/schema.py`,
Pydantic) al cargarlo — `cargar_config()` falla con un mensaje claro
señalando el campo exacto (p. ej. `servicios.0.precio: Field required`)
en vez de un `KeyError` críptico cuando algún caso de uso intenta leer
un campo que falta o tiene un typo. Los campos con valor por defecto
razonable (`tono`, `canales`, `vault_obsidian`...) son opcionales; solo
`nombre` es obligatorio.

## Cómo sustituir un adaptador

Ejemplo: pasar de repositorios en memoria a Postgres.

1. Crea `adapters/out/repositorios_postgres.py` implementando las
   mismas interfaces de `domain/ports.py` (`RepositorioCitas`, etc.)
2. En `main.py`, cambia la instanciación en `construir_sistema()`.
3. Nada en `domain/` ni en `application/` se modifica.
