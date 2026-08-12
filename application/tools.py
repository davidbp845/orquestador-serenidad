"""
Aquí se define el "menú" de acciones que el agente puede ejecutar,
en formato de tool schema (compatible con la API de Anthropic).
Cada tool se resuelve contra un caso de uso del dominio: el LLM
nunca toca el dominio directamente, siempre a través de esta capa.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Solo para el type hint de sesion en EjecutorHerramientas.ejecutar
    # (#77) — un import real aquí crearía un ciclo, ya que
    # application/orchestrator.py importa TOOLS_SCHEMA/EjecutorHerramientas
    # de este mismo módulo.
    from .orchestrator import SesionConversacion

TOOLS_SCHEMA = [
    {
        "name": "comprobar_disponibilidad",
        "description": (
            "Consulta huecos libres para un servicio en una fecha dada, "
            "opcionalmente con un profesional concreto. Úsalo antes de "
            "ofrecer una hora al cliente."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "servicio_id": {"type": "string"},
                "fecha": {"type": "string", "description": "formato YYYY-MM-DD"},
                "profesional_id": {"type": "string"},
            },
            "required": ["servicio_id", "fecha"],
        },
    },
    {
        "name": "crear_reserva",
        "description": (
            "Crea una reserva/cita confirmada para un cliente. Necesita "
            "el nombre completo y el teléfono del cliente — pídeselos "
            "antes de llamar a esta herramienta si no los tienes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "servicio_id": {"type": "string"},
                "profesional_id": {"type": "string"},
                "nombre": {"type": "string", "description": "Nombre completo del cliente"},
                "telefono": {"type": "string", "description": "Teléfono del cliente"},
                "inicio": {"type": "string", "description": "ISO 8601"},
            },
            "required": ["servicio_id", "profesional_id", "nombre", "telefono", "inicio"],
        },
    },
    {
        "name": "registrar_pedido",
        "description": "Registra un pedido de productos o servicios adicionales.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cliente_id": {"type": "string"},
                "lineas": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "servicio_id": {"type": "string"},
                            "cantidad": {"type": "integer"},
                            "notas": {"type": "string"},
                        },
                        "required": ["servicio_id", "cantidad"],
                    },
                },
            },
            "required": ["cliente_id", "lineas"],
        },
    },
    {
        "name": "consultar_conocimiento_negocio",
        "description": (
            "Busca en la documentación del negocio (precios, políticas, "
            "horarios, servicios) para responder preguntas informativas."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"consulta": {"type": "string"}},
            "required": ["consulta"],
        },
    },
    {
        "name": "guardar_nota_cliente",
        "description": (
            "Guarda una anotación relevante sobre el cliente para futuras "
            "conversaciones (una alergia, una preferencia de profesional, "
            "una incidencia) — no para resumir cada mensaje. Si en esta "
            "conversación todavía no conoces el cliente_id del cliente "
            "(porque aún no se ha reservado con crear_reserva), llama a "
            "esta herramienta igualmente sin indicar cliente_id: la nota "
            "queda pendiente y se guarda automáticamente en cuanto "
            "crear_reserva resuelva quién es el cliente."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "texto": {"type": "string"},
                "cliente_id": {
                    "type": "string",
                    "description": "Omítelo si todavía no lo conoces en esta conversación.",
                },
            },
            "required": ["texto"],
        },
    },
]


class EjecutorHerramientas:
    """Traduce una llamada de tool del LLM en una invocación real
    al caso de uso correspondiente del dominio."""

    def __init__(self, casos_de_uso: dict):
        self._casos = casos_de_uso

    def ejecutar(
        self,
        nombre_tool: str,
        entrada: dict,
        canal: str | None = None,
        usuario_id: str | None = None,
        sesion: SesionConversacion | None = None,
    ) -> dict:
        try:
            if nombre_tool == "comprobar_disponibilidad":
                slots = self._casos["comprobar_disponibilidad"].ejecutar(
                    servicio_id=entrada["servicio_id"],
                    dia=date.fromisoformat(entrada["fecha"]),
                    profesional_id=entrada.get("profesional_id"),
                )
                return {
                    "slots": [
                        {
                            "profesional_id": s.profesional_id,
                            "inicio": s.inicio.isoformat(),
                            "fin": s.fin.isoformat(),
                        }
                        for s in slots
                    ]
                }

            if nombre_tool == "crear_reserva":
                kwargs = {
                    "servicio_id": entrada["servicio_id"],
                    "profesional_id": entrada["profesional_id"],
                    "nombre": entrada["nombre"],
                    "telefono": entrada["telefono"],
                    "inicio": datetime.fromisoformat(entrada["inicio"]),
                }
                # El chat_id de Telegram solo se conoce (y solo tiene
                # sentido persistirlo) cuando la reserva se hace por ese
                # canal — ver Cliente.telegram_chat_id y #38.
                if canal == "telegram" and usuario_id is not None:
                    kwargs["telegram_chat_id"] = usuario_id
                cita = self._casos["crear_reserva"].ejecutar(**kwargs)
                # cliente_id va en el resultado para que el LLM lo
                # reutilice tal cual si necesita registrar_pedido para
                # el mismo cliente en la misma conversación — ya no lo
                # decide el LLM libremente, lo resuelve CrearReserva
                # (por teléfono si existe, o lo genera el contador).
                # Vuelca cualquier nota de guardar_nota_cliente que se
                # hubiera quedado pendiente en la sesión por no conocer
                # todavía el cliente_id (#77) — ya se conoce.
                if sesion is not None and sesion.notas_pendientes:
                    for texto_pendiente in sesion.notas_pendientes:
                        self._casos["anadir_nota_cliente"].ejecutar(
                            cliente_id=cita.cliente_id, texto=texto_pendiente,
                        )
                    sesion.notas_pendientes.clear()
                return {
                    "cita_id": cita.id_visible,
                    "cliente_id": cita.cliente_id,
                    "estado": cita.estado.value,
                }

            if nombre_tool == "registrar_pedido":
                from domain.entities import LineaPedido
                lineas = [
                    LineaPedido(
                        servicio_id=linea["servicio_id"],
                        cantidad=linea["cantidad"],
                        notas=linea.get("notas", ""),
                    )
                    for linea in entrada["lineas"]
                ]
                pedido = self._casos["registrar_pedido"].ejecutar(
                    cliente_id=entrada["cliente_id"], lineas=lineas
                )
                return {"pedido_id": str(pedido.id), "estado": pedido.estado.value}

            if nombre_tool == "guardar_nota_cliente":
                texto = entrada["texto"]
                cliente_id = entrada.get("cliente_id")
                if cliente_id:
                    nota = self._casos["anadir_nota_cliente"].ejecutar(
                        cliente_id=cliente_id, texto=texto
                    )
                    return {"nota_id": nota.id, "cliente_id": nota.cliente_id}
                # Sin cliente_id todavía: se difiere en el buffer de la
                # sesión (ver el flush en crear_reserva más arriba). Sin
                # sesión (ej. llamada directa fuera del orquestador) no
                # hay dónde guardarla — se informa al LLM en vez de
                # perder el texto en silencio.
                if sesion is not None:
                    sesion.notas_pendientes.append(texto)
                    return {"guardada": "pendiente_de_cliente_id"}
                return {"error": "Falta cliente_id y no hay sesión donde diferir la nota."}

            if nombre_tool == "consultar_conocimiento_negocio":
                return self._casos["consultar_conocimiento"].ejecutar(
                    entrada["consulta"]
                )

            return {"error": f"Herramienta desconocida: {nombre_tool}"}

        except Exception as exc:  # noqa: BLE001 — se traduce a error legible para el LLM
            return {"error": str(exc)}
