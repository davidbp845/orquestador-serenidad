---
description: Resuelve todos los retoques pendientes del issue de ajustes finos del panel interno, uno a uno, con pausa antes de pasar al siguiente
---

Resuelve los retoques pendientes del issue paraguas de ajustes finos del panel interno (`panel_empleados/`):

1. Localiza el issue igual que `/crear-retoque-panel`: `gh issue list --search '"ajustes finos" in:title' --state open --json number,title`, quedándote con el del panel (título tipo "Panel interno: ajustes finos varios"). No asumas un número fijo. Si no hay ninguno claro, pregunta antes de seguir.
2. Lista sus comentarios (`gh repo view --json nameWithOwner -q .nameWithOwner` para el repo, luego `gh api repos/<owner>/<repo>/issues/<n>/comments`).
3. Identifica los retoques PENDIENTES: comentarios cuyo cuerpo empieza por `**Retoque:**` y que NO contienen `Commit:` en ningún punto del texto (los que sí la contienen ya están resueltos). Ordénalos cronológicamente, del más antiguo al más reciente.
4. Si no hay ninguno pendiente, dilo y termina — no hagas nada más.
5. Procesa la lista de pendientes en orden, uno por uno. Para cada retoque:
   a. Antes de tocar nada, muestra al usuario el texto exacto del retoque que vas a abordar (y cuántos quedan detrás, incluyendo este).
   b. Implementa el cambio mínimo necesario en `panel_empleados/` para resolverlo.
   c. Verifica el cambio de forma razonable (lint si aplica; recuerda que ejecutar el panel/Streamlit no prueba por sí solo que el código corrió — usa `runpy.run_path` si necesitas comprobarlo de verdad). No levantes servidores en background para comprobarlo salvo que el usuario lo pida explícitamente en este turno.
   d. Haz commit siguiendo la convención de este repo: asunto `tipo(panel): resumen breve`, cuerpo con el porqué/antes-después si no es obvio, pie `Issue: #<n>`.
   e. Comenta en el issue con el mismo formato usado en los retoques ya resueltos: `**Retoque implementado:** <qué se hizo y por qué>\n\nCommit: <hash corto>`.
   f. Encadena automáticamente sin pausa con el siguiente.
6. Si el usuario decide parar antes de agotar la lista, deja constancia de cuántos retoques quedan aún pendientes sin resolver.

Si algún retoque es ambiguo o implica una decisión de diseño no especificada en su texto, pregunta antes de implementarlo en vez de asumir, y no dejes que eso bloquee el resto de la lista.
