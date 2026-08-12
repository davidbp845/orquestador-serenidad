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
import urllib.parse
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

from adapters.in_.rate_limit import (
    LIMITE_PETICIONES_DEFECTO,
    VENTANA_SEGUNDOS_DEFECTO,
    LimitadorPeticionesRedis,
)
from adapters.out.obsidian_ingest import procesar_vault
from adapters.out.repositorios_memoria import (
    RepositorioCitasMemoria,
    RepositorioClientesMemoria,
    RepositorioContadoresMemoria,
    RepositorioPedidosMemoria,
    RepositorioProfesionalesMemoria,
    RepositorioServiciosMemoria,
    RepositorioTestimoniosMemoria,
)
from adapters.out.vector_store import RepositorioConocimientoChroma
from config.loader import cargar_config, construir_profesionales, construir_servicios
from domain.entities import EstadoPedido
from domain.exceptions import ClienteYaExiste, TransicionEstadoInvalida, ValoracionInvalida
from domain.use_cases import (
    _DIAS_SEMANA_ES,
    _TRANSICIONES_CITA_VALIDAS,
    CambiarEstadoCita,
    CambiarEstadoPedido,
    CrearCliente,
    CrearTestimonio,
    DetectarClientesDuplicados,
    EditarCliente,
    EditarTestimonio,
    EliminarCliente,
    EliminarTestimonio,
    FusionarClientes,
    _clave_orden_fusion,
)

load_dotenv()

st.set_page_config(page_title="Panel interno", page_icon="📋", layout="centered")


@st.cache_resource
def _construir_repos():
    """Cacheado a nivel de proceso: Streamlit re-ejecuta todo el script
    en cada interacción, así que sin cache los repos en memoria (sin
    DATABASE_URL) perderían las citas/pedidos en cada clic."""
    config = cargar_config(os.environ.get("CONFIG_PATH", "config/business.yaml"))
    repo_servicios = RepositorioServiciosMemoria(construir_servicios(config))
    repo_profesionales = RepositorioProfesionalesMemoria(construir_profesionales(config))

    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        from adapters.out.repositorios_postgres import (
            RepositorioCitasPostgres,
            RepositorioClientesPostgres,
            RepositorioContadoresPostgres,
            RepositorioPedidosPostgres,
            RepositorioTestimoniosPostgres,
            crear_engine,
        )
        engine = crear_engine(database_url)
        repo_citas = RepositorioCitasPostgres(engine)
        repo_clientes = RepositorioClientesPostgres(engine)
        repo_pedidos = RepositorioPedidosPostgres(engine)
        repo_testimonios = RepositorioTestimoniosPostgres(engine)
        repo_contadores = RepositorioContadoresPostgres(engine)
    else:
        repo_citas = RepositorioCitasMemoria()
        repo_clientes = RepositorioClientesMemoria()
        repo_pedidos = RepositorioPedidosMemoria()
        repo_testimonios = RepositorioTestimoniosMemoria()
        repo_contadores = RepositorioContadoresMemoria()

    return (
        config, repo_servicios, repo_profesionales, repo_citas, repo_clientes, repo_pedidos,
        repo_testimonios, repo_contadores,
    )


@st.cache_resource
def _construir_conocimiento() -> RepositorioConocimientoChroma:
    return RepositorioConocimientoChroma()


@st.cache_resource
def _construir_limitador_consumo() -> LimitadorPeticionesRedis | None:
    # A diferencia de los otros _construir_*, no hay alternativa en
    # memoria aquí (#50): el panel es un proceso distinto a main.py,
    # sin memoria compartida, así que un LimitadorPeticionesMemoria
    # propio del panel siempre estaría vacío — nunca reflejaría el
    # consumo real del backend. Sin REDIS_URL, esta sección no tiene
    # nada real que mostrar.
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        return None
    return LimitadorPeticionesRedis(redis_url)


