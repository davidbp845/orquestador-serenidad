"""
Puertos: contratos que el dominio necesita y que los adaptadores
implementan. El dominio depende de estas interfaces, nunca de una
implementación concreta (Postgres, Anthropic, Telegram...).

Esto es lo que te da la modularidad real: cambiar de LLM o de canal
de mensajería es escribir un adaptador nuevo que cumpla el puerto,
sin tocar una sola línea del dominio.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import date
from uuid import UUID

from .entities import (
    Cita,
    Cliente,
    Pedido,
    Profesional,
    Servicio,
)

# ---------- Puertos de salida: persistencia ----------

class RepositorioServicios(ABC):
    @abstractmethod
    def obtener(self, servicio_id: str) -> Servicio | None: ...

    @abstractmethod
    def listar(self) -> list[Servicio]: ...


class RepositorioProfesionales(ABC):
    @abstractmethod
    def obtener(self, profesional_id: str) -> Profesional | None: ...

    @abstractmethod
    def listar_por_servicio(self, servicio_id: str) -> list[Profesional]: ...


class RepositorioCitas(ABC):
    @abstractmethod
    def guardar(self, cita: Cita) -> None: ...

    @abstractmethod
    def obtener(self, cita_id: UUID) -> Cita | None: ...

    @abstractmethod
    def citas_de_profesional_en_fecha(
        self, profesional_id: str, dia: date
    ) -> list[Cita]: ...

    @abstractmethod
    def citas_en_rango(self, desde: date, hasta: date) -> list[Cita]:
        """Todas las citas entre 'desde' y 'hasta' (ambos incluidos),
        de cualquier profesional — la agenda agregada que necesita
        el panel interno (vista de día/semana/mes)."""
        ...

    def citas_en_fecha(self, dia: date) -> list[Cita]:
        """Atajo de citas_en_rango para un único día."""
        return self.citas_en_rango(dia, dia)

    @abstractmethod
    def cancelar(self, cita_id: UUID) -> None: ...


class RepositorioClientes(ABC):
    @abstractmethod
    def obtener(self, cliente_id: str) -> Cliente | None: ...

    @abstractmethod
    def guardar(self, cliente: Cliente) -> None: ...

    @abstractmethod
    def buscar_por_telefono(self, telefono: str) -> Cliente | None: ...

    @abstractmethod
    def listar(self) -> list[Cliente]: ...


class RepositorioPedidos(ABC):
    @abstractmethod
    def guardar(self, pedido: Pedido) -> None: ...

    @abstractmethod
    def obtener(self, pedido_id: UUID) -> Pedido | None: ...

    @abstractmethod
    def listar_pendientes(self) -> list[Pedido]:
        """Pedidos que aún no han llegado a un estado terminal
        (ni entregados ni cancelados) — lo que el panel interno
        necesita gestionar activamente."""
        ...


# ---------- Puertos de salida: conocimiento e IA ----------

class RepositorioConocimiento(ABC):
    """RAG: recupera fragmentos relevantes del vault de Obsidian
    (ya trocidos e indexados) para una consulta dada."""

    @abstractmethod
    def buscar(self, consulta: str, top_k: int = 5) -> list[str]: ...

    @abstractmethod
    def buscar_con_fuentes(self, consulta: str, top_k: int = 5) -> list[dict]:
        """Como buscar(), pero conserva la metadata de cada fragmento
        (al menos 'fuente': el fichero de origen relativo al vault, y
        el resto del frontmatter, ej. 'categoria', 'publicar_web')."""
        ...


class ProveedorLLM(ABC):
    """Adaptador hacia el proveedor de modelo (Anthropic, u otro)."""

    @abstractmethod
    def generar_respuesta(
        self,
        mensajes: list[dict],
        herramientas: list[dict] | None = None,
        system: str | None = None,
    ) -> dict:
        """Devuelve la respuesta cruda del modelo (texto y/o tool_use)."""
        ...

    @abstractmethod
    def generar_respuesta_stream(
        self,
        mensajes: list[dict],
        herramientas: list[dict] | None = None,
        system: str | None = None,
    ) -> Iterator[dict]:
        """Genera eventos incrementales de la respuesta del modelo:
        {"tipo": "delta_texto", "texto": str} — cero o más, en orden.
        {"tipo": "final", "content": [...]} — exactamente uno al final,
        con el mismo shape que generar_respuesta()["content"]."""
        ...


# ---------- Puertos de salida: notificaciones ----------

class NotificadorMensajes(ABC):
    """Envía mensajes salientes a un canal (Telegram, WhatsApp, email...)."""

    @abstractmethod
    def enviar(self, destinatario_id: str, texto: str) -> None: ...


# ---------- Puertos de salida: calendario ----------

class SincronizadorCalendario(ABC):
    """Refleja las citas del sistema en un calendario externo (Google
    Calendar u otro). Los casos de uso lo tratan como best-effort: un
    fallo aquí no debe impedir crear/cancelar una cita en el dominio."""

    @abstractmethod
    def crear_evento(
        self, cita: Cita, servicio: Servicio, profesional: Profesional
    ) -> str:
        """Crea el evento en el calendario externo y devuelve su id,
        para poder cancelarlo más tarde."""
        ...

    @abstractmethod
    def cancelar_evento(self, evento_id: str) -> None: ...
