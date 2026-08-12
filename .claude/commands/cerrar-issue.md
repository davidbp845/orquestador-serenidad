---
description: Cierra un issue de GitHub siguiendo el patrón de comentario y transición de Status usado en este proyecto
argument-hint: [número de issue]
---

Cierra el issue de GitHub `$1` del proyecto "Orquestador Serenidad" (owner `davidbp845`, project number `1`) siguiendo el ciclo estándar de este proyecto:

1. Comenta en el issue qué se implementó y cómo se verificó (tests, `ruff check`, comprobaciones manuales si aplica) — si ya se comentó el plan al empezar, este es el comentario de cierre con los resultados.
2. Cierra el issue (`gh issue close`).
3. Mueve el campo Status del proyecto a **In review** — nunca a Done, salvo que el usuario lo haya pedido explícitamente para este issue.
4. Confirma con un resumen breve: issue cerrado, Status final, y el link.

Si el issue `$1` no está terminado/verificado todavía, dilo en vez de cerrarlo igualmente — no fuerces el cierre solo porque se ha invocado el comando.