@st.cache_resource
def _construir_notificador():
    # Mismo condicional "opcional, sin ella no se notifica nada" que ya
    # usa main.py::construir_sistema() — el panel no tenía hasta ahora
    # ningún NotificadorMensajes propio.
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return None
    from adapters.out.notificador_telegram import NotificadorMensajesTelegram
    return NotificadorMensajesTelegram(token)


@st.cache_resource
def _construir_calendario():
    # Mismo condicional que main.py:104-113 — solo lo usa la
    # herramienta de borrado de datos (sección Herramientas) para
    # cancelar los eventos espejo antes de vaciar las citas.
    credenciales = os.environ.get("GOOGLE_CALENDAR_CREDENTIALS_JSON")
    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID")
    if not (credenciales and calendar_id):
        return None
    from adapters.out.calendario_google import SincronizadorCalendarioGoogle
    zona_horaria = os.environ.get("GOOGLE_CALENDAR_TIMEZONE", "Europe/Madrid")
    return SincronizadorCalendarioGoogle(credenciales, calendar_id, zona_horaria)


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


def _tarjeta_cita(cita, repo_servicios, repo_profesionales, repo_clientes, cambiar_estado_cita) -> None:
    servicio = repo_servicios.obtener(cita.servicio_id)
    profesional = repo_profesionales.obtener(cita.profesional_id)
    cliente = repo_clientes.obtener(cita.cliente_id)
    with st.container(border=True):
        st.markdown(f"**{cita.inicio:%H:%M} – {cita.fin:%H:%M}** · `{cita.id_visible}`")
        st.write(f"{servicio.nombre if servicio else cita.servicio_id} · "
                 f"{profesional.nombre if profesional else cita.profesional_id}")
        nombre_cliente = cliente.nombre if cliente else cita.cliente_id
        st.caption(f"Cliente: {nombre_cliente} ({cita.cliente_id}) · Estado: {cita.estado.value}")

        # Solo confirmar/en curso/finalizar/no-show: cancelar sigue su
        # propio camino (CancelarReserva), no pasa por aquí — por eso no
        # aparece como opción, en vez de ofrecerla y que falle siempre.
        opciones_estado = sorted(_TRANSICIONES_CITA_VALIDAS[cita.estado], key=lambda e: e.value)
        if opciones_estado:
            nuevo_estado = st.selectbox(
                "Cambiar a", opciones_estado,
                format_func=lambda e: e.value,
                key=f"estado_cita_{cita.id}",
            )
            if st.button("Actualizar", key=f"btn_cita_{cita.id}"):
                try:
                    cambiar_estado_cita.ejecutar(cita.id, nuevo_estado)
                    st.rerun()
                except TransicionEstadoInvalida as exc:
                    st.error(str(exc))


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

(
    config, repo_servicios, repo_profesionales, repo_citas, repo_clientes, repo_pedidos,
    repo_testimonios, repo_contadores,
) = _construir_repos()
notificador = _construir_notificador()
cambiar_estado_pedido = CambiarEstadoPedido(repo_pedidos)
cambiar_estado_cita = CambiarEstadoCita(repo_citas, repo_clientes, notificador)
crear_testimonio = CrearTestimonio(repo_testimonios, repo_contadores)
editar_testimonio = EditarTestimonio(repo_testimonios)
eliminar_testimonio = EliminarTestimonio(repo_testimonios)
crear_cliente = CrearCliente(repo_clientes, repo_contadores)
editar_cliente = EditarCliente(repo_clientes)
eliminar_cliente = EliminarCliente(repo_clientes)
detectar_clientes_duplicados = DetectarClientesDuplicados(repo_clientes)
fusionar_clientes = FusionarClientes(repo_clientes, repo_citas, repo_pedidos)

# ---------- Cabecera ----------
_hoy = date.today()
st.title(config["nombre"])
# _DIAS_SEMANA_ES en vez de strftime('%A'): esto último depende del
# locale del sistema operativo, no siempre da nombres en español.
st.caption(f"{_DIAS_SEMANA_ES[_hoy.weekday()].capitalize()}, {_hoy:%d/%m/%Y}")

