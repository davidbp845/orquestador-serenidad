"""adapters/in_/fastapi_app.py define `app` a nivel de módulo, y
crear_router() añade rutas sobre ese mismo `app` cada vez que se
llama. Para que cada test tenga rutas limpias (y no dependa del orden
de ejecución), recargamos el módulo en cada test en lugar de
reutilizar la instancia compartida. Las sesiones ya no viven en el
módulo (ver #18) — cada test crea su propio RepositorioSesionesMemoria."""
import importlib

import pytest
from fastapi.testclient import TestClient

from adapters.out.repositorio_sesiones_memoria import RepositorioSesionesMemoria


class FakeOrquestador:
    def __init__(self, respuesta="Hola, ¿en qué puedo ayudarte?", fuentes=None, eventos_stream=None):
        self.respuesta = respuesta
        self.fuentes = fuentes or []
        self.eventos_stream = eventos_stream
        self.llamadas = []

    def responder(self, sesion, mensaje):
        self.llamadas.append((sesion.usuario_id, mensaje))
        return self.respuesta

    def responder_stream(self, sesion, mensaje):
        self.llamadas.append((sesion.usuario_id, mensaje))
        if self.eventos_stream is not None:
            yield from self.eventos_stream
            return
        yield {"tipo": "delta", "texto": self.respuesta}
        yield {"tipo": "done", "respuesta": self.respuesta, "fuentes": self.fuentes}


@pytest.fixture
def modulo():
    import adapters.in_.fastapi_app as fastapi_app
    importlib.reload(fastapi_app)
    return fastapi_app


@pytest.fixture
def cliente(modulo):
    orquestador = FakeOrquestador()
    repositorio_sesiones = RepositorioSesionesMemoria()
    app = modulo.crear_router(orquestador, repositorio_sesiones)
    return TestClient(app), orquestador, repositorio_sesiones


@pytest.fixture
def cliente_con_limite(modulo):
    orquestador = FakeOrquestador()
    repositorio_sesiones = RepositorioSesionesMemoria()
    app = modulo.crear_router(
        orquestador, repositorio_sesiones, limite_peticiones=2, ventana_segundos=60
    )
    return TestClient(app), orquestador, repositorio_sesiones


def test_health(cliente):
    client, _, _ = cliente
    respuesta = client.get("/health")
    assert respuesta.status_code == 200
    assert respuesta.json() == {"status": "ok"}


def test_chat_devuelve_la_respuesta_del_orquestador(cliente):
    client, orquestador, _ = cliente
    respuesta = client.post("/chat", json={"usuario_id": "u1", "mensaje": "hola"})

    assert respuesta.status_code == 200
    assert respuesta.json() == {"respuesta": orquestador.respuesta}
    assert orquestador.llamadas == [("u1", "hola")]


def test_chat_reutiliza_la_sesion_del_mismo_usuario(cliente):
    client, orquestador, repositorio_sesiones = cliente

    client.post("/chat", json={"usuario_id": "u2", "mensaje": "primero"})
    client.post("/chat", json={"usuario_id": "u2", "mensaje": "segundo"})

    sesion = repositorio_sesiones.obtener("web", "u2")
    assert sesion is not None
    assert sesion.canal == "web"
    assert [m for _, m in orquestador.llamadas] == ["primero", "segundo"]


def test_chat_valida_payload_incompleto(cliente):
    client, _, _ = cliente
    respuesta = client.post("/chat", json={"usuario_id": "u3"})
    assert respuesta.status_code == 422


def test_chat_stream_emite_frames_sse_de_delta_fuentes_y_done(cliente):
    client, orquestador, _ = cliente
    orquestador.respuesta = "Hola!"
    orquestador.fuentes = [{"fuente": "servicios.md", "categoria": "servicios"}]

    respuesta = client.post("/chat/stream", json={"usuario_id": "u1", "mensaje": "hola"})

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith("text/event-stream")
    cuerpo = respuesta.text
    assert "event: delta" in cuerpo
    assert '"texto": "Hola!"' in cuerpo
    assert "event: fuentes" in cuerpo
    assert "servicios.md" in cuerpo
    assert "event: done" in cuerpo
    assert orquestador.llamadas == [("u1", "hola")]


