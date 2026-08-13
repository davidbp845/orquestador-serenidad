"""
Adaptador de entrada: expone el orquestador de agentes vía HTTP para
el chat de la web. No contiene lógica de negocio, solo traduce
HTTP <-> orquestador.
"""
from __future__ import annotations

import json
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from adapters.out.promobar_html import sanear_html_promobar
from application.orchestrator import OrquestadorAgente, SesionConversacion
from application.ports import RepositorioSesiones
from domain.use_cases import ListarTestimoniosRecientes, ObtenerPromoBar

from .rate_limit import (
    LIMITE_PETICIONES_DEFECTO,
    VENTANA_SEGUNDOS_DEFECTO,
    LimitadorPeticiones,
    LimitadorPeticionesMemoria,
)

app = FastAPI(title="Orquestador agéntico — chat web")

# Orígenes de dev habituales (Vite, alternativa común en 3000; 4321 es
# el puerto por defecto de Astro) para que un frontend en desarrollo
# pueda llamar al backend sin bloqueo CORS. En producción, CORS_ORIGINS
# (lista separada por comas) los sustituye por el/los dominio(s) real(es)
# — mismo patrón "opcional, degrada al comportamiento de hoy" que
# DATABASE_URL/GOOGLE_CALENDAR_*.
_CORS_ORIGINS_DEV = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://localhost:4321",
]
_cors_origins_env = os.environ.get("CORS_ORIGINS", "")
_cors_origins = (
    [origen.strip() for origen in _cors_origins_env.split(",") if origen.strip()]
    if _cors_origins_env
    else _CORS_ORIGINS_DEV
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class MensajeEntrante(BaseModel):
    usuario_id: str
    mensaje: str


class RespuestaAgente(BaseModel):
    respuesta: str


class TestimonioSalida(BaseModel):
    id: int
    nombre: str
    titulo: str
    descripcion: str
    valoracion: int


class PromoBarSalida(BaseModel):
    activo: bool
    contenido_html: str


def crear_router(
    orquestador: OrquestadorAgente,
    repositorio_sesiones: RepositorioSesiones,
    limitador: LimitadorPeticiones | None = None,
    limite_peticiones: int = LIMITE_PETICIONES_DEFECTO,
    ventana_segundos: int = VENTANA_SEGUNDOS_DEFECTO,
    listar_testimonios_recientes: ListarTestimoniosRecientes | None = None,
    obtener_promo_bar: ObtenerPromoBar | None = None,
) -> FastAPI:
    limitador = limitador or LimitadorPeticionesMemoria()

    def _obtener_sesion(usuario_id: str) -> SesionConversacion:
        return repositorio_sesiones.obtener("web", usuario_id) or SesionConversacion(
            canal="web", usuario_id=usuario_id
        )

    def _comprobar_limite(usuario_id: str) -> None:
        # Por usuario_id, no por IP (#49): es el mismo identificador que ya
        # separa sesiones, más significativo que una IP que puede
        # compartirse entre varios clientes reales detrás de un NAT/proxy.
        if not limitador.permitir(usuario_id, limite_peticiones, ventana_segundos):
            raise HTTPException(
                status_code=429,
                detail="Demasiadas peticiones, espera un momento antes de volver a escribir.",
            )

    @app.post("/chat", response_model=RespuestaAgente)
    def chat(payload: MensajeEntrante):
        _comprobar_limite(payload.usuario_id)
        sesion = _obtener_sesion(payload.usuario_id)
        respuesta = orquestador.responder(sesion, payload.mensaje)
        repositorio_sesiones.guardar(sesion)
        return RespuestaAgente(respuesta=respuesta)

    @app.post("/chat/stream")
    def chat_stream(payload: MensajeEntrante):
        _comprobar_limite(payload.usuario_id)
        sesion = _obtener_sesion(payload.usuario_id)

        def eventos_sse():
            try:
                for evento in orquestador.responder_stream(sesion, payload.mensaje):
                    if evento["tipo"] == "delta":
                        yield f"event: delta\ndata: {json.dumps({'texto': evento['texto']})}\n\n"
                    elif evento["tipo"] == "done":
                        yield f"event: fuentes\ndata: {json.dumps({'fuentes': evento['fuentes']})}\n\n"
                        yield f"event: done\ndata: {json.dumps({'respuesta': evento['respuesta']})}\n\n"
            except Exception as exc:  # noqa: BLE001 — un fallo se convierte en un evento, no en una conexión cortada
                yield f"event: error\ndata: {json.dumps({'mensaje': str(exc)})}\n\n"
            finally:
                repositorio_sesiones.guardar(sesion)

        return StreamingResponse(
            eventos_sse(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/testimonios", response_model=list[TestimonioSalida])
    def testimonios():
        if listar_testimonios_recientes is None:
            return []
        return [
            TestimonioSalida(
                id=t.id, nombre=t.nombre, titulo=t.titulo,
                descripcion=t.descripcion, valoracion=t.valoracion,
            )
            for t in listar_testimonios_recientes.ejecutar()
        ]

    @app.get("/promobar", response_model=PromoBarSalida)
    def promobar():
        promo_bar = obtener_promo_bar.ejecutar() if obtener_promo_bar else None
        if promo_bar is None:
            return PromoBarSalida(activo=False, contenido_html="")
        return PromoBarSalida(
            activo=True, contenido_html=sanear_html_promobar(promo_bar.contenido_html),
        )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app
