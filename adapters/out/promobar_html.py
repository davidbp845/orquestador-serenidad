"""Saneado del HTML libre del promobar (`PromoBar.contenido_html`,
escrito desde el panel interno) antes de mostrarlo a nadie — al
visitante público (`GET /promobar` en `adapters/in_/fastapi_app.py`)
o en la previsualización del propio panel (`panel_empleados/`). Vive
aquí, sin depender de FastAPI, precisamente para que ambos lo
reutilicen sin duplicar la lista blanca ni arriesgarse a que se
desincronicen."""
from __future__ import annotations

import bleach

# El contenido del promobar lo escribe quien tenga acceso al panel
# (formulario de HTML libre, issue #78) pero se sirve tal cual a
# cualquier visitante público de la web — nunca se puede devolver sin
# pasar por esta lista blanca. strip=True (en vez de escapar) para que
# una etiqueta no permitida desaparezca en vez de mostrarse como texto
# literal roto; sin atributo "target" ni "rel" en <a>, deliberadamente,
# para no tener que razonar sobre reverse tabnabbing.
PROMOBAR_TAGS_PERMITIDAS = ["a", "strong", "em", "b", "i", "s", "br", "span"]
PROMOBAR_ATRIBUTOS_PERMITIDOS = {"a": ["href"]}
PROMOBAR_PROTOCOLOS_PERMITIDOS = ["http", "https"]


def sanear_html_promobar(html: str) -> str:
    return bleach.clean(
        html,
        tags=PROMOBAR_TAGS_PERMITIDAS,
        attributes=PROMOBAR_ATRIBUTOS_PERMITIDOS,
        protocols=PROMOBAR_PROTOCOLOS_PERMITIDOS,
        strip=True,
    )
