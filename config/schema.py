"""Schema de validación de config/business.yaml. Sin esto, un typo o
un campo que falte en el YAML solo se descubre cuando algún caso de
uso lo intenta leer, con un KeyError críptico y sin decir en qué
servicio/profesional ni qué campo está el problema. cargar_config()
valida contra este schema antes de devolver la config, así que el
fallo (si lo hay) es inmediato y señala exactamente qué está mal."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

_PATRON_HORA = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _validar_horario_dict(valor: dict[str, list[str]], campo: str) -> dict[str, list[str]]:
    for dia, rango in valor.items():
        if len(rango) != 2 or not all(_PATRON_HORA.match(h) for h in rango):
            raise ValueError(f'{campo}.{dia} debe ser ["HH:MM", "HH:MM"], se recibió {rango!r}')
    return valor


class ServicioConfig(BaseModel):
    id: str
    nombre: str
    duracion_minutos: int = Field(gt=0)
    precio: float = Field(ge=0)


class ProfesionalConfig(BaseModel):
    id: str
    nombre: str
    servicios_ids: list[str] = Field(default_factory=list)
    horario_semanal: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("horario_semanal")
    @classmethod
    def _validar_horario(cls, valor: dict[str, list[str]]) -> dict[str, list[str]]:
        return _validar_horario_dict(valor, "horario_semanal")


class DireccionConfig(BaseModel):
    """Para el JSON-LD de SEO (schema.org PostalAddress) en
    frontend/src/components/DatosEstructurados.astro — antes esto
    estaba transcrito a mano en ese componente (#75)."""
    calle: str
    localidad: str
    codigo_postal: str
    pais: str = "ES"


class CanalesConfig(BaseModel):
    web: bool = False
    telegram: bool = False
    whatsapp: bool = False


class CtaCitaConfig(BaseModel):
    """Botón CTA de la cabecera (frontend/src/components/Cabecera.astro)
    que escribe un mensaje predefinido en el chat — ver issue #56.
    texto_corto/texto_largo son la etiqueta visible del botón (según
    hueco disponible); mensaje es el texto literal que se envía al
    chat al pulsarlo, independiente de la etiqueta."""
    texto_corto: str = "Pedir cita"
    texto_largo: str = "Reservar una cita"
    mensaje: str = "Quiero reservar una cita"


class ConfigNegocio(BaseModel):
    nombre: str
    tono: str = "cercano y profesional"
    instrucciones_extra: str = ""
    instrucciones_comerciales: str = ""
    vault_obsidian: str = "./vault_negocio"
    logo_url: str | None = None
    # Variante compacta (solo icono, sin texto) mostrada en móvil cuando
    # el logo principal (logo_url) es demasiado ancho para el hueco —
    # ver frontend/src/components/Cabecera.astro. Opcional: sin este
    # campo, la cabecera usa logo_url en todos los tamaños.
    logo_compacto_url: str | None = None
    hero_titulo: str | None = None
    hero_subtitulo: str = "Escríbenos y te ayudamos al momento."
    imagen_fondo_url: str | None = None
    cta_cita: CtaCitaConfig = Field(default_factory=CtaCitaConfig)
    canales: CanalesConfig = Field(default_factory=CanalesConfig)
    servicios: list[ServicioConfig] = Field(default_factory=list)
    profesionales: list[ProfesionalConfig] = Field(default_factory=list)
    # Para el JSON-LD de SEO (DatosEstructurados.astro, #75) — todo
    # opcional: un negocio puede no querer exponer estos datos.
    direccion: DireccionConfig | None = None
    telefono: str | None = None
    email: str | None = None
    # Horario de apertura del negocio (para SEO), distinto de
    # horario_semanal por profesional: mismas claves de día
    # (lunes..domingo) y mismo formato ["HH:MM", "HH:MM"].
    horario_apertura: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("horario_apertura")
    @classmethod
    def _validar_horario_apertura(cls, valor: dict[str, list[str]]) -> dict[str, list[str]]:
        return _validar_horario_dict(valor, "horario_apertura")
