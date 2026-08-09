# Extender a otro negocio: un restaurante paso a paso

## La genericidad no es una promesa abstracta

`domain/entities.py` ya deja pistas explícitas de que el modelo no está
pensado solo para un centro de masajes: el comentario de `Servicio` dice
literalmente *"Ej: 'Masaje relajante 60 min'. Genérico: podría ser 'Mesa 4
personas'"*, y el de `Profesional`, *"Ej: terapeuta. Genérico: camarero,
estilista, técnico..."*. Este documento pone esa afirmación a prueba con un
ejemplo concreto: adaptar el sistema a un restaurante, "La Tasca del Puerto",
donde el chat debe poder reservar mesa, informar del menú y tomar un pedido.

## Paso 1 — Duplicar y adaptar `config/business.yaml`

Los cuatro conceptos del dominio (`Servicio`, `Profesional`, `Cliente`,
`Cita`) se reasignan sin tocar ni una línea de `domain/`:

- **`Servicio`** deja de ser un tipo de masaje y pasa a ser un tipo de mesa:
  `duracion_minutos` se convierte en el turno de comida habitual (p. ej. 90
  minutos), y `precio` puede ser 0 si el negocio no cobra por reservar.
- **`Profesional`** deja de ser una terapeuta y pasa a ser la mesa física en
  sí (o el camarero responsable, si el negocio prefiere asignar por persona
  en vez de por mesa) — lo único que exige el dominio es un `id`, un
  `nombre`, y un `horario_semanal`.

```yaml
nombre: "La Tasca del Puerto"
tono: "cercano, informal, con acento andaluz"
vault_obsidian: "./vault_tasca_puerto"

servicios:
  - id: "mesa_2"
    nombre: "Mesa para 2"
    duracion_minutos: 90
    precio: 0
  - id: "mesa_4"
    nombre: "Mesa para 4"
    duracion_minutos: 90
    precio: 0
  - id: "mesa_6"
    nombre: "Mesa para 6"
    duracion_minutos: 120
    precio: 0

profesionales:
  - id: "mesa_1"
    nombre: "Mesa 1 (terraza)"
    servicios_ids: ["mesa_2"]
    horario_semanal:
      martes: ["13:00", "16:00"]
      # ... resto de días de servicio
  - id: "mesa_5"
    nombre: "Mesa 5 (salón, junto a ventana)"
    servicios_ids: ["mesa_4", "mesa_6"]
    horario_semanal:
      martes: ["13:00", "16:00"]
```

Con solo este YAML, `ComprobarDisponibilidad` y `CrearReserva` ya funcionan
tal cual para reservar mesa: comprueban huecos libres de una "mesa para 4" en
una fecha dada exactamente igual que comprobaban huecos de un masaje de 60
minutos — el dominio nunca supo que la palabra era "masaje", solo vio
`servicio_id`, `duracion_minutos` y un `horario_semanal`.

## Paso 2 — Un vault de Obsidian nuevo, con el conocimiento de este negocio

`vault_tasca_puerto/` con notas equivalentes a las del centro de masajes pero
con contenido de restaurante: `menu.md` (entrantes, platos principales,
alérgenos), `horarios.md`, `ubicacion-contacto.md`,
`politicas-reserva.md` ("no-shows", tiempo de cortesía), `promociones.md`
(menú del día, ofertas de temporada). Mismo formato de frontmatter que ya
usa el vault de ejemplo:

```markdown
---
categoria: menu
tags: [menu, platos, alergenos]
publicar_web: true
orden: 1
resumen: "Entrantes, platos principales y postres, con alérgenos marcados."
---

# Menú

## Entrantes
...
```

## Paso 3 — Reindexar

```bash
python -m adapters.out.obsidian_ingest --vault ./vault_tasca_puerto
```

A partir de aquí, un cliente ya puede preguntar "¿tenéis gluten en la
lasaña?" y el RAG responde desde `menu.md`, exactamente con el mismo
mecanismo descrito en `doc/005-conocimiento-del-negocio.md`.

## Paso 4 — El pedido de comida ya existe: `Pedido`/`LineaPedido`

Tomar nota de lo que un cliente quiere comer no necesita ningún caso de uso
nuevo — es literalmente para lo que sirve `RegistrarPedido`
(`domain/use_cases.py`), ya genérico por diseño: el comentario de `Pedido`
en `domain/entities.py` dice explícitamente *"pedido de productos/servicios
adicionales (ej. venta de productos de cosmética en el centro de masajes, o
comida en un restaurante)"*. La tool `registrar_pedido`
(`application/tools.py`) ya acepta una lista de líneas con `servicio_id`,
`cantidad` y `notas` — basta con que los platos del menú también existan
como entradas en `servicios:` (con su propio `id`, aunque no se reserven
como una mesa) para que el LLM pueda registrar "2 raciones de pulpo a la
brasa, una sin sal" sin ningún cambio de código.

Con los pasos 1 a 4, **el restaurante entero funciona sin tocar `domain/` ni
`application/`** — la frontera de la que habla `doc/001-intro.md` se
sostiene en este ejemplo con cambios puramente de configuración y contenido.

## Cuándo sí hace falta código nuevo

No todo negocio encaja en "reservar un recurso en un hueco de tiempo +
registrar un pedido". Un caso real donde La Tasca del Puerto necesitaría
extender el dominio: una **lista de espera de walk-ins** (clientes que
llegan sin reserva y esperan a que se libere una mesa) — un concepto distinto
a una cita con hora fija, porque no tiene un `inicio`/`fin` conocido de
antemano, solo una posición en una cola.

Eso sí encajaría en el patrón que describe `CLAUDE.md` ("si el negocio
necesita un caso de uso genuinamente distinto"):

1. Una entidad nueva en `domain/entities.py`, p. ej. `EntradaListaEspera`
   (`cliente_id`, `tamano_grupo`, `hora_llegada`).
2. Un puerto nuevo en `domain/ports.py`, `RepositorioListaEspera`, con los
   métodos que ese flujo necesita (`añadir`, `siguiente`, `quitar`).
3. Un caso de uso nuevo, `UnirseAListaEspera` (o similar), en
   `domain/use_cases.py`.
4. Una tool nueva en `application/tools.py` (entrada en `TOOLS_SCHEMA` +
   rama en `EjecutorHerramientas.ejecutar`) para que el LLM pueda invocarla.
5. Al menos una implementación del puerto en `adapters/out/` (en memoria
   para empezar, Postgres si necesita sobrevivir a un reinicio) y su cableado
   en `main.py::construir_sistema()`.

Nada de esto está implementado aquí — es una ilustración de *dónde* iría el
código, no una funcionalidad añadida al esqueleto. El punto del ejemplo es
justo ese: la mayoría de negocios (incluido un restaurante, que a primera
vista parece bastante distinto a un centro de masajes) caben en el modelo
existente solo con configuración; hace falta código nuevo solo cuando el
negocio tiene un concepto de dominio genuinamente distinto a "reservar un
recurso" o "pedir productos", no antes.
