# Errores y warnings conocidos

Cosas que vas a ver corriendo el sistema, los tests o la CI que **no son
bugs** — ya diagnosticadas, con una razón documentada de por qué se dejan
así. El objetivo de este documento es que nadie (ni una futura sesión de
Claude Code) pierda tiempo re-investigando algo ya resuelto como "se deja
así, y esto es por qué".

## Aviso de Hugging Face Hub sin autenticar

```
Warning: You are sending unauthenticated requests to the HF Hub. Please set a HF_TOKEN to enable higher rate limits and faster downloads.
```

Aparece en cada arranque que necesita cargar el modelo de embeddings
(`adapters/out/vector_store.py`, vía `sentence-transformers`) — al arrancar
`main.py`, el panel interno, o al ingerir el vault. Con `python main.py`
sale directamente en la terminal; con `scripts/dev_up.sh` va a
`logs/backend.log` (o `logs/panel.log`), no a la terminal, así que puede
parecer que "ha desaparecido" cuando en realidad solo cambió de sitio.

**Por qué se deja así — [#23](https://github.com/davidbp845/orquestador-serenidad/issues/23)
(cerrado sin implementar):** el token de Hugging Face solo sube el rate
limit y acelera la descarga — no desbloquea ninguna funcionalidad, y con el
volumen de este proyecto (un puñado de fragmentos en el vault) nunca se
llega a tocar ningún límite real. Se intentó darse de alta en
huggingface.co para crear el token, pero el registro falla en Firefox sobre
Ubuntu — sospecha razonable: el alta usa un captcha Cloudflare Turnstile,
que es conocido por fallar en silencio con `privacy.resistFingerprinting` u
otras protecciones de fingerprinting/tracking activadas (probar en ventana
privada, con esa opción desactivada en `about:config`, o desde otro
navegador/dispositivo, si se retoma). Se cerró por prioridad: el aviso es
cosmético. `HF_TOKEN=` ya está documentado como placeholder en
`.env.example` para cuando alguien quiera retomarlo — basta con crear el
token y pegarlo ahí, sin tocar código.

## Warnings de terceros en la suite de tests

`pytest` termina con ~26 warnings — ninguno del código propio del proyecto.
Ejemplos recurrentes:

```
DeprecationWarning: 'asyncio.iscoroutinefunction' is deprecated and slated for removal in Python 3.16; use inspect.iscoroutinefunction() instead
StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
```

**Por qué se dejan así — [#13](https://github.com/davidbp845/orquestador-serenidad/issues/13)
(cerrado):** de los warnings originales, los que eran del propio código
(`datetime.utcnow()` deprecado) ya se corrigieron entonces. Los que quedan
vienen de dentro de `chromadb`, `cohere`, `starlette`/`fastapi` — no de
código de este repo — y solo se resolverían fijando otras versiones de esas
librerías, lo que se decidió conscientemente no perseguir en un skeleton.
Si el número de warnings sube de forma notable en una sesión, vale la pena
mirar si alguno nuevo sí viene de código propio (eso sí sería accionable);
si sigue siendo la misma familia de warnings de siempre, no hace falta
investigar más.

## `mypy` no cubre todo el repo

```bash
mypy .              # 47 errores en adapters/ y main.py
mypy domain application   # limpio — esto es lo que corre en CI
```

**Por qué se deja así — [#19](https://github.com/davidbp845/orquestador-serenidad/issues/19)
(cerrado, parcial/incremental por diseño):** el job `mypy` de CI
(`.github/workflows/ci.yml`) solo corre sobre `domain/` y `application/` —
las capas sin dependencias externas, donde `disallow_untyped_defs` pasa
limpio. Extender a `adapters/`/`main.py` quedó explícitamente para otra
iteración: incompatibilidades de tipos entre `chromadb` y
`sentence-transformers`, un `dict` con tipos heterogéneos en
`llm_cohere.py`, y variables reasignadas entre implementaciones en
memoria/Postgres en `main.py::construir_sistema` sin anotar con el tipo del
puerto. Ver `doc/002-fase-1-alcance.md` sección 7 para el detalle completo.
Si tocas algo en `adapters/` o `main.py`, no te sorprendas si `mypy .`
(a diferencia del `mypy domain application` que corre en CI) saca errores
preexistentes que no tienen que ver con tu cambio.

## Panel: el botón "Acceder al Calendario" sigue exigiendo sesión de Google

La sección Agenda del panel (`panel_empleados/streamlit_app.py`) tiene un
botón `st.link_button("Acceder al Calendario", ...)` que abre
`https://calendar.google.com/calendar/u/0/r?cid=...` — esa URL siempre
exige que quien la abra tenga sesión iniciada en una cuenta de Google con
acceso compartido al calendario del negocio, aunque el propio panel ya
esté protegido por `PANEL_EMPLEADOS_PASSWORD`.

**Por qué se deja así — [#63](https://github.com/davidbp845/orquestador-serenidad/issues/63)
(cerrado sin implementar, por tiempo):** técnicamente es abordable sin
credenciales nuevas — `SincronizadorCalendarioGoogle`
(`adapters/out/calendario_google.py`) ya se autentica con una cuenta de
servicio con scope de lectura+escritura sobre el calendario, solo que hoy
únicamente implementa `crear_evento`/`cancelar_evento`, sin ningún método
de listado. El issue deja documentado el plan completo para cuando se
retome:

1. Añadir un método de lectura al adaptador (ej. `listar_eventos(desde,
   hasta)` vía `events().list(...)`).
2. Decidir el puerto: ampliar `SincronizadorCalendario` (hoy documentado
   explícitamente como escritura *best-effort* — mezclar lectura ahí
   podría confundir esa semántica) o crear uno nuevo y separado (ej.
   `LectorCalendario`).
3. En el panel, sustituir o complementar el botón actual por una vista
   embebida en Streamlit que llame a ese método — sin sesión de Google, y
   sin salir del gate `PANEL_EMPLEADOS_PASSWORD` ya existente.

Se valoró la alternativa sin código de hacer el calendario público en los
ajustes de Google Calendar (genera una URL de embed/iCal sin login), pero
`crear_evento` ya mete `description: f"Cliente: {cita.cliente_id}"` en
cada evento — publicar el calendario completo expondría ese dato a
cualquiera con el enlace, así que la vía API (control de acceso ya
resuelto por el panel) es la opción correcta si se retoma.

## Aviso de Node.js 20 deprecado en cada run de CI

```
Node.js 20 is deprecated. The following actions target Node.js 20 but are
being forced to run on Node.js 24: actions/checkout@v4, actions/setup-python@v5.
```

Aparece como *annotation* en los tres jobs de `.github/workflows/ci.yml`
(`lint`, `test`, `mypy`) en cada ejecución — GitHub Actions lo fuerza a
correr sobre Node 24 automáticamente, así que hoy no rompe nada ni requiere
acción. Viene de que `actions/checkout@v4` y `actions/setup-python@v5` (las
versiones fijadas en el workflow) todavía declaran Node 20 como runtime; se
resolverá solo cuando esas actions se actualicen a una versión mayor que
declare Node 24, sin que haga falta ningún cambio de lógica en el workflow.
No hay issue abierto para esto — es una nota informativa de GitHub, no un
fallo del proyecto.
