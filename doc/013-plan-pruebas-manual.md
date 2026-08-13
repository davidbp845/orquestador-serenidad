# Plan de pruebas manual

`pytest` cubre la lógica unitaria — este plan cubre lo que solo se detecta
usando el sistema como lo usaría un cliente real o un empleado: tono
comercial, streaming, layout responsivo, comportamiento cruzando canales y
proveedores de LLM. Pensado para ejecutarse a mano, sin automatizar: cada
bloque dice qué preparar, qué hacer y qué se espera ver. Marca cada caja al
pasarlo; si algo falla, anota el mensaje/comportamiento real junto a la caja
en vez de solo dejarla sin marcar.

## 0. Preparación

- [ ] Entorno virtual activado, `pip install -r requirements.txt` +
      `requirements-dev.txt` (para poder correr `pytest` como referencia).
- [ ] `export ANTHROPIC_API_KEY=...` **o** `export PROVEEDOR_LLM=mock`
      (recomendado para la primera pasada: gratis, determinista, sin gastar
      tokens).
- [ ] Vault indexado: `python -m adapters.out.obsidian_ingest --vault ./vault_negocio`
- [ ] `python main.py` arrancado, sin errores en el log de arranque. Confirmar
      qué adaptadores se han activado leyendo las primeras líneas de log
      (LLM elegido, si hay Redis/Postgres/Calendar/Telegram configurados).
- [ ] `curl http://localhost:8000/health` → `{"status":"ok"}`.
- [ ] Sin `CONFIG_PATH` definida (comportamiento por defecto): backend, panel
      y frontend usan `config/business.yaml` — ver sección 10 para probar el
      override.
- [ ] **Importante para la sección 1.3**: desde que existe la verificación de
      teléfono (ver sección 7.3), `crear_reserva`/`guardar_nota_cliente` con
      un teléfono nuevo por chat web exigen verificarlo primero — necesitas
      **o bien** `WHATSAPP_*`/`TWILIO_*` configuradas (sección 7), **o bien**
      probar ese flujo por Telegram (sección 6), que está exento. Sin ninguna
      de las dos cosas, `crear_reserva` por chat web se queda bloqueada en el
      paso de verificación — es el comportamiento esperado, no un bug, pero
      cambia lo que hace falta preparar antes de la sección 1.

Repite todo este plan (o al menos las secciones 1-4) una segunda vez con
`PROVEEDOR_LLM=anthropic` (o `cohere`/`openai` si es lo que hay configurado
en producción) antes de dar por buena una release — el modo `mock` no
detecta problemas de calidad de respuesta real del LLM.

---

## 1. Chat web — flujo básico y herramientas

