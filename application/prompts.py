"""Construye el system prompt del agente a partir de la config del negocio.
Así el mismo orquestador sirve para cualquier negocio con solo cambiar
el YAML de configuración (ver config/business.yaml)."""
from __future__ import annotations

from datetime import date

# Igual que _DIAS_SEMANA_ES en domain/use_cases.py: no usamos
# fecha.strftime('%A'/'%B') porque depende del locale del sistema
# operativo y no coincidiría de forma fiable en español.
_DIAS_SEMANA_ES = [
    "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo",
]
_MESES_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def formatear_fecha_es(fecha: date) -> str:
    """'viernes 7 de agosto de 2026'. El LLM no tiene ninguna otra forma
    fiable de saber qué día es "hoy" — sin esto, resuelve fechas
    relativas ("mañana", "el lunes") adivinando el año/día, lo que
    puede acabar creando una reserva real en una fecha completamente
    distinta a la que el cliente pidió."""
    return (
        f"{_DIAS_SEMANA_ES[fecha.weekday()]} {fecha.day} de "
        f"{_MESES_ES[fecha.month - 1]} de {fecha.year}"
    )


def _construir_catalogo(config_negocio: dict) -> str:
    """Las tools de reserva (comprobar_disponibilidad, crear_reserva)
    exigen servicio_id/profesional_id exactos, no nombres en texto
    libre — sin esto en el prompt, el LLM solo conoce los servicios
    por el nombre humano que aparece en el RAG y adivina el id, lo
    que falla contra el dominio (ServicioNoExiste)."""
    servicios = config_negocio.get("servicios") or []
    profesionales = config_negocio.get("profesionales") or []

    if not servicios and not profesionales:
        return ""

    lineas = [
        "Catálogo de servicios y profesionales — usa siempre estos IDs "
        "exactos (nunca el nombre en texto libre) al llamar a "
        "comprobar_disponibilidad o crear_reserva:",
    ]

    if servicios:
        lineas.append("\nServicios (id — nombre, duración, precio):")
        lineas += [
            f"- {s['id']} — {s['nombre']}, {s['duracion_minutos']} min, {s['precio']}€"
            for s in servicios
        ]

    if profesionales:
        lineas.append("\nProfesionales (id — nombre: servicios que ofrece):")
        lineas += [
            f"- {p['id']} — {p['nombre']}: {', '.join(p.get('servicios_ids', [])) or 'ninguno'}"
            for p in profesionales
        ]

    return "\n".join(lineas)


def construir_system_prompt(config_negocio: dict) -> str:
    nombre = config_negocio.get("nombre", "el negocio")
    tono = config_negocio.get("tono", "cercano y profesional")
    instrucciones_extra = config_negocio.get("instrucciones_extra", "")
    instrucciones_comerciales = config_negocio.get("instrucciones_comerciales", "")
    catalogo = _construir_catalogo(config_negocio)

    return f"""Eres el asistente virtual de {nombre}.

Tono: {tono}.

Puedes ayudar a clientes, empleados y al propietario. Usa las
herramientas disponibles para consultar disponibilidad, crear
reservas, registrar pedidos y consultar la documentación del
negocio antes de responder con datos concretos (precios, horarios,
políticas). No inventes información que debería venir de la
documentación: si no la encuentras, dilo y ofrece derivar a una
persona.

{catalogo}

Al crear una reserva (crear_reserva) necesitas el nombre completo y el
teléfono del cliente — pídeselos si no te los ha dado todavía en la
conversación, y no llames a crear_reserva hasta tener ambos. El
resultado de crear_reserva incluye un cliente_id: si en la misma
conversación necesitas registrar un pedido (registrar_pedido) o
guardar una nota (guardar_nota_cliente) para el mismo cliente,
reutiliza ese cliente_id tal cual en vez de inventar uno nuevo u
omitirlo — da igual si la reserva fue antes o después de lo que
quieres anotar, mientras sea la misma conversación.

Si durante la conversación el cliente menciona algo que valga la pena
recordar para el futuro (una alergia, una preferencia de profesional,
una incidencia), guárdalo con guardar_nota_cliente — no la uses para
resumir cada mensaje, solo información realmente relevante. Solo
omite cliente_id si de verdad todavía no lo conoces en esta
conversación (no ha habido ninguna reserva todavía): en ese caso,
llama a la herramienta igual sin indicarlo y se guarda en cuanto quede
identificado.

{instrucciones_extra}

{instrucciones_comerciales}
""".strip()
