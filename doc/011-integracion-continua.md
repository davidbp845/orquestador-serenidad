# Integración continua (CI)

Este documento explica qué corre automáticamente en cada push/PR, por qué
cada comprobación tiene el alcance que tiene (nunca "todo el repo, sin más"),
y qué no está cubierto todavía a propósito. Complementa a
`doc/009-errores-conocidos.md` (avisos concretos que vas a ver correr) sin
duplicarlo.

## `.github/workflows/ci.yml`: qué corre en cada push/PR a `main`

Tres jobs, en paralelo, disparados en `push`/`pull_request` contra `main`:

| Job | Comando | Alcance |
|---|---|---|
| `lint` | `ruff check .` | Todo el repo, salvo `frontend/`, `vault_negocio/`, `chroma_data/`, `migrations/versions/` (excluidos en `pyproject.toml`, sección `[tool.ruff]`) |
| `mypy` | `mypy domain application` | Solo `domain/` y `application/` — **no** todo el repo |
| `test` | `pytest` | Toda la suite (`tests/`) |

Ninguno de los tres necesita credenciales ni red: `test` mockea cualquier SDK
externo (`anthropic.Anthropic`, `chromadb.PersistentClient`...) en vez de
llamarlo de verdad — es la misma garantía que documenta `CLAUDE.md` para
poder correr la suite sin `ANTHROPIC_API_KEY` ni un Chroma/Telegram real.

### Por qué `mypy` no cubre `adapters/` ni `main.py`

Esto no es una omisión, es una decisión explícita del **#19** (cerrado,
"parcial/incremental" tal como pedía el propio issue). `domain/` y
`application/` no dependen de ningún SDK externo, así que pasan limpio con
`disallow_untyped_defs` activo (`pyproject.toml`, `[[tool.mypy.overrides]]`).
Extender esa exigencia a `adapters/`/`main.py` se dejó para otra iteración:
`mypy .` sobre todo el repo da hoy decenas de errores ahí — incompatibilidades
de tipos entre `chromadb` y `sentence-transformers`, un `dict` con tipos
heterogéneos en `llm_cohere.py`, variables reasignadas entre implementaciones
en memoria/Postgres en `main.py::construir_sistema()` sin anotar con el tipo
del puerto. Si tocas algo en `adapters/`, `mypy .` en local puede sacar
errores preexistentes que no tienen nada que ver con tu cambio — no te
sorprenda que no coincida con lo que corre en CI (`doc/009-errores-conocidos.md`
tiene el detalle completo).

### Un incidente real: CI en verde no garantiza que alguien lo esté mirando

El **#42** es la lección concreta de por qué este documento existe. Un push
rutinario disparó un email de fallo de CI, pero el diagnóstico mostró que no
era un caso aislado: los 14 pushes anteriores a `main` (desde el commit que
añadió `scripts/evaluar_prompt.py`) llevaban **fallando el job `lint`** sin
que nadie lo notara, porque `ruff` no corre en ningún hook local de
pre-commit, solo en CI — y nadie estaba revisando el estado de cada run.
Causa: `E402` (el script inserta la raíz del repo en `sys.path` antes de
importar `application/`, necesario por cómo se ejecuta suelto — le faltaba su
propia excepción en `pyproject.toml`, ya existente para `main.py`/`tests/`)
y `UP037` (comillas innecesarias en un forward reference). El job `test`
nunca estuvo roto, solo `lint`. La lección no es "arreglar ese lint" —eso fue
trivial— sino que **CI en rojo silencioso durante dos semanas es posible en
un proyecto sin colaboradores activos revisando cada run**: vale la pena
correr `ruff check .` en local antes de cada push, no confiar solo en el
email de GitHub.

## Sin gate de merge todavía

`main` no tiene branch protection configurada — no hay ninguna comprobación
de CI marcada como obligatoria para poder mergear. Los tres jobs son hoy
puramente informativos: si `lint`/`mypy`/`test` fallan, el push a `main` se
completa igual (el propio #42 es la prueba). Esto es razonable a la escala
actual del proyecto (un solo desarrollador, sin PRs de terceros), pero es una
carencia real a resolver si el proyecto gana colaboradores — añadir
"Require status checks to pass before merging" en la configuración de la
rama en GitHub, sin que haga falta ningún cambio en `ci.yml` para ello.

## El job opcional de calidad de prompts: `evaluar-prompts.yml`

A diferencia de los tres jobs de arriba, `.github/workflows/evaluar-prompts.yml`
(#22) es deliberadamente distinto en tres aspectos, y por una razón concreta
en cada caso:

- **Disparo**: solo `workflow_dispatch` (manual, desde la pestaña Actions o
  `gh workflow run evaluar-prompts.yml`) — nunca en push ni en pull_request.
- **Gasta dinero real**: llama a la API de OpenAI (`PROVEEDOR_LLM=openai`)
  para evaluar el banco de "casos difíciles"
  (`tests/03_application/casos-dificiles/centro_masajes.yaml`) contra un
  modelo real, no contra un mock.
- **Gating opcional**: si el repo no tiene configurado el secret
  `OPENAI_API_KEY`, el job se completa en verde pero solo imprime un aviso —
  mismo patrón "opcional, degrada" que ya usa el proyecto para
  `DATABASE_URL`/`REDIS_URL`/`GOOGLE_CALENDAR_*`.

La razón de fondo, no solo el coste: los LLMs alojados no son 100%
deterministas ni con `temperature=0` (ver el hallazgo del **#32** en
`doc/010-prompt-engineering.md`) — meter esto en el flujo normal de cada PR
generaría fallos intermitentes sin relación con el cambio de código real.
`doc/010-prompt-engineering.md` tiene el contexto completo de qué evalúa este
job y el método para añadir casos nuevos al banco; este documento solo cubre
cómo encaja en la CI del repo.

## Reproducir CI en local antes de hacer push

Los tres jobs obligatorios, en el mismo orden en que corren en CI:

```bash
ruff check .              # job lint
mypy domain application   # job mypy
pytest                    # job test
```

Y, si el cambio toca `config/business.yaml` o cualquier superficie de prompt
(ver `doc/010-prompt-engineering.md`), el job opcional de calidad, en local
y sin depender de que exista el secret en GitHub:

```bash
export PROVEEDOR_LLM=openai   # o el proveedor real que tengas configurado
python scripts/evaluar_prompt.py
```
