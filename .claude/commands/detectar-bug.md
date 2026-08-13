---
description: Diagnostica un comportamiento observado y, si es un bug confirmado, crea el issue siguiendo el patrón de /crear-issue
argument-hint: [descripción del comportamiento observado]
---

Diagnostica el comportamiento observado: "$1"

1. Investiga en el código (domain/application/adapters/config/tests, según a qué capa apunte el síntoma) qué debería pasar frente a lo que se reporta. Cita fichero:línea de lo que sustenta el diagnóstico. Si ayuda a confirmarlo, ejecuta el test relacionado o reproduce el flujo (sin tocar `DATABASE_URL`/Telegram/Calendar reales — mismas restricciones que el resto de `CLAUDE.md`).
2. Decide:
   - **No es un bug**: si el comportamiento es el esperado por diseño, por configuración, por un límite conocido, o corresponde a funcionalidad premium no implementada en este skeleton (ver el chequeo open-core/premium de `CLAUDE.md`), explica claramente por qué no es un bug, qué está pasando en realidad, y qué haría falta cambiar (config, uso, o sería una petición de feature) si aplica. No crees ningún issue, salvo el caso del punto 3.
   - **Es un bug**: redacta el diagnóstico (causa raíz si la localizaste; si no, síntomas + hipótesis más probable) y antes de crear nada comprueba que no exista ya un issue abierto para lo mismo (`gh issue list --search '<términos clave>' --state open --json number,title`). Si ya existe, no dupliques — dilo y pregunta si prefiere que comentes ahí en vez de crear uno nuevo.
3. Si no es un bug pero el comportamiento se arregla con una mejora, comprueba primero que no exista ya un issue abierto para esa mejora (mismo criterio de búsqueda que en el punto 2), y si no lo hay invoca el skill `crear-issue` (Skill tool) pasándole como argumento un título breve y descriptivo, mencionando que se creó al reportar algo que parecía un bug pero no lo es.
4. Si es un bug nuevo, invoca el skill `crear-issue` (Skill tool) pasándole como argumento un título breve y descriptivo del bug. Deja que ese comando gestione el body, el alta en el proyecto GitHub y los campos Status/Priority/Semana — no repliques esa lógica aquí.
5. Si falta información para diagnosticar con confianza (no puedes localizar el flujo relevante, faltan pasos para reproducir, el síntoma es ambiguo), pregunta antes de asumir o de crear un issue especulativo.
