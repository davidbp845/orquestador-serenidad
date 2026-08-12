---
description: Da de alta un nuevo negocio/vertical reutilizando el esqueleto (business.yaml + vault Obsidian + casos de uso si hacen falta)
argument-hint: [nombre del negocio]
---

Da de alta un nuevo negocio ("$1" si se indica) reutilizando el esqueleto hexagonal existente:

1. Duplica `config/business.yaml` para el nuevo negocio y ajusta servicios, profesionales y tono. Si no está claro dónde debe vivir el nuevo archivo (¿sustituye al actual, o convive como config alternativa vía `CONFIG_PATH`?), pregunta antes de decidir.
2. Crea un vault de Obsidian nuevo con el conocimiento de ese negocio, apunta `vault_obsidian` al nuevo vault en su `business.yaml`, y reindexa con `python -m adapters.out.obsidian_ingest --vault <ruta-del-vault>`.
3. Solo si el negocio necesita un caso de uso genuinamente distinto (p.ej. "reservar mesa" en vez de "reservar cita"): añádelo en `domain/use_cases.py` y expón la herramienta correspondiente en `application/tools.py` (entrada en `TOOLS_SCHEMA` + rama de dispatch en `EjecutorHerramientas.ejecutar`). Si el negocio encaja en los casos de uso ya existentes, no toques `domain/` ni `application/` — la gracia del esqueleto es que solo cambien `config/business.yaml` y el vault.
4. No implementes nada de la lista de funcionalidad premium (ver el chequeo open-core/premium en `CLAUDE.md`) aunque el nuevo negocio "lo necesite" — sigue el mismo procedimiento de aviso/pregunta que para cualquier otro negocio.

Al terminar, resume qué cambió: archivo de config nuevo, ruta del vault, y si se tocó `domain/`/`application/` o no (y por qué).