Usar `curl` o el frontend (`cd frontend && npm run dev`, http://localhost:4321).
Con `curl`:

```bash
curl -s -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"usuario_id": "prueba-1", "mensaje": "..."}' | python -m json.tool
```

Usa el **mismo `usuario_id`** durante todo un escenario para mantener la
sesión/historial; cambia de `usuario_id` para empezar una conversación nueva.

### 1.1 `consultar_conocimiento_negocio`
- [ ] Preguntar `"¿cuánto cuesta el masaje relajante de 60 minutos?"` →
      responde **55€** de forma directa (sin rodeos) y cierra con un
      siguiente paso (ofrecer franja / preguntar si quiere reservar).
- [ ] Preguntar algo que no está en el vault (p.ej. `"¿tenéis parking
      gratuito?"` si no aparece en `vault_negocio/ubicacion-contacto.md`) →
      lo dice con naturalidad, sin sonar a "no puedo ayudarte", y ofrece
      derivar a una persona.
- [ ] Repetir la primera pregunta de precio dos veces seguidas en la misma
      sesión → la segunda vez no repite el mismo cierre de venta si ya se
      ha dejado claro que solo se quería el dato (probar con `"vale,
      gracias"` como segundo mensaje y comprobar que no insiste).

### 1.2 `comprobar_disponibilidad`
- [ ] `"¿tenéis hueco para un masaje descontracturante de 45 minutos el
      próximo lunes?"` → el agente debe llamar a la herramienta y devolver
      horas concretas dentro del horario de Ana García (lunes 09:00–18:00
      en `config/business.yaml`), no horas inventadas.
- [ ] Pedir un día fuera de horario (sábado o domingo, ningún profesional
      trabaja) → responde que no hay huecos ese día, sin error ni
      alucinación de horas.
- [ ] Pedir un servicio inexistente (`"quiero un masaje con piedras
      calientes"`, no está en `config/business.yaml`) → el agente no debe
      inventar disponibilidad; debe aclarar que ese servicio no existe y
      ofrecer los que sí hay.

### 1.3 `crear_reserva`
- [ ] Completar un flujo natural: preguntar disponibilidad → elegir una
      hora ofrecida → confirmar datos de cliente (nombre/teléfono si los
      pide) → **verificar el teléfono si el agente lo pide** (primera vez que
      aparece ese número en la conversación y el canal no está exento — ver
      sección 7.3 para el detalle) → reserva creada. Comprobar que la
      respuesta final es un resumen cálido (servicio, día, hora), no un
      "reserva creada" seco.
- [ ] Verificar la reserva por fuera del chat: abrir el panel interno
      (sección 8.1) y comprobar que la cita aparece en Agenda con los
      datos correctos, incluido el **nombre del cliente** junto a su id.
- [ ] Repetir el mismo hueco horario con otro `usuario_id`/cliente
      (double-booking) → el agente debe detectar que ya no está libre
      (`ProfesionalNoDisponible`) y ofrecer alternativas, no crear una cita
      solapada.
- [ ] Pedir una reserva con datos incompletos (sin decir a qué hora) → el
      agente pregunta antes de llamar a la herramienta, no inventa un
      `inicio`.
- [ ] Reservar con el teléfono de una clienta que **ya existe** (creada en
      una pasada anterior de este plan) → no se duplica: se reutiliza el
      mismo `Cliente` (el teléfono es la clave de reconocimiento, no el
      nombre) y solo se actualiza el nombre si cambió.

### 1.4 `registrar_pedido`
- [ ] Pedir algo que encaje como "producto/servicio adicional" según lo que
      haya en `vault_negocio/servicios.md` o `promociones.md` (p.ej. un
      bono o producto de venta) → se registra el pedido y aparece luego en
      el panel interno, sección Pedidos, con estado inicial pendiente.

---

## 2. Instrucciones comerciales del negocio (`instrucciones_comerciales`)

Estos casos verifican el *tono y comportamiento comercial*, no una
herramienta — son los más fáciles de romper al cambiar de proveedor de LLM
o de prompt. Compara contra lo descrito en `config/business.yaml`.

- [ ] **Molestia leve** (`"tengo un poco de contractura en la espalda"`) →
      recomienda servicio adecuado, tono de recepcionista, **sin**
      disclaimer médico.
- [ ] **Señal médica real** (`"me he operado hace poco de la espalda,
      ¿puedo daros un masaje?"`) → SÍ debe aparecer el disclaimer ("no
      somos un servicio médico...") y ofrecer contacto humano directo, no
      un "profesional sanitario" en abstracto.
- [ ] Repetir una segunda señal médica en la **misma conversación** → el
      disclaimer no debe repetirse una segunda vez.
- [ ] **Señal de abandono/insatisfacción** (`"es muy caro comparado con
      otros centros de la zona"`) → nunca se despide ni dice "no puedo
      ayudarte"; en un solo mensaje: reconoce, pregunta qué le haría
      quedarse, ofrece contacto humano si procede, deja la puerta abierta.
      Comprobar explícitamente que **no** aparecen frases tipo "buena
      suerte" o "no podemos ayudarte más".
- [ ] **Indecisión antes de reservar** (`"es mi primera vez, no sé si el de
      90 minutos es demasiado"`) → ayuda a decidir con un criterio
      concreto y sugiere la opción de menor compromiso (60 min), sin
      tratarlo como señal de abandono.
- [ ] **Cierre satisfecho** (`"perfecto, gracias, nada más"` tras una
      reserva) → lo acepta sin insistir en vender nada más.

---

## 3. Streaming (`/chat/stream`) y fuentes RAG

- [ ] `curl -N -X POST http://localhost:8000/chat/stream -H 'Content-Type:
      application/json' -d '{"usuario_id":"prueba-stream","mensaje":"¿qué
      servicios ofrecéis?"}'` → se reciben varios `event: delta` con texto
      incremental, luego `event: fuentes` y `event: done` con la respuesta
      completa. Ningún `event: error` en un caso normal.
- [ ] Con el frontend levantado (`npm run dev` en `frontend/`), enviar el
      mismo mensaje desde la UI → el texto aparece progresivamente (no de
      golpe al final).
- [ ] Provocar una fuente del vault marcada `publicar_web: true` (pregunta
      de precio/horario) → tras la respuesta, la tarjeta correspondiente en
      `GridContenido` se resalta (evento `orquestador:fuentes`).
- [ ] Pasar el ratón por encima de una tarjeta de contenido, marcada como
      fuente o no → ambas se resaltan igual on hover (mismo estilo que las
      sugerencias de pregunta del chat).
- [ ] Preguntar algo cuya fuente en el vault **no** tiene `publicar_web:
      true` → el LLM puede usar el contenido para responder, pero no debe
      aparecer como "fuente" clicable ni resaltar ninguna tarjeta.
- [ ] Revisar visualmente `http://localhost:4321` (páginas públicas de
      contenido) para confirmar que solo aparecen notas del vault con
      `publicar_web: true`.

---

## 4. Frontend público — funcionalidades adicionales

- [ ] CTA de la cabecera (issue #56): pulsar el botón de reservar → abre/
      despliega el chat y escribe el mensaje configurado en
      `cta_cita.mensaje` letra a letra, enviándolo solo al terminar.
- [ ] Enviar un mensaje escribiendo en el campo de texto y pulsando **Tab**
      → el foco pasa al botón "Enviar" (antes quedaba fuera del orden de
      tabulación); **Intro** dentro del campo de texto envía sin necesidad
      de hacer clic.
- [ ] Icono de comprimir/expandir la respuesta del chat: apunta en
      **vertical** (chevron que rota 180°), no en diagonal.
- [ ] Logo: en desktop se ve completo (icono + "Masajes" + nombre); en
      viewport móvil (por debajo de `sm`) cambia a la variante compacta
      (solo icono) (#70).
- [ ] Fondo del body (#59): si `imagen_fondo_url` está configurada en
      `business.yaml`, se ve como fondo fijo con la transparencia esperada,
      sin romper la legibilidad del contenido por encima.
- [ ] Widget de Testimonios (Hero, issues #61/#72), con al menos 2-3
      testimonios cargados:
  - [ ] Desktop con el chat **expandido**: el widget queda en una columna
        vertical alta → el carrusel muestra varios testimonios a la vez y
        se desplaza en vertical.
  - [ ] Comprimir el chat (icono junto a "Enviar") → el widget pasa a
        horizontal, mostrando 1 solo testimonio.
  - [ ] Redimensionar a anchura de tablet (~768–1023px; el widget pasa a
        quedar debajo del chat, no al lado) → carrusel horizontal, hasta 3
        testimonios visibles si hay espacio.
  - [ ] Seguir estrechando hasta móvil → el número de testimonios visibles
        baja progresivamente hasta 1.
  - [ ] Recargar la página con el backend caído o lento → aparece un
        placeholder animado (`animate-pulse`) del mismo tamaño que tendrá
        el contenido real, sin hueco vacío ni salto de layout; si la
        primera petición falla, se reintenta una vez antes de rendirse.
- [ ] Márgenes: comparar visualmente el margen horizontal de la sección
      Hero y el de la sección de contenido público a la misma anchura de
      pantalla (probar en concreto alrededor de ~1090px) → deben coincidir
      exactamente, sin que el widget de Testimonios (ni ningún otro
      elemento) toque el borde derecho de la pantalla.
- [ ] Enlace al panel interno (#58): con `PUBLIC_MOSTRAR_PANEL=true` en
      `frontend/.env`, aparece el enlace "Panel interno" en el pie
      apuntando a `PUBLIC_PANEL_URL`. Sin definir la variable, el enlace no
      existe en el HTML generado por `npm run build` (no solo oculto por
      CSS) — comprobable con `grep 'Panel interno' frontend/dist/index.html`.

---

## 5. Rate limiting (`/chat` y `/chat/stream`)

- [ ] Con los valores por defecto (20 peticiones / 60s) o los que estén en
      `RATE_LIMIT_CHAT_MAX_PETICIONES`/`RATE_LIMIT_CHAT_VENTANA_SEGUNDOS`,
      enviar más peticiones que el límite en bucle rápido, mismo
      `usuario_id`:
      ```bash
      for i in $(seq 1 25); do
        curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/chat \
          -H 'Content-Type: application/json' \
          -d '{"usuario_id":"prueba-rate","mensaje":"hola"}'
      done
      ```
      → las primeras N devuelven 200, el resto devuelve **429** con el
      mensaje "Demasiadas peticiones...".
- [ ] Cambiar de `usuario_id` durante el bloqueo → esa nueva identidad no
      está limitada (el límite es por `usuario_id`, no global ni por IP).
- [ ] Esperar a que pase la ventana (por defecto 60s) → volver a poder
      enviar mensajes con el `usuario_id` bloqueado.

---

## 6. Telegram (opcional — requiere `TELEGRAM_BOT_TOKEN`)

> Según el `CLAUDE.md` del repo, correr `main.py` con `TELEGRAM_BOT_TOKEN`
> puesto inicia polling real e interactúa con Telegram real — pide
> confirmación antes de hacerlo si no está ya explícitamente autorizado.

- [ ] Enviar un mensaje al bot desde un chat real de Telegram → responde
      con el mismo comportamiento que el chat web (mismo orquestador).
- [ ] Completar un flujo de `crear_reserva` desde Telegram → comprobar en
      el panel interno que el `Cliente` correspondiente queda con
      `telegram_chat_id` vinculado (visible como "📱 Telegram vinculado"
      en la sección Clientes del panel).
- [ ] Verificar que la sesión de Telegram es independiente de la sesión web
      del mismo usuario (canales distintos, historiales distintos).

---

## 7. WhatsApp, SMS y verificación de teléfono

Issue de referencia con el paso a paso completo de credenciales/prerrequisitos
para esta sección entera: **#87**.

### 7.1 Webhook de entrada — WhatsApp (opcional — requiere `WHATSAPP_*` + túnel público)

- [ ] `GET /webhook/whatsapp` con los parámetros `hub.mode=subscribe`,
      `hub.verify_token=<WHATSAPP_VERIFY_TOKEN>`, `hub.challenge=<valor>`
      → responde con `hub.challenge` tal cual (handshake de verificación de
      Meta).
- [ ] `GET /webhook/whatsapp` con un `hub.verify_token` incorrecto →
      rechazado (no debe hacer echo del challenge).
- [ ] Mensaje de texto entrante real (o simulado con el payload de ejemplo
      de la documentación de Meta) → el bot responde vía la Graph API y el
      mensaje llega al número de WhatsApp de prueba.
- [ ] Firma HMAC del payload (`WHATSAPP_APP_SECRET`) inválida → la petición
      se rechaza, no se procesa como mensaje válido.

### 7.2 Notificaciones salientes — WhatsApp y SMS (opcional — requiere `WHATSAPP_ACCESS_TOKEN`/`WHATSAPP_PHONE_NUMBER_ID` y/o `TWILIO_*`)

No hace falta `canales.whatsapp: true` ni el webhook de 7.1 activo para esto:
el notificador saliente se instancia solo por las variables de entorno,
independiente del canal de entrada.

- [ ] Con `WHATSAPP_ACCESS_TOKEN`/`WHATSAPP_PHONE_NUMBER_ID` definidas,
      completar una reserva por chat web con un teléfono ya verificado (ver
      7.3) → el mensaje de confirmación de la reserva llega al WhatsApp de
      prueba.
- [ ] Repetir con `TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN`/
      `TWILIO_NUMERO_REMITENTE` en vez de las de WhatsApp (recuerda que una
      cuenta trial de Twilio solo manda SMS a números verificados en su
      panel) → el mensaje llega por SMS.
- [ ] Con las credenciales de los dos canales definidas a la vez → se usa
      WhatsApp, no SMS (prioridad fija en `main.py`, no aleatoria).
- [ ] Cancelar esa cita desde el panel interno (sección 8.1) → llega el
      aviso de cancelación por el mismo canal.
- [ ] Confirmar una cita desde el panel (transición a `CONFIRMADA`) → llega
      el aviso de confirmación.
- [ ] Sin `WHATSAPP_*`/`TWILIO_*` ni `telegram_chat_id` para ese cliente →
      no se manda ninguna notificación y el flujo no se rompe (best-effort).

### 7.3 Verificación de teléfono (opcional — requiere 7.2, o probar por Telegram)

- [ ] Por chat web, reservar (1.3) o guardar una nota de cliente (
      `guardar_nota_cliente`) con un teléfono que no haya aparecido antes en
      esa conversación, en un canal no exento → el agente llama a
      `verificar_telefono`, avisa de que ha enviado un código, y no completa
      la acción hasta confirmarlo con `confirmar_codigo_verificacion`.
- [ ] Dar un código incorrecto → el agente lo indica y permite reintentar,
      sin insistir más de 2-3 veces (según la instrucción del prompt de
      sistema) antes de ofrecer derivar a una persona.
- [ ] Dar el código correcto → la acción pendiente (reserva o nota) se
      completa con normalidad.
- [ ] Repetir una segunda acción (p.ej. una nota tras haber reservado) para
      el mismo `cliente_id` ya conocido en la misma conversación → no vuelve
      a pedir verificación.
- [ ] Por Telegram (sección 6) → nunca pide código, aunque sea la primera
      vez que ese teléfono aparece en el sistema.
- [ ] Por WhatsApp (7.1), dando como teléfono el mismo número desde el que
      se escribe → no pide código. Dando un número distinto → sí lo pide.
- [ ] Sin `WHATSAPP_*` ni `TWILIO_*` configuradas y fuera de Telegram/
      WhatsApp-mismo-número → `verificar_telefono` devuelve un error claro
      (no hay canal disponible para mandar el código), el chat no se rompe.

---

## 8. Panel interno (`panel_empleados/`)

```bash
streamlit run panel_empleados/streamlit_app.py
```

- [ ] Si `PANEL_EMPLEADOS_PASSWORD` está definida → pantalla de acceso
      pide contraseña; contraseña incorrecta muestra error y no deja
      pasar; correcta entra al panel. Sin la variable definida, el panel
      abre directo sin pantalla de acceso.
- [ ] Redimensionar la ventana / abrir en móvil → el menú se colapsa a la
      izquierda (sidebar) y el contenido se apila en tarjetas sin scroll
      horizontal.

### 8.1 Agenda
- [ ] Vista **Día**: muestra las citas de hoy (las creadas en la sección 1
      deberían aparecer aquí). Botones "◀ Anterior" / "Hoy" / "Siguiente ▶"
      navegan correctamente por días.
- [ ] Vista **Semana** y **Mes**: agrupan las citas por día con subcabecera,
      sin romper el layout.
- [ ] Cambiar el estado de una cita (p.ej. a "completada" o "cancelada")
      desde una tarjeta → se actualiza sin recargar manualmente
      (`st.rerun()`), y una transición inválida muestra un error legible
      en vez de romper la página.
- [ ] Cancelar una cita desde el panel y volver a preguntar disponibilidad
      por chat para ese mismo hueco → debe volver a aparecer libre.

### 8.2 Pedidos
- [ ] El pedido creado en la sección 1.4 aparece listado con sus líneas
      (servicio, cantidad, notas) y su estado actual.
- [ ] Cambiar su estado con el selector + "Actualizar" → se refleja
      inmediatamente; probar una transición no permitida y comprobar que
      muestra `TransicionEstadoInvalida` de forma legible, no una excepción
      sin capturar.

### 8.3 Clientes
- [ ] El cliente creado al reservar por chat aparece en la lista, con
      teléfono/email si se dieron, y su `id` generado automáticamente por
      el contador (no escrito a mano).
- [ ] Crear/editar/eliminar un cliente manualmente desde el panel → se
      refleja al momento; el `id` es visible pero no editable.
- [ ] Buscar por nombre parcial y por teléfono parcial → filtra
      correctamente (insensible a mayúsculas).
- [ ] Un cliente que reservó por Telegram (sección 6) muestra "📱 Telegram
      vinculado"; uno que solo usó el chat web muestra "Sin Telegram
      vinculado".
- [ ] **Duplicados**: crear (o localizar) dos clientes con el mismo nombre
      y teléfono → marcar el checkbox "Ver solo duplicados" los agrupa;
      pulsar "Fusionar en el más antiguo" los combina en un solo `Cliente`
      (el de id más antiguo sobrevive) y reasigna sus citas/pedidos.
      Comprobar que, tras la fusión y el recargo automático de la vista, el
      checkbox **queda desmarcado solo** (no atascado en "solo duplicados"
      con la lista ya vacía).

### 8.4 Rate limiting (panel)
- [ ] **Sin `REDIS_URL`**: la sección muestra el aviso de que no está
      disponible sin Redis (el panel es un proceso aparte sin memoria
      compartida con `main.py`).
- [ ] **Con `REDIS_URL`** (ver sección 9.2): repetir el bloque de la
      sección 5 (bucle de peticiones) y comprobar que el consumo por
      `usuario_id` aparece aquí en vivo, con el contador correcto y
      "Límite alcanzado" cuando corresponde.

### 8.5 Ajustes — reindexar RAG
- [ ] Botón "Reindexar conocimiento" → tras el spinner, mensaje de éxito
      con el número de fragmentos indexados. Editar una nota del vault
      antes de pulsar (p.ej. cambiar un precio en `servicios.md`) y
      comprobar por chat que la respuesta usa el valor nuevo después de
      reindexar.
- [ ] Provocar un error (p.ej. apuntar `vault_obsidian` a una ruta
      inexistente temporalmente) → el panel muestra el error en vez de
      crashear.
- [ ] Sección de solo lectura de **contadores** (uno por tipo de entidad):
      muestra el valor actual de cada contador (clientes, testimonios...);
      inicializarlos a un valor concreto desde aquí y comprobar que el
      siguiente id generado por ese tipo de entidad continúa desde ahí.

### 8.6 Testimonios
- [ ] Crear/editar/eliminar un testimonio manualmente desde el panel → se
      refleja de inmediato en esta lista y (tras recargar) en el carrusel
      del Hero del frontend (sección 4).
- [ ] Crear un testimonio **sin título** → se guarda sin error (el título
      no es obligatorio) y se muestra correctamente en el carrusel sin un
      hueco en blanco donde iría el título.

---

## 9. Persistencia opcional

### 9.1 Postgres (`DATABASE_URL`)
> Solo contra una base de datos **local**, nunca compartida/producción —
> ver política de autonomía del repo.
- [ ] `alembic upgrade head` aplica sin error sobre una base nueva.
- [ ] Crear una reserva/pedido por chat con `DATABASE_URL` puesto → parar
      `main.py` y volver a arrancarlo → la cita/pedido siguen existiendo
      (a diferencia del modo en memoria).
- [ ] Repetir la sección 8 (panel) apuntando al mismo `DATABASE_URL` → ve
      los mismos datos que el backend.

### 9.2 Redis — sesiones (`REDIS_URL`)
- [ ] Mantener una conversación con varios turnos → reiniciar `main.py` →
      seguir la conversación con el mismo `usuario_id` → el agente recuerda
      el contexto previo (a diferencia del modo en memoria, que lo pierde
      al reiniciar).
- [ ] Con Redis puesto, repetir la sección 8.4 (rate limiting en el panel)
      y confirmar que ahí sí hay datos.

### 9.3 Google Calendar (`GOOGLE_CALENDAR_CREDENTIALS_JSON` + `GOOGLE_CALENDAR_ID`)
> Esto sincroniza un calendario de Google **real y externamente visible** —
> requiere confirmación explícita antes de ejecutar, según la política de
> autonomía del repo. Usar un calendario de prueba, no uno real de negocio.
- [ ] Crear una reserva por chat → aparece como evento en el calendario de
      Google configurado, con la zona horaria correcta
      (`GOOGLE_CALENDAR_TIMEZONE`).
- [ ] Cancelar la cita desde el panel → el evento se elimina/actualiza en
      Google Calendar.
- [ ] Simular un fallo de la API de Calendar (credenciales inválidas
      temporalmente) → la reserva se sigue creando en la app (best-effort:
      un fallo de sync no debe bloquear la reserva).

---

## 10. Desplegar con negocio real (`CONFIG_PATH`)

Ver issue #73. Verifica que se puede servir un negocio distinto al de demo
(Masajes Serenidad) sin forkear el repo ni commitear datos reales encima del
`business.yaml` de ejemplo.

- [ ] Copiar `config/business.yaml` a una ruta fuera del repo y cambiar al
      menos `nombre`.
- [ ] `CONFIG_PATH=/ruta/al/yaml/alternativo` al arrancar `python main.py`
      → el chat responde con el nombre/tono/servicios de ese yaml
      alternativo, no los de Masajes Serenidad.
- [ ] Misma variable definida al correr
      `streamlit run panel_empleados/streamlit_app.py` → el panel muestra
      el negocio alternativo (servicios/profesionales derivados de ese
      yaml).
- [ ] Misma variable definida en el entorno al hacer `npm run dev` o
      `npm run build` en `frontend/` → el nombre/tono mostrado en la web
      pública es el del yaml alternativo.
- [ ] Sin `CONFIG_PATH` definida en ninguno de los tres — comportamiento
      idéntico al de siempre (demo Masajes Serenidad), confirmando que el
      override es puramente opt-in.

---

## 11. Multi-proveedor LLM

Repetir un subconjunto reducido de la sección 1 y 2 (al menos: una pregunta
de conocimiento, un flujo de reserva completo, y el caso de "señal de
abandono") con cada proveedor disponible, comparando calidad/tono de
respuesta:

- [ ] `PROVEEDOR_LLM=mock` — determinista, sirve de referencia rápida de
      que el *cableado* (tools, RAG, sesiones) funciona sin gastar tokens.
- [ ] `PROVEEDOR_LLM=anthropic` (si hay `ANTHROPIC_API_KEY` con crédito).
- [ ] `PROVEEDOR_LLM=cohere` (si hay `COHERE_API_KEY`) — cuidado con el
      límite de 1000 llamadas/mes de la clave de prueba.
- [ ] `PROVEEDOR_LLM=openai` (si hay `OPENAI_API_KEY`) — usado
      históricamente para descartar si un bug de calidad es específico de
      Cohere o sistémico; comparar la misma pregunta entre ambos si se
      sospecha de una regresión de proveedor.

---

## 12. Errores y bordes técnicos

- [ ] `POST /chat` con `usuario_id` o `mensaje` vacío/ausente → error 4xx
      claro (validación de Pydantic), no un 500.
- [ ] Provocar que una tool falle (p.ej. `crear_reserva` con
      `servicio_id` inexistente vía un mensaje que fuerce ese dato) → el
      chat no se rompe, el LLM recibe `{"error": ...}` y responde algo
      razonable al usuario en vez de colgarse.
- [ ] Mandar un mensaje que fuerce muchas iteraciones de tool-calling
      seguidas → tras `max_iteraciones_tool` (por defecto 4) el agente da
      un mensaje de fallback en vez de bucle infinito.
- [ ] `CORS_ORIGINS` sin definir → el frontend en `localhost:4321` puede
      llamar al backend sin error de CORS en la consola del navegador.

---

## 13. Smoke test rápido (5 minutos, antes de cualquier release)

Si no hay tiempo para el plan completo, como mínimo:

1. [ ] `GET /health` → 200.
2. [ ] Pregunta de precio por chat → dato correcto + cierre comercial.
3. [ ] Flujo completo de reserva (por Telegram, o con `WHATSAPP_*`/
       `TWILIO_*` configuradas para poder verificar el teléfono — ver 7.3) →
       cita visible en el panel (Agenda), con nombre de cliente correcto.
4. [ ] Un caso comercial "difícil" (sección 2) al azar → tono correcto.
5. [ ] Vistazo rápido a `http://localhost:4321`: Testimonios, CTA de
       cabecera y márgenes se ven correctos, sin nada pegado al borde.
6. [ ] `pytest` en verde (referencia automática, no sustituye lo anterior).
