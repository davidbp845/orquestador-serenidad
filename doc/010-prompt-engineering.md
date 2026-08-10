# Prompt engineering en este proyecto

Este documento recoge todo lo que hace falta saber para tocar con criterio la
*calidad de las respuestas* del asistente — no el protocolo de tool-calling en
sí (eso ya funciona, ver `doc/004-arquitectura.md` y los issues #31/#32 más
abajo), sino cómo suena, cuándo insiste, cuándo cede, y cuándo debería decir
"no lo sé". Es la pieza de contexto que le falta a `doc/002-fase-1-alcance.md`
para poder retomar el #21 (Mejorar las respuestas del asistente en el ámbito
comercial) sin tener que redescubrir esto desde cero cada vez.

## Introducción: no hay "el prompt", hay varias superficies

La primera idea que hay que descartar es que este proyecto tiene un fichero
de prompt estático que se edita y ya está. No existe tal fichero. Lo que
llega al LLM en cada turno es el resultado de ensamblar, en tiempo de
ejecución, varias piezas que viven en sitios distintos del código, se
construyen en momentos distintos, y cambian con frecuencias distintas:

| Pieza | Dónde vive | Cuándo se construye | Con qué frecuencia cambia |
|---|---|---|---|
| Plantilla estructural del prompt | `application/prompts.py::construir_system_prompt()` | Una vez, al arrancar (`main.py::construir_sistema()`) | Rara vez — es común a cualquier negocio |
| Tono, instrucciones de negocio | `config/business.yaml` (`tono`, `instrucciones_extra`, `instrucciones_comerciales`) | Una vez, al arrancar (se lee dentro de lo anterior) | Cada vez que se itera sobre calidad conversacional (#21) |
| Catálogo de servicios/profesionales | `_construir_catalogo()` en `prompts.py`, derivado de `config/business.yaml` | Una vez, al arrancar | Cuando cambia la oferta del negocio |
| Fecha de hoy | `OrquestadorAgente._system_prompt_con_fecha()` en `application/orchestrator.py` | **En cada turno**, no al arrancar | Cada día que el proceso sigue vivo |
| Descripciones y schemas de las tools | `application/tools.py::TOOLS_SCHEMA` | Constante, no depende de config | Cuando se añade o cambia una tool |
| Resultados (y errores) de tool | `domain/use_cases.py` (excepciones), formateados por `EjecutorHerramientas`/`OrquestadorAgente` | En cada llamada a una tool dentro del turno | Cuando cambia un mensaje de excepción del dominio |
| Fragmentos del vault (RAG) | `vault_negocio/`, recuperados vía `consultar_conocimiento_negocio` | Bajo demanda, cuando el LLM invoca esa tool | Cuando se edita una nota del vault |
| Parámetros del proveedor (temperatura, formato de `system`) | `adapters/out/llm_*.py` | Fijo por proveedor | Cuando se cambia de proveedor o se ajusta fiabilidad |

Cada fila de esa tabla es una superficie de prompt engineering distinta, con
su propio ciclo de vida. Tratarlas todas como "el prompt" es lo que hace
fácil tocar la pieza equivocada — el ejemplo real de esto en este proyecto es
el #32 (ver más abajo): el síntoma parecía de "instrucciones", pero la causa
era que una pieza (la fecha) se calculaba en el momento equivocado.

## Anatomía del system prompt

`construir_system_prompt(config_negocio)` (`application/prompts.py`) devuelve
un único string, montado así, en este orden:

1. **Identidad y tono**: `"Eres el asistente virtual de {nombre}. Tono: {tono}."`
   — lo único puramente estilístico del bloque base.
2. **Instrucción general de herramientas**: un párrafo fijo, igual para
   cualquier negocio, que le dice al modelo que use las tools antes de dar
   datos concretos y que no invente información que debería venir de la
   documentación. Este párrafo es la razón de que el sistema no alucine
   precios: no depende del RAG para eso, depende de que el modelo tenga
   la instrucción explícita de ir a buscarlo.
3. **Catálogo de servicios y profesionales** (`_construir_catalogo()`): lista
   cada servicio y profesional con su `id` interno exacto. Existe porque el
   RAG solo conoce los servicios por su nombre humano (el que aparece en las
   notas de Obsidian) — sin este bloque, el modelo tiene que *adivinar* el
   `id` que exige `crear_reserva`/`comprobar_disponibilidad`, y falla contra
   el dominio (`ServicioNoExiste`). Este fue exactamente el bug del #31.
4. **Instrucción sobre `cliente_id`**: cómo obtener el dato (pedir teléfono o
   nombre) y usarlo tal cual como identificador — sin esto, el modelo
   inventa un `cliente_id` o se bloquea preguntando de más.
5. **`{instrucciones_extra}`**: cajón general para lo que no encaje en lo
   comercial (legal, accesibilidad, peculiaridades puntuales). Vacío por
   defecto en el negocio de ejemplo — ver más abajo por qué.
6. **`{instrucciones_comerciales}`**: el bloque más grande, con reglas de
   comportamiento comercial concretas, organizadas por escenario (ver la
   sección siguiente). Es el campo que más se toca al iterar sobre #21.

Los puntos 5 y 6 son mecánicamente idénticos — `prompts.py` los concatena sin
ningún tratamiento diferenciado — la única diferencia es de convención: 6 es
específicamente para comportamiento cara al cliente en situaciones
comerciales, 5 es todo lo demás. Si algún día vuelven a acumularse frases
sueltas en `instrucciones_extra` que en realidad son comerciales, es señal de
que deberían moverse a `instrucciones_comerciales` (esto es justo lo que se
limpió antes de retomar el #21: un aviso médico de una frase en
`instrucciones_extra` que quedó duplicado por una versión mucho más completa
del mismo caso en `instrucciones_comerciales`).

### `instrucciones_comerciales` hoy: organizada por escenario, con la misma forma

El contenido actual de `config/business.yaml` bajo `instrucciones_comerciales`
está dividido en secciones con encabezado `##`, y cada una sigue la misma
forma: **cuándo aplica** → **pasos numerados** → **un ejemplo de respuesta
entrecomillado**. Esa forma no es casualidad, es lo que ha funcionado para
que el modelo generalice bien la regla en vez de memorizar el ejemplo literal:

- **Cómo tratar molestias y síntomas del cliente** — no confundir una queja
  física ("tengo dolor de espalda") con una consulta médica; cuándo sí/no
  añadir el disclaimer sanitario.
- **Cómo responder ante señales de abandono o insatisfacción** — nunca
  despedirse ni dar la conversación por cerrada; tratar la señal de fuga como
  algo a gestionar en un único mensaje (reconocer, preguntar qué le haría
  quedarse, ofrecer contacto humano, dejar la puerta abierta).
- **Cómo responder antes de que el cliente decida reservar** — indecisión
  normal antes de la primera reserva, explícitamente *no* tratada como
  abandono.
- **Cómo dar respuestas informativas** — regla de "cierre suave" tras un dato
  factual (precio/horario), sin insistir si el cliente ya ha dicho que solo
  quería el dato.
- **Cómo cerrar la conversación** — distingue un cierre positivo (cliente
  satisfecho) de un cierre por insatisfacción, para no aplicarle a un cliente
  contento las reglas pensadas para retener a uno que se va.

Un patrón que se repite a propósito entre secciones: cada regla nueva deja
explícito **con qué otra regla no debe confundirse** ("esto no es una señal
de abandono", "esto no es una pregunta sin respuesta"). Eso no es relleno —
es la forma de evitar que el modelo generalice de más y aplique la regla de
retención de un cliente insatisfecho a alguien que simplemente se despide
contento, o viceversa. Cuando se añada una sección nueva, vale la pena
preguntarse explícitamente con qué sección existente podría confundirse el
modelo, y decirlo.

## La fecha: por qué se recalcula en cada turno, no al arrancar

`OrquestadorAgente._system_prompt_con_fecha()` (`application/orchestrator.py`)
añade `"Hoy es {fecha}."` al system prompt base **en cada llamada** a
`responder()`/`responder_stream()`, usando `date.today()` en ese momento —
no una vez al construir el orquestador. `formatear_fecha_es()`
(`application/prompts.py`) formatea esa fecha en español sin depender del
locale del sistema operativo, por la misma razón que `_DIAS_SEMANA_ES` en
`domain/use_cases.py` evita `strftime('%A')`.

Esto existe por un bug real, no por precaución teórica: el **#32** documentó
un caso donde, sin esta pieza, el modelo calculó "viernes 7 de agosto" como
si fuera **2023** en vez de 2026 (el 7/8/2023 sí cae en lunes, así que la
hora pedida sí encajaba en el horario del profesional) — la reserva se creó
de verdad, con una fecha completamente distinta a la pedida por el cliente.
El dominio (`domain/use_cases.py`) rechazaba correctamente la reserva cuando
se le llamaba directamente con la fecha real; el fallo estaba enteramente en
que el LLM no tenía ninguna forma fiable de saber qué día era "hoy".

La lección general, más allá de este caso concreto: **cualquier dato de
contexto que cambie con el tiempo de vida del proceso** (no solo la fecha —
piénsese en disponibilidad de última hora, promociones con fecha de
caducidad, etc.) tiene que inyectarse por turno, nunca cachearse en el
prompt base construido al arrancar. Un servidor puede llevar días
corriendo sin reiniciarse.

## Las tools también son prompt: `application/tools.py`

`TOOLS_SCHEMA` no es solo un contrato técnico de entrada/salida — el campo
`description` de cada tool es texto que el modelo lee para decidir *cuándo*
invocarla, exactamente igual que si estuviera en el system prompt. Ejemplos
concretos ya en el código:

- `comprobar_disponibilidad`: `"...Úsalo antes de ofrecer una hora al
  cliente."` — esa frase es lo que empuja al modelo a comprobar huecos antes
  de prometer un horario, no una validación que haga el código.
- `consultar_conocimiento_negocio`: `"Busca en la documentación del negocio
  (precios, políticas, horarios, servicios) para responder preguntas
  informativas."` — la lista entre paréntesis existe para que el modelo
  reconozca ese tipo de pregunta como "consultable", no como algo que deba
  responder de memoria.

Si una mejora de calidad conversacional pasa por cambiar *cuándo* el modelo
decide llamar a una tool (no solo qué le dice al cliente), el sitio a tocar
es la `description` de esa tool en `tools.py`, no `instrucciones_comerciales`
— son dos mecanismos distintos aunque el modelo los lea de forma parecida.

## Los mensajes de error del dominio también los lee el LLM

`EjecutorHerramientas.ejecutar()` (`application/tools.py`) captura cualquier
excepción del caso de uso y la convierte en `{"error": str(exc)}`, que vuelve
al modelo como resultado de la tool (`str(resultado)` en
`OrquestadorAgente.responder()`). Eso significa que el texto de una excepción
como `ProfesionalNoDisponible` o `ServicioNoExiste` (`domain/exceptions.py`)
no es solo para un log o un desarrollador — es lo que el LLM lee para decidir
cómo disculparse ante el cliente o si debe reintentar con otro dato. Redactar
esos mensajes pensando en que un LLM los va a interpretar (claros, sin jerga
interna, con el dato que falta explícito) es tan parte del prompt engineering
de este sistema como tocar `business.yaml`, aunque el fichero que se edite
sea `domain/use_cases.py` o `domain/exceptions.py`.

## Frontera importante: instrucciones (comportamiento) vs. vault (hechos)

`instrucciones_comerciales` controla *cómo* responde el asistente. El vault
de Obsidian (`vault_negocio/`, ver `doc/005-conocimiento-del-negocio.md`)
controla *qué sabe* — precios, horarios, políticas de cancelación. Es una
distinción que vale la pena mantener con disciplina: un precio o un horario
nunca debería aparecer hardcodeado dentro de `instrucciones_comerciales`,
porque entonces hay dos fuentes de verdad para el mismo dato (el vault y el
prompt) que pueden desincronizarse. Las instrucciones comerciales deben
poder reescribirse enteras sin que ningún dato factual del negocio dependa
de ellas.

## El proveedor de LLM no es neutral respecto al mismo prompt

El mismo texto de `system` no se comporta igual en todos los proveedores,
por dos razones que ya están resueltas en el código pero conviene conocer:

- **Cómo se inserta el `system`**: la API de Anthropic (`llm_anthropic.py`)
  acepta un parámetro `system` nativo, separado de los mensajes. Cohere y
  OpenAI (`llm_cohere.py`, `llm_openai.py`) no tienen ese concepto en el
  mismo formato — ambos lo traducen a un mensaje más con `role: "system"`
  al principio del historial (`_traducir_historial()` en cada adaptador).
  Funciona igual de bien en la práctica, pero es la clase de detalle que
  hace que este sistema tenga adaptadores de traducción por proveedor en
  vez de un único cliente HTTP genérico.
- **Temperatura**: `llm_cohere.py` y `llm_openai.py` fijan `temperature=0`
  explícitamente en ambos métodos (`generar_respuesta`/`generar_respuesta_stream`).
  Es una decisión tomada durante el propio #32: en una prueba aislada con el
  mismo caso, la temperatura por defecto de Cohere dio resultados distintos
  en 3 intentos de 3; con `temperature=0`, 4/4 correctos. `llm_anthropic.py`
  hoy **no** fija `temperature` (usa el valor por defecto del SDK) — es una
  inconsistencia real entre proveedores, no una decisión deliberada
  documentada, y candidata razonable a revisar si se retoma fiabilidad de
  tool-calling entre proveedores. El trade-off a tener en cuenta si se
  homogeneiza: `temperature=0` mejora la fiabilidad estructural (fechas,
  ids, confirmaciones) pero también puede hacer que las respuestas
  conversacionales suenen más mecánicas — el objetivo de #21 es justo tono
  cercano, así que no es un cambio gratis.
- **Idioma de respuesta**: el prompt no incluye hoy ninguna instrucción
  explícita de "responde siempre en español" — funciona porque el negocio de
  ejemplo, su vault y sus clientes son hispanohablantes, y los tres
  proveedores tienden a responder en el idioma del último mensaje del
  usuario. Si algún negocio necesitara servir clientes en varios idiomas de
  forma fiable, esto dejaría de ser implícito y pasaría a ser una instrucción
  explícita más en `construir_system_prompt()`.

## El método para mejorar y verificar un prompt

Esto es lo que ya se ha seguido, con éxito documentado, en #31/#32, y lo que
debería repetirse al retomar #21. La pieza clave que lo hace un método y no
"tocar texto a ojo" es `scripts/evaluar_prompt.py` + el banco de casos en
`tests/03_application/casos-dificiles/centro_masajes.yaml`.

### 0. Diagnosticar antes de tocar el prompt

El síntoma no siempre está en la capa donde parece. El #32 es el ejemplo de
libro: el síntoma era "el asistente confirma reservas inválidas", que suena
a "hace falta una instrucción que le diga que valide mejor" — pero la causa
real era que faltaba un dato de contexto (la fecha de hoy), no una regla de
comportamiento. Antes de escribir una instrucción nueva, vale la pena
reproducir el caso llamando directamente al dominio (sin pasar por el LLM)
para confirmar que el dominio en sí ya rechaza/acepta correctamente — si lo
hace, el problema es de contexto o de instrucción; si no lo hace, es un bug
de dominio y ningún prompt lo va a arreglar.

### 1. Reproducir el caso

A mano, contra el chat (`POST /chat` o el frontend), o directamente en
Python con `SesionConversacion` + `OrquestadorAgente.responder()` si hace
falta más control (por ejemplo, para probar el mismo mensaje varias veces
seguidas y ver si el fallo es sistemático o intermitente, como se hizo en
el #32 al aislar el efecto de la temperatura).

### 2. Categorizar el fallo, no solo el caso exacto, y añadirlo al banco

`tests/03_application/casos-dificiles/centro_masajes.yaml` es una lista de
casos con esta forma:

```yaml
- id: dolor_espalda_generico
  entrada: "tengo dolor de espalda"
  no_debe_contener:
    - "no puedo ayudarte"
    - "consulta con un profesional"
  debe_contener_alguno:
    - "descontracturante"
    - "recomiendo"
```

El propio fichero lo dice en su cabecera: "cada vez que encuentres una
respuesta torpe en producción o pruebas manuales, añade un caso nuevo aquí
— categoriza el fallo, no solo el caso exacto". Un caso demasiado literal
(que solo falla con esa frase exacta) no protege contra la siguiente
variación del mismo problema. Los campos disponibles:

- `no_debe_contener` — frases que invalidan la respuesta si aparecen.
- `debe_contener_alguno` — al menos una debe aparecer.
- `debe_contener_todos` — todas deben aparecer.
- `turnos_previos` — mensajes de usuario antes del turno evaluado, para
  casos multi-turno (ejemplo real: `disclaimer_no_repetido`, que comprueba
  que el aviso médico dado en un turno anterior no se repite en el
  siguiente).

Hoy el banco cubre molestias/síntomas y señales de abandono. Las tres
secciones nuevas de `instrucciones_comerciales` (antes de reservar,
informativas, cierre de conversación) todavía no tienen casos — es el
siguiente paso natural antes de dar por buena esa redacción.

### 3. Iterar rápido con el mock

```bash
export PROVEEDOR_LLM=mock
python scripts/evaluar_prompt.py --solo dolor_espalda_generico,abandono_competencia
```

`ProveedorLLMMock` es heurístico y gratis — sirve para detectar errores
obvios de formato/aserciones mientras se ajusta el texto, pero **no** es una
validación real de que un LLM entienda la instrucción: es determinista y no
razona sobre matices, así que puede pasar un caso que un modelo real
interpretaría distinto.

### 4. Validar contra un proveedor real antes de dar el cambio por bueno

```bash
export PROVEEDOR_LLM=anthropic   # o cohere / openai
python scripts/evaluar_prompt.py
```

Sin `--solo`, corre el banco completo — importante para detectar
regresiones, no solo para confirmar el caso nuevo. El propio banco tiene un
caso pensado exactamente para esto (`disclaimer_no_repetido`): una regla
nueva no debería romper el comportamiento ya verificado de una regla
anterior.

### 5. Saber cuándo el límite ya no es el texto del prompt

El desenlace honesto del #32 es la parte más importante del método: tras
arreglar la causa real (fecha) y fijar `temperature=0`, seguía apareciendo
un fallo genuino de vez en cuando con Cohere en su tier gratuito. La
conclusión documentada no fue "seguir puliendo el prompt indefinidamente",
sino reconocer que ese proveedor concreto tiene un techo de fiabilidad que
ninguna instrucción de texto va a superar, y usarlo como argumento para
añadir un proveedor alternativo (#34, OpenAI) en vez de seguir iterando
sobre algo que no era el problema. Si un caso falla de forma intermitente
pese a `temperature=0` y a un prompt correcto, vale la pena sospechar del
proveedor antes que seguir reescribiendo la instrucción.

### 6. Documentar la decisión, no solo el cambio

Los issues #31/#32 no son solo "bug arreglado" — documentan el síntoma, el
diagnóstico erróneo inicial, el diagnóstico corregido, el fix, y una
verificación honesta de qué quedó resuelto del todo y qué no. Eso es lo que
permite que este mismo documento pueda reconstruir la razón de cada
decisión sin tener que volver a experimentar el bug. El mismo estándar
aplica a cambios de `instrucciones_comerciales`: qué caso motivó la
sección, con qué otra regla podría confundirse el modelo, y cómo se
verificó.

## Qué falta para que esto esté automatizado de verdad: #22

Todo el método de arriba se ejecuta a mano, desde terminal. El **#22**
(Automatizar tests prompts difíciles, abierto) es la pieza que falta para
que correr `scripts/evaluar_prompt.py` con `PROVEEDOR_LLM=mock` sea parte de
la CI (`.github/workflows/ci.yml`) y una regresión de calidad conversacional
se detecte sola, en vez de depender de que alguien la note en pruebas
manuales. La validación contra un proveedor real casi seguro debería quedar
fuera de CI (coste de API en cada push), como job manual o programado aparte.

## Resumen: qué tocar según lo que se quiera cambiar

- **Tono o reglas de comportamiento comercial de este negocio** →
  `config/business.yaml` (`instrucciones_comerciales`/`instrucciones_extra`).
  No requiere tocar código ni tests, salvo añadir casos nuevos al banco.
- **Instrucción común a cualquier negocio** (p.ej. idioma de respuesta) →
  `application/prompts.py::construir_system_prompt()`.
- **Cuándo el modelo decide invocar una acción concreta** →
  `application/tools.py::TOOLS_SCHEMA` (campo `description`).
- **Cómo se disculpa o reacciona ante un fallo de dominio** →
  el mensaje de la excepción en `domain/exceptions.py`/`domain/use_cases.py`.
- **Fiabilidad de tool-calling entre proveedores** →
  `adapters/out/llm_*.py` (temperatura, formato de `system`) — no es texto
  de prompt, pero cambia cómo se interpreta el mismo prompt.
- **Un dato factual del negocio** (precio, horario, política) → nunca en
  ninguno de los anteriores: siempre `vault_negocio/`.
