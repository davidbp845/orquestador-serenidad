"""Implementaciones Postgres (vía SQLModel) de los repositorios de
estado mutable: Citas, Clientes y Pedidos. Servicios y Profesionales
siguen viniendo de config/business.yaml a través de
RepositorioServiciosMemoria/RepositorioProfesionalesMemoria — son
catálogo, no estado que deba sobrevivir a un reinicio.

Cambiar de motor (ej. volver a memoria, o pasar a otro store) es
sustituir la instanciación en main.py::construir_sistema(); estas
clases implementan los mismos puertos de domain/ports.py y nada más
en el sistema necesita saber que existen."""
from __future__ import annotations

import os
from datetime import date
from uuid import UUID

from sqlalchemy import delete, text, update
from sqlmodel import Session, SQLModel, create_engine, select

from domain.entities import (
    Cita,
    Cliente,
    EstadoCita,
    EstadoPedido,
    LineaPedido,
    NotaCliente,
    Pedido,
    PromoBar,
    Testimonio,
)
from domain.ports import (
    RepositorioCitas,
    RepositorioClientes,
    RepositorioContadores,
    RepositorioNotasCliente,
    RepositorioPedidos,
    RepositorioPromoBar,
    RepositorioTestimonios,
)

from .db_models import (
    CitaDB,
    ClienteDB,
    ContadorDB,
    LineaPedidoDB,
    NotaClienteDB,
    PedidoDB,
    PromoBarDB,
    TestimonioDB,
)


def _como_uuid(valor) -> UUID | None:
    """IDs de dominio no tienen por qué venir ya como UUID (ej. un
    id de tool call inventado por el LLM). Un id con formato inválido
    se trata como 'no existe', igual que en los repos en memoria, en
    vez de propagar el error de parseo."""
    if isinstance(valor, UUID):
        return valor
    try:
        return UUID(str(valor))
    except (ValueError, AttributeError, TypeError):
        return None


def _como_int(valor) -> int | None:
    """Mismo motivo que _como_uuid, para las entidades con id int
    (Cita, Testimonio, tras #68/#69): a diferencia de SQLite (usado en
    los tests de este módulo), Postgres es estrictamente tipado y
    lanza DataError si se compara una columna Integer contra un valor
    no convertible — confirmado manualmente contra el Postgres de
    desarrollo con sesion.get(CitaDB, "no_existe"). Un id con formato
    inválido se trata como 'no existe' en vez de propagar el error."""
    if isinstance(valor, int):
        return valor
    try:
        return int(valor)
    except (ValueError, TypeError):
        return None


def crear_engine(url: str | None = None):
    url = url or os.environ["DATABASE_URL"]
    return create_engine(url)


def crear_tablas(engine) -> None:
    """Crea las tablas que falten a partir de la metadata actual, sin
    pasar por Alembic. Útil en tests o scripts puntuales contra una
    base efímera (ej. SQLite en memoria); el esquema de la app real se
    gestiona con `alembic upgrade head` (ver migrations/), no con esta
    función."""
    SQLModel.metadata.create_all(engine)


class RepositorioCitasPostgres(RepositorioCitas):
    def __init__(self, engine):
        self._engine = engine

    def guardar(self, cita: Cita) -> None:
        with Session(self._engine) as sesion:
            sesion.merge(CitaDB(
                id=cita.id,
                servicio_id=cita.servicio_id,
                profesional_id=cita.profesional_id,
                cliente_id=cita.cliente_id,
                inicio=cita.inicio,
                fin=cita.fin,
                estado=cita.estado.value,
                evento_calendario_id=cita.evento_calendario_id,
            ))
            sesion.commit()

    def obtener(self, cita_id: int) -> Cita | None:
        cita_id = _como_int(cita_id)
        if cita_id is None:
            return None
        with Session(self._engine) as sesion:
            fila = sesion.get(CitaDB, cita_id)
            return self._a_entidad(fila) if fila else None

    def citas_de_profesional_en_fecha(self, profesional_id: str, dia: date) -> list[Cita]:
        with Session(self._engine) as sesion:
            filas = sesion.exec(
                select(CitaDB).where(CitaDB.profesional_id == profesional_id)
            ).all()
            return [self._a_entidad(f) for f in filas if f.inicio.date() == dia]

    def citas_en_rango(self, desde: date, hasta: date) -> list[Cita]:
        with Session(self._engine) as sesion:
            filas = sesion.exec(select(CitaDB)).all()
            return [self._a_entidad(f) for f in filas if desde <= f.inicio.date() <= hasta]

    def cancelar(self, cita_id: int) -> None:
        cita_id = _como_int(cita_id)
        if cita_id is None:
            return
        with Session(self._engine) as sesion:
            fila = sesion.get(CitaDB, cita_id)
            if fila is not None:
                fila.estado = EstadoCita.CANCELADA.value
                sesion.add(fila)
                sesion.commit()

    def reasignar_cliente(self, id_antiguo: str, id_nuevo: str) -> int:
        with Session(self._engine) as sesion:
            n = sesion.execute(
                update(CitaDB).where(CitaDB.cliente_id == id_antiguo).values(cliente_id=id_nuevo)
            ).rowcount
            sesion.commit()
            return n

    def borrar_todo(self) -> int:
        with Session(self._engine) as sesion:
            n = sesion.execute(delete(CitaDB)).rowcount
            sesion.commit()
            return n

    @staticmethod
    def _a_entidad(fila: CitaDB) -> Cita:
        return Cita(
            id=fila.id,
            servicio_id=fila.servicio_id,
            profesional_id=fila.profesional_id,
            cliente_id=fila.cliente_id,
            inicio=fila.inicio,
            fin=fila.fin,
            estado=EstadoCita(fila.estado),
            evento_calendario_id=fila.evento_calendario_id,
        )