def test_chat_stream_emite_evento_error_si_el_orquestador_lanza(cliente):
    client, orquestador, _ = cliente

    def generador_roto(sesion, mensaje):
        yield {"tipo": "delta", "texto": "empiezo..."}
        raise RuntimeError("fallo de LLM")

    orquestador.responder_stream = generador_roto

    respuesta = client.post("/chat/stream", json={"usuario_id": "u1", "mensaje": "hola"})

    assert respuesta.status_code == 200
    assert "event: error" in respuesta.text
    assert "fallo de LLM" in respuesta.text


def test_chat_stream_persiste_la_sesion_incluso_si_el_orquestador_lanza(cliente):
    client, orquestador, repositorio_sesiones = cliente

    def generador_roto(sesion, mensaje):
        yield {"tipo": "delta", "texto": "empiezo..."}
        raise RuntimeError("fallo de LLM")

    orquestador.responder_stream = generador_roto

    client.post("/chat/stream", json={"usuario_id": "u4", "mensaje": "hola"})

    assert repositorio_sesiones.obtener("web", "u4") is not None


@pytest.mark.parametrize("origen", ["http://localhost:5173", "http://localhost:3000", "http://localhost:4321"])
def test_cors_permite_origenes_de_dev_habituales(cliente, origen):
    client, _, _ = cliente
    respuesta = client.options(
        "/chat",
        headers={
            "Origin": origen,
            "Access-Control-Request-Method": "POST",
        },
    )
    assert respuesta.headers["access-control-allow-origin"] == origen


