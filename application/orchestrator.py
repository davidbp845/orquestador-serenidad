"""
Orquestador de agentes: puerto de entrada conversacional. Recibe un
mensaje de cualquier canal (web, Telegram...) junto con el historial,
decide qué herramientas invocar mediante el LLM, ejecuta esas
herramientas contra el dominio, y devuelve una respuesta en lenguaje
natural. Es agnóstico del canal: no sabe si viene de Telegram o web.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date

from domain.ports import ProveedorLLM

from .prompts import formatear_fecha_es
from .tools import TOOLS_SCHEMA, EjecutorHerramientas

_MENSAJE_FALLBACK = (
    "Lo siento, no he podido completar la solicitud. "
    "¿Puedes reformularla o contactar directamente con el negocio?"
)


@dataclass
class SesionConversacion:
    """Estado conversacional de un usuario concreto (por canal + id)."""
    canal: str
    usuario_id: str
    historial: list[dict] = field(default_factory=list)
    # Buffer de textos de guardar_nota_cliente (#77) para cuando el LLM
    # todavía no conoce el cliente_id en esta conversación — se vuelca a
    # NotaCliente en cuanto crear_reserva lo resuelve en la misma sesión
    # (ver EjecutorHerramientas.ejecutar). Si la sesión termina sin
    # reservar, se pierde junto con el resto del historial — sin
    # infraestructura nueva, mismo criterio que ya aplica hoy a las
    # sesiones sin Redis.
    notas_pendientes: list[str] = field(default_factory=list)


class OrquestadorAgente:
    def __init__(
        self,
        llm: ProveedorLLM,
        ejecutor_herramientas: EjecutorHerramientas,
        system_prompt: str,
        max_iteraciones_tool: int = 4,
    ):
        self._llm = llm
        self._ejecutor = ejecutor_herramientas
        self._system_prompt = system_prompt
        self._max_iteraciones = max_iteraciones_tool

    def _system_prompt_con_fecha(self) -> str:
        # Calculado en cada turno (no una vez al construir el orquestador):
        # el proceso puede llevar días corriendo. Sin esto, el LLM no
        # tiene ninguna forma fiable de saber qué día es "hoy" y adivina
        # fechas relativas ("mañana", "el lunes") con años/días
        # incorrectos — ver issue #32.
        return f"{self._system_prompt}\n\nHoy es {formatear_fecha_es(date.today())}."

    def responder(self, sesion: SesionConversacion, mensaje_usuario: str) -> str:
        sesion.historial.append({"role": "user", "content": mensaje_usuario})
        system = self._system_prompt_con_fecha()

        for _ in range(self._max_iteraciones):
            respuesta = self._llm.generar_respuesta(
                mensajes=sesion.historial,
                herramientas=TOOLS_SCHEMA,
                system=system,
            )

            bloques_tool = [b for b in respuesta["content"] if b["type"] == "tool_use"]
            bloques_texto = [b for b in respuesta["content"] if b["type"] == "text"]

            sesion.historial.append({"role": "assistant", "content": respuesta["content"]})

            if not bloques_tool:
                return "\n".join(b["text"] for b in bloques_texto)

            resultados_tool = []
            for bloque in bloques_tool:
                resultado = self._ejecutor.ejecutar(
                    bloque["name"], bloque["input"],
                    canal=sesion.canal, usuario_id=sesion.usuario_id, sesion=sesion,
                )
                resultados_tool.append({
                    "type": "tool_result",
                    "tool_use_id": bloque["id"],
                    "content": str(resultado),
                })

            sesion.historial.append({"role": "user", "content": resultados_tool})

        return _MENSAJE_FALLBACK

    def responder_stream(
        self, sesion: SesionConversacion, mensaje_usuario: str
    ) -> Iterator[dict]:
        """Como responder(), pero emitiendo eventos incrementales:
        {"tipo": "delta", "texto": str} — texto según va llegando del LLM.
        {"tipo": "done", "respuesta": str, "fuentes": [...]} — al cerrar
        el turno, con las fuentes RAG usadas (deduplicadas) en todas las
        iteraciones del bucle de herramientas."""
        sesion.historial.append({"role": "user", "content": mensaje_usuario})
        system = self._system_prompt_con_fecha()
        fuentes_turno: dict[str, dict] = {}

        for _ in range(self._max_iteraciones):
            bloques_finales: list[dict] = []
            for evento in self._llm.generar_respuesta_stream(
                mensajes=sesion.historial,
                herramientas=TOOLS_SCHEMA,
                system=system,
            ):
                if evento["tipo"] == "delta_texto":
                    yield {"tipo": "delta", "texto": evento["texto"]}
                elif evento["tipo"] == "final":
                    bloques_finales = evento["content"]

            bloques_tool = [b for b in bloques_finales if b["type"] == "tool_use"]
            bloques_texto = [b for b in bloques_finales if b["type"] == "text"]

            sesion.historial.append({"role": "assistant", "content": bloques_finales})

            if not bloques_tool:
                yield {
                    "tipo": "done",
                    "respuesta": "\n".join(b["text"] for b in bloques_texto),
                    "fuentes": list(fuentes_turno.values()),
                }
                return

            resultados_tool = []
            for bloque in bloques_tool:
                resultado = self._ejecutor.ejecutar(
                    bloque["name"], bloque["input"],
                    canal=sesion.canal, usuario_id=sesion.usuario_id, sesion=sesion,
                )
                if isinstance(resultado, dict):
                    for f in resultado.get("fuentes", []):
                        fuentes_turno.setdefault(f["fuente"], f)
                resultados_tool.append({
                    "type": "tool_result",
                    "tool_use_id": bloque["id"],
                    "content": str(resultado),
                })

            sesion.historial.append({"role": "user", "content": resultados_tool})

        yield {
            "tipo": "done",
            "respuesta": _MENSAJE_FALLBACK,
            "fuentes": list(fuentes_turno.values()),
        }
