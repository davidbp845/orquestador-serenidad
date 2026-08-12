---
description: Ejecuta un sprint completo sobre los issues en Status=Ready del proyecto GitHub, encadenados sin pausar
---

Ejecuta un sprint completo siguiendo el ciclo autónomo ya autorizado en `CLAUDE.md` (Autonomous Operation Policy → "Safe to do without asking").

1. Lista los issues del proyecto GitHub "Orquestador Serenidad" (owner `davidbp845`, project number `1`) que estén en Status = **Ready**.
2. Si no hay ninguno, dilo y termina — no hace falta seguir.
3. Para cada issue, en orden, sin pausar entre ellos ni pedir confirmación:
   a. Pon Status = **In progress**.
   b. Comenta en el issue el plan antes de empezar (situación/diagnóstico + qué vas a hacer).
   c. Implementa el issue de punta a punta: código y tests, y pasa `ruff check .`.
   d. Haz commit local (nunca push).
   e. Comenta en el issue qué se implementó y cómo se verificó (tests, ruff, comprobaciones manuales si aplica).
   f. Cierra el issue y pon Status = **In review** — nunca Done, salvo que el usuario lo haya pedido explícitamente para ese issue en concreto.
   g. Pasa al siguiente issue Ready.
4. Para en seco y pide confirmación si te topas con algo de "Blocked entirely" o "Still requires explicit confirmation" en `CLAUDE.md` (`git push`, merge de PR, downgrade de DB, etc.) — reporta lo que llevas hecho hasta ese punto.
5. Al terminar el lote (o al pararte por lo anterior), da un resumen: issues cerrados, qué se implementó en cada uno, y cualquier issue que se quedó a medias y por qué.

Campos del proyecto en uso: Status (Backlog/Ready/In progress/In review/Done), Priority (P0/P1/P2), Semana (S1-S4).
