from datetime import datetime, time

from domain.entities import (
    Cita,
    Cliente,
    EstadoCita,
    EstadoPedido,
    LineaPedido,
    Pedido,
    Profesional,
    Servicio,
    SlotDisponible,
)


def test_servicio_valores_por_defecto():
    servicio = Servicio(id="s1", nombre="Masaje", duracion_minutos=60, precio=50.0)
    assert servicio.descripcion == ""


def test_profesional_valores_por_defecto():
    profesional = Profesional(id="p1", nombre="Ana")
    assert profesional.servicios_ids == []
    assert profesional.horario_semanal == {}


def test_profesional_horario_semanal():
    horario = {"lunes": (time(9, 0), time(18, 0))}
    profesional = Profesional(id="p1", nombre="Ana", horario_semanal=horario)
    assert profesional.horario_semanal["lunes"] == (time(9, 0), time(18, 0))


def test_cliente_valores_por_defecto():
    cliente = Cliente(id="c1", nombre="Juan")
    assert cliente.telefono is None
    assert cliente.email is None
    assert cliente.notas == ""


def test_estado_cita_tiene_los_seis_valores_del_ciclo_de_vida():
    # Ver issue #43: pendiente al crear, confirmada/en_curso/finalizada/
    # no_show manuales desde el panel, cancelada vía CancelarReserva.
    assert {e.value for e in EstadoCita} == {
        "pendiente", "confirmada", "en_curso", "finalizada", "cancelada", "no_show",
    }


def test_cita_nueva_genera_id_y_estado_pendiente():
    inicio = datetime(2026, 8, 3, 9, 0)
    fin = datetime(2026, 8, 3, 10, 0)
    cita = Cita.nueva("s1", "p1", "c1", inicio, fin)

    assert cita.id is not None
    assert cita.servicio_id == "s1"
    assert cita.profesional_id == "p1"
    assert cita.cliente_id == "c1"
    assert cita.inicio == inicio
    assert cita.fin == fin
    assert cita.estado == EstadoCita.PENDIENTE


def test_dos_citas_nuevas_tienen_ids_distintos():
    inicio = datetime(2026, 8, 3, 9, 0)
    fin = datetime(2026, 8, 3, 10, 0)
    cita1 = Cita.nueva("s1", "p1", "c1", inicio, fin)
    cita2 = Cita.nueva("s1", "p1", "c1", inicio, fin)
    assert cita1.id != cita2.id


def test_slot_disponible():
    slot = SlotDisponible(
        profesional_id="p1",
        inicio=datetime(2026, 8, 3, 9, 0),
        fin=datetime(2026, 8, 3, 10, 0),
    )
    assert slot.profesional_id == "p1"
    assert slot.fin > slot.inicio


def test_pedido_nuevo_genera_id_y_estado_recibido():
    lineas = [LineaPedido(servicio_id="s1", cantidad=2)]
    pedido = Pedido.nuevo("c1", lineas)

    assert pedido.id is not None
    assert pedido.cliente_id == "c1"
    assert pedido.lineas == lineas
    assert pedido.estado == EstadoPedido.RECIBIDO
    assert isinstance(pedido.creado_en, datetime)


def test_linea_pedido_valores_por_defecto():
    linea = LineaPedido(servicio_id="s1", cantidad=1)
    assert linea.notas == ""
