# Despliegue: de `localhost` a un dominio real

> Este documento nace de **#37 — Puesta en producción**, que en su forma
> original era un análisis de estado con un bloqueante de código (CORS) y un
> checklist final. El bloqueante ya está resuelto; lo que queda es
> exactamente ese checklist — que, por naturaleza, se ejecuta en el momento
> de un despliegue real, no como código de este repo. Vive aquí en vez de en
> el issue por el mismo motivo que `doc/002-fase-1-alcance.md` y
> `doc/003-modelo-datos.md`: es referencia viva, no una tarea que se cierra
> una vez.

## Lo que ya está resuelto

- **CORS ya no está hardcodeado a `localhost`.** `adapters/in_/fastapi_app.py`
  lee `CORS_ORIGINS` (lista de orígenes separados por comas) y solo cae a los
  puertos de desarrollo (`:5173`, `:3000`, `:4321`) si la variable no está
  definida — mismo patrón "opcional, degrada al comportamiento de hoy" que el
  resto de piezas configurables del proyecto. **Imprescindible definirla al
  desplegar fuera de `localhost`**, o el navegador bloqueará el preflight
  CORS del frontend contra el dominio real.
- **Las sesiones de conversación pueden sobrevivir a un reinicio.** Cuando
  `doc/003-modelo-datos.md` se escribió, esto (#18) ya estaba resuelto:
  `REDIS_URL` activa `RepositorioSesionesRedis` en vez del diccionario en
  memoria de siempre. Sigue siendo *opcional* — sin ella, cada reinicio del
  proceso sigue borrando las conversaciones activas, que es justo la
  limitación que motivó originalmente este punto en el checklist de #37.
- **Postgres real ya no es solo teórico.** #41 provisionó uno de verdad (un
  plan gratuito de [Neon](https://neon.tech/)) y verificó que, con
  `DATABASE_URL` definida, `main.py` y el panel interno comparten el mismo
  estado. El mismo patrón sirve para producción: lo que cambia es solo qué
  Postgres hay detrás de esa URL, no el código.

## Limitaciones que siguen sin resolver — decisiones, no bugs

Ninguna de estas bloquea un despliegue de facto, pero conviene decidir
explícitamente qué hacer con cada una antes de abrir el dominio al público
real, aunque la decisión sea "lo asumimos por ahora":

- **Un solo proceso, sin supervisor.** `main.py:158` (`main()`) lanza
  `uvicorn` en un hilo daemon dentro del propio proceso Python — no hay
  systemd, Docker con `restart: unless-stopped`, ni ningún otro supervisor
  que lo reinicie si crashea. Además, con el diseño actual de sesiones (un
  diccionario en memoria por defecto, o Redis compartido si está activo), no
  se puede simplemente levantar más de un worker sin haber activado Redis
  primero — cada worker en memoria tendría su propio estado de conversación,
  aislado de los demás. `GET /health` (`doc/008-api.md`) ya existe y es
  justo la pieza que un supervisor real (systemd, Docker, un balanceador)
  necesitaría consultar para decidir cuándo reiniciar el proceso — hoy nadie
  lo consulta automáticamente, solo está disponible para quien lo conecte.
- **`/chat` y `/chat/stream` son públicos y sin límite de uso.** No hay rate
  limiting ni autenticación en ninguno de los dos endpoints. En cuanto el
  dominio sea público e indexable, cualquiera — o un bot — puede agotar la
  cuota del proveedor de LLM configurado sin ningún freno. No hay issue
  abierto todavía específicamente para esto; si se aborda, un rate limit por
  IP o por `usuario_id` (p. ej. vía `slowapi` o un middleware propio) sería
  el punto de partida más simple.

## Checklist de infraestructura para un despliegue real

Estos cinco puntos no son código de este repo — es trabajo que se ejecuta en
el momento del despliegue, específico del hosting/proveedor que se elija:

1. **Dominio + DNS + TLS/HTTPS.** Let's Encrypt vía Caddy/nginx como *reverse
   proxy* delante de `uvicorn`, o TLS gestionado directamente por el
   hosting. Decidir si backend y frontend viven en el mismo dominio o en
   subdominios distintos — afecta directamente a qué valor necesita
   `CORS_ORIGINS`.
2. **Secrets reales en el servidor.** `.env` con `ANTHROPIC_API_KEY` (o la
   clave del proveedor de LLM elegido) real, nunca committeado — el patrón ya
   establecido es `.env` en `.gitignore` y `.env.example` documentando qué
   variables existen sin valores reales.
3. **Postgres real provisionado + `alembic upgrade head`.** Si se quiere que
   citas/clientes/pedidos sobrevivan a reinicios (si no, siguen en memoria,
   igual que en desarrollo sin `DATABASE_URL`). #41 documenta cómo se hizo
   esto mismo para desarrollo con Neon; el mismo patrón sirve para
   producción, con un plan de pago si el volumen lo justifica.
4. **Indexar el vault antes de abrir al público.**
   `python -m adapters.out.obsidian_ingest --vault ./vault_negocio` como
   parte del propio proceso de despliegue — sin esto, el RAG arranca vacío y
   el asistente no tiene ninguna respuesta informativa que dar.
5. **Build + hosting del frontend.** `npm run build` en `frontend/`, subir
   `dist/` a hosting estático (Netlify, Vercel, Cloudflare Pages, o el mismo
   servidor detrás del reverse proxy del punto 1), con
   `PUBLIC_API_BASE_URL` (`frontend/.env`) apuntando al dominio real del
   backend, no a `localhost:8000`.

## Variables de entorno relevantes para producción

Adicionales a las que ya cubre `.env.example` para desarrollo local
(`ANTHROPIC_API_KEY`/`PROVEEDOR_LLM`, `DATABASE_URL`, `REDIS_URL`,
`GOOGLE_CALENDAR_*`) — estas dos son las que específicamente cambian de
valor al salir de `localhost`:

- `CORS_ORIGINS` — el dominio real del frontend, no los puertos de dev.
- `PANEL_EMPLEADOS_PASSWORD` — sin ella, el panel interno
  (`panel_empleados/streamlit_app.py`) se abre sin ningún gate; en
  producción, con datos reales de citas/pedidos, conviene definirla.

## Cuándo se da este checklist por completado

Deliberadamente no hay una fecha ni una condición de "hecho" — la última
línea de #37 lo decía explícitamente: se recorre en el momento de un
despliegue real, no antes. Este documento es la referencia que se sigue en
ese momento, y se actualiza si el checklist cambia (un nuevo punto de
infraestructura, una limitación resuelta) igual que `doc/002` y `doc/003` se
actualizan cuando cambia lo que documentan.
