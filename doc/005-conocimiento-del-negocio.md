# Conocimiento del negocio: el vault y el RAG

## Por qué Obsidian y no una base de datos de FAQs

Precios, horarios, políticas de cancelación, contraindicaciones de salud —
todo eso es información que cambia por negocio y con el tiempo, y que no
tiene sentido hardcodear en el prompt ni en el código. La decisión de
`vault_negocio/` fue usar [Obsidian](https://obsidian.md) (notas Markdown con
frontmatter YAML) como única fuente de verdad, en vez de un CMS o una base de
datos de FAQs: es una herramienta que un dueño de negocio no técnico ya
podría usar para escribir y organizar notas — actualizar un precio o añadir
una política nueva es editar un `.md`, sin tocar código.

El vault de ejemplo (`vault_negocio/`) tiene ocho notas:
`equipo.md`, `faq.md`, `horarios.md`, `politicas-cancelacion.md`,
`promociones.md`, `salud-contraindicaciones.md`, `servicios.md`,
`ubicacion-contacto.md`. Cada una es a la vez la fuente que alimenta al RAG
del chat y (si lo marca así) una página pública en la web — la misma nota,
dos consumidores.

## Cómo llega una nota al RAG: la ingesta

`python -m adapters.out.obsidian_ingest --vault ./vault_negocio`
(`adapters/out/obsidian_ingest.py`) recorre todos los `.md` del vault,
separa el frontmatter YAML del contenido (librería `python-frontmatter`), y
trocea el cuerpo en fragmentos de ~800 caracteres respetando límites de
párrafo, con 100 caracteres de solape entre fragmentos consecutivos
(`trocear_texto()`, `TAMANO_CHUNK`/`SOLAPE_CHUNK` en la cabecera del
fichero) — un chunking simple por diseño, deliberadamente reemplazable por
algo más fino (`langchain.text_splitter` u otro) sin tocar el resto del
pipeline si algún vault necesitara mejor granularidad semántica.

Cada fragmento se indexa con un id determinista
(`sha256(f"{fichero}-{i}")[:16]`) y **todo el frontmatter de la nota se
adjunta como metadata sin filtrar** (`metadata_base = dict(post.metadata)`,
`obsidian_ingest.py:57`) — esto es importante: `publicar_web`, `categoria`,
`tags`, `resumen`, cualquier campo que exista en el frontmatter viaja tal
cual hasta Chroma, y es lo que permite que capas más arriba (el caso de uso
de dominio, el frontend) decidan qué hacer con esa nota sin que la ingesta
tenga que saber nada de esas reglas.

## Dónde vive el índice: Chroma + embeddings multilingües

`adapters/out/vector_store.py::RepositorioConocimientoChroma` implementa el
puerto `RepositorioConocimiento` (`domain/ports.py`) sobre
[ChromaDB](https://www.trychroma.com/) en modo local/embebido
(`chromadb.PersistentClient`, carpeta `./chroma_data` por defecto,
configurable con `CHROMA_PATH`). El modelo de embeddings por defecto es
`paraphrase-multilingual-MiniLM-L12-v2`, no el `all-MiniLM-L6-v2` que trae
Chroma de fábrica — ese modelo está entrenado sobre todo en inglés, y con
contenido y *queries* en español el ranking semántico salía notablemente
peor (comprobado en su momento: un fragmento con el precio exacto quedaba en
el puesto 9 de 12 resultados para la consulta "precios"). El modelo
multilingüe es el que hace que el RAG funcione bien en español sin ningún
otro cambio de código.

`buscar_con_fuentes()` es el método que realmente usa el sistema en
producción — a diferencia de `buscar()` (que solo devuelve los textos),
conserva la metadata completa de cada resultado, incluida la que decide
visibilidad (`publicar_web`) y agrupación (`categoria`).

## El puente hacia el LLM: la tool y el filtro de visibilidad

La tool `consultar_conocimiento_negocio` (`application/tools.py`) es lo que
el LLM invoca cuando necesita responder algo informativo; se resuelve contra
`ConsultarConocimientoNegocio` (`domain/use_cases.py:298`), que llama a
`buscar_con_fuentes()` y aplica una regla concreta:

- **Todos** los fragmentos encontrados se devuelven como contexto de texto
  para que el LLM los use al responder — una nota sin `publicar_web: true`
  puede perfectamente seguir alimentando la respuesta.
- Pero solo los fragmentos cuya nota de origen tiene `publicar_web: true`
  (comparación estricta, `r.get("publicar_web") is True`) entran en la lista
  de `fuentes` que se devuelve aparte — la que el frontend usa para mostrar
  un enlace citable ("fuente: horarios.md").

Esa distinción — "el LLM puede usarlo para responder" vs. "esto es citable
públicamente" — es la pieza central del control de qué información interna
es apta para exponerse como contenido público, y vive enteramente en este
caso de uso: `obsidian_ingest.py` no filtra nada al indexar, y Chroma no sabe
que existe esa regla.

## El mismo vault, dos consumidores: RAG y web pública

`frontend/src/content.config.ts` define una content collection de Astro
(`vault`) que lee `vault_negocio/` directamente vía el loader `glob()` —
literalmente la misma carpeta que indexa `obsidian_ingest.py`, sin
duplicación. El schema Zod de esa colección exige `publicar_web` (con
`default(false)` si el campo no está) y, si `publicar_web` es `true`, exige
también un `resumen` no vacío (`.refine(...)` en `content.config.ts`) — la
validación falla en build-time si alguien marca una nota como pública sin
darle el resumen corto que necesita su tarjeta en la web.

Una nota se convierte en página pública automáticamente en cuanto su
frontmatter tiene `publicar_web: true`; no hay ningún paso de publicación
manual aparte de editar ese campo. Y hay un enlace más entre el chat y ese
contenido: cuando el chat en streaming recibe el evento SSE `fuentes`
(`useChatStream.ts:103`), dispara un `CustomEvent('orquestador:fuentes', ...)`
en `window`, que `GridContenido.astro` escucha para resaltar la tarjeta cuyo
`data-fuente` coincide con el fichero de origen — si el asistente responde
usando `horarios.md`, la tarjeta de horarios se ilumina en la página, sin que
el chat y el grid de contenido tengan ninguna otra conexión directa entre sí.

## Reindexar

Reindexar es simplemente volver a correr la ingesta:

```bash
python -m adapters.out.obsidian_ingest --vault ./vault_negocio
```

`indexar_fragmentos()` usa `upsert` (no `insert`), así que volver a indexar
el vault entero es seguro — los fragmentos con el mismo id (mismo fichero,
mismo índice de trozo) se sobrescriben, no se duplican. El panel interno
(`panel_empleados/streamlit_app.py`) expone esto mismo como un botón
"reindexar RAG" para quien gestiona el contenido sin tener que usar la
terminal.