class RepositorioClientesPostgres(RepositorioClientes):
    def __init__(self, engine):
        self._engine = engine

    def obtener(self, cliente_id: str) -> Cliente | None:
        with Session(self._engine) as sesion:
            fila = sesion.get(ClienteDB, cliente_id)
            return self._a_entidad(fila) if fila else None

    def guardar(self, cliente: Cliente) -> None:
        with Session(self._engine) as sesion:
            sesion.merge(ClienteDB(
                id=cliente.id,
                nombre=cliente.nombre,
                telefono=cliente.telefono,
                email=cliente.email,
                telegram_chat_id=cliente.telegram_chat_id,
                borrado=cliente.borrado,
            ))
            sesion.commit()

    def buscar_por_telefono(self, telefono: str) -> Cliente | None:
        with Session(self._engine) as sesion:
            fila = sesion.exec(
                select(ClienteDB).where(ClienteDB.telefono == telefono, ClienteDB.borrado.is_(False))
            ).first()
            return self._a_entidad(fila) if fila else None

    def listar(self) -> list[Cliente]:
        with Session(self._engine) as sesion:
            filas = sesion.exec(select(ClienteDB).where(ClienteDB.borrado.is_(False))).all()
            return [self._a_entidad(fila) for fila in filas]

    def eliminar(self, cliente_id: str) -> None:
        with Session(self._engine) as sesion:
            fila = sesion.get(ClienteDB, cliente_id)
            if fila is not None:
                sesion.delete(fila)
                sesion.commit()

    def marcar_borrado(self, cliente_id: str) -> None:
        with Session(self._engine) as sesion:
            fila = sesion.get(ClienteDB, cliente_id)
            if fila is not None:
                fila.borrado = True
                sesion.add(fila)
                sesion.commit()

    def borrar_todo(self) -> int:
        with Session(self._engine) as sesion:
            n = sesion.execute(delete(ClienteDB)).rowcount
            sesion.commit()
            return n

    @staticmethod
    def _a_entidad(fila: ClienteDB) -> Cliente:
        return Cliente(
            id=fila.id, nombre=fila.nombre, telefono=fila.telefono,
            email=fila.email,
            telegram_chat_id=fila.telegram_chat_id, borrado=fila.borrado,
        )


class RepositorioNotasClientePostgres(RepositorioNotasCliente):
    def __init__(self, engine):
        self._engine = engine

    def crear(self, nota: NotaCliente) -> None:
        with Session(self._engine) as sesion:
            sesion.add(NotaClienteDB(
                id=nota.id, cliente_id=nota.cliente_id,
                texto=nota.texto, creado_en=nota.creado_en,
            ))
            sesion.commit()

    def listar_de_cliente(self, cliente_id: str) -> list[NotaCliente]:
        with Session(self._engine) as sesion:
            filas = sesion.exec(
                select(NotaClienteDB).where(NotaClienteDB.cliente_id == cliente_id)
            ).all()
            return [self._a_entidad(fila) for fila in filas]

    def reasignar_cliente(self, id_antiguo: str, id_nuevo: str) -> int:
        with Session(self._engine) as sesion:
            resultado = sesion.execute(
                update(NotaClienteDB)
                .where(NotaClienteDB.cliente_id == id_antiguo)
                .values(cliente_id=id_nuevo)
            )
            sesion.commit()
            return resultado.rowcount

    def borrar_todo(self) -> int:
        with Session(self._engine) as sesion:
            n = sesion.execute(delete(NotaClienteDB)).rowcount
            sesion.commit()
            return n

    @staticmethod
    def _a_entidad(fila: NotaClienteDB) -> NotaCliente:
        return NotaCliente(
            id=fila.id, cliente_id=fila.cliente_id,
            texto=fila.texto, creado_en=fila.creado_en,
        )


