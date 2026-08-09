# Arquitectura: hexagonal, puertos y adaptadores

## La regla de una sola frase

Las dependencias apuntan siempre hacia dentro: `adapters/` puede importar de
`application/` y `domain/`, `application/` puede importar de `domain/`, pero
`domain/` no importa de nada de fuera — ni SDK de LLM, ni driver de base de
datos, ni framework web. Todo lo externo se conecta a través de una interfaz
abstracta (un "puerto") que un adaptador concreto implementa. Esa única regla
es la que hace que el resto de este documento tenga sentido: cambiar Postgres
por otra base de datos, o Anthropic por Cohere, es escribir una clase nueva
que cumpla el mismo contrato, sin tocar el dominio ni el orquestador.

## Las cuatro capas, de dentro hacia fuera

### `domain/` — las reglas del negocio, sin nada más

Tres ficheros: `entities.py` (los datos: `Servicio`, `Profesional`, `Cliente`,
`Cita`, `Pedido`, todos `dataclass` sin lógica más allá de un par de
constructores de conveniencia como `Cita.nueva()`), `ports.py` (las
interfaces `ABC` que el dominio necesita — `RepositorioCitas`,
`ProveedorLLM`, `RepositorioConocimiento`, `SincronizadorCalendario`,
`NotificadorMensajes` — y nada más: el dominio declara qué necesita, nunca
cómo se satisface), y `use_cases.py` (las operaciones que sí saben *cómo*
resolver algo: `ComprobarDisponibilidad`, `CrearReserva`, `CancelarReserva`,
`RegistrarPedido`, `ConsultarConocimientoNegocio`).

Un caso de uso recibe sus puertos por constructor y solo llama a métodos de
esas interfaces — nunca instancia una clase concreta de `adapters/`. Por
ejemplo, `CrearReserva.__init__` (`domain/use_cases.py:107`) recibe
`servicios: RepositorioServicios`, `citas: RepositorioCitas`, etc., y su
`ejecutar()` solo sabe que puede llamarles `.obtener()`, `.guardar()` — no
sabe ni le importa si eso es un diccionario en memoria o una fila de
Postgres. Eso es lo que permite a `tests/01_domain` probar los casos de uso
enteros con fakes hechos a mano (clases mínimas que implementan el puerto
sobre un `dict`) en vez de una base de datos real.

### `application/` — el bucle conversacional

Esta capa sabe que existe un LLM con tool-calling y una conversación con
historial, pero no sabe nada de HTTP, Telegram, ni de qué proveedor de LLM
está detrás. Tres piezas:

- **`orchestrator.py`**: `OrquestadorAgente`, con el bucle
  `responder()`/`responder_stream()` (ver más abajo), y `SesionConversacion`
  — el estado de una conversación (`canal`, `usuario_id`, `historial`).
  `SesionConversacion` vive aquí y no en `domain/` a propósito: una sesión de
  chat es un concepto del orquestador, no del negocio.
- **`tools.py`**: `TOOLS_SCHEMA` (el "menú" de acciones que el LLM puede
  invocar, en el formato de tool-calling de Anthropic) y
  `EjecutorHerramientas`, que traduce cada llamada de tool en una invocación
  real a un caso de uso de `domain/`. Es el único puente entre lo que decide
  el LLM y lo que ejecuta el dominio — el LLM nunca toca `domain/` directamente.
- **`prompts.py`**: construye el system prompt a partir de
  `config/business.yaml` (`construir_system_prompt()`), incluyendo el
  catálogo de servicios/profesionales con sus IDs exactos (necesario porque
  las tools exigen IDs, no nombres en texto libre — ver el comentario en
  `_construir_catalogo()`) y la fecha de hoy en español, recalculada en cada
  turno (`_system_prompt_con_fecha()` en `orchestrator.py:46`).

