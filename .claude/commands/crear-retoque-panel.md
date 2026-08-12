---
description: Registra un retoque de UI/UX del panel interno como comentario en su issue paraguas de ajustes finos (sin implementarlo)
argument-hint: [descripción breve del retoque]
---

Registra el retoque "$1" en el issue paraguas de ajustes finos del panel interno (`panel_empleados/`):

1. Busca el issue con `gh issue list --search '"ajustes finos" in:title' --state open --json number,title` y quédate con el que corresponda al panel interno (título tipo "Panel interno: ajustes finos varios"). No asumas un número fijo — el issue paraguas actual puede no ser el mismo que en conversaciones anteriores. Si no hay ninguno claro para el panel, o hay más de uno, pregunta antes de seguir.
2. Comprueba que su Status en el proyecto GitHub "Orquestador Serenidad" (owner `davidbp845`, project number `1`) es **In progress** (`gh project item-list 1 --owner davidbp845 --format json`, filtrando por ese número de issue). Si no está en In progress, avísalo y pregunta si continuar igualmente.
3. Añade un comentario al issue con el formato usado en este proyecto: `**Retoque:** <descripción del retoque>` — sin mencionar commit, porque no se implementa nada.
4. Analiza lo que hay que hacer para resolverlo y déjalo documentado en el mismo comentatio.
5. No toques código ni implementes el cambio. El objetivo es solo dejarlo anotado para ir agrupando retoques, hasta que el usuario pida explícitamente empezar a resolverlos.
6. Confirma con un resumen breve: en qué issue quedó registrado y el link al comentario.
