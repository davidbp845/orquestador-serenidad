from datetime import time
from textwrap import dedent

import pytest

from config.loader import (
    _parse_hora,
    cargar_config,
    construir_profesionales,
    construir_servicios,
)


def test_parse_hora():
    assert _parse_hora("09:00") == time(9, 0)
    assert _parse_hora("18:30") == time(18, 30)


def test_cargar_config_lee_yaml(tmp_path):
    ruta = tmp_path / "business.yaml"
    ruta.write_text(dedent("""
        nombre: "Negocio de prueba"
        tono: "cercano"
        servicios: []
        profesionales: []
    """))

    config = cargar_config(str(ruta))

    assert config["nombre"] == "Negocio de prueba"
    assert config["tono"] == "cercano"


def test_cargar_config_aplica_valores_por_defecto_a_los_campos_opcionales(tmp_path):
    ruta = tmp_path / "business.yaml"
    ruta.write_text(dedent("""
        nombre: "Negocio de prueba"
    """))

    config = cargar_config(str(ruta))

    assert config["vault_obsidian"] == "./vault_negocio"
    assert config["canales"] == {"web": False, "telegram": False, "whatsapp": False}
    assert config["servicios"] == []
    assert config["profesionales"] == []
    assert config["direccion"] is None
    assert config["telefono"] is None
    assert config["email"] is None
    assert config["horario_apertura"] == {}
    assert config["tema"] == {
        "color_fondo": None,
        "color_superficie": None,
        "color_texto": None,
        "color_texto_suave": None,
        "color_borde": None,
        "color_acento": None,
        "color_acento_suave": None,
        "fuente_titulo_url": None,
        "fuente_cuerpo_url": None,
    }


def test_cargar_config_tema(tmp_path):
    ruta = tmp_path / "business.yaml"
    ruta.write_text(dedent("""
        nombre: "Negocio de prueba"
        tema:
          color_acento: "#123456"
          color_fondo: "#fafafa"
          fuente_titulo_url: "/fonts/titulo.woff2"
          fuente_cuerpo_url: "/fonts/cuerpo.woff2"
    """))

    config = cargar_config(str(ruta))

    assert config["tema"]["color_acento"] == "#123456"
    assert config["tema"]["color_fondo"] == "#fafafa"
    assert config["tema"]["color_texto"] is None
    assert config["tema"]["fuente_titulo_url"] == "/fonts/titulo.woff2"
    assert config["tema"]["fuente_cuerpo_url"] == "/fonts/cuerpo.woff2"


def test_cargar_config_direccion_telefono_email_horario_apertura(tmp_path):
    ruta = tmp_path / "business.yaml"
    ruta.write_text(dedent("""
        nombre: "Negocio de prueba"
        direccion:
          calle: "Calle Falsa, 123"
          localidad: "Springfield"
          codigo_postal: "00000"
        telefono: "+34600000000"
        email: "hola@negocio.example"
        horario_apertura:
          lunes: ["09:00", "18:00"]
    """))

    config = cargar_config(str(ruta))

    assert config["direccion"] == {
        "calle": "Calle Falsa, 123",
        "localidad": "Springfield",
        "codigo_postal": "00000",
        "pais": "ES",
    }
    assert config["telefono"] == "+34600000000"
    assert config["email"] == "hola@negocio.example"
    assert config["horario_apertura"] == {"lunes": ["09:00", "18:00"]}


def test_cargar_config_horario_apertura_mal_formado_lanza_error_claro(tmp_path):
    ruta = tmp_path / "business.yaml"
    ruta.write_text(dedent("""
        nombre: "Negocio de prueba"
        horario_apertura:
          lunes: ["9am", "18:00"]
    """))

    with pytest.raises(ValueError, match="horario_apertura.lunes"):
        cargar_config(str(ruta))


def test_cargar_config_sin_nombre_lanza_error_claro(tmp_path):
    ruta = tmp_path / "business.yaml"
    ruta.write_text(dedent("""
        tono: "cercano"
    """))

    with pytest.raises(ValueError, match="nombre"):
        cargar_config(str(ruta))


def test_cargar_config_servicio_con_campo_que_falta_lanza_error_claro(tmp_path):
    ruta = tmp_path / "business.yaml"
    ruta.write_text(dedent("""
        nombre: "Negocio de prueba"
        servicios:
          - id: "s1"
            nombre: "Masaje"
            duracion_minutos: 60
            # falta "precio" (p. ej. un typo como "precios")
    """))

    with pytest.raises(ValueError, match="servicios.0.precio"):
        cargar_config(str(ruta))


def test_cargar_config_horario_mal_formado_lanza_error_claro(tmp_path):
    ruta = tmp_path / "business.yaml"
    ruta.write_text(dedent("""
        nombre: "Negocio de prueba"
        profesionales:
          - id: "ana"
            nombre: "Ana"
            horario_semanal:
              lunes: ["9am", "18:00"]
    """))

    with pytest.raises(ValueError, match="horario_semanal.lunes"):
        cargar_config(str(ruta))


def test_construir_servicios():
    config = {
        "servicios": [
            {"id": "s1", "nombre": "Masaje", "duracion_minutos": 60, "precio": 55.0},
        ]
    }
    servicios = construir_servicios(config)

    assert len(servicios) == 1
    assert servicios[0].id == "s1"
    assert servicios[0].duracion_minutos == 60
    assert servicios[0].precio == 55.0


def test_construir_servicios_config_vacia():
    assert construir_servicios({}) == []


def test_construir_profesionales():
    config = {
        "profesionales": [
            {
                "id": "ana",
                "nombre": "Ana García",
                "servicios_ids": ["s1"],
                "horario_semanal": {"lunes": ["09:00", "18:00"]},
            }
        ]
    }
    profesionales = construir_profesionales(config)

    assert len(profesionales) == 1
    ana = profesionales[0]
    assert ana.id == "ana"
    assert ana.servicios_ids == ["s1"]
    assert ana.horario_semanal["lunes"] == (time(9, 0), time(18, 0))


def test_construir_profesionales_config_vacia():
    assert construir_profesionales({}) == []


def test_carga_config_negocio_real():
    """El config/business.yaml del repo debe seguir siendo válido y
    cargable, con los servicios y profesionales que la documentación
    (vault_negocio) da por hechos."""
    config = cargar_config("config/business.yaml")

    servicios = construir_servicios(config)
    profesionales = construir_profesionales(config)

    ids_servicios = {s.id for s in servicios}
    assert "masaje_relajante_60" in ids_servicios
    assert "masaje_descontracturante_45" in ids_servicios
    assert any(p.id == "ana" for p in profesionales)
    assert config["direccion"]["localidad"] == "Madrid"
    assert config["telefono"]
    assert config["horario_apertura"]["lunes"] == ["09:00", "18:00"]
