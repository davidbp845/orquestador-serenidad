# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A hexagonal-architecture (ports & adapters) skeleton for an "agentic orchestrator" — a chat-first AI assistant for AI-first small businesses (the example config is a massage center). The same domain/application code serves any business vertical; only `config/business.yaml` and the Obsidian vault of business knowledge change. Code, comments, and identifiers are in Spanish; keep new code consistent with that.

## Commands

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-...
export TELEGRAM_BOT_TOKEN=...   # optional, only if canales.telegram is enabled
export PROVEEDOR_LLM=mock       # optional: anthropic (default) | mock (no key, no tokens spent) | cohere (needs COHERE_API_KEY) | openai (needs OPENAI_API_KEY)
export COHERE_API_KEY=...       # only if PROVEEDOR_LLM=cohere; a free trial key works for prototyping
export OPENAI_API_KEY=...       # only if PROVEEDOR_LLM=openai
export LOG_LEVEL=DEBUG          # optional, default INFO

# Index the Obsidian vault into the RAG (Chroma) before first run
python -m adapters.out.obsidian_ingest --vault ./vault_negocio

export DATABASE_URL=postgresql://user:pass@localhost/orquestador  # optional; unset = citas/clientes/pedidos in-memory
alembic upgrade head  # only if DATABASE_URL is set — applies/creates the Postgres schema

export GOOGLE_CALENDAR_CREDENTIALS_JSON=/path/to/service-account.json  # optional, both needed together
export GOOGLE_CALENDAR_ID=business@group.calendar.google.com          # unset = reservations aren't synced to a calendar
export GOOGLE_CALENDAR_TIMEZONE=Europe/Madrid                          # optional, default Europe/Madrid; IANA tz name

export REDIS_URL=redis://localhost:6379  # optional; unset = conversation sessions live in-process, not persisted

# Run the system (starts FastAPI on :8000, and Telegram polling if configured)
python main.py

# Tests
pip install -r requirements-dev.txt
pytest                                  # run the whole suite
pytest tests/01_domain                  # run one layer only
pytest tests/03_application/test_orchestrator.py::test_da_mensaje_de_fallback_tras_agotar_iteraciones  # single test
```

`ruff` is configured (`pyproject.toml`, `[tool.ruff]`) and wired into CI (`.github/workflows/ci.yml`, `lint` job) — run `ruff check .` before committing. `mypy`/type-checking is still not set up; don't assume it's wired up.

There's also a sibling frontend project (`frontend/`, Astro + Preact) that talks to this backend over HTTP — see [Frontend cliente](#frontend-cliente-frontend) below for how to run it alongside `main.py`.

### Tests

`tests/` mirrors the dependency order of the architecture, and directories are numbered (`01_domain`, `02_config`, `03_application`, `04_adapters_out`, `05_adapters_in`, `06_main`) so the suite runs innermost-layer-first — the same order you'd want to debug a failure in. Domain tests use small hand-written fakes of the ports instead of the real adapters; adapter tests mock the external SDK/client (`anthropic.Anthropic`, `chromadb.PersistentClient`) rather than hitting real network or requiring credentials — nothing in the suite needs `ANTHROPIC_API_KEY` set or a running Chroma/Telegram backend. A root `conftest.py` puts the repo root on `sys.path` so `domain`/`application`/`adapters`/`config` are importable without installing the project as a package.

One gotcha the tests work around: `adapters/in_/fastapi_app.py` defines `app` and `_sesiones` at module scope, and `crear_router()` adds routes to that same shared `app` on every call — calling it twice registers duplicate routes, and Starlette keeps routing to whichever was registered first. `tests/05_adapters_in/test_fastapi_app.py` reloads the module per test to get an isolated `app`/`_sesiones` each time; keep that pattern if you add more tests there.

The web chat endpoint is `POST http://localhost:8000/chat` with body `{"usuario_id": "...", "mensaje": "..."}`, returning the full reply as JSON. There's also a streaming variant, `POST /chat/stream` (SSE) — see [Frontend cliente](#frontend-cliente-frontend) below.