# ---------- Menú (sidebar: colapsado automáticamente en móvil) ----------
with st.sidebar:
    opcion = st.radio(
        "Menú",
        [
            "📅 Agenda", "📦 Pedidos", "👤 Clientes", "⭐ Testimonios",
            "🔢 Contadores", "🚦 Rate limiting", "🛠️ Herramientas",
        ],
    )

# ---------- Agenda ----------
if opcion == "📅 Agenda":
    # Solo si hay un calendario configurado (GOOGLE_CALENDAR_ID) — sin
    # sincronización activa no hay nada que enlazar. No hace falta
    # GOOGLE_CALENDAR_CREDENTIALS_JSON aquí: el enlace solo abre la
    # interfaz web de Google Calendar, no llama a la API.
    _calendar_id = os.environ.get("GOOGLE_CALENDAR_ID")
    if _calendar_id:
        _url_calendario = f"https://calendar.google.com/calendar/u/0/r?cid={urllib.parse.quote(_calendar_id)}"
        st.link_button("Acceder al Calendario", _url_calendario)

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
            _tarjeta_cita(cita, repo_servicios, repo_profesionales, repo_clientes, cambiar_estado_cita)
    else:
        # Agrupadas por día (subcabecera), no una lista plana — sigue
        # siendo tarjetas apiladas, legible en móvil.
        citas_por_dia: dict[date, list] = {}
        for cita in citas:
            citas_por_dia.setdefault(cita.inicio.date(), []).append(cita)
        for dia_grupo in sorted(citas_por_dia):
            st.markdown(f"**{_DIAS_SEMANA_ES[dia_grupo.weekday()].capitalize()} {dia_grupo:%d/%m}**")
            for cita in citas_por_dia[dia_grupo]:
                _tarjeta_cita(cita, repo_servicios, repo_profesionales, repo_clientes, cambiar_estado_cita)

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

