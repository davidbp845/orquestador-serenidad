# Decisiones tecnológicas: qué se usa, qué no, y por qué

## Por qué existe este documento

`doc/002-fase-1-alcance.md` ya recorre, módulo por módulo, con qué
tecnología está construida cada pieza del sistema. Este documento mira el
mismo sistema desde el ángulo contrario: no "qué se eligió", sino **qué se
eligió no usar** frente a lo que hoy es el stack por defecto de facto para
construir agentes IA — LangChain, LangGraph, CrewAI, LlamaIndex, LangSmith,
Next.js, Pinecone... el mismo catálogo que enseña prácticamente cualquier
bootcamp o curso de "Aplicaciones LLM y Agentes IA" del mercado en 2025-2026.

La respuesta corta es siempre la misma y aparece ya en `doc/004-arquitectura.md`:
`domain/` y `application/` están construidos con la regla de "cero
dependencias externas" como restricción de diseño, no como omisión. Este
documento es el porqué desarrollado de esa frase, aplicado tecnología por
tecnología, con los trade-offs reales de haberlo hecho así — incluido cuándo
*dejaría* de tener sentido.

## El principio que organiza todas las decisiones de esta lista

Un framework de agentes (LangChain, LangGraph, CrewAI...) no es neutral: trae
su propio modelo de abstracción — su propia idea de qué es un "mensaje", un
"tool call", un "estado" — y en el momento en que el dominio o el
orquestador programan contra esas abstracciones, dejan de programar contra
las suyas propias. `domain/ports.py` es la prueba de que la alternativa
existe y es barata: nueve interfaces (`RepositorioCitas`, `ProveedorLLM`,
`RepositorioConocimiento`, `SincronizadorCalendario`...) que cualquier
adaptador puede implementar. Cambiar de Anthropic a Cohere a OpenAI a lo
largo de este proyecto (`adapters/out/llm_anthropic.py`,
`llm_cohere.py`, `llm_openai.py`) ha costado exactamente eso: una clase
nueva por proveedor, sin tocar una línea de `domain/` ni de
`application/orchestrator.py`. Ese es el resultado que se estaba comprando
al no adoptar un framework: el "punto de acoplamiento" con cualquier
proveedor externo (LLM, vector store, framework de agentes) es una interfaz
propia de un fichero, no la API de un paquete de terceros.

El coste de esa elección también es real y merece decirse sin rodeos: cada
pieza de infraestructura de agentes que un framework te da "gratis"
(gestión de memoria con distintas estrategias, checkpoints/pausas de un
grafo, retries y backoff sobre llamadas al LLM, integraciones ya hechas con
docenas de vector stores y herramientas) hay que escribirla o no tenerla.
Este proyecto ha elegido conscientemente construir menos superficie y
mantenerla toda legible, a cambio de no tener ese catálogo de
funcionalidad de serie. La sección final de este documento es honesta sobre
en qué punto esa balanza cambiaría.

## Orquestación de agentes: bucle propio en vez de LangChain/LangGraph/CrewAI

`application/orchestrator.py` no usa ningún framework de agentes. El "grafo
de estados" que en LangGraph se declararía como nodos y aristas es, aquí,
literalmente un bucle `for` en `OrquestadorAgente.responder()`/
`responder_stream()`: llamar al LLM con `TOOLS_SCHEMA`, por cada bloque
`tool_use` despachar a `EjecutorHerramientas.ejecutar()`
(`application/tools.py`), devolver el resultado al LLM, repetir hasta que
responde con texto plano o se agotan las `max_iteraciones_tool` (4 por
defecto). No hay ni siquiera una abstracción de "grafo" interna — cuatro
tools y un flujo conversacional lineal no la necesitan, y añadirla habría
sido la abstracción prematura que el propio estilo de este repo evita.

CrewAI y los sistemas "multi-agente" (varios agentes especializados
coordinándose) tampoco tienen equivalente aquí, y por un motivo distinto al
de LangChain/LangGraph: no es solo una preferencia de implementación, es
que el caso de uso — un único asistente de atención al cliente con un
catálogo pequeño de acciones — no tiene ningún problema que resolver
repartiendo el trabajo entre agentes especializados. Añadir
multi-agente aquí sería resolver un problema que el sistema no tiene.