## Architecture

Strict hexagonal architecture with dependency direction always pointing inward. Read `domain/ports.py` first — it's the contract every adapter must satisfy, and the fastest way to see the whole system's shape.

- **`domain/`** — entities (`entities.py`), abstract ports (`ports.py`), and use cases (`use_cases.py`). Pure Python, zero external dependencies (no LLM SDK, no DB driver, no web framework). This is the only layer that meaningfully differs between businesses (e.g. "book a table" instead of "book an appointment").
- **`application/`** — the agent orchestrator (`orchestrator.py`, which also defines `SesionConversacion`), the tool schema + tool executor that bridges LLM tool calls to domain use cases (`tools.py`), system-prompt construction from business config (`prompts.py`), and this layer's own port, `RepositorioSesiones` (`ports.py` — separate from `domain/ports.py` because `SesionConversacion` is an application-layer concept, not a domain one). Knows about the LLM tool-calling protocol but not about any specific channel (web vs Telegram) or specific LLM vendor.
- **`adapters/in_/`** — inbound adapters (FastAPI web chat, Telegram bot). Pure translation layers: HTTP/Telegram ↔ `OrquestadorAgente.responder()`/`responder_stream()`. No business logic ever belongs here. `fastapi_app.py` has `CORSMiddleware` enabled for `http://localhost:5173`, `:3000`, and `:4321` (typical Vite/Astro dev origins, the last one for `frontend/`) — add any other dev origins there.
- **`adapters/out/`** — outbound adapters. Four implementations of `ProveedorLLM`, selected via `PROVEEDOR_LLM=anthropic|mock|cohere|openai` (default `anthropic`) in `main.py::construir_sistema()`: `llm_anthropic.py` (Anthropic SDK), `llm_mock.py` (`ProveedorLLMMock`, a heuristic fake — no network calls, used for frontend/client development without spending API tokens), `llm_cohere.py` (`ProveedorLLMCohere`, Cohere's Chat API v2 — useful for prototyping with real, non-heuristic responses on a free trial key; Cohere's message/tool-calling shape is structurally different from Anthropic's, so this adapter is the only place that translates between them, and the trial key is capped at 1000 calls/month and explicitly not for production), and `llm_openai.py` (`ProveedorLLMOpenAI`, OpenAI's Chat Completions API — added in issue #34 as a second real, non-mock option to cross-check whether response-quality bugs seen under Cohere were provider-specific or systemic; same translation-layer role as `llm_cohere.py`, and the same `temperature=0` convention for tool-calling reliability). Beyond the LLM: `vector_store.py` (Chroma implementing `RepositorioConocimiento`), `obsidian_ingest.py` (chunks and indexes the Obsidian vault — the vault is the single source of truth for business knowledge/FAQs/pricing), `repositorios_memoria.py` (in-memory repos for citas/clientes/pedidos/servicios/profesionales — always used for servicios/profesionales, since those are catalog data derived from `business.yaml` on every boot), `repositorio_sesiones_memoria.py` + `repositorio_sesiones_redis.py` (two implementations of `RepositorioSesiones` — in-memory, equivalent to what the inbound adapters used to do themselves, and Redis-backed, JSON-serializing `SesionConversacion.historial`; selected in `main.py::construir_repositorio_sesiones()` based on `REDIS_URL`, same optional/degrades-to-today's-behavior pattern as `DATABASE_URL`), `db_models.py` + `repositorios_postgres.py` (SQLModel-backed Postgres repos for citas/clientes/pedidos, the state that must survive a restart; used instead of the in-memory ones whenever `DATABASE_URL` is set in `main.py::construir_sistema()`), `calendario_google.py` (`SincronizadorCalendarioGoogle`, implements the `SincronizadorCalendario` port — mirrors each `Cita` as a Google Calendar event via a service account; only wired in when both `GOOGLE_CALENDAR_CREDENTIALS_JSON` and `GOOGLE_CALENDAR_ID` are set, otherwise `CrearReserva`/`CancelarReserva` get `calendario=None` and skip sync entirely — same "optional, degrades to today's behavior" pattern as `DATABASE_URL`; sync is best-effort, a Calendar API failure never blocks a reservation from being created in the app's own store).
- **`config/`** — `business.yaml` declares one business's services, professionals, tone, and channels. `loader.py::cargar_config()` validates it against `schema.py` (Pydantic) before parsing it into domain entities — a missing/mistyped field fails fast with a clear message (e.g. `servicios.0.precio: Field required`) instead of a `KeyError` wherever that field happens to get read first. Only `nombre` is required; everything else has a sensible default.
- **`main.py`** — the composition root. This is the *only* file allowed to know about concrete implementations; it wires adapters into use cases into the orchestrator. Swapping an adapter (e.g. Chroma → Qdrant, in-memory → Postgres, Telegram → WhatsApp) means writing a new class satisfying the same port and changing its instantiation here — nothing in `domain/` or `application/` changes.
- **`migrations/`** — Alembic migrations for the Postgres schema (`db_models.py`'s `SQLModel.metadata`). Needs `DATABASE_URL` set (`migrations/env.py` reads it, loading `.env` the same way `main.py` does). New migration after changing `db_models.py`: `alembic revision --autogenerate -m "..."` — always read the generated file before applying, autogenerate doesn't catch everything (renames, some constraint changes).

### Request flow

Inbound adapter → `OrquestadorAgente.responder(sesion, mensaje)` → calls the LLM with `TOOLS_SCHEMA` → for each `tool_use` block, `EjecutorHerramientas.ejecutar()` dispatches to the matching domain use case → tool results are fed back to the LLM → loop (bounded by `max_iteraciones_tool`, default 4) until the LLM replies with plain text.

`responder_stream()` is the same loop, used by the web `POST /chat/stream` endpoint: instead of returning once at the end, it yields `delta` events as text streams in from the LLM and a final `done` event carrying the full reply plus any RAG `fuentes` (source vault notes) used that turn. Every `ProveedorLLM` adapter must implement both `generar_respuesta()` (one-shot) and `generar_respuesta_stream()` (yields `delta_texto` events, then one `final` event with the same content-block shape `generar_respuesta()` returns) — see [Conventions worth knowing](#conventions-worth-knowing).

### Extending to a new business

1. Duplicate `config/business.yaml`, adjust services/professionals/tone.
2. Create a new Obsidian vault with that business's knowledge, point `vault_obsidian` at it, and re-run `obsidian_ingest`.
3. If the business needs a genuinely different use case (e.g. "reserve a table" instead of "reserve an appointment"), add it in `domain/use_cases.py` and expose a corresponding tool in `application/tools.py` (both the `TOOLS_SCHEMA` entry and the dispatch branch in `EjecutorHerramientas.ejecutar`). Nothing else in the system needs to change.

### Replacing an adapter

Example: swapping in-memory repos for Postgres — implement the same interfaces from `domain/ports.py` (`RepositorioCitas`, etc.) in a new `adapters/out/repositorios_postgres.py`, then change the instantiation in `main.py::construir_sistema()`. Domain and application code stay untouched.

## Frontend cliente (`frontend/`)

Sibling project (Astro + Preact + Tailwind v4) at the repo root, independent of the Python backend except for the chat's HTTP calls. Not part of the `orquestador` package — no Python module imports or references it.

```bash
cd frontend
npm install
npm run dev     # http://localhost:4321
npm run build
```

- **Public content**: `frontend/src/content.config.ts` defines a content collection (`vault`) that reads `../vault_negocio` directly (the same vault `obsidian_ingest.py` indexes for the RAG) via Astro's `glob()` loader. A note becomes a public page/card only if its frontmatter has `publicar_web: true` (defaults to `false` if absent) — the rest of the frontmatter (`categoria`, `tags`) passes through as-is. Changing what's published is just editing a note's frontmatter, no code changes.
- **Business name/tone**: `frontend/src/lib/negocio.ts` reads `config/business.yaml` at build time (Node, not in the browser) so the business name isn't hand-duplicated in the frontend — same file the backend uses.
- **Chat streaming**: `POST /chat/stream` (alongside the existing non-streaming `POST /chat`, still used by Telegram) returns `text/event-stream` with `event: delta` frames (incremental text), `event: fuentes` (vault notes the RAG used for that reply, already filtered to `publicar_web: true` — see `ConsultarConocimientoNegocio` in `domain/use_cases.py`), `event: done` (full reply), or `event: error` if something fails mid-stream. The chat island (`frontend/src/components/chat/`) parses those frames by hand via `fetch` + `ReadableStream` (not `EventSource`, since it doesn't support `POST` with a body).
- **Chat↔content link**: on receiving `event: fuentes`, the chat dispatches a `CustomEvent('orquestador:fuentes', ...)` on `window`; `GridContenido.astro` listens for it and highlights the card whose `data-fuente` matches the source's filename.
- Serving the frontend in production needs `npm run build` + static hosting of `frontend/dist/`, with `PUBLIC_API_BASE_URL` (`frontend/.env`) pointing at the real backend.
- **Discreet link to the internal panel** (issue #58): `PUBLIC_MOSTRAR_PANEL=true` (`frontend/.env`, unset/empty by default) shows a "Panel interno" link in the footer (`Pie.astro`) pointing at `PUBLIC_PANEL_URL` (default `http://localhost:8501`, Streamlit's default port). Opt-in explicit env var rather than inferred from `import.meta.env.DEV` or the URL — same "opt-in, not inferred" philosophy as `ENTORNO_LOCAL` in `panel_empleados/`, so the link can't leak into a production build accidentally generated on a dev machine. Since `frontend/` builds fully static (Astro `output: 'static'`), the condition lives in the `.astro` frontmatter so the `<a>` node is entirely absent from the built HTML when unset, not just hidden with CSS.

## Panel interno (`panel_empleados/`)

Streamlit app for employees/owner (issue #10): today's agenda (all professionals, read-only), pending orders with status changes, and a "reindex RAG" button. Run with `streamlit run panel_empleados/streamlit_app.py`. It calls the domain use cases directly — no orchestrator, no LLM — building its own repos the same way `main.py::construir_sistema()` does (Postgres if `DATABASE_URL` is set, else in-memory, cached via `@st.cache_resource` so they survive Streamlit's rerun-per-interaction model). Optional `PANEL_EMPLEADOS_PASSWORD` gates access behind a single shared password (`secrets.compare_digest`); unset, the panel opens with no gate. Mobile-first by construction rather than by CSS: navigation lives in `st.sidebar`, which Streamlit already collapses on narrow viewports, and content is stacked cards (`st.container(border=True)`) instead of tables/columns to avoid horizontal scrolling. `.streamlit/config.toml` sets `client.toolbarMode = "minimal"` to hide Streamlit's default "Deploy" button/hamburger menu — this is an internal panel, not something meant for Streamlit Community Cloud.

## Conventions worth knowing

- `ProveedorLLM.generar_respuesta` returns a plain dict (not the Anthropic SDK's response object) — this keeps the orchestrator decoupled from the Anthropic SDK's types, so swapping LLM providers only requires a new adapter matching this same normalized shape. `generar_respuesta_stream` follows the same principle: whatever the vendor's streaming event format looks like (Anthropic's `content_block_delta`, Cohere's `content-delta`/`tool-call-*`...), the adapter must translate it into `{"tipo": "delta_texto", "texto": ...}` events followed by one `{"tipo": "final", "content": [...]}` — the `content` list uses the exact same block shape as `generar_respuesta`, so the orchestrator's tool-dispatch logic doesn't care which adapter produced it.
- `publicar_web: true` is a vault-note frontmatter convention, not a schema Python enforces: `obsidian_ingest.py` passes all frontmatter through to Chroma metadata untouched, so it's `ConsultarConocimientoNegocio` (`domain/use_cases.py`) that reads it back out to decide which RAG sources are safe to surface to the frontend, and the Astro content collection (`frontend/src/content.config.ts`) that decides which notes become public pages. A note not marked `publicar_web: true` can still be used by the LLM to answer in text — it just never appears as a clickable "fuente" or a public page.
- Day-of-week lookups use `date.weekday()` mapped through `_DIAS_SEMANA_ES` in `domain/use_cases.py`, not `strftime('%A')`, because the latter depends on OS locale and won't reliably match the Spanish day names used in `config/business.yaml`.
- Conversation sessions (`SesionConversacion`) are persisted through the `RepositorioSesiones` port (`application/ports.py`), injected into both inbound adapters (`crear_router()`, `crear_bot()`) from `main.py`. `OrquestadorAgente.responder()`/`responder_stream()` mutate `sesion.historial` in place, so the call pattern in both adapters is `obtener()` before calling the orchestrator, `guardar()` after (in a `finally` for the streaming endpoint, so a partial history still persists if the LLM call fails mid-stream). Without `REDIS_URL`, sessions live in an in-process dict (`RepositorioSesionesMemoria`) and don't survive a restart or share across processes — same caveat as before, just behind a swappable port now instead of hardcoded in the adapters.
- `EjecutorHerramientas.ejecutar` catches all exceptions and returns `{"error": str(exc)}` rather than raising, so tool failures become a message the LLM can react to instead of crashing the conversation.
- `main.py` sets up logging via `logging.basicConfig()` and explicitly caps `httpx`/`httpcore`/`urllib3`/`huggingface_hub` at `WARNING` — those libraries (pulled in transitively by `chromadb`/`sentence-transformers`) log one `INFO` line per HTTP request when downloading the embedding model, which drowns out the app's own logs otherwise. If you add a new dependency that turns out to be similarly chatty at `INFO`, silence it the same way rather than dropping `LOG_LEVEL` to `WARNING` globally.

## Open-core vs SaaS Premium boundary

This repo is the OPEN-CORE FUNCTIONAL SKELETON of the agentic
orchestrator (initial use case: massage center, designed to be
reusable across businesses). It's genuinely functional, not a toy
app — but it is NOT the final product. The SaaS version with premium
functionality lives in a separate private fork.

The skeleton must demonstrate the architecture and be genuinely
useful for a real small business, but without the capabilities that
constitute the SaaS's competitive/commercial advantage.

Before implementing any new functionality, check whether it fits the
"Premium functionality" list (see `002_limites_producto.md` in the
project context). If it does:

1. Do NOT implement the full logic in this repo.
2. Explicitly flag it in the response: "This is premium functionality
   (reserved for the SaaS), I'm not implementing it here in the
   skeleton."
3. If it makes sense to keep the hexagonal architecture honest and
   extensible, offer at most one of these two options (ask which one
   I prefer before doing either — never decide unilaterally):
   a) The port/interface in `domain/ports.py`, with no real
      implementation.
   b) A "stub" adapter that raises `NotImplementedError` or returns a
      mock, with an explicit comment:
      `# PREMIUM: real implementation only in SaaS fork`
4. Ask whether I want that stub, or would rather the code not be
   touched at all.

This rule applies EVEN IF I request the functionality directly
without mentioning it's premium. Checking against the list is
proactive and your responsibility — it doesn't depend on me labeling
it every time.

If you're unsure whether something is premium and the list doesn't
make it clear, ask me instead of assuming.

## Autonomous Operation Policy

This project is fully tracked in git. Local, reversible changes can always be undone
with `git reset --hard` or `git checkout`, so Claude should NOT ask for approval
before performing the actions listed below. Act autonomously and only report back
with a summary when done.

### Safe to do without asking (local, reversible via git)
- Read, search, and analyze any file in the repository.
- Create, edit, or delete files within the project working tree.
- Implement new features, refactor code, or fix bugs across any number of files.
- Run the test suite (`npm test`, `pytest`, etc.) and any linters/formatters/type checkers.
- Run build commands (`npm run build`, `tsc`, etc.).
- Install/update dependencies declared in the project (`npm install`, `npm ci`,
  `pip install -r requirements.txt`) as long as they modify only local
  lockfiles/manifests already tracked in git.
- Run arbitrary local npm/yarn/pnpm scripts defined in `package.json`.
- Create local git branches, `git add`, `git commit`, view `git diff`/`git log`/`git status`,
  and stash changes.
- Read GitHub issues and pull requests (`gh issue list/view`, `gh pr list/view/diff`).
- Create or comment on GitHub issues to report progress or findings.
- Run scripts/commands that only read data (no external side effects), e.g. hitting a
  read-only API, querying a local/dev database.
- Run `alembic upgrade head` against a local `DATABASE_URL` (additive schema change,
  not data-destructive).
- Run a full **sprint**: for every GitHub issue currently at project Status = Ready,
  implement it end-to-end (code, tests, `ruff check`), commit locally, comment on the
  issue documenting what was done and how it was verified, then close it and move
  Status to **In review** (never Done) — following the documented open/close cycle.
  Move on to the next Ready issue without pausing for confirmation in between. Still
  stop for anything listed under "Blocked entirely" or "Still requires explicit
  confirmation" below (e.g. `git push`, PR merges) — report back with a summary once
  the batch of Ready issues is exhausted or one of those is hit.

### Blocked entirely (enforced in `.claude/settings.json`, not even askable in-session)
- `git push --force` to any remote.
- `git reset --hard` / `git clean -fd` — even when nothing uncommitted is at risk. If one
  of these is genuinely the right fix, ask me to run it myself rather than trying to work
  around the block.

### Still requires explicit confirmation
- `git push` (non-force) to any remote, and merging pull requests.
- Deleting or renaming remote branches, closing or reopening GitHub pull requests,
  reopening GitHub issues, changing labels/milestones in bulk. (Closing an issue after
  finishing and verifying its work is covered by the sprint workflow above, not this.)
- Publishing packages (`npm publish`), tagging releases, or anything that touches
  a production/staging environment or deployment pipeline.
- Modifying CI/CD configuration, secrets, environment variables, or `.env` files
  containing credentials.
- Installing global packages or anything that changes the system outside the
  project directory.
- Running destructive database migrations (`alembic downgrade`, manual schema/data
  changes) or any command against a production/shared (non-local) database.
- Running the test suite or the app in a way that writes to a *local* Postgres
  `DATABASE_URL` (inserts/updates/deletes citas/clientes/pedidos) — that data isn't
  tracked in git, so it can't be undone with `git reset --hard`.
- Running the app (`python main.py`) or any flow that exercises `CrearReserva`/
  `CancelarReserva` while `GOOGLE_CALENDAR_CREDENTIALS_JSON`/`GOOGLE_CALENDAR_ID`
  are set — this syncs a real, externally-visible Google Calendar event.
- Running the app while `TELEGRAM_BOT_TOKEN` is set — this starts live polling
  and can interact with real Telegram users.
- Editing this `CLAUDE.md` file itself.

### General principle
If an action is fully contained inside this git repository and any mistake can be
undone with `git reset --hard` or by deleting an untracked file, proceed without
asking. If an action affects anything outside the repo (remote git history, GitHub
issue/PR state, external services, published artifacts, production systems),
ask for confirmation first.
