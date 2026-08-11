from datetime import datetime
from unittest.mock import MagicMock, patch

from adapters.out.calendario_google import SincronizadorCalendarioGoogle
from domain.entities import Cita, Profesional, Servicio


def _sincronizador_con_cliente_falso():
    with (
        patch("adapters.out.calendario_google.service_account") as mock_service_account,
        patch("adapters.out.calendario_google.build") as mock_build,
    ):
        mock_credenciales = MagicMock()
        mock_service_account.Credentials.from_service_account_file.return_value = mock_credenciales
        mock_servicio_google = MagicMock()
        mock_build.return_value = mock_servicio_google

        sincronizador = SincronizadorCalendarioGoogle(
            credenciales_json_path="/ruta/falsa/credenciales.json",
            calendar_id="negocio@group.calendar.google.com",
        )
        return sincronizador, mock_servicio_google, mock_service_account, mock_build


def _cita():
    return Cita.nueva(
        1, "masaje_relajante_60", "ana", "cliente1",
        datetime(2026, 8, 10, 9, 0), datetime(2026, 8, 10, 10, 0),
    )


def _servicio():
    return Servicio(id="masaje_relajante_60", nombre="Masaje relajante", duracion_minutos=60, precio=55.0)


def _profesional():
    return Profesional(id="ana", nombre="Ana García", servicios_ids=["masaje_relajante_60"])


def test_se_autentica_con_la_cuenta_de_servicio_y_el_scope_de_calendar():
    _, _, mock_service_account, mock_build = _sincronizador_con_cliente_falso()

    mock_service_account.Credentials.from_service_account_file.assert_called_once_with(
        "/ruta/falsa/credenciales.json",
        scopes=["https://www.googleapis.com/auth/calendar"],
    )
    mock_build.assert_called_once_with(
        "calendar", "v3",
        credentials=mock_service_account.Credentials.from_service_account_file.return_value,
    )


def test_crear_evento_llama_a_events_insert_y_devuelve_el_id():
    sincronizador, mock_servicio_google, _, _ = _sincronizador_con_cliente_falso()
    mock_servicio_google.events().insert().execute.return_value = {"id": "evento-abc"}

    resultado = sincronizador.crear_evento(_cita(), _servicio(), _profesional())

    assert resultado == "evento-abc"
    args, kwargs = mock_servicio_google.events().insert.call_args
    assert kwargs["calendarId"] == "negocio@group.calendar.google.com"
    assert kwargs["body"]["start"]["dateTime"] == "2026-08-10T09:00:00"
    assert kwargs["body"]["start"]["timeZone"] == "Europe/Madrid"
    assert kwargs["body"]["end"]["dateTime"] == "2026-08-10T10:00:00"
    assert kwargs["body"]["end"]["timeZone"] == "Europe/Madrid"
    assert "Masaje relajante" in kwargs["body"]["summary"]
    assert "Ana García" in kwargs["body"]["summary"]


def test_cancelar_evento_llama_a_events_delete():
    sincronizador, mock_servicio_google, _, _ = _sincronizador_con_cliente_falso()

    sincronizador.cancelar_evento("evento-abc")

    args, kwargs = mock_servicio_google.events().delete.call_args
    assert kwargs["calendarId"] == "negocio@group.calendar.google.com"
    assert kwargs["eventId"] == "evento-abc"