class RepositorioTestimoniosPostgres(RepositorioTestimonios):
    def __init__(self, engine):
        self._engine = engine

    def obtener(self, testimonio_id: int) -> Testimonio | None:
        testimonio_id = _como_int(testimonio_id)
        if testimonio_id is None:
            return None
        with Session(self._engine) as sesion:
            fila = sesion.get(TestimonioDB, testimonio_id)
            return self._a_entidad(fila) if fila else None

    def guardar(self, testimonio: Testimonio) -> None:
        with Session(self._engine) as sesion:
            sesion.merge(TestimonioDB(
                id=testimonio.id,
                nombre=testimonio.nombre,
                titulo=testimonio.titulo,
                descripcion=testimonio.descripcion,
                valoracion=testimonio.valoracion,
                creado_en=testimonio.creado_en,
            ))
            sesion.commit()

    def listar(self) -> list[Testimonio]:
        with Session(self._engine) as sesion:
            filas = sesion.exec(select(TestimonioDB)).all()
            return [self._a_entidad(fila) for fila in filas]

    def eliminar(self, testimonio_id: int) -> None:
        testimonio_id = _como_int(testimonio_id)
        if testimonio_id is None:
            return
        with Session(self._engine) as sesion:
            fila = sesion.get(TestimonioDB, testimonio_id)
            if fila is not None:
                sesion.delete(fila)
                sesion.commit()

    def borrar_todo(self) -> int:
        with Session(self._engine) as sesion:
            n = sesion.execute(delete(TestimonioDB)).rowcount
            sesion.commit()
            return n

    @staticmethod
    def _a_entidad(fila: TestimonioDB) -> Testimonio:
        return Testimonio(
            id=fila.id, nombre=fila.nombre, titulo=fila.titulo,
            descripcion=fila.descripcion, valoracion=fila.valoracion,
            creado_en=fila.creado_en,
        )


class RepositorioPromoBarPostgres(RepositorioPromoBar):
    def __init__(self, engine):
        self._engine = engine

    def obtener(self, promo_bar_id: int) -> PromoBar | None:
        promo_bar_id = _como_int(promo_bar_id)
        if promo_bar_id is None:
            return None
        with Session(self._engine) as sesion:
            fila = sesion.get(PromoBarDB, promo_bar_id)
            return self._a_entidad(fila) if fila else None

    def guardar(self, promo_bar: PromoBar) -> None:
        with Session(self._engine) as sesion:
            sesion.merge(PromoBarDB(
                id=promo_bar.id, nombre=promo_bar.nombre, activo=promo_bar.activo,
                contenido_html=promo_bar.contenido_html, actualizado_en=promo_bar.actualizado_en,
            ))
            sesion.commit()

    def listar(self) -> list[PromoBar]:
        with Session(self._engine) as sesion:
            filas = sesion.exec(select(PromoBarDB)).all()
            return [self._a_entidad(fila) for fila in filas]

    def eliminar(self, promo_bar_id: int) -> None:
        promo_bar_id = _como_int(promo_bar_id)
        if promo_bar_id is None:
            return
        with Session(self._engine) as sesion:
            fila = sesion.get(PromoBarDB, promo_bar_id)
            if fila is not None:
                sesion.delete(fila)
                sesion.commit()

    def obtener_activo(self) -> PromoBar | None:
        with Session(self._engine) as sesion:
            fila = sesion.exec(select(PromoBarDB).where(PromoBarDB.activo.is_(True))).first()
            return self._a_entidad(fila) if fila else None

    def activar(self, promo_bar_id: int) -> None:
        # Una sola transacción: desactivar todos + activar el elegido.
        # Sin esto, dos llamadas a activar() casi simultáneas (o un
        # fallo a mitad) podrían dejar dos promobars activos a la vez,
        # o ninguno — mismo motivo que RepositorioContadoresPostgres
        # usa un UPSERT atómico en vez de SELECT+UPDATE.
        with Session(self._engine) as sesion:
            sesion.execute(update(PromoBarDB).values(activo=False))
            sesion.execute(
                update(PromoBarDB).where(PromoBarDB.id == promo_bar_id).values(activo=True)
            )
            sesion.commit()

    @staticmethod
    def _a_entidad(fila: PromoBarDB) -> PromoBar:
        return PromoBar(
            id=fila.id, nombre=fila.nombre, activo=fila.activo,
            contenido_html=fila.contenido_html, actualizado_en=fila.actualizado_en,
        )


