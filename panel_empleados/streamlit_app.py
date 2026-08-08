"""
Panel interno para empleados/propietario del negocio: agenda del día,
gestión de pedidos pendientes y reindexado del RAG. Consume los casos
de uso de domain/ directamente, sin pasar por el orquestador ni por
ningún LLM — igual que hacen los adaptadores de entrada con
OrquestadorAgente, pero aquí la "entrada" es la propia interfaz de
Streamlit.

Uso:
    streamlit run panel_empleados/streamlit_app.py
"""
from __future__ import annotations

import os
import secrets
import sys
from datetime import date, timedelta
from pathlib import Path

# `streamlit run` pone en sys.path el directorio de este script
# (panel_empleados/), no la raíz del repo — a diferencia de main.py
# (ya en la raíz) o de los tests (root conftest.py lo hace por ellos),
# así que hay que añadirla a mano para poder importar domain/application/
# adapters/config sin instalar el proyecto como paquete.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from dotenv import load_dotenv

from adapters.out.obsidian_ingest import procesar_vault
from adapters.out.repositorios_memoria import (
    RepositorioCitasMemoria,
    RepositorioPedidosMemoria,
    RepositorioProfesionalesMemoria,
    RepositorioServiciosMemoria,
)
from adapters.out.vector_store import RepositorioConocimientoChroma
from config.loader import cargar_config, construir_profesionales, construir_servicios
from domain.entities import EstadoPedido
from domain.exceptions import TransicionEstadoInvalida
from domain.use_cases import _DIAS_SEMANA_ES, CambiarEstadoPedido

load_dotenv()

st.set_page_config(page_title="Panel interno", page_icon="📋", layout="centered")


@st.cache_resource
def _construir_repos():
    """Cacheado a nivel de proceso: Streamlit re-ejecuta todo el script
    en cada interacción, así que sin cache los repos en memoria (sin
    DATABASE_URL) perderían las citas/pedidos en cada clic."""
    config = cargar_config("config/business.yaml")
    repo_servicios = RepositorioServiciosMemoria(construir_servicios(config))
    repo_profesionales = RepositorioProfesionalesMemoria(construir_profesionales(config))

    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        from adapters.out.repositorios_postgres import (
            RepositorioCitasPostgres,
            RepositorioPedidosPostgres,
            crear_engine,
        )
        engine = crear_engine(database_url)
        repo_citas = RepositorioCitasPostgres(engine)
        repo_pedidos = RepositorioPedidosPostgres(engine)
    else:
        repo_citas = RepositorioCitasMemoria()
        repo_pedidos = RepositorioPedidosMemoria()

    return config, repo_servicios, repo_profesionales, repo_citas, repo_pedidos


@st.cache_resource
def _construir_conocimiento() -> RepositorioConocimientoChroma:
    return RepositorioConocimientoChroma()


def _mes_relativo(d: date, delta: int) -> date:
    """Primer día del mes `delta` meses antes/después del de `d`
    (delta negativo = hacia atrás). Evita sumar '±30 días', que
    desfasa entre meses de distinta longitud."""
    mes_index = d.month - 1 + delta
    anio = d.year + mes_index // 12
    mes = mes_index % 12 + 1
    return date(anio, mes, 1)


def _rango_agenda(ancla: date, vista: str) -> tuple[date, date]:
    if vista == "Semana":
        inicio_semana = ancla - timedelta(days=ancla.weekday())
        return inicio_semana, inicio_semana + timedelta(days=6)
    if vista == "Mes":
        primer_dia = ancla.replace(day=1)
        return primer_dia, _mes_relativo(primer_dia, 1) - timedelta(days=1)
    return ancla, ancla  # Día


def _desplazar_ancla(ancla: date, vista: str, direccion: int) -> date:
    if vista == "Semana":
        return ancla + timedelta(days=7 * direccion)
    if vista == "Mes":
        return _mes_relativo(ancla, direccion)
    return ancla + timedelta(days=direccion)  # Día


def _tarjeta_cita(cita, repo_servicios, repo_profesionales) -> None:
    servicio = repo_servicios.obtener(cita.servicio_id)
    profesional = repo_profesionales.obtener(cita.profesional_id)
    with st.container(border=True):
        st.markdown(f"**{cita.inicio:%H:%M} – {cita.fin:%H:%M}**")
        st.write(f"{servicio.nombre if servicio else cita.servicio_id} · "
                 f"{profesional.nombre if profesional else cita.profesional_id}")
        st.caption(f"Cliente: {cita.cliente_id} · Estado: {cita.estado.value}")


# ---------- Gate de acceso mínimo ----------
# Sin PANEL_EMPLEADOS_PASSWORD, el panel se abre directamente (cómodo
# para desarrollo local); con ella, hay que introducirla una vez por
# sesión de Streamlit. No es un sistema de usuarios/roles — identidad
# por persona queda fuera de alcance de este panel.
_clave_panel = os.environ.get("PANEL_EMPLEADOS_PASSWORD")
if _clave_panel and not st.session_state.get("autenticado"):
    st.title("🔒 Acceso al panel")
    # st.form en vez de un text_input + button sueltos: sin form, el
    # navegador puede mandar el clic del botón antes de confirmar el
    # último cambio del campo de texto, así que a veces se compara
    # contra un valor desactualizado. El form sincroniza campo y envío
    # en un único evento atómico, y de paso permite enviar con Enter.
    with st.form("form_acceso"):
        intento = st.text_input("Contraseña", type="password")
        entrar = st.form_submit_button("Entrar")
    if entrar:
        if secrets.compare_digest(intento, _clave_panel):
            st.session_state["autenticado"] = True
            st.rerun()
        else:
            st.error("Contraseña incorrecta")
    st.stop()