# ---------- Clientes ----------
elif opcion == "👤 Clientes":
    if not st.session_state.get("mostrar_form_nuevo_cliente"):
        if st.button("+ Nuevo cliente"):
            st.session_state["mostrar_form_nuevo_cliente"] = True
            st.rerun()
    else:
        st.subheader("Nuevo cliente")
        # st.form: mismo motivo que en Testimonios — evita envíos con campos
        # a medio sincronizar, y clear_on_submit vacía el formulario tras
        # crear en vez de dejar el cliente anterior a medio rellenar.
        with st.form("form_nuevo_cliente", clear_on_submit=True):
            nombre_nuevo = st.text_input("Nombre")
            telefono_nuevo = st.text_input("Teléfono (opcional)")
            email_nuevo = st.text_input("Email (opcional)")
            notas_nuevas = st.text_area("Notas (opcional)")
            col_crear, col_cancelar = st.columns(2)
            crear = col_crear.form_submit_button("Crear cliente", use_container_width=True)
            cancelar = col_cancelar.form_submit_button("Cancelar", use_container_width=True)
        if crear:
            if not nombre_nuevo.strip():
                st.error("Rellena el nombre.")
            else:
                try:
                    nuevo = crear_cliente.ejecutar(
                        nombre_nuevo,
                        telefono=telefono_nuevo or None, email=email_nuevo or None,
                        notas=notas_nuevas,
                    )
                    st.success(f"Cliente creado con id {nuevo.id}.")
                    st.session_state["mostrar_form_nuevo_cliente"] = False
                    st.rerun()
                except ClienteYaExiste as exc:
                    st.error(str(exc))
        if cancelar:
            st.session_state["mostrar_form_nuevo_cliente"] = False
            st.rerun()

    st.divider()
    ver_duplicados = st.checkbox("Ver solo duplicados (mismo nombre y teléfono)", key="ver_clientes_duplicados")

    if ver_duplicados:
        grupos = detectar_clientes_duplicados.ejecutar()
        if not grupos:
            st.info("No se han detectado clientes duplicados.")
        for grupo in grupos:
            with st.container(border=True):
                st.markdown(f"**{grupo[0].nombre}** · {grupo[0].telefono}")
                ids_ordenados = sorted(grupo, key=lambda c: _clave_orden_fusion(c.id))
                for cliente in ids_ordenados:
                    st.caption(f"`{cliente.id}`" + (" (más antiguo)" if cliente is ids_ordenados[0] else ""))
                if st.button("Fusionar en el más antiguo", key=f"btn_fusionar_{grupo[0].id}"):
                    superviviente = fusionar_clientes.ejecutar([c.id for c in grupo])
                    st.success(f"Fusionados en `{superviviente.id}`.")
                    st.session_state["ver_clientes_duplicados"] = False
                    st.rerun()
        clientes = []
    else:
        busqueda = st.text_input("Buscar por nombre o teléfono").strip().lower()

        clientes = repo_clientes.listar()
        if busqueda:
            clientes = [
                c for c in clientes
                if busqueda in c.nombre.lower() or busqueda in (c.telefono or "").lower()
            ]
        clientes.sort(key=lambda c: c.nombre.lower())

        if not clientes:
            st.info("Sin clientes que coincidan con la búsqueda." if busqueda else "No hay clientes registrados.")

    for cliente in clientes:
        clave_editando = f"editando_cliente_{cliente.id}"
        with st.container(border=True):
            if not st.session_state.get(clave_editando):
                st.markdown(f"**{cliente.nombre}** · `{cliente.id}`")
                st.write(cliente.telefono or "Sin teléfono")
                st.write(cliente.email or "Sin email")
                if cliente.notas:
                    st.caption(cliente.notas)
                st.caption("📱 Telegram vinculado" if cliente.telegram_chat_id else "📱 Sin Telegram vinculado")
                col_editar, col_eliminar = st.columns(2)
                if col_editar.button("Editar", key=f"btn_editar_cliente_{cliente.id}", use_container_width=True):
                    st.session_state[clave_editando] = True
                    st.rerun()
                if col_eliminar.button("Eliminar", key=f"btn_eliminar_cliente_{cliente.id}", use_container_width=True):
                    eliminar_cliente.ejecutar(cliente.id)
                    st.rerun()
            else:
                with st.form(f"form_editar_cliente_{cliente.id}"):
                    st.text_input("ID", value=cliente.id, disabled=True)
                    nombre_editado = st.text_input("Nombre", value=cliente.nombre)
                    telefono_editado = st.text_input("Teléfono", value=cliente.telefono or "")
                    email_editado = st.text_input("Email", value=cliente.email or "")
                    notas_editadas = st.text_area("Notas", value=cliente.notas)
                    col_guardar, col_cancelar = st.columns(2)
                    guardar = col_guardar.form_submit_button("Guardar", use_container_width=True)
                    cancelar = col_cancelar.form_submit_button("Cancelar", use_container_width=True)
                if guardar:
                    if not nombre_editado.strip():
                        st.error("Rellena el nombre.")
                    else:
                        editar_cliente.ejecutar(
                            cliente.id, nombre_editado,
                            telefono_editado or None, email_editado or None, notas_editadas,
                        )
                        st.session_state[clave_editando] = False
                        st.rerun()
                if cancelar:
                    st.session_state[clave_editando] = False
                    st.rerun()