LangSmith, la pieza de observabilidad/evaluación del ecosistema LangChain,
está sustituida por dos piezas propias y más simples: `logging` estándar de
Python configurado en `main.py::construir_sistema()` para observabilidad en
caliente, y `scripts/evaluar_prompt.py` — que corre un banco de "casos
difíciles" en YAML (`tests/03_application/casos-dificiles/`) contra el
asistente y reporta qué pasa y qué falla — para evaluación offline de
calidad de prompt. `doc/010-prompt-engineering.md` documenta ese método a
fondo. Es deliberadamente más pobre que un LangSmith real: no hay tracing
visual de cada paso del agente, ni comparación histórica de runs, ni una UI.
Lo que compra a cambio es que evaluar la calidad del prompt no depende de
una cuenta ni un servicio externo — corre en local, gratis, en CI
(`.github/workflows/evaluar-prompts.yml`, opcional, ver
`doc/011-integracion-continua.md`).

## RAG: Chroma + código propio en vez de LlamaIndex

El pipeline de RAG completo — trocear el vault de Obsidian en chunks
(`adapters/out/obsidian_ingest.py`), indexarlos con embeddings
(`adapters/out/vector_store.py`, usando `chromadb.utils.embedding_functions`
con `sentence-transformers` directamente, no vía LangChain/LlamaIndex), y
recuperarlos en cada consulta informativa (`ConsultarConocimientoNegocio`
en `domain/use_cases.py`) — está escrito contra el cliente de Chroma
directamente, sin LlamaIndex ni el módulo de RAG de LangChain de por medio.

La razón es la misma que en la sección anterior, pero aquí además hay una
frontera de dominio que un framework de RAG genérico no conoce: qué
fragmentos son aptos para mostrarse como "fuente" pública en la web
(`publicar_web: true` en el frontmatter de cada nota, ver
`doc/005-conocimiento-del-negocio.md`) es una regla de negocio de este
proyecto, no un concepto que LlamaIndex tenga. Metabolizarla habría exigido
trabajar *alrededor* del framework en vez de con él — a este tamaño de
problema (una base de conocimiento por negocio, decenas o cientos de notas,
no millones de documentos), el framework no paga su propio coste de
indirección.

## Bases de datos: Postgres relacional + Chroma vectorial, sin Pinecone/FAISS/DeepLake

Dos bases de datos, cada una para lo suyo, sin solaparse:

- **Postgres** (`adapters/out/repositorios_postgres.py`, vía SQLModel +
  Alembic) para el estado transaccional que debe sobrevivir a un reinicio:
  citas, clientes, pedidos. Es una base de datos relacional normal — no se
  usa como base de datos vectorial (no hay `pgvector` en juego), a
  diferencia de cómo aparece Postgres en la lista de "bases de datos
  vectoriales" de algunos cursos.
- **Chroma** (`adapters/out/vector_store.py`) exclusivamente para el RAG del
  conocimiento del negocio.

Ni Pinecone, ni FAISS, ni DeepLake tienen equivalente en el repo. Pinecone es
un servicio gestionado de pago — para una base de conocimiento por negocio
del tamaño de un vault de Obsidian de una pyme, un Chroma embebido en el
mismo proceso cubre el caso sin añadir una dependencia de infraestructura ni
un coste recurrente. FAISS (una librería de búsqueda vectorial pura, sin
persistencia ni metadata propia) habría exigido construir a mano justo lo
que Chroma ya da de serie (persistencia, filtrado por metadata como
`publicar_web`). Retrieval híbrido (semántico + léxico) tampoco está
implementado — la recuperación es solo por embeddings; no ha hecho falta
más precisión que esa para el volumen de contenido de un vault de negocio.

## Frontend: Astro + Preact en vez de Next.js

`frontend/` es Astro + Preact + Tailwind, no Next.js. La diferencia de fondo
es de forma, no solo de marca: la mayor parte de ese frontend es contenido
público estático generado en build time desde el mismo vault que alimenta
al RAG (`frontend/src/content.config.ts`, ver
`doc/005-conocimiento-del-negocio.md`) — un catálogo de servicios, FAQ,
políticas. Astro está diseñado para exactamente ese patrón (contenido
mayormente estático con islas interactivas puntuales) y envía cero
JavaScript por defecto salvo donde se declara explícitamente una isla — que
aquí es solo el chat (`frontend/src/components/chat/`), el único punto
realmente interactivo de la página. Next.js habría sido la opción por
defecto si el frontend fuera, en sí mismo, una aplicación (un dashboard, un
panel con muchos estados de UI) — no es el caso: eso ya lo cubre
`panel_empleados/` con Streamlit, un frontend interno con audiencia y
necesidades completamente distintas a la web pública.

Flask tampoco se usa en ningún punto — FastAPI (`adapters/in_/fastapi_app.py`)
cubre en solitario el rol de framework web backend, elegido en su día sobre
todo por soporte nativo a async y a `StreamingResponse` (necesario para
`/chat/stream`, SSE) y por generar validación de payloads gratis vía
Pydantic.

