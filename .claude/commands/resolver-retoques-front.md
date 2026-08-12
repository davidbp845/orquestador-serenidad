---
description: Resuelve todos los retoques pendientes del issue de ajustes finos del frontend cliente, uno a uno, con pausa antes de pasar al siguiente
---

Resuelve los retoques pendientes del issue paraguas de ajustes finos del frontend cliente (`frontend/`):

1. Localiza el issue igual que `/crear-retoque-front`: `gh issue list --search '"ajustes finos" in:title' --state open --json number,title`, quedándote con el de frontend (título tipo "Frontend: ajustes finos varios"). No asumas un número fijo. Si no hay ninguno claro, pregunta antes de seguir.
2. Lista sus comentarios (`gh repo view --json nameWithOwner -q .nameWithOwner` para el repo, luego `gh api repos/<owner>/<repo>/issues/<n>/comments`).
3. Identifica los retoques PENDIENTES: comentarios cuyo cuerpo empieza por `**Retoque:**` y que NO contienen `Commit:` en ningún punto del texto (los que sí la contienen ya están resueltos). Ordénalos cronológicamente, del más antiguo al más reciente.
4. Si no hay ninguno pendiente, dilo y termina — no hagas nada más.
5. Procesa la lista de pendientes en orden, uno por uno. Para cada retoque:
   a. Antes de tocar nada, muestra al usuario el texto exacto del retoque que vas a abordar (y cuántos quedan detrás, incluyendo este).
   b. Implementa el cambio mínimo necesario en `frontend/` para resolverlo.
   c. Verifica el cambio de forma razonable (build/lint si aplica). No levantes servidores en background para comprobarlo salvo que el usuario lo pida explícitamente en este turno.
   d. Haz commit siguiendo la convención de este repo: asunto `tipo(frontend): resumen breve`, cuerpo con el porqué/antes-después si no es obvio, pie `Issue: #<n>`.
   e. Comenta en el issue con el mismo formato usado en los retoques ya resueltos: `**Retoque implementado:** <qué se hizo y por qué>\n\nCommit: <hash corto>`.
   f. Para aquí y espera confirmación explícita del usuario antes de pasar al siguiente retoque de la lista — no encadenes automáticamente varios retoques sin pausa (a diferencia de `/sprint`, que si encadena issues sin parar). Si el usuario confirma, continúa con el siguiente pendiente de la misma lista sin tener que volver a invocar el comando.
6. Si el usuario decide parar antes de agotar la lista, deja constancia de cuántos retoques quedan aún pendientes sin resolver.

Si algún retoque es ambiguo o implica una decisión de diseño no especificada en su texto, pregunta antes de implementarlo en vez de asumir, y no dejes que eso bloquee el resto de la lista.