# ---------- Testimonios ----------
elif opcion == "⭐ Testimonios":
    if not st.session_state.get("mostrar_form_nuevo_testimonio"):
        if st.button("+ Nuevo testimonio"):
            st.session_state["mostrar_form_nuevo_testimonio"] = True
            st.rerun()
    else:
        st.subheader("Nuevo testimonio")
        # st.form: mismo motivo que el gate de contraseña — sin form, el
        # slider/text_input pueden no haberse sincronizado todavía cuando
        # se pulsa el botón, y clear_on_submit vacía el formulario tras
        # crear en vez de dejar el testimonio anterior a medio rellenar.
        with st.form("form_nuevo_testimonio", clear_on_submit=True):
            nombre = st.text_input("Nombre")
            titulo = st.text_input("Título (opcional)")
            descripcion = st.text_area("Descripción")
            valoracion = st.slider("Valoración", 1, 5, 5, format="%d ⭐")
            col_crear, col_cancelar = st.columns(2)
            crear = col_crear.form_submit_button("Crear testimonio", use_container_width=True)
            cancelar = col_cancelar.form_submit_button("Cancelar", use_container_width=True)
        if crear:
            if not nombre.strip() or not descripcion.strip():
                st.error("Rellena nombre y descripción.")
            else:
                try:
                    crear_testimonio.ejecutar(nombre, descripcion, valoracion, titulo=titulo)
                    st.success("Testimonio creado.")
                    st.session_state["mostrar_form_nuevo_testimonio"] = False
                    st.rerun()
                except ValoracionInvalida as exc:
                    st.error(str(exc))
        if cancelar:
            st.session_state["mostrar_form_nuevo_testimonio"] = False
            st.rerun()

    st.divider()
    testimonios = sorted(repo_testimonios.listar(), key=lambda t: t.creado_en, reverse=True)

    if not testimonios:
        st.info("No hay testimonios todavía.")

    for testimonio in testimonios:
        clave_editando = f"editando_testimonio_{testimonio.id}"
        with st.container(border=True):
            if not st.session_state.get(clave_editando):
                st.markdown("⭐" * testimonio.valoracion)
                st.caption(testimonio.descripcion)
                firma = f"— {testimonio.nombre}"
                if testimonio.titulo:
                    firma += f" · {testimonio.titulo}"
                st.markdown(f"**{firma}**")
                col_editar, col_eliminar = st.columns(2)
                if col_editar.button("Editar", key=f"btn_editar_{testimonio.id}", use_container_width=True):
                    st.session_state[clave_editando] = True
                    st.rerun()
                if col_eliminar.button("Eliminar", key=f"btn_eliminar_{testimonio.id}", use_container_width=True):
                    eliminar_testimonio.ejecutar(testimonio.id)
                    st.rerun()
            else:
                with st.form(f"form_editar_testimonio_{testimonio.id}"):
                    nombre_editado = st.text_input("Nombre", value=testimonio.nombre)
                    titulo_editado = st.text_input("Título (opcional)", value=testimonio.titulo)
                    descripcion_editada = st.text_area("Descripción", value=testimonio.descripcion)
                    valoracion_editada = st.slider(
                        "Valoración", 1, 5, testimonio.valoracion, format="%d ⭐",
                    )
                    col_guardar, col_cancelar = st.columns(2)
                    guardar = col_guardar.form_submit_button("Guardar", use_container_width=True)
                    cancelar = col_cancelar.form_submit_button("Cancelar", use_container_width=True)
                if guardar:
                    if not nombre_editado.strip() or not descripcion_editada.strip():
                        st.error("Rellena nombre y descripción.")
                    else:
                        try:
                            editar_testimonio.ejecutar(
                                testimonio.id, nombre_editado,
                                descripcion_editada, valoracion_editada, titulo=titulo_editado,
                            )
                            st.session_state[clave_editando] = False
                            st.rerun()
                        except ValoracionInvalida as exc:
                            st.error(str(exc))
                if cancelar:
                    st.session_state[clave_editando] = False
                    st.rerun()

# ---------- Contadores ----------
elif opcion == "🔢 Contadores":
    st.caption("Vista de solo lectura — consultar no incrementa ningún contador.")
    contadores = repo_contadores.listar()

    if not contadores:
        st.info("No hay contadores todavía (se crean al usarse por primera vez).")

    for tipo_entidad, valor in sorted(contadores.items()):
        with st.container(border=True):
            st.markdown(f"**{tipo_entidad}**")
            st.write(valor)

