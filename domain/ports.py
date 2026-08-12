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
    PromoBar,
    Servicio,
    Testimonio,
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
    def obtener(self, cita_id: int) -> Cita | None: ...

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
    def cancelar(self, cita_id: int) -> None: ...

    @abstractmethod
    def reasignar_cliente(self, id_antiguo: str, id_nuevo: str) -> int:
        """Reasigna todas las citas de id_antiguo a id_nuevo (ej. al
        fusionar dos Cliente duplicados, ver FusionarClientes en
        domain/use_cases.py) — UPDATE a nivel de repositorio, no
        enumerando citas una a una desde el dominio. Devuelve cuántas
        citas se reasignaron."""
        ...

    @abstractmethod
    def borrar_todo(self) -> int:
        """Vacía el repositorio entero. Solo lo usa la herramienta de
        borrado de datos del panel interno (entorno local/desarrollo,
        ver panel_empleados/streamlit_app.py) — ningún caso de uso del
        dominio la llama. Devuelve cuántas filas se borraron."""
        ...


class RepositorioClientes(ABC):
    @abstractmethod
    def obtener(self, cliente_id: str) -> Cliente | None: ...

    @abstractmethod
    def guardar(self, cliente: Cliente) -> None: ...

    @abstractmethod
    def buscar_por_telefono(self, telefono: str) -> Cliente | None: ...

    @abstractmethod
    def listar(self) -> list[Cliente]:
        """No incluye los clientes marcados borrado=True (ver
        marcar_borrado) — un cliente fusionado en otro no debe volver
        a aparecer en listados/búsquedas normales."""
        ...

    @abstractmethod
    def eliminar(self, cliente_id: str) -> None:
        """Borrado unitario **físico**, a diferencia de borrar_todo()
        (vaciado masivo, solo entorno local) — mismo patrón introducido
        por RepositorioTestimonios. Distinto de marcar_borrado() (borrado
        lógico, usado por la fusión de duplicados)."""
        ...

    @abstractmethod
    def marcar_borrado(self, cliente_id: str) -> None:
        """Borrado lógico: pone borrado=True sin eliminar la fila. Lo
        usa FusionarClientes sobre los clientes absorbidos — nunca
        eliminar(), para no perder el id como referencia histórica."""
        ...

    @abstractmethod
    def borrar_todo(self) -> int:
        """Ver RepositorioCitas.borrar_todo — misma herramienta de
        panel, mismo alcance de "solo entorno local"."""
        ...


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

    @abstractmethod
    def reasignar_cliente(self, id_antiguo: str, id_nuevo: str) -> int:
        """Ver RepositorioCitas.reasignar_cliente — mismo propósito,
        para pedidos."""
        ...

    @abstractmethod
    def borrar_todo(self) -> int:
        """Ver RepositorioCitas.borrar_todo. Incluye también las líneas
        de pedido (pedido_lineas), que este repositorio gestiona de
        forma interna."""
        ...


class RepositorioTestimonios(ABC):
    @abstractmethod
    def obtener(self, testimonio_id: int) -> Testimonio | None: ...

    @abstractmethod
    def guardar(self, testimonio: Testimonio) -> None: ...

    @abstractmethod
    def listar(self) -> list[Testimonio]: ...

    @abstractmethod
    def eliminar(self, testimonio_id: int) -> None:
        """Borrado unitario, a diferencia de borrar_todo() (vaciado
        masivo, solo entorno local) — el panel permite eliminar un
        testimonio suelto."""
        ...

    @abstractmethod
    def borrar_todo(self) -> int:
        """Ver RepositorioCitas.borrar_todo — misma herramienta de
        panel, mismo alcance de "solo entorno local"."""
        ...


class RepositorioPromoBar(ABC):
    @abstractmethod
    def obtener(self, promo_bar_id: int) -> PromoBar | None: ...

    @abstractmethod
    def guardar(self, promo_bar: PromoBar) -> None: ...

    @abstractmethod
    def listar(self) -> list[PromoBar]: ...

    @abstractmethod
    def eliminar(self, promo_bar_id: int) -> None: ...

    @abstractmethod
    def obtener_activo(self) -> PromoBar | None:
        """El que tenga activo=True, o None si ninguno lo está —
        nunca puede haber más de uno (ver activar())."""
        ...

    @abstractmethod
    def activar(self, promo_bar_id: int) -> None:
        """Pone este PromoBar en activo=True y cualquier otro en
        activo=False, en una sola operación atómica (importante en
        Postgres: evita una ventana de carrera donde dos promobars
        pudieran quedar activos, o ninguno)."""
        ...


class RepositorioContadores(ABC):
    """Contador atómico por tipo de entidad (ej. 'testimonio', 'cliente'):
    garantiza que dos llamadas a siguiente_valor() con el mismo
    tipo_entidad nunca devuelvan el mismo número, ni siquiera entre
    procesos distintos escribiendo contra el mismo Postgres a la vez
    (ver RepositorioContadoresPostgres). No decide el formato final del
    id (numérico plano, con prefijo...) — eso es cosa de cada entidad
    cuando adopte este mecanismo."""

    @abstractmethod
    def siguiente_valor(self, tipo_entidad: str) -> int:
        """Incrementa y devuelve el contador de tipo_entidad, empezando
        en 1 la primera vez que se pide ese tipo_entidad."""
        ...

    @abstractmethod
    def listar(self) -> dict[str, int]:
        """Lectura pura {tipo_entidad: valor actual} — a diferencia de
        siguiente_valor(), no incrementa nada. Pensado para una vista de
        solo lectura (ej. panel interno), no para generar ids."""
        ...

    @abstractmethod
    def borrar_todo(self) -> int:
        """Ver RepositorioCitas.borrar_todo — misma herramienta de
        panel, mismo alcance de "solo entorno local". Reinicia todos
        los contadores, no solo uno."""
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
