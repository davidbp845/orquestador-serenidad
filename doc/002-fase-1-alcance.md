# Qué hace (y hará) la aplicación en Fase I

> Recoge, organizado por módulo, todo lo que compone el
> alcance de Fase I: lo ya construido y verificado, y lo que queda planificado
> (con su issue de GitHub correspondiente), junto con qué pieza tecnológica
> resuelve cada cosa y por qué se eligió esa pieza y no otra.

## El objetivo de fondo

Fase I no es "construir un chatbot". Es construir un **esqueleto open-core** de
un orquestador agéntico que sea genuinamente útil para un negocio real —el caso
de ejemplo es un centro de masajes, pero la frontera entre lo que cambia por
negocio (`config/business.yaml`, el vault de Obsidian) y lo que no cambia nunca
(dominio, orquestador, adaptadores) es el eje de todo el diseño. Cada decisión
tecnológica de las que siguen está tomada pensando en esa frontera: que mañana
alguien pueda copiar el repo, cambiar un YAML y una carpeta de notas, y tener
un asistente para una peluquería o un restaurante sin tocar una línea de
`domain/` ni de `application/`.

La arquitectura es hexagonal (puertos y adaptadores) de forma estricta: el
dominio no importa nada de fuera (ni SDK de LLM, ni driver de base de datos, ni
framework web), y todo lo externo se conecta a través de una interfaz
(`domain/ports.py`, y su equivalente de aplicación, `application/ports.py`)
que un adaptador concreto implementa. Eso es lo que permite que buena parte de
esta lista de "tecnología que resuelve cada cosa" pueda cambiar sin que el
resto del sistema se entere — Postgres en vez de memoria, Redis en vez de un
dict, OpenAI en vez de Anthropic, todo son adaptadores intercambiables detrás
del mismo contrato.

---

## 1. El núcleo del negocio (dominio)

**Qué resuelve:** las reglas que no dependen de ningún negocio concreto, solo
del *tipo* de negocio que reserva citas y gestiona un catálogo. Aquí vive la
noción de que un servicio tiene una duración, que un profesional tiene un
horario semanal, que dos citas no pueden solaparse, que un pedido tiene líneas
y un estado que avanza.

**Tecnología:** Python puro, sin ninguna dependencia externa (`domain/`). Cinco
entidades (`Servicio`, `Profesional`, `Cliente`, `Cita`, `Pedido`) modeladas
como `dataclass`, y cinco casos de uso (`ComprobarDisponibilidad`,
`CrearReserva`, `CancelarReserva`, `RegistrarPedido`,
`ConsultarConocimientoNegocio`) que son las únicas piezas del sistema que
saben *cómo* se resuelve una reserva o un pedido. La elección de no usar ningún
framework aquí (ni siquiera un ORM) es deliberada: es la capa que sobrevive
intacta si mañana cambia la base de datos, el LLM o el canal de mensajería —
issue #1, ya cerrado, es literalmente "que exista esta frontera".

Un matiz importante sobre disponibilidad: `ComprobarDisponibilidad` no
consulta un calendario de huecos precalculado, los *calcula* — recorre el
horario semanal del profesional en bloques de 15 minutos y descarta los que
solapan con citas ya existentes. Es una implementación deliberadamente simple
(no hay conceptos de descansos, buffers entre citas, o duración variable por
profesional) que basta para el alcance de Fase I y que un negocio con reglas
de agenda más complejas tendría que extender.

Una pieza de este módulo quedó señalada como pendiente de mejora y ya se
resolvió — decidiendo explícitamente no construirla: **#8 — Tabla
profesional_servicio (N:M)** (cerrado, no aplica) planteaba que la relación
entre un profesional y los servicios que ofrece, hoy una lista de IDs dentro
de la propia entidad `Profesional` (`servicios_ids: list[str]`), pasara a ser
una relación N:M de verdad en Postgres, con tabla intermedia. Pero esa tabla
solo tiene sentido si el catálogo (servicios/profesionales) deja de derivarse
de `business.yaml` en cada arranque y pasa a persistirse en Postgres — y esa
decisión, evaluada explícitamente, se descartó por ahora: la ventaja (poder
editar el catálogo en caliente desde un panel admin sin redeploy) no compensa
el coste (replicar en otro sitio la validación de `config/schema.py`, más
`RepositorioServiciosPostgres`/`RepositorioProfesionalesPostgres` nuevos) sin
que exista todavía una necesidad concreta de esa edición en caliente. Mientras
nadie la pida, `business.yaml` como fuente de verdad del catálogo sigue siendo
lo más simple.

