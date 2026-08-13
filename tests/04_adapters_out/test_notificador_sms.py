"""No golpea la API real de Twilio: se inyecta un cliente falso."""
from unittest.mock import MagicMock

from adapters.out.notificador_sms import NotificadorMensajesSMS


def test_enviar_crea_un_mensaje_con_el_remitente_y_el_texto():
    cliente_falso = MagicMock()
    notificador = NotificadorMensajesSMS(
        "sid-falso", "token-falso", "+34900000000", cliente=cliente_falso
    )

    notificador.enviar("+34600111222", "Reserva confirmada")

    cliente_falso.messages.create.assert_called_once_with(
        body="Reserva confirmada", from_="+34900000000", to="+34600111222",
    )


def test_sin_cliente_inyectado_construye_uno_con_las_credenciales(monkeypatch):
    mock_cliente_cls = MagicMock()
    monkeypatch.setattr("adapters.out.notificador_sms.Client", mock_cliente_cls)

    NotificadorMensajesSMS("sid-falso", "token-falso", "+34900000000")

    mock_cliente_cls.assert_called_once_with("sid-falso", "token-falso")