# ---------- Rate limiting ----------
elif opcion == "🚦 Rate limiting":
    limitador_consumo = _construir_limitador_consumo()
    # Mismo motivo que en main.py: `or` en vez de un default en .get(),
    # para que una variable definida pero vacía en .env no rompa int().
    limite = int(os.environ.get("RATE_LIMIT_CHAT_MAX_PETICIONES") or LIMITE_PETICIONES_DEFECTO)
    ventana = int(os.environ.get("RATE_LIMIT_CHAT_VENTANA_SEGUNDOS") or VENTANA_SEGUNDOS_DEFECTO)

    if limitador_consumo is None:
        st.info(
            "No disponible sin REDIS_URL configurada — sin Redis, el "
            "contador de peticiones vive solo dentro del proceso del "
            "backend (main.py) y este panel no puede leerlo."
        )
    else:
        st.caption(f"Límite configurado: {limite} peticiones / {ventana}s, por usuario_id.")
        consumo = sorted(limitador_consumo.listar_consumo(), key=lambda c: c.peticiones, reverse=True)

        if not consumo:
            st.info("Sin peticiones registradas en la ventana actual.")

        for entrada in consumo:
            with st.container(border=True):
                st.markdown(f"**{entrada.clave}**")
                st.write(f"{entrada.peticiones}/{limite} peticiones")
                st.caption(f"Ventana se libera en {entrada.segundos_restantes}s")
                if entrada.peticiones >= limite:
                    st.error("Límite alcanzado")

# ---------- Herramientas ----------
elif opcion == "🛠️ Herramientas":
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

    st.divider()
    st.subheader("Borrado de datos")
    # Gate explícito por opt-in (ENTORNO_LOCAL=true), no inferido de
    # DATABASE_URL/localhost: un túnel SSH a producción también
    # resolvería a "localhost", lo que sería peligroso para un botón
    # destructivo (ver issue #53).
    if os.environ.get("ENTORNO_LOCAL", "").lower() != "true":
        st.caption(
            "Sección oculta salvo con ENTORNO_LOCAL=true en el entorno del "
            "proceso — nunca debe activarse en producción."
        )
    else:
        st.warning(
            "Borra TODAS las citas, clientes, pedidos y líneas de pedido, y "
            "testimonios, reinicia todos los contadores, y cancela los "
            "eventos de Google Calendar asociados (si hay uno configurado). "
            "Acción irreversible."
        )
        confirmar = st.checkbox("Sí, quiero borrar todos los datos")
        if st.button("Borrar todos los datos", type="primary", disabled=not confirmar):
            with st.spinner("Borrando..."):
                calendario = _construir_calendario()
                eventos_cancelados = 0
                eventos_fallidos = 0
                if calendario is not None:
                    for cita in repo_citas.citas_en_rango(date.min, date.max):
                        if not cita.evento_calendario_id:
                            continue
                        try:
                            calendario.cancelar_evento(cita.evento_calendario_id)
                            eventos_cancelados += 1
                        except Exception:
                            eventos_fallidos += 1

                n_citas = repo_citas.borrar_todo()
                n_clientes = repo_clientes.borrar_todo()
                n_pedidos = repo_pedidos.borrar_todo()
                n_testimonios = repo_testimonios.borrar_todo()
                n_contadores = repo_contadores.borrar_todo()

            st.success(
                f"Borrado: {n_citas} citas, {n_clientes} clientes, "
                f"{n_pedidos} pedidos (con sus líneas), {n_testimonios} testimonios, "
                f"{n_contadores} contadores reiniciados."
            )
            if calendario is not None:
                st.caption(
                    f"Google Calendar: {eventos_cancelados} eventos cancelados"
                    + (f", {eventos_fallidos} fallos." if eventos_fallidos else ".")
                )
            st.rerun()
