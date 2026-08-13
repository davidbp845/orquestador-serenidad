"""No golpea la Graph API real: se mockea httpx.post."""
from unittest.mock import MagicMock, patch

import httpx
import pytest

from adapters.out.notificador_whatsapp import NotificadorMensajesWhatsApp


def test_enviar_llama_a_la_graph_api_con_el_mensaje():
    notificador = NotificadorMensajesWhatsApp("access-123", "1234567890")

    with patch("adapters.out.notificador_whatsapp.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        notificador.enviar("34600111222", "Reserva confirmada")

    url_llamada, kwargs = mock_post.call_args[0][0], mock_post.call_args[1]
    assert "1234567890" in url_llamada
    assert kwargs["headers"]["Authorization"] == "Bearer access-123"
    assert kwargs["json"] == {
        "messaging_product": "whatsapp",
        "to": "34600111222",
        "type": "text",
        "text": {"body": "Reserva confirmada"},
    }


def test_enviar_propaga_el_error_si_la_api_falla():
    notificador = NotificadorMensajesWhatsApp("access-123", "1234567890")

    with patch("adapters.out.notificador_whatsapp.httpx.post") as mock_post:
        respuesta = MagicMock(status_code=400)
        respuesta.raise_for_status.side_effect = httpx.HTTPStatusError(
            "bad request", request=MagicMock(), response=respuesta
        )
        mock_post.return_value = respuesta

        with pytest.raises(httpx.HTTPStatusError):
            notificador.enviar("34600111222", "texto")