Esta capa tiene también su propio puerto, `RepositorioSesiones`
(`application/ports.py`) — separado de `domain/ports.py` por el mismo motivo
que `SesionConversacion` vive aquí: no es una noción del negocio.

### `adapters/in_/` — traductores de entrada, sin lógica

`fastapi_app.py` y `telegram_bot.py`. Ninguno de los dos decide nada: reciben
un mensaje en el formato de su canal, obtienen o crean la
`SesionConversacion` correspondiente vía `RepositorioSesiones`, llaman a
`orquestador.responder()` (o `responder_stream()`), y traducen la respuesta
de vuelta al formato del canal — JSON para FastAPI, un mensaje de texto para
Telegram. Si algún día se añade WhatsApp, es un tercer fichero de este
mismo estilo, no un cambio en `application/`.

### `adapters/out/` — todo lo externo, detrás de un puerto

Cada pieza externa del sistema tiene aquí (al menos) una implementación de un
puerto de `domain/ports.py` o `application/ports.py`:

| Puerto | Implementación(es) | Selección |
|---|---|---|
| `ProveedorLLM` | `llm_anthropic.py`, `llm_cohere.py`, `llm_openai.py`, `llm_mock.py` | `PROVEEDOR_LLM` |
| `RepositorioCitas`/`Clientes`/`Pedidos` | `repositorios_memoria.py`, `repositorios_postgres.py` | `DATABASE_URL` |
| `RepositorioServicios`/`Profesionales` | `repositorios_memoria.py` (siempre — catálogo derivado del YAML) | — |
| `RepositorioConocimiento` | `vector_store.py` (Chroma) | — (siempre) |
| `RepositorioSesiones` | `repositorio_sesiones_memoria.py`, `repositorio_sesiones_redis.py` | `REDIS_URL` |
| `SincronizadorCalendario` | `calendario_google.py` | `GOOGLE_CALENDAR_CREDENTIALS_JSON` + `GOOGLE_CALENDAR_ID` |
| `NotificadorMensajes` | `notificador_telegram.py` | `TELEGRAM_BOT_TOKEN` |

`doc/003-modelo-datos.md` detalla el mapa de persistencia con más
profundidad; esta tabla es solo el resumen de "qué puerto, qué adaptador".

### `config/` y `main.py` — configuración y composición

`config/business.yaml` declara un negocio (nombre, tono, servicios,
profesionales, canales); `loader.py::cargar_config()` lo valida contra
`schema.py` (Pydantic) antes de convertirlo en las entidades de dominio —
así un YAML con un typo falla con un mensaje señalando el campo exacto, no
con un `KeyError` en el primer sitio que lo lee.

`main.py::construir_sistema()` es la **única** función de todo el repo que
conoce las clases concretas de `adapters/out/` — decide, según qué variables
de entorno están definidas, qué implementación de cada puerto instanciar, las
inyecta en los casos de uso de dominio, construye el `EjecutorHerramientas`
con todos ellos, y devuelve un `OrquestadorAgente` ya montado. Si mañana
Chroma se sustituye por Qdrant, o Telegram por WhatsApp, este es el único
fichero que necesita saberlo.

## El camino completo de un mensaje de chat

1. **Entrada**: `POST /chat` con `{"usuario_id": ..., "mensaje": ...}`
   (`adapters/in_/fastapi_app.py:62`), o un mensaje de Telegram
   (`adapters/in_/telegram_bot.py:24`). El adaptador obtiene la
   `SesionConversacion` existente (o crea una nueva) vía
   `RepositorioSesiones.obtener()`.
2. **`OrquestadorAgente.responder(sesion, mensaje)`** (`application/orchestrator.py:54`):
   añade el mensaje al historial, construye el system prompt con la fecha de
   hoy, y entra en un bucle acotado a `max_iteraciones_tool` (4 por defecto).
