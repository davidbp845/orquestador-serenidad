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

from domain.entities import Cita, Cliente, EstadoPedido, Pedido, Profesional, Servicio, Testimonio
from domain.ports import (
    RepositorioCitas,
    RepositorioClientes,
    RepositorioContadores,
    RepositorioPedidos,
    RepositorioProfesionales,
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
        return next((c for c in self._data.values() if c.telefono == telefono), None)

    def listar(self) -> list[Cliente]:
        return list(self._data.values())

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

    def borrar_todo(self) -> int:
        n = len(self._data)
        self._data.clear()
        return n