class RepositorioContadoresPostgres(RepositorioContadores):
    """A diferencia del resto de repos de este módulo (que hacen
    sesion.merge()/sesion.get() vía el ORM), este usa una única
    sentencia UPSERT atómica: un SELECT seguido de UPDATE tiene una
    ventana de carrera entre ambas sentencias donde dos transacciones
    concurrentes (ej. main.py y panel_empleados escribiendo contra el
    mismo Postgres a la vez) podrían leer el mismo valor y devolver un
    id duplicado. INSERT ... ON CONFLICT ... RETURNING es una sola
    sentencia: el bloqueo de fila de Postgres serializa los incrementos
    concurrentes sin necesidad de un lock explícito en la aplicación.
    Sintaxis soportada también por SQLite (>=3.35, usada en los tests
    de este módulo vía motor en memoria), no es exclusiva de Postgres."""

    def __init__(self, engine):
        self._engine = engine

    def siguiente_valor(self, tipo_entidad: str) -> int:
        with Session(self._engine) as sesion:
            resultado = sesion.execute(
                text(
                    "INSERT INTO contadores (tipo_entidad, valor) VALUES (:tipo, 1) "
                    "ON CONFLICT (tipo_entidad) DO UPDATE SET valor = contadores.valor + 1 "
                    "RETURNING valor"
                ),
                {"tipo": tipo_entidad},
            )
            valor = resultado.scalar_one()
            sesion.commit()
            return valor

    def listar(self) -> dict[str, int]:
        with Session(self._engine) as sesion:
            filas = sesion.exec(select(ContadorDB)).all()
            return {fila.tipo_entidad: fila.valor for fila in filas}

    def borrar_todo(self) -> int:
        with Session(self._engine) as sesion:
            n = sesion.execute(delete(ContadorDB)).rowcount
            sesion.commit()
            return n


class RepositorioPedidosPostgres(RepositorioPedidos):
    def __init__(self, engine):
        self._engine = engine

    def guardar(self, pedido: Pedido) -> None:
        with Session(self._engine) as sesion:
            sesion.merge(PedidoDB(
                id=pedido.id,
                cliente_id=pedido.cliente_id,
                estado=pedido.estado.value,
                creado_en=pedido.creado_en,
            ))
            # Las líneas no tienen identidad propia en el dominio: se
            # sustituyen enteras en cada guardado en vez de intentar
            # diffear la lista.
            lineas_previas = sesion.exec(
                select(LineaPedidoDB).where(LineaPedidoDB.pedido_id == pedido.id)
            ).all()
            for linea in lineas_previas:
                sesion.delete(linea)
            for linea in pedido.lineas:
                sesion.add(LineaPedidoDB(
                    pedido_id=pedido.id,
                    servicio_id=linea.servicio_id,
                    cantidad=linea.cantidad,
                    notas=linea.notas,
                ))
            sesion.commit()

    def obtener(self, pedido_id) -> Pedido | None:
        pedido_id = _como_uuid(pedido_id)
        if pedido_id is None:
            return None
        with Session(self._engine) as sesion:
            cabecera = sesion.get(PedidoDB, pedido_id)
            if cabecera is None:
                return None
            return self._a_entidad(sesion, cabecera)

    def listar_pendientes(self) -> list[Pedido]:
        estados_terminales = (EstadoPedido.ENTREGADO.value, EstadoPedido.CANCELADO.value)
        with Session(self._engine) as sesion:
            cabeceras = sesion.exec(
                select(PedidoDB).where(PedidoDB.estado.not_in(estados_terminales))
            ).all()
            return [self._a_entidad(sesion, c) for c in cabeceras]

    def reasignar_cliente(self, id_antiguo: str, id_nuevo: str) -> int:
        with Session(self._engine) as sesion:
            n = sesion.execute(
                update(PedidoDB).where(PedidoDB.cliente_id == id_antiguo).values(cliente_id=id_nuevo)
            ).rowcount
            sesion.commit()
            return n

    def borrar_todo(self) -> int:
        # pedido_lineas antes que pedidos: es la única FK real del
        # esquema (pedido_lineas.pedido_id -> pedidos.id).
        with Session(self._engine) as sesion:
            sesion.execute(delete(LineaPedidoDB))
            n = sesion.execute(delete(PedidoDB)).rowcount
            sesion.commit()
            return n

    @staticmethod
    def _a_entidad(sesion: Session, cabecera: PedidoDB) -> Pedido:
        lineas = sesion.exec(
            select(LineaPedidoDB).where(LineaPedidoDB.pedido_id == cabecera.id)
        ).all()
        return Pedido(
            id=cabecera.id,
            cliente_id=cabecera.cliente_id,
            lineas=[
                LineaPedido(servicio_id=linea.servicio_id, cantidad=linea.cantidad, notas=linea.notas)
                for linea in lineas
            ],
            estado=EstadoPedido(cabecera.estado),
            creado_en=cabecera.creado_en,
        )