3. En cada vuelta del bucle, llama a `ProveedorLLM.generar_respuesta()` con
   el historial completo, `TOOLS_SCHEMA` y el system prompt. La respuesta
   normalizada trae bloques `{"type": "text", ...}` y/o
   `{"type": "tool_use", "name": ..., "input": ..., "id": ...}`.
4. Si no hay bloques `tool_use`, el texto es la respuesta final — sale del
   bucle.
5. Si los hay, cada uno se pasa a `EjecutorHerramientas.ejecutar(nombre,
   entrada, canal, usuario_id)` (`application/tools.py:88`), que despacha al
   caso de uso de `domain/` correspondiente (p. ej. `crear_reserva` →
   `CrearReserva.ejecutar()`) y devuelve un `dict` — nunca lanza una
   excepción hacia arriba: cualquier fallo del caso de uso se captura y se
   convierte en `{"error": str(exc)}`, para que el LLM pueda reaccionar en
   lenguaje natural en vez de que la conversación se corte con un 500.
6. El resultado de cada tool se añade al historial como un bloque
   `tool_result`, y el bucle vuelve al paso 3 — el LLM ve el resultado y
   decide si necesita otra herramienta o ya puede responder en texto.
7. Si se agotan las 4 iteraciones sin que el LLM converja a una respuesta de
   texto, se devuelve un mensaje de fallback genérico en vez de dejar la
   conversación colgada.
8. **Salida**: el adaptador de entrada persiste la sesión actualizada
   (`RepositorioSesiones.guardar()`) y devuelve la respuesta en el formato de
   su canal.

`responder_stream()` (`application/orchestrator.py:89`) es el mismo bucle,
pero cada llamada al LLM es a `generar_respuesta_stream()`, que va emitiendo
eventos `{"tipo": "delta_texto", ...}` según llega el texto y termina con uno
`{"tipo": "final", "content": [...]}` de la misma forma que
`generar_respuesta()`. El orquestador reenvía cada delta como un evento
`{"tipo": "delta"}` al llamador, y al cerrar el turno emite uno `{"tipo":
"done", "respuesta": ..., "fuentes": [...]}` con las fuentes RAG usadas en
todas las iteraciones del turno (deduplicadas por fichero de origen). Es lo
que consume `POST /chat/stream` para no dejar el chat "colgado" mientras el
modelo genera texto — ver `doc/008-api.md` para el shape exacto de los
eventos SSE.

## Por qué cada adaptador de LLM devuelve la misma forma

`ProveedorLLM.generar_respuesta()` no devuelve el objeto de respuesta crudo
del SDK de turno — devuelve un `dict` normalizado con el shape del wire
format de Anthropic (`{"content": [{"type": "text"/"tool_use", ...}]}`) como
formato canónico interno, sea cual sea el proveedor real detrás. Eso es lo
que permite que `OrquestadorAgente` no sepa ni le importe si está hablando
con Anthropic, Cohere o un mock: cada adaptador (`llm_cohere.py`,
`llm_openai.py`...) es el único punto del sistema que conoce las diferencias
reales de protocolo de su proveedor (Cohere, por ejemplo, separa `tool_plan`
del texto y usa mensajes `tool` dedicados) y las traduce a esa forma común
antes de devolver el control al orquestador.

## Los tests siguen la misma forma que la arquitectura

`tests/` está organizado en carpetas numeradas —
`01_domain` → `02_config` → `03_application` → `04_adapters_out` →
`05_adapters_in` → `06_main` — que siguen el mismo orden de dependencia que
las capas de arriba, de dentro hacia fuera. Los tests de dominio usan fakes
hechos a mano de los puertos (una clase mínima sobre un `dict`, no una base
de datos real); los de adaptadores mockean el SDK/cliente externo
correspondiente (`anthropic.Anthropic`, `chromadb.PersistentClient`,
`redis.Redis`...). Nada en la suite necesita credenciales reales, red, ni un
servicio externo corriendo — el mismo principio de aislamiento que organiza
el código de producción organiza también cómo se prueba.