**#36 — Revisar modelo de datos** (cerrado): en la práctica era un documento
de referencia, no una tarea con entregable de código, así que se movió a
`doc/003-modelo-datos.md` — mapa de dónde vive cada entidad hoy (memoria,
Postgres, Redis, Google Calendar) y qué cambió desde la primera foto. Dos
preguntas de fondo que ese issue dejaba abiertas siguen sin decidirse y no
tienen issue propio todavía: si el modelo actual (una única entidad
`Servicio` sin variantes, un `Cliente` sin historial estructurado más allá de
`notas: str`) aguanta un negocio real más allá del centro de masajes, y qué
pasa con las sesiones en memoria en un despliegue con más de un worker sin
Redis delante.

## 2. El orquestador de agentes (aplicación)

**Qué resuelve:** el bucle conversacional — recibir un mensaje, decidir si
hace falta consultar disponibilidad o crear una reserva, ejecutar esa acción
contra el dominio, y devolver una respuesta en lenguaje natural. Es la pieza
que traduce entre "lo que dice un cliente por chat" y "una llamada a
`CrearReserva.ejecutar(...)`".

**Tecnología:** tool-calling nativo del LLM (`application/orchestrator.py` +
`application/tools.py`), no un framework de agentes de terceros (LangChain,
CrewAI...). La razón es la misma frontera de siempre: el tool-calling es un
protocolo suficientemente estándar entre proveedores (Anthropic, Cohere,
OpenAI lo implementan con formas distintas pero equivalentes) como para no
necesitar una capa de abstracción adicional — cada adaptador de LLM ya hace
esa traducción él mismo (ver sección 4). `EjecutorHerramientas` es el único
puente entre lo que decide el LLM y lo que ejecuta el dominio: cuatro
herramientas expuestas hoy — `comprobar_disponibilidad`, `crear_reserva`,
`registrar_pedido`, `consultar_conocimiento_negocio` — cada una resuelta
contra su caso de uso correspondiente.

Vale la pena una nota honesta aquí: el caso de uso `CancelarReserva` existe en
el dominio y está conectado en el executor, pero **no** está expuesto como
herramienta en `TOOLS_SCHEMA` — hoy el LLM no puede cancelar una cita por
chat. No hay un issue abierto específicamente para esto; queda documentado
aquí porque es relevante para saber qué puede hacer el asistente hoy, no solo
qué existe en el dominio.

El bucle está acotado a `max_iteraciones_tool = 4` (evita que el LLM entre en
un ciclo de llamadas a herramientas sin converger a una respuesta) y cada
turno reinyecta la fecha de hoy en el system prompt
(`formatear_fecha_es(date.today())`) — sin esto, el LLM no tiene ninguna forma
fiable de saber qué día es "hoy" y resuelve fechas relativas como "mañana" con
años incorrectos. Este fix nació de un bug real, no de precaución teórica: el
#32 documenta un caso concreto donde el modelo, sin esta ayuda, calculó
"viernes 7 de agosto" como si fuera 2023 en vez de 2026, y estuvo a punto de
confirmar una reserva con una fecha completamente distinta a la pedida. El
mismo prompt también incluye el catálogo completo de servicios y
profesionales con sus IDs internos exactos (`_construir_catalogo()`) — el #31
documentó el problema simétrico: sin esto, el LLM solo conocía los servicios
por su nombre humano (vía RAG) y adivinaba el ID al llamar a una herramienta,
fallando contra el dominio.

**Streaming (#6, cerrado):** además de `responder()` (respuesta completa de
una vez), existe `responder_stream()`, que emite el texto incrementalmente a
medida que llega del LLM (eventos SSE `delta`/`fuentes`/`done`) — es lo que
consume el frontend para que el chat no se sienta "colgado" mientras el modelo
genera la respuesta.