config, repo_servicios, repo_profesionales, repo_citas, repo_pedidos = _construir_repos()
cambiar_estado_pedido = CambiarEstadoPedido(repo_pedidos)

# ---------- Cabecera ----------
_hoy = date.today()
st.title(config["nombre"])
# _DIAS_SEMANA_ES en vez de strftime('%A'): esto último depende del
# locale del sistema operativo, no siempre da nombres en español.
st.caption(f"{_DIAS_SEMANA_ES[_hoy.weekday()].capitalize()}, {_hoy:%d/%m/%Y}")

# ---------- Menú (sidebar: colapsado automáticamente en móvil) ----------
with st.sidebar:
    opcion = st.radio("Menú", ["📅 Agenda", "📦 Pedidos", "⚙️ Ajustes"])

# ---------- Agenda ----------
if opcion == "📅 Agenda":
    if "agenda_ancla" not in st.session_state:
        st.session_state["agenda_ancla"] = date.today()  # arranca en hoy

    vista = st.radio("Vista", ["Día", "Semana", "Mes"], horizontal=True, key="agenda_vista")

    col_ant, col_hoy, col_sig = st.columns(3)
    if col_ant.button("◀ Anterior", use_container_width=True):
        st.session_state["agenda_ancla"] = _desplazar_ancla(st.session_state["agenda_ancla"], vista, -1)
        st.rerun()
    if col_hoy.button("Hoy", use_container_width=True):
        st.session_state["agenda_ancla"] = date.today()
        st.rerun()
    if col_sig.button("Siguiente ▶", use_container_width=True):
        st.session_state["agenda_ancla"] = _desplazar_ancla(st.session_state["agenda_ancla"], vista, 1)
        st.rerun()

    ancla = st.session_state["agenda_ancla"]
    desde, hasta = _rango_agenda(ancla, vista)

    if vista == "Día":
        st.caption(f"{_DIAS_SEMANA_ES[ancla.weekday()].capitalize()}, {ancla:%d/%m/%Y}")
    else:
        st.caption(f"{desde:%d/%m/%Y} – {hasta:%d/%m/%Y}")

    citas = sorted(repo_citas.citas_en_rango(desde, hasta), key=lambda c: c.inicio)

    if not citas:
        st.info("Sin citas en este periodo.")

    if vista == "Día":
        for cita in citas:
            _tarjeta_cita(cita, repo_servicios, repo_profesionales)
    else:
        # Agrupadas por día (subcabecera), no una lista plana — sigue
        # siendo tarjetas apiladas, legible en móvil.
        citas_por_dia: dict[date, list] = {}
        for cita in citas:
            citas_por_dia.setdefault(cita.inicio.date(), []).append(cita)
        for dia_grupo in sorted(citas_por_dia):
            st.markdown(f"**{_DIAS_SEMANA_ES[dia_grupo.weekday()].capitalize()} {dia_grupo:%d/%m}**")
            for cita in citas_por_dia[dia_grupo]:
                _tarjeta_cita(cita, repo_servicios, repo_profesionales)

# ---------- Pedidos pendientes ----------
elif opcion == "📦 Pedidos":
    pedidos = sorted(repo_pedidos.listar_pendientes(), key=lambda p: p.creado_en)

    if not pedidos:
        st.info("No hay pedidos pendientes.")

    for pedido in pedidos:
        with st.container(border=True):
            st.markdown(f"**Pedido {str(pedido.id)[:8]}** · Cliente: {pedido.cliente_id}")
            for linea in pedido.lineas:
                servicio = repo_servicios.obtener(linea.servicio_id)
                nombre = servicio.nombre if servicio else linea.servicio_id
                sufijo = f" ({linea.notas})" if linea.notas else ""
                st.write(f"- {linea.cantidad}× {nombre}{sufijo}")
            st.caption(f"Estado actual: {pedido.estado.value}")

            opciones_estado = [e for e in EstadoPedido if e != pedido.estado]
            nuevo_estado = st.selectbox(
                "Cambiar a", opciones_estado,
                format_func=lambda e: e.value,
                key=f"estado_{pedido.id}",
            )
            if st.button("Actualizar", key=f"btn_{pedido.id}"):
                try:
                    cambiar_estado_pedido.ejecutar(pedido.id, nuevo_estado)
                    st.rerun()
                except TransicionEstadoInvalida as exc:
                    st.error(str(exc))

# ---------- Ajustes ----------
else:
    st.subheader("Base de conocimiento (RAG)")
    st.write("Reindexa el vault de Obsidian tras editar precios, horarios u otro contenido.")
    if st.button("Reindexar conocimiento"):
        with st.spinner("Reindexando..."):
            try:
                fragmentos = procesar_vault(config["vault_obsidian"])
                _construir_conocimiento().indexar_fragmentos(fragmentos)
                st.success(f"Reindexados {len(fragmentos)} fragmentos.")
            except Exception as exc:
                st.error(f"Error al reindexar: {exc}")