def test_cors_rechaza_origen_no_autorizado(cliente):
    client, _, _ = cliente
    respuesta = client.options(
        "/chat",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in respuesta.headers


def test_cors_origins_env_var_sustituye_los_origenes_de_dev(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://miapp.com, https://www.miapp.com")

    import adapters.in_.fastapi_app as fastapi_app
    importlib.reload(fastapi_app)

    orquestador = FakeOrquestador()
    repositorio_sesiones = RepositorioSesionesMemoria()
    app = fastapi_app.crear_router(orquestador, repositorio_sesiones)
    client = TestClient(app)

    respuesta = client.options(
        "/chat",
        headers={
            "Origin": "https://miapp.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert respuesta.headers["access-control-allow-origin"] == "https://miapp.com"

    respuesta_dev = client.options(
        "/chat",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in respuesta_dev.headers


def test_chat_devuelve_429_al_superar_el_limite_de_peticiones(cliente_con_limite):
    client, orquestador, _ = cliente_con_limite

    for _ in range(2):
        respuesta = client.post("/chat", json={"usuario_id": "u1", "mensaje": "hola"})
        assert respuesta.status_code == 200

    respuesta = client.post("/chat", json={"usuario_id": "u1", "mensaje": "hola"})

    assert respuesta.status_code == 429
    assert len(orquestador.llamadas) == 2  # la 3ª petición no llega al orquestador


def test_chat_el_limite_es_independiente_por_usuario_id(cliente_con_limite):
    client, orquestador, _ = cliente_con_limite

    for _ in range(2):
        client.post("/chat", json={"usuario_id": "u1", "mensaje": "hola"})

    respuesta_otro_usuario = client.post("/chat", json={"usuario_id": "u2", "mensaje": "hola"})

    assert respuesta_otro_usuario.status_code == 200
    assert ("u2", "hola") in orquestador.llamadas


def test_chat_stream_tambien_respeta_el_limite_de_peticiones(cliente_con_limite):
    client, _, _ = cliente_con_limite

    for _ in range(2):
        respuesta = client.post("/chat/stream", json={"usuario_id": "u1", "mensaje": "hola"})
        assert respuesta.status_code == 200

    respuesta = client.post("/chat/stream", json={"usuario_id": "u1", "mensaje": "hola"})

    assert respuesta.status_code == 429


class FakeListarTestimoniosRecientes:
    def __init__(self, testimonios):
        self.testimonios = testimonios

    def ejecutar(self, limite=5):
        return self.testimonios[:limite]


def test_testimonios_devuelve_vacio_si_no_hay_caso_de_uso_configurado(cliente):
    client, _, _ = cliente
    respuesta = client.get("/testimonios")
    assert respuesta.status_code == 200
    assert respuesta.json() == []


def test_testimonios_devuelve_los_del_caso_de_uso(modulo):
    from domain.entities import Testimonio

    orquestador = FakeOrquestador()
    repositorio_sesiones = RepositorioSesionesMemoria()
    testimonio = Testimonio.nuevo(1, "Juan", "Repetiré seguro", 5, titulo="Genial")
    app = modulo.crear_router(
        orquestador, repositorio_sesiones,
        listar_testimonios_recientes=FakeListarTestimoniosRecientes([testimonio]),
    )
    client = TestClient(app)

    respuesta = client.get("/testimonios")

    assert respuesta.status_code == 200
    assert respuesta.json() == [
        {"id": 1, "nombre": "Juan", "titulo": "Genial", "descripcion": "Repetiré seguro", "valoracion": 5}
    ]


class FakeObtenerPromoBar:
    def __init__(self, promo_bar):
        self.promo_bar = promo_bar

    def ejecutar(self):
        return self.promo_bar


def test_promobar_devuelve_inactivo_si_no_hay_caso_de_uso_configurado(cliente):
    client, _, _ = cliente
    respuesta = client.get("/promobar")
    assert respuesta.status_code == 200
    assert respuesta.json() == {"activo": False, "contenido_html": ""}


def test_promobar_devuelve_inactivo_si_no_esta_activo(modulo):
    from domain.entities import PromoBar

    orquestador = FakeOrquestador()
    repositorio_sesiones = RepositorioSesionesMemoria()
    app = modulo.crear_router(
        orquestador, repositorio_sesiones,
        obtener_promo_bar=FakeObtenerPromoBar(PromoBar(activo=False, contenido_html="<p>Oferta</p>")),
    )
    client = TestClient(app)

    respuesta = client.get("/promobar")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"activo": False, "contenido_html": ""}


def test_promobar_devuelve_el_contenido_saneado_si_esta_activo(modulo):
    from domain.entities import PromoBar

    orquestador = FakeOrquestador()
    repositorio_sesiones = RepositorioSesionesMemoria()
    app = modulo.crear_router(
        orquestador, repositorio_sesiones,
        obtener_promo_bar=FakeObtenerPromoBar(
            PromoBar(activo=True, contenido_html='<p>Oferta con <a href="/x">enlace</a></p>')
        ),
    )
    client = TestClient(app)

    respuesta = client.get("/promobar")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["activo"] is True
    # <p> no está en la lista blanca de saneado, pero su contenido y el
    # <a href> sí se conservan.
    assert cuerpo["contenido_html"] == 'Oferta con <a href="/x">enlace</a>'


def test_promobar_elimina_etiquetas_peligrosas(modulo):
    from domain.entities import PromoBar

    orquestador = FakeOrquestador()
    repositorio_sesiones = RepositorioSesionesMemoria()
    app = modulo.crear_router(
        orquestador, repositorio_sesiones,
        obtener_promo_bar=FakeObtenerPromoBar(
            PromoBar(activo=True, contenido_html='<script>alert(1)</script><strong>2x1</strong>')
        ),
    )
    client = TestClient(app)

    respuesta = client.get("/promobar")

    cuerpo = respuesta.json()
    # bleach quita la etiqueta <script> pero no su texto interior (queda
    # como texto inerte, no ejecutable) — lo que importa es que la
    # etiqueta en sí desaparezca, no el texto plano que dejara dentro.
    assert "<script>" not in cuerpo["contenido_html"]
    assert "<strong>2x1</strong>" in cuerpo["contenido_html"]


def test_promobar_elimina_protocolo_javascript_en_enlaces(modulo):
    from domain.entities import PromoBar

    orquestador = FakeOrquestador()
    repositorio_sesiones = RepositorioSesionesMemoria()
    app = modulo.crear_router(
        orquestador, repositorio_sesiones,
        obtener_promo_bar=FakeObtenerPromoBar(
            PromoBar(activo=True, contenido_html='<a href="javascript:alert(1)">click</a>')
        ),
    )
    client = TestClient(app)

    respuesta = client.get("/promobar")

    cuerpo = respuesta.json()
    assert "javascript:" not in cuerpo["contenido_html"]