**Prompt engineering específico de negocio (#21, Backlog):** aunque el
protocolo de tool-calling ya funciona, la *calidad* de las respuestas en
situaciones comerciales (cliente insatisfecho, comparación de precios con la
competencia, dudas de salud antes de reservar) sigue siendo trabajo de
afinado de prompt, no de código — `config/business.yaml` ya tiene un campo
`instrucciones_comerciales` con reglas concretas (cómo tratar molestias sin
sonar a consulta médica, cómo no "despedirse" nunca de un cliente que amenaza
con irse a la competencia), pero #21 es el hueco abierto para seguir
iterando sobre esto de forma sistemática. **#22 — Automatizar tests de
prompts difíciles** (Backlog) es la pieza complementaria: hoy verificar que el
asistente responde bien a estos casos es manual (como se hizo para verificar
los fixes de #31/#32 contra el proveedor OpenAI); automatizarlo significa
poder detectar una regresión de tono/calidad sin tener que probarlo a mano
cada vez.

## 3. Conocimiento del negocio (RAG)

**Qué resuelve:** preguntas informativas — precios, horarios, políticas de
cancelación, ubicación — que no son una acción de dominio sino un dato que
vive en la documentación del negocio, y que no queremos hardcodear en el
prompt ni en el código porque cambia por negocio y con el tiempo.

**Tecnología:** un vault de [Obsidian](https://obsidian.md) (`vault_negocio/`,
notas Markdown con frontmatter YAML) como única fuente de verdad, indexado en
[Chroma](https://www.trychroma.com/) (`adapters/out/vector_store.py`,
`adapters/out/obsidian_ingest.py`) usando embeddings de
`sentence-transformers` (modelo multilingüe, importante porque el contenido
está en español). La elección de Obsidian como formato de entrada —en vez de,
por ejemplo, un CMS o una base de datos de FAQs— es deliberada: es la
herramienta que un dueño de negocio no técnico ya podría usar para escribir y
organizar notas, sin necesitar tocar código para actualizar un precio o
añadir una política nueva (issue #3, cerrado).

El puente entre el LLM y este índice es la herramienta
`consultar_conocimiento_negocio`, resuelta por el caso de uso
`ConsultarConocimientoNegocio`: busca los fragmentos más relevantes para la
consulta y se los da al modelo como contexto. Una convención de frontmatter
importante aquí, `publicar_web: true`, decide qué notas pueden aparecer como
"fuente" citable en el frontend público — una nota sin esa marca puede seguir
alimentando la respuesta del LLM en texto libre, pero nunca sale como enlace
clicable, lo que da control fino sobre qué información interna es apta para
mostrarse como contenido público.

**Cerrado sin implementar — #23 — Crear token de Hugging Face Hub.** Hoy la
descarga del modelo de embeddings funciona sin autenticación, pero con rate
limits más bajos y un aviso en el log en cada arranque (`Warning: You are
sending unauthenticated requests to the HF Hub...`, visible en
`logs/backend.log` si se arranca vía `scripts/dev_up.sh`, o directamente en
la terminal con `python main.py`); el token no desbloquea ninguna
funcionalidad nueva, solo hace la descarga más fiable. Se intentó darse de
alta en huggingface.co para crear el token, pero el registro falla en
Firefox sobre Ubuntu — sospecha razonable: el alta usa un captcha Cloudflare
Turnstile, que es conocido por fallar en silencio con
`privacy.resistFingerprinting` u otras protecciones de fingerprinting/tracking
activadas. Se cierra por prioridad (el aviso es cosmético, no bloquea
ninguna funcionalidad) — `HF_TOKEN` ya quedó documentado como placeholder en
`.env.example` por si se retoma más adelante, desde otro navegador o
dispositivo.

## 4. El agente habla con distintos proveedores de LLM

**Qué resuelve:** no depender de un único proveedor de modelo — ni por
robustez (qué pasa si se acaba el crédito de uno) ni por poder desarrollar sin
gastar dinero real en cada prueba.

**Tecnología:** el puerto `ProveedorLLM` (`domain/ports.py`) con **cuatro**
implementaciones intercambiables, seleccionadas por la variable de entorno
`PROVEEDOR_LLM`:

- **`llm_anthropic.py`** (Claude, vía el SDK oficial de Anthropic) — el
  proveedor por defecto, pensado como la opción de producción.
- **`llm_mock.py`** (#7, cerrado) — un proveedor heurístico, sin red ni
  credenciales, pensado para desarrollar el frontend o probar flujos sin
  gastar tokens reales.
- **`llm_cohere.py`** — Cohere Chat API v2, con clave de trial gratuita; usado
  activamente hoy mientras no hay crédito de Anthropic disponible. Cohere
  estructura el tool-calling de forma bastante distinta a Anthropic (mensajes
  `tool` dedicados, `tool_plan` separado del texto), así que este adaptador es
  el único punto del sistema que conoce esa diferencia y la traduce al shape
  normalizado que usa el orquestador.
- **`llm_openai.py`** (#34, cerrado) — ChatGPT vía la Chat Completions API de
  OpenAI. Se añadió específicamente como segunda opción *real* (no heurística)
  para poder contrastar si un problema de calidad de respuesta observado con
  Cohere era del proveedor o del propio prompt/sistema — y sirvió justo para
  eso: los bugs #31 y #32, ya corregidos, se reprodujeron manualmente contra
  OpenAI tras el fix y se confirmó que la corrección generaliza entre
  proveedores, no que "tapaba" un problema específico de Cohere.

Los cuatro exponen exactamente el mismo contrato normalizado
(`generar_respuesta()` / `generar_respuesta_stream()`, devolviendo bloques
`{"type": "text"/"tool_use", ...}` con la forma del wire format de Anthropic
como formato canónico interno) — el orquestador nunca sabe cuál está activo.
`temperature=0` es una convención compartida por Cohere y OpenAI en este
proyecto, no un capricho: en pruebas aisladas documentadas en el #32, la
temperatura por defecto de Cohere dio resultados distintos (fallo/fallo/éxito)
para el mismo mensaje repetido, mientras que con `temperature=0` fue
consistente — importante en un flujo donde una llamada a herramienta mal
formada puede significar una reserva mal creada.

## 5. Canales de entrada: web y Telegram

**Qué resuelve:** que el mismo orquestador pueda hablar con un cliente por la
web del negocio o por Telegram sin que el dominio ni la aplicación sepan que
existen esos canales.

**Tecnología:** dos adaptadores de entrada puramente traductores
(`adapters/in_/fastapi_app.py`, `adapters/in_/telegram_bot.py`), issue #4
cerrado. FastAPI expone `POST /chat` (respuesta completa) y
`POST /chat/stream` (Server-Sent Events, consumido por el frontend web);
`python-telegram-bot` conecta el mismo `OrquestadorAgente.responder()` a los
mensajes entrantes de un bot de Telegram. Ninguno de los dos contiene lógica
de negocio — su único trabajo es traducir HTTP o el SDK de Telegram a una
llamada al orquestador y de vuelta.

El canal de Telegram funciona por *polling* (`bot.run_polling()`) — es el
propio proceso el que pregunta a los servidores de Telegram si hay mensajes
nuevos, no al revés — así que, a diferencia de un webhook, no necesita
dominio público ni HTTPS para probarse: **#39** (cerrado) documenta la
verificación manual end-to-end con un bot real creado vía
[@BotFather](https://t.me/BotFather), confirmando que responde con el mismo
`OrquestadorAgente` que el chat web (RAG, herramientas de reserva) y que la
sesión se mantiene por `usuario_id` de Telegram entre mensajes.

## 6. Persistencia: qué sobrevive a un reinicio

**Qué resuelve:** por defecto, todo el estado del sistema (citas, clientes,
pedidos, sesiones de conversación) vive en memoria del proceso — perfecto para
desarrollar y para tests, pero se pierde entero si el proceso se reinicia. Fase
I resuelve esto haciendo que la persistencia real sea *opcional* y
*activable*, sin que active nada por defecto ni obligue a montar
infraestructura para simplemente probar el sistema.

**Tecnología — datos de negocio:** [SQLModel](https://sqlmodel.tiangolo.com/)
sobre Postgres (`adapters/out/db_models.py`, `adapters/out/repositorios_postgres.py`,
migraciones con Alembic) implementando los mismos puertos
(`RepositorioCitas`, `RepositorioClientes`, `RepositorioPedidos`) que la
versión en memoria. Activado con `DATABASE_URL`; sin ella, el sistema sigue
funcionando exactamente igual que antes de que existiera esta pieza. Los
servicios y profesionales (catálogo) nunca pasan por aquí — siempre se
derivan de `business.yaml` en cada arranque, porque son configuración, no
estado que cambie en producción. Dentro de este bloque, **#9 — Tabla propia
para LineaPedido** (cerrado) resolvió que las líneas de un pedido tuvieran su
propia tabla relacional en vez de vivir serializadas dentro de la fila del
pedido.

**Tecnología — sesiones de conversación (#18, cerrado):** el historial de
cada conversación (`SesionConversacion`, definida en `application/orchestrator.py`)
tiene su propio puerto, `RepositorioSesiones` (`application/ports.py` — vive
en la capa de aplicación y no en `domain/ports.py` porque una sesión
conversacional no es un concepto del dominio del negocio, es un concepto del
orquestador). Dos implementaciones: una en memoria
(`RepositorioSesionesMemoria`, el comportamiento de siempre) y otra sobre
[Redis](https://redis.io/) (`RepositorioSesionesRedis`, serializando el
historial como JSON), activada con `REDIS_URL`. Se verificó manualmente que
con Redis activo una conversación sobrevive a un reinicio completo del
proceso, y que sin él, no — exactamente el problema que motivó el issue
("el bot olvida a todo el mundo en cada despliegue").

**Postgres real de desarrollo (#41, cerrado):** el código de la persistencia
Postgres ya funcionaba y estaba probado (repositorios, migraciones,
selección automática por `DATABASE_URL` tanto en `main.py` como en el panel);
lo que faltaba era infraestructura, no código. Se resolvió provisionando un
Postgres gestionado gratuito en Neon (opción C de las barajadas en el
issue — sin Docker ni permisos de sistema, mismo patrón que la clave de
trial de Cohere para prototipar sin infraestructura propia), aplicando
`alembic upgrade head` contra él, y documentando `DATABASE_URL` en
`.env.example` (antes sin comentario, a diferencia del resto de variables).
Verificado explícitamente el síntoma original: dos procesos Python
independientes, cada uno construyendo sus propios repositorios contra el
mismo `DATABASE_URL` (igual que hacen `main.py::construir_sistema()` y
`panel_empleados/streamlit_app.py::_construir_repos()`), comparten los datos
— una cita creada por el primero es visible por el segundo sin reiniciar
nada. Postgres de producción queda fuera de este issue — eso sigue siendo
parte del checklist de #37.

**Sincronización externa — Google Calendar (#33, cerrado):**
`adapters/out/calendario_google.py` refleja cada `Cita` creada como un evento
en un calendario real de Google, vía una cuenta de servicio
(`GOOGLE_CALENDAR_CREDENTIALS_JSON` + `GOOGLE_CALENDAR_ID`). Es
deliberadamente *best-effort*: si la sincronización falla, la reserva se crea
igual en el sistema propio — el calendario externo es una comodidad para el
negocio (ver la agenda en una app que ya usan), no la fuente de verdad de si
una cita existe.

## 7. Calidad y confiabilidad

**Qué resuelve:** que el sistema sea genuinamente fiable, no solo que
"funcione en la demo" — esto cubre desde tests hasta bugs de producción reales
encontrados probando el flujo completo.

- **86 tests iniciales → 219 hoy** (#5, cerrado, y crecido orgánicamente desde
  entonces): la suite sigue la misma estructura en capas que la arquitectura
  (`tests/01_domain` → `tests/06_main`, de dentro hacia fuera), con fakes
  hechos a mano para los tests de dominio y mocks de los SDKs externos
  (Anthropic, Cohere, OpenAI, chromadb, redis) para los de adaptadores — nada
  en la suite necesita credenciales reales ni red.
- **#13 — Revisar warnings de los 86 tests** (cerrado): de 27 warnings, 7 eran
  del propio código (`datetime.utcnow()` deprecado) y se corrigieron; los 20
  restantes son de dependencias de terceros, no accionables sin pinnear otras
  versiones — decisión consciente de no perseguir eso en un skeleton.
- **#31 y #32** (cerrados): los dos bugs más serios encontrados probando el
  flujo de reservas de principio a fin — el LLM no reconocía servicios por no
  tener sus IDs en el prompt, y (más grave) llegó a confirmarle a un cliente
  una reserva que el dominio en realidad había rechazado, por una fecha mal
  calculada. Ambos con causa raíz identificada llamando al dominio
  directamente para descartar que el fallo estuviera ahí, y ambos verificados
  también contra OpenAI además de Cohere tras el fix.
- **#35** (cerrado): bug de UI del widget de chat (se encogía al recibir una
  respuesta comprimida durante una conversación real).
- **#19 — Type-checking (mypy)** (cerrado, parcial/incremental tal como
  planteaba el propio issue): `mypy` corre en CI sobre `domain/` y
  `application/` con la exigencia alta (`disallow_untyped_defs`), que son las
  capas sin dependencias externas — pasa limpio. Extenderlo a `adapters/` y
  `main.py` se dejó explícitamente para otra iteración: `mypy .` sobre todo el
  repo da hoy 47 errores ahí (incompatibilidades de tipos entre `chromadb` y
  `sentence-transformers`, un `dict` con tipos heterogéneos en
  `llm_cohere.py`, variables reasignadas entre implementaciones en
  memoria/Postgres en `main.py::construir_sistema` sin anotar con el tipo del
  puerto) — deuda conocida y documentada, no una omisión.
- **#42 — CI en `main` rota desde hace 3 días por lint** (cerrado): detectado
  por el email de fallo de CI en un push rutinario, pero el diagnóstico mostró
  que no era un caso aislado — los 14 pushes anteriores a `main`, desde el
  commit que añadió `scripts/evaluar_prompt.py` (2026-08-06), habían fallado
  en el job `lint` sin que nadie lo notara, porque `ruff` no corre en un
  pre-commit hook local, solo en CI. Dos errores concretos: `E402` (el script
  inserta la raíz del repo en `sys.path` antes de importar `application/`,
  necesario porque se ejecuta suelto — mismo patrón ya exceptuado para
  `main.py`/`tests/`/el panel en `pyproject.toml`, solo le faltaba su propia
  entrada) y `UP037` (comillas innecesarias en un forward reference con
  `from __future__ import annotations` ya activo). El job `test` nunca estuvo
  roto — solo `lint`. Fix trivial, verificado con `ruff check .` limpio y los
  219 tests en verde antes de hacer push, y confirmado después con el run de
  CI ya en verde.

## 8. El sitio web público y su SEO

**Qué resuelve:** que el negocio tenga presencia web real (no solo un widget
de chat embebible), y que ese contenido sea indexable/citable por buscadores y
por asistentes de IA que rastrean la web — sin duplicar el trabajo de
mantenimiento respecto al vault de Obsidian que ya alimenta al RAG.

**Tecnología:** [Astro](https://astro.build/) + Preact + Tailwind v4
(`frontend/`, proyecto hermano e independiente del backend Python salvo por
las llamadas HTTP del chat). La pieza clave de diseño es que el frontend *lee
el mismo vault* que indexa el RAG (`frontend/src/content.config.ts`, vía el
loader `glob()` de Astro sobre `../vault_negocio`) — una nota se convierte en
página pública automáticamente si su frontmatter tiene `publicar_web: true`,
sin ningún paso de publicación manual aparte de editar ese campo.

Dentro de este bloque, cuatro issues de SEO/GEO, todos cerrados:

- **#26 — Meta tags básicos**: title/description/OG por página.
- **#27 — Datos estructurados JSON-LD (LocalBusiness)**
  (`DatosEstructurados.astro`): marcado semántico para que buscadores (y
  asistentes de IA que consumen datos estructurados) entiendan qué tipo de
  negocio es, horarios, ubicación.
- **#28 — Sitemap y robots.txt**: generado con `@astrojs/sitemap`
  (integración en `astro.config.mjs`) + `robots.txt.ts` a medida.
- **#29 — Páginas propias por nota de contenido**: cada nota pública tiene su
  propia URL (`/contenido/[slug]`), no solo aparece en un lightbox/modal —
  importante para que cada pieza de contenido sea indexable individualmente.

El chat web (`frontend/src/components/chat/`) consume `POST /chat/stream` a
mano con `fetch` + `ReadableStream` (no `EventSource`, porque este no soporta
`POST` con body), y al recibir el evento `fuentes` dispara un
`CustomEvent('orquestador:fuentes', ...)` que `GridContenido.astro` escucha
para resaltar la tarjeta de contenido correspondiente — el chat y el
contenido público están enlazados en la misma página.

## 9. Panel interno para el negocio

**Qué resuelve:** que alguien del equipo (no el dueño necesariamente) pueda
ver la agenda del día y los pedidos pendientes sin tener que hablar con el
propio chat del asistente para consultarlo.

**Tecnología (construida):** [Streamlit](https://streamlit.io/)
(`panel_empleados/streamlit_app.py`),
issue **#10** (cerrado). Absorbió también el alcance de **#25 — Interfaz
Admin Streamlit** (cerrado como duplicado, fusionado aquí: su única pieza de
MVP, un botón de "reindexar RAG", pasa a ser parte de este mismo panel en vez
de una app separada). Construirlo requirió ampliar primero el dominio con dos
piezas que no existían: `RepositorioCitas.citas_en_fecha(dia)` (agenda
agregada de *todos* los profesionales, distinta de
`citas_de_profesional_en_fecha`, que ya existía pero es por profesional) y el
caso de uso `CambiarEstadoPedido`, con una pequeña máquina de estados
(`_TRANSICIONES_PEDIDO_VALIDAS`) que valida la transición antes de delegar en
`RepositorioPedidos.listar_pendientes()` — un pedido ya `entregado` o
`cancelado`, por ejemplo, no admite ninguna transición más.

El panel consume esos casos de uso directamente, sin pasar por el orquestador
ni por ningún LLM (construye sus propios repositorios igual que
`main.py::construir_sistema()`: Postgres si hay `DATABASE_URL`, en memoria si
no). Tres secciones — agenda (solo lectura), pedidos pendientes (con cambio
de estado) y un botón de reindexado de RAG — con un enfoque mobile-first
deliberadamente barato: la navegación vive en `st.sidebar`, que
Streamlit ya colapsa por sí solo en pantallas estrechas, y el contenido son
tarjetas apiladas (`st.container(border=True)`) en vez de tablas o columnas,
que en móvil fuerzan scroll horizontal. Un gate de acceso mínimo
(`PANEL_EMPLEADOS_PASSWORD`, opcional, mismo patrón "sin ella, se abre sin
gate" que el resto de variables de entorno del proyecto) protege el acceso,
ya que el panel muestra datos de citas/pedidos que no deberían quedar
abiertos a quien tenga la URL.

Dos detalles no obvios de construir un segundo entrypoint de Python fuera de
`main.py`: `streamlit run` pone en `sys.path` el directorio del propio script
(`panel_empleados/`), no la raíz del repo, así que hace falta el mismo
`sys.path.insert(...)` que ya usa `conftest.py` para los tests — sin él, falla
con `ModuleNotFoundError: No module named 'adapters'` en cuanto alguien lo
ejecuta de verdad (un `curl` al puerto no lo detecta: Streamlit solo ejecuta
el script cuando un navegador abre sesión por WebSocket, así que un simple
chequeo HTTP puede dar un falso positivo). Y `.streamlit/config.toml`
(`client.toolbarMode = "minimal"`) oculta el botón "Deploy" que Streamlit
añade por defecto a cualquier app local — este panel es interno, no algo
pensado para Streamlit Community Cloud.

**Agenda día/semana/mes con navegación (#40, cerrado):** la sección de agenda
arrancó (#10) mostrando un único día elegido con un `st.date_input`, sin más
navegación. #40 la amplió con un selector de vista (día/semana/mes) y botones
"◀ Anterior" / "Hoy" / "Siguiente ▶" que desplazan una fecha ancla guardada en
`st.session_state` (1 día, 7 días o 1 mes según la vista activa, usando el
primer día del mes siguiente/anterior en vez de `± 30 días` para no
desfasarse entre meses de distinta longitud). Requirió un método nuevo en el
puerto, `RepositorioCitas.citas_en_rango(desde, hasta)` (rango inclusivo,
todos los profesionales), implementado en `RepositorioCitasMemoria` y
`RepositorioCitasPostgres`; `citas_en_fecha(dia)` pasó a delegar en
`citas_en_rango(dia, dia)` en vez de duplicar el filtro de fecha en ambas
implementaciones. Ver `doc/003-modelo-datos.md` para el detalle de este
cambio en el modelo de datos.

**Notificaciones de reserva conectadas a Telegram (#38, cerrado):** el puerto
`NotificadorMensajes` (`domain/ports.py`) ya tenía una implementación real,
`NotificadorMensajesTelegram` (#12), pero deliberadamente sin conectar a
nada — ni `CrearReserva`/`CancelarReserva` la recibían como dependencia, ni
`main.py` la instanciaba. #38 cerró esa conexión: `Cliente`
(`domain/entities.py`) ganó un campo `telegram_chat_id: str | None`
(migración `8c8bf2f0d3c8_telegram_chat_id_en_clientes.py`), poblado desde
`CrearReserva` cuando la reserva se origina en una sesión de Telegram, y
`CrearReserva`/`CancelarReserva` reciben ahora un `NotificadorMensajes | None`
opcional que manda confirmación/cancelación tras guardar la cita —
best-effort, mismo patrón que la sincronización con Google Calendar: un fallo
de Telegram nunca impide crear o cancelar una reserva en el sistema propio.
`main.py` instancia `NotificadorMensajesTelegram` solo si `TELEGRAM_BOT_TOKEN`
está definido. Email como canal de notificación quedó fuera de alcance (ver
#12), descartado por ahora sin un caso de uso claro que lo dispare.

**Roadmap no construido — autoedición del vault por el propietario (#25):**
al analizar #25 se detectó que el flujo actual de contenido (propietario edita
`.md` en Obsidian → ingesta RAG + build de Astro leen el mismo archivo) exige
manejar markdown, frontmatter YAML y git — no es realista pedírselo a un
dueño de negocio no técnico. La recomendación del propio análisis, nunca
construida, era separar dos audiencias sobre el mismo vault: developer sigue
editando en Obsidian para contenido rico/estructural, y al propietario se le
da en su lugar el panel (formularios específicos por tipo de dato — precio de
un servicio, texto de una promoción, horario de un día, FAQ nueva — que
escriben el `.md` con el frontmatter correcto generado por código, y disparan
la reindexación en RAG). Se decidió conscientemente no construirlo en Fase I
(no forma parte del flujo crítico reserva-de-principio-a-fin): el vault sigue
siendo developer-only, y el panel solo tiene un botón "Reindexar RAG" para
cuando el propio developer edita a mano. Si se retoma, el patrón
formulario-específico-por-tipo-de-contenido (no un editor de markdown libre)
es la parte del análisis que hace esto viable para alguien no técnico; para
producción además haría falta un webhook que dispare un rebuild de Astro
(deploy hook de Cloudflare Pages/Vercel/Netlify) cuando el vault cambie, ya
que hoy el sitio solo se actualiza en el siguiente build manual.

**Ciclo de vida de la Cita completado (#43, cerrado):** `EstadoCita` pasó de
cuatro valores con solo dos transiciones reales (creación en `PENDIENTE`,
cancelación a `CANCELADA`; `CONFIRMADA`/`COMPLETADA` nunca se asignaban en
ningún sitio del código) a seis: `PENDIENTE`, `CONFIRMADA`, `EN_CURSO`,
`FINALIZADA`, `CANCELADA`, `NO_SHOW`. Las cuatro nuevas transiciones
(`confirmar`, `marcar en curso`, `finalizar`, `no-show`) son manuales desde
el panel — nunca las dispara el LLM — vía el caso de uso nuevo
`CambiarEstadoCita` (`domain/use_cases.py`), con su propia tabla
`_TRANSICIONES_CITA_VALIDAS`, mismo patrón que `CambiarEstadoPedido`.
`CANCELADA` sigue sin cambios, gestionada solo por `CancelarReserva` — no es
un destino válido de `CambiarEstadoCita`, así que el selector del panel no
la ofrece como opción (evita mostrar una opción que siempre fallaría).

Al confirmar una cita se manda una notificación al cliente, mismo patrón
*best-effort* que ya usan `CrearReserva`/`CancelarReserva`
(`NotificadorMensajes` opcional, silencioso si el cliente no tiene
`telegram_chat_id`). Esto exigió un cambio no obvio: el panel no construía
hasta ahora ni `repo_clientes` ni ningún `NotificadorMensajes` propio —
`panel_empleados/streamlit_app.py::_construir_repos()` y una función nueva,
`_construir_notificador()`, lo añaden con el mismo condicional
`TELEGRAM_BOT_TOKEN` que ya usa `main.py::construir_sistema()`.

Ninguna de estas transiciones toca el evento de Google Calendar —
deliberado, son puramente internas al sistema. Y un hueco real que salió al
analizar esto, documentado en el propio issue: hoy no hay ninguna forma de
cancelar una cita desde la aplicación en marcha (ni chat ni panel) — el
caso de uso `CancelarReserva` existe y está conectado en el executor, pero
no está expuesto en `TOOLS_SCHEMA` ni tiene botón en el panel. Queda fuera
de #43 tal como se pidió, pero conviene tenerlo presente.

## 10. Base para operar en producción

**Qué resuelve:** el hueco final entre "funciona en local" y "se puede
desplegar de verdad" — documentación, tipado, y un par de cosas hardcodeadas
para desarrollo que no deberían llegar tal cual a producción.

- **#20 — Documentación inicial** (cerrado): la serie completa de
  documentos en `doc/` (narrativa profunda, no referencia terse como
  `README.md`/`CLAUDE.md`), numerada `001` a `008` — introducción,
  este mismo documento de alcance, modelo de datos, arquitectura,
  conocimiento del negocio, cómo extender a otro negocio, despliegue, y
  referencia de la API del chat. `doc/001-intro.md` (antes vacío, enlazado en
  roto desde el `README.md`) es ahora el punto de entrada que enlaza al
  resto de la serie.
- **#37 — Puesta en producción: checklist + arreglar CORS hardcodeado**
  (cerrado): el bloqueante de código (CORS hardcodeado) ya estaba resuelto
  desde antes — `adapters/in_/fastapi_app.py` lo expone vía `CORS_ORIGINS`,
  manteniendo los orígenes de dev como default si no está definida. El resto
  del issue —qué hacer con las sesiones en RAM y el proceso único antes de
  abrir el dominio al público, rate limiting en `/chat` (que sigue sin
  tener), y la checklist de infraestructura (DNS, TLS, secrets, Postgres
  provisionado, indexar el vault, build del frontend)— no era código de este
  repo, así que se movió tal cual a `doc/007-despliegue.md` como referencia
  viva que se recorre en el momento de un despliegue real, en vez de quedar
  como una tarea de tracker que nunca se puede marcar "hecha" de verdad.
- **#19 — Type-checking (mypy)** (ya mencionado en la sección 7 — cerrado de
  forma incremental, `domain`/`application` cubiertos, `adapters`/`main.py`
  pendientes): tipado estático ayuda a que refactors futuros —muy probables
  en cuanto se extienda a un segundo negocio— no rompan cosas silenciosamente.

---

## Resumen por estado

| Estado | Issues |
|---|---|
| **Hecho y cerrado** | #1, #2, #3, #4, #5, #6, #7, #8 (no aplica), #9, #10, #12, #13, #18, #19 (parcial/incremental), #20, #23 (cerrado sin implementar — signup de Hugging Face bloqueado, aviso cosmético, ver sección 3), #25 (fusionado en #10), #26, #27, #28, #29, #31, #32, #33, #34, #35, #36 (movido a `doc/003-modelo-datos.md`), #37 (movido a `doc/007-despliegue.md`), #38, #39, #40, #41, #43, #46 |
| **Listo para empezar (Ready)** | #17 (movido de Fase II — canal de entrada más, no integración comercial, ver el propio issue) |
| **Backlog** | #21, #22 |

De 37 issues etiquetados `Fase I`, 34 están cerrados. Lo único que queda por
delante es **calidad conversacional** (#21, #22 — el modelo ya funciona,
pero afinar el tono comercial y automatizar su verificación es trabajo
continuo) y **#17**, un canal de entrada más (WhatsApp) ya analizado y
documentado, listo para empezar cuando haya hueco. Las notificaciones
proactivas al cliente (#38), la revisión del modelo de datos (#36), el
Postgres real de desarrollo (#41), la CI rota en `main` (#42, sin label
`Fase I` por ser un fallo de infraestructura de CI, no de alcance — fuera de
este recuento), la documentación inicial completa (#20), el checklist de
producción (#37), el vault de ejemplo versionado (#46) y el ciclo de vida
completo de la Cita (#43) ya están resueltos — ver la
sección 9,
`doc/003-modelo-datos.md` y `doc/007-despliegue.md` respectivamente.
