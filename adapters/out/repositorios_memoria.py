"""
Implementaciones en memoria de los repositorios. Sirven para arrancar
rápido y para tests. En producción se sustituyen por adaptadores
Postgres/SQLModel que implementen los mismos puertos — el dominio y
el orquestador no cambian ni una línea.
"""
from __future__ import annotations

import threading
from datetime import date
from uuid import UUID

from domain.entities import Cita, Cliente, EstadoPedido, Pedido, Profesional, PromoBar, Servicio, Testimonio
from domain.ports import (
    RepositorioCitas,
    RepositorioClientes,
    RepositorioContadores,
    RepositorioPedidos,
    RepositorioProfesionales,
    RepositorioPromoBar,
    RepositorioServicios,
    RepositorioTestimonios,
)


class RepositorioServiciosMemoria(RepositorioServicios):
    def __init__(self, servicios: list[Servicio] | None = None):
        self._data = {s.id: s for s in (servicios or [])}

    def obtener(self, servicio_id: str) -> Servicio | None:
        return self._data.get(servicio_id)

    def listar(self) -> list[Servicio]:
        return list(self._data.values())


class RepositorioProfesionalesMemoria(RepositorioProfesionales):
    def __init__(self, profesionales: list[Profesional] | None = None):
        self._data = {p.id: p for p in (profesionales or [])}

    def obtener(self, profesional_id: str) -> Profesional | None:
        return self._data.get(profesional_id)

    def listar_por_servicio(self, servicio_id: str) -> list[Profesional]:
        return [p for p in self._data.values() if servicio_id in p.servicios_ids]


class RepositorioCitasMemoria(RepositorioCitas):
    def __init__(self):
        self._data: dict = {}

    def guardar(self, cita: Cita) -> None:
        self._data[cita.id] = cita

    def obtener(self, cita_id) -> Cita | None:
        return self._data.get(cita_id)

    def citas_de_profesional_en_fecha(self, profesional_id: str, dia: date) -> list[Cita]:
        return [
            c for c in self._data.values()
            if c.profesional_id == profesional_id and c.inicio.date() == dia
        ]

    def citas_en_rango(self, desde: date, hasta: date) -> list[Cita]:
        return [c for c in self._data.values() if desde <= c.inicio.date() <= hasta]

    def cancelar(self, cita_id) -> None:
        if cita_id in self._data:
            from domain.entities import EstadoCita
            self._data[cita_id].estado = EstadoCita.CANCELADA

    def reasignar_cliente(self, id_antiguo: str, id_nuevo: str) -> int:
        n = 0
        for cita in self._data.values():
            if cita.cliente_id == id_antiguo:
                cita.cliente_id = id_nuevo
                n += 1
        return n

    def borrar_todo(self) -> int:
        n = len(self._data)
        self._data.clear()
        return n


class RepositorioClientesMemoria(RepositorioClientes):
    def __init__(self):
        self._data: dict[str, Cliente] = {}

    def obtener(self, cliente_id: str) -> Cliente | None:
        return self._data.get(cliente_id)

    def guardar(self, cliente: Cliente) -> None:
        self._data[cliente.id] = cliente

    def buscar_por_telefono(self, telefono: str) -> Cliente | None:
        return next(
            (c for c in self._data.values() if c.telefono == telefono and not c.borrado), None
        )

    def listar(self) -> list[Cliente]:
        return [c for c in self._data.values() if not c.borrado]

    def eliminar(self, cliente_id: str) -> None:
        self._data.pop(cliente_id, None)

    def marcar_borrado(self, cliente_id: str) -> None:
        if cliente_id in self._data:
            self._data[cliente_id].borrado = True

    def borrar_todo(self) -> int:
        n = len(self._data)
        self._data.clear()
        return n


class RepositorioTestimoniosMemoria(RepositorioTestimonios):
    def __init__(self):
        self._data: dict[UUID, Testimonio] = {}

    def obtener(self, testimonio_id: UUID) -> Testimonio | None:
        return self._data.get(testimonio_id)

    def guardar(self, testimonio: Testimonio) -> None:
        self._data[testimonio.id] = testimonio

    def listar(self) -> list[Testimonio]:
        return list(self._data.values())

    def eliminar(self, testimonio_id: UUID) -> None:
        self._data.pop(testimonio_id, None)

    def borrar_todo(self) -> int:
        n = len(self._data)
        self._data.clear()
        return n


class RepositorioPromoBarMemoria(RepositorioPromoBar):
    def __init__(self):
        self._data: dict[int, PromoBar] = {}

    def obtener(self, promo_bar_id: int) -> PromoBar | None:
        return self._data.get(promo_bar_id)

    def guardar(self, promo_bar: PromoBar) -> None:
        self._data[promo_bar.id] = promo_bar

    def listar(self) -> list[PromoBar]:
        return list(self._data.values())

    def eliminar(self, promo_bar_id: int) -> None:
        self._data.pop(promo_bar_id, None)

    def obtener_activo(self) -> PromoBar | None:
        return next((p for p in self._data.values() if p.activo), None)

    def activar(self, promo_bar_id: int) -> None:
        for promo_bar in self._data.values():
            promo_bar.activo = promo_bar.id == promo_bar_id


class RepositorioContadoresMemoria(RepositorioContadores):
    def __init__(self):
        self._data: dict[str, int] = {}
        self._lock = threading.Lock()

    def siguiente_valor(self, tipo_entidad: str) -> int:
        # FastAPI ejecuta los endpoints síncronos en un threadpool real
        # (no un único hilo con GIL cooperativo como asyncio), así que
        # dos creaciones concurrentes del mismo tipo de entidad sí
        # pueden entrelazarse entre el "leer" y el "escribir" sin lock.
        with self._lock:
            nuevo_valor = self._data.get(tipo_entidad, 0) + 1
            self._data[tipo_entidad] = nuevo_valor
            return nuevo_valor

    def listar(self) -> dict[str, int]:
        with self._lock:
            return dict(self._data)

    def borrar_todo(self) -> int:
        with self._lock:
            n = len(self._data)
            self._data.clear()
            return n


class RepositorioPedidosMemoria(RepositorioPedidos):
    def __init__(self):
        self._data: dict = {}

    def guardar(self, pedido: Pedido) -> None:
        self._data[pedido.id] = pedido

    def obtener(self, pedido_id) -> Pedido | None:
        return self._data.get(pedido_id)

    def listar_pendientes(self) -> list[Pedido]:
        return [
            p for p in self._data.values()
            if p.estado not in (EstadoPedido.ENTREGADO, EstadoPedido.CANCELADO)
        ]

    def reasignar_cliente(self, id_antiguo: str, id_nuevo: str) -> int:
        n = 0
        for pedido in self._data.values():
            if pedido.cliente_id == id_antiguo:
                pedido.cliente_id = id_nuevo
                n += 1
        return n

    def borrar_todo(self) -> int:
        n = len(self._data)
        self._data.clear()
        return n
