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
        for dia, rango in valor.items():
            if len(rango) != 2 or not all(_PATRON_HORA.match(h) for h in rango):
                raise ValueError(
                    f'horario_semanal.{dia} debe ser ["HH:MM", "HH:MM"], se recibió {rango!r}'
                )
        return valor


class CanalesConfig(BaseModel):
    web: bool = False
    telegram: bool = False
    whatsapp: bool = False


class ConfigNegocio(BaseModel):
    nombre: str
    tono: str = "cercano y profesional"
    instrucciones_extra: str = ""
    instrucciones_comerciales: str = ""
    vault_obsidian: str = "./vault_negocio"
    logo_url: str | None = None
    hero_titulo: str | None = None
    hero_subtitulo: str = "Escríbenos y te ayudamos al momento."
    imagen_fondo_url: str | None = None
    canales: CanalesConfig = Field(default_factory=CanalesConfig)
    servicios: list[ServicioConfig] = Field(default_factory=list)
    profesionales: list[ProfesionalConfig] = Field(default_factory=list)
