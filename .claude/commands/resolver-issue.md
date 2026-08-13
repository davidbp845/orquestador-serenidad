---
description: Implementa de punta a punta un issue de GitHub concreto (código, tests, commit) y lo cierra siguiendo el patrón de /cerrar-issue
argument-hint: [número de issue]
---

Resuelve el issue de GitHub `$1` del proyecto "Orquestador Serenidad" (owner `davidbp845`, project number `1`) siguiendo el mismo ciclo que usa `/sprint` por cada issue, pero para este uno solo:

1. Lee el issue (`gh issue view $1 --json title,body,state,url,comments`) y confirma que está abierto. Si su alcance queda ambiguo o depende de una decisión no tomada en el propio issue, pregunta antes de implementar en vez de asumir.
2. Pon su Status en el proyecto GitHub a **In progress** (`gh project item-list 1 --owner davidbp845 --format json` para localizar el item, `gh project item-edit` para el campo).
3. Comenta en el issue el plan antes de empezar (situación/diagnóstico + qué vas a hacer) — salvo que ya haya un comentario tuyo reciente cubriendo exactamente lo mismo.
4. Implementa el issue de punta a punta: código y tests, y pasa `ruff check .`.
5. Haz commit local siguiendo la convención de este repo (asunto `tipo(ámbito): resumen breve`, pie `Issue: #$1`) — nunca push.
6. Cierra el issue invocando el skill `cerrar-issue` (Skill tool) pasándole `$1` como argumento. Deja que gestione el comentario de cierre, el `gh issue close` y el cambio de Status a **In review** — no repliques esa lógica aquí.

Para en seco y pide confirmación si te topas con algo de "Blocked entirely" o "Still requires explicit confirmation" en `CLAUDE.md` (`git push`, merge de PR, downgrade de DB, etc.) — reporta lo que llevas hecho hasta ese punto.

Si el issue `$1` no existe, ya está cerrado, o hay algo en su alcance que no permite implementarlo con confianza, dilo y pregunta en vez de forzarlo.