## Streamlit: panel interno permanente, no prototipo desechable

`panel_empleados/` usa Streamlit, que en el material algunis cursos suele
aparecer bajo "deployment provisional" — un modo rápido de montar una demo
de cara al cliente antes de construir la interfaz de verdad. Aquí el uso es
distinto: es la interfaz de verdad, pero para una audiencia distinta a la
del negocio (empleados/propietario viendo agenda, pedidos, clientes,
reindexando el RAG — ver `doc/002-fase-1-alcance.md`, sección 9), no un
sustituto temporal de un frontend público. Que sea "rápido de montar" sigue
siendo la razón de fondo para haberlo elegido — un panel interno de uso
interno no necesita el nivel de pulido de la web pública — pero no está
pensado para reemplazarse por otra cosa más adelante.

## Deployment: VPS propio en vez de una PaaS (Vercel/Render)

`doc/007-despliegue.md` documenta un despliegue sobre un VPS propio —
`uvicorn` detrás de Caddy/nginx como reverse proxy con TLS vía Let's
Encrypt, supervisado por `systemd` o Docker — no una plataforma gestionada
como Vercel o Render para el backend. (Sí menciona Vercel/Netlify/Cloudflare
Pages como una opción válida para el *hosting estático* del frontend Astro,
que es exactamente el tipo de carga para la que esas plataformas están
pensadas.) La razón no es ideológica: un backend con estado (Postgres,
Redis, Chroma persistente en disco) encaja peor en el modelo *serverless*
sin estado de una PaaS típica que en una única máquina donde todo el stack
convive; y para el tamaño de tráfico de un chat de negocio pequeño, un VPS
es sustancialmente más barato que el nivel de PaaS que soportaría el mismo
stack con estado. AWS S3 no aparece en ningún punto porque no hay ningún
activo (imágenes, ficheros subidos) que necesite almacenamiento de objetos
remoto — el vault y las credenciales son ficheros locales del servidor.

## Multimodalidad y herramientas externas: fuera de alcance, no sustituidas

A diferencia de las secciones anteriores, esto no es "se sustituyó X por
Y" — es simplemente terreno que Fase I no cubre:

- **Multimodal** (imagen, voz — Replicate AI, Stable Diffusion, Deepgram en
  el vocabulario de los cursos): el sistema es solo texto. Ni genera ni
  interpreta imágenes, ni transcribe audio. Ningún caso de uso del centro de
  masajes de ejemplo lo pedía.
- **Búsqueda web como tool** (Tavily Search y similares): la única fuente de
  conocimiento del agente es el RAG sobre el vault propio del negocio
  (`consultar_conocimiento_negocio`); no hay ninguna tool que salga a
  internet. Es coherente con el diseño — un asistente de atención al
  cliente de un negocio concreto no necesita ni debería responder con
  información no verificada por el propio negocio.
- **Integraciones de productividad** (GmailToolkit, calendarios de terceros
  más allá de Google Calendar): la única integración externa de este tipo
  es `adapters/out/calendario_google.py`, y es unidireccional y best-effort
  (espejar citas creadas, nunca leer del calendario ni bloquear la reserva
  si falla la sincronización).

## Cuándo dejaría de tener sentido esta elección

Vale la pena decir explícitamente en qué condiciones la balanza descrita al
principio de este documento se inclinaría hacia adoptar un framework en vez
de seguir escribiéndolo a mano:

- Si el catálogo de tools creciera a decenas, con dependencias entre pasos
  (esperar aprobación humana, ramificarse según el resultado de una tool),
  el bucle plano de `orchestrator.py` empezaría a necesitar justo lo que
  LangGraph formaliza (checkpoints, pausas, grafo de estados) — hoy, con 4
  tools y un flujo lineal, esa complejidad no tiene contrapartida.
- Si el sistema pasara a coordinar varios agentes con roles distintos y
  reales (no solo "una tool más"), CrewAI o un framework equivalente dejaría
  de ser una capa superflua.
- Si el volumen de conocimiento por negocio creciera de un vault de una
  pyme a un corpus documental grande y heterogéneo (múltiples formatos,
  millones de fragmentos), la recuperación híbrida y el escalado gestionado
  de un Pinecone empezarían a justificar su coste operativo frente a un
  Chroma embebido.

Hasta que alguna de esas condiciones sea cierta, la superficie de código
propia que ya existe (`domain/ports.py`, el bucle de
`application/orchestrator.py`, el pipeline de RAG en `adapters/out/`) sigue
siendo más barata de mantener, más fácil de leer de principio a fin, y —
sobre todo — más fácil de razonar sobre lo que hace realmente, que
delegarla en un framework de terceros para un problema que hoy no lo
necesita.
