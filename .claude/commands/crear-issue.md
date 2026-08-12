---
description: Crea un issue de GitHub con el patrón de body/proyecto/campos usado en este proyecto
argument-hint: [título breve o descripción del problema]
---

Crea un issue de GitHub para "$1" siguiendo el patrón de este proyecto:

1. Redacta un cuerpo detallado: situación/diagnóstico (qué pasa o qué falta) + plan (qué se va a hacer). No menciones consideraciones de Fase II/SaaS/premium en el texto del issue — eso se evalúa aparte (ver el chequeo open-core/premium en `CLAUDE.md`), mantén el body centrado en qué hay que hacer.
2. Añádelo siempre al proyecto GitHub "Orquestador Serenidad" (owner `davidbp845`, project number `1`) — un issue sin añadir al proyecto no aparece en el tablero.
3. Pon los campos del proyecto:
   - Status = **Backlog** por defecto, salvo que el usuario pida otra cosa para este issue en concreto.
   - Priority (P0/P1/P2) — infiérelo del contexto (p.ej. bug que bloquea un flujo core → P0).
   - Semana (S1-S4) — infiérelo de en qué semana del plan original encaja.
4. Confirma con un resumen: número de issue, título, Status/Priority/Semana asignados, y el link.

Si falta información clave para el diagnóstico o el plan, pregunta antes de crear el issue en vez de rellenar con suposiciones.
