# -*- coding: utf-8 -*-
"""
=======================================================================
 QuoteTrip · Generador de Cotizaciones de Viaje
=======================================================================
Punto de entrada de la app (Streamlit + ReportLab). La lógica vive en el
paquete quotetrip/; este archivo arma la pantalla: acceso (registro/login),
tutorial guiado, y las tres pestañas (Cotización, Historial, Ayuda).

Ejecutar:   streamlit run app.py
=======================================================================
"""

from datetime import date

import streamlit as st

from quotetrip import auth, self_update, trm, tutorial
from quotetrip.calculos import formato_cop
from quotetrip.config import (
    APP_VERSION,
    COLOR_PRIMARIO_DEF,
    COLOR_SECUNDARIO_DEF,
    LOG_PATH,
    PRODUCTO_NOMBRE,
    UPDATE_RELEASES_URL,
    UPDATE_URL,
    buscar_actualizacion,
    ruta_logo_cuenta,
)
from quotetrip.cotizacion_ui import render_tab_cotizacion, render_tab_historial
from quotetrip.db import init_db, obtener_cuenta
from quotetrip.plantillas_ui import (
    esta_editando_plantilla,
    render_editor_plantilla,
    render_tab_plantillas,
)

st.set_page_config(
    page_title=f"{PRODUCTO_NOMBRE} · Cotizaciones",
    page_icon="✈️",
    layout="wide",
    # Streamlit oculta el menú ≡ (y con él "Configuración", donde vive el
    # selector de tema Claro/Oscuro/Usar tema del sistema — este último ya
    # sigue el tema de Windows en vivo, sin código nuestro) mientras
    # desktop.py use --client.toolbarMode=minimal Y no haya menu_items
    # definidos. Con menu_items el menú vuelve a aparecer; "Obtener ayuda"
    # y "Reportar un error" se ocultan (no aplican, esto es una app de
    # escritorio de un solo tenant) y "Acerca de" queda con marca propia.
    menu_items={
        "Get help": None,
        "Report a bug": None,
        "About": f"**{PRODUCTO_NOMBRE}** · versión {APP_VERSION}",
    },
)
init_db()

# ----------------------------------------------------------------------
# ACCESO: registro de cuenta (primera vez) / código de recuperación / login
# ----------------------------------------------------------------------
cuenta = obtener_cuenta()
if cuenta is None:
    auth.pantalla_registro()
    st.stop()

_codigo_pendiente = st.session_state.get("codigo_recuperacion_mostrado")
if _codigo_pendiente:
    auth.pantalla_codigo_recuperacion(_codigo_pendiente)
    st.stop()

# "Recordarme en este equipo": se marcó en un login anterior y persiste en la
# BD (sobrevive a cerrar y volver a abrir la app, no solo a un rerun).
if cuenta.get("sesion_recordada"):
    st.session_state["autenticado"] = True

if not st.session_state.get("autenticado"):
    auth.pantalla_login(cuenta)
    st.stop()

# ----------------------------------------------------------------------
# TUTORIAL GUIADO (primera vez tras registrarse, o "volver a ver")
# ----------------------------------------------------------------------
if not cuenta.get("tutorial_visto") or st.session_state.get("mostrar_tutorial_manual"):
    st.session_state["mostrar_tutorial_manual"] = False
    tutorial.mostrar_tutorial()

# ----------------------------------------------------------------------
# EDITOR DE PLANTILLAS: pantalla completa de verdad — se decide ANTES de
# construir la barra lateral, no solo antes de las pestañas (bug de la
# versión anterior: la sidebar con datos del cliente/colores/cuenta se
# seguía viendo mientras se editaba). Nada de Cotización/Historial/
# Plantillas/Ayuda ni la sidebar existen en esta rama — el editor ocupa
# toda la ventana, con su único camino de vuelta ("← Volver a Plantillas").
# ----------------------------------------------------------------------
if esta_editando_plantilla():
    render_editor_plantilla(cuenta)
    st.stop()


def _restaurar_colores():
    """Callback del botón: se ejecuta antes de recrear los selectores de color."""
    st.session_state["cp"] = COLOR_PRIMARIO_DEF
    st.session_state["cs"] = COLOR_SECUNDARIO_DEF


# ----------------------------------------------------------------------
# SIDEBAR · Ajustes globales
# ----------------------------------------------------------------------
with st.sidebar:
    _logo = ruta_logo_cuenta(cuenta)
    if _logo:
        st.image(_logo, width=120)
    st.markdown(f"### {cuenta.get('razon_social') or PRODUCTO_NOMBRE}")
    st.caption(" · ".join(x for x in [cuenta.get("nit"), cuenta.get("rnt")] if x))

    st.divider()
    st.markdown("#### Datos del cliente")
    st.session_state.setdefault("cliente", "")
    st.session_state.setdefault("fecha_cotiz", date.today())
    cliente = st.text_input(
        "Nombre del cliente", key="cliente", placeholder="Ej: Familia Pérez Gómez"
    )
    fecha_cotiz = st.date_input("Fecha de la cotización", key="fecha_cotiz", format="DD/MM/YYYY")

    st.divider()
    st.markdown("#### 🎨 Colores corporativos")
    st.session_state.setdefault("cp", cuenta.get("color_primario") or COLOR_PRIMARIO_DEF)
    st.session_state.setdefault("cs", cuenta.get("color_secundario") or COLOR_SECUNDARIO_DEF)
    color_primario = st.color_picker("Color primario (acentos y líneas)", key="cp")
    color_secundario = st.color_picker("Color secundario (títulos)", key="cs")
    st.button("Restaurar colores de fábrica", use_container_width=True, on_click=_restaurar_colores)

    st.divider()
    st.markdown("#### Vuelos y traslados")
    st.session_state.setdefault("compartir", True)
    compartir = st.checkbox(
        "Usar los mismos vuelos y traslados en todas las opciones", key="compartir"
    )

    st.divider()
    with st.expander("💱 Moneda y redondeo"):
        st.session_state.setdefault("moneda_entrada", "COP")
        st.session_state.setdefault("moneda_salida", "COP")
        ce1, ce2 = st.columns(2)
        with ce1:
            moneda_entrada = st.selectbox(
                "Ingreso los precios en", ["COP", "USD"], key="moneda_entrada"
            )
        with ce2:
            moneda_salida = st.selectbox("Mostrar el PDF en", ["COP", "USD"], key="moneda_salida")

        if moneda_entrada == "USD" or moneda_salida == "USD":
            _trm = trm.obtener_trm()
            if _trm:
                st.session_state.setdefault("trm_manual", _trm["valor"])
                origen = " (caché)" if _trm["de_cache"] else ""
                st.caption(f"TRM del {_trm['fecha']}{origen}: ${formato_cop(_trm['valor'])} COP")
            else:
                st.session_state.setdefault("trm_manual", 4000.0)
                st.warning("No se pudo obtener la TRM automáticamente. Ingrésala a mano:")
            st.number_input("TRM (COP por 1 USD)", min_value=0.0, step=10.0, key="trm_manual")
            if st.button("🔄 Actualizar TRM", use_container_width=True):
                trm.obtener_trm(forzar=True)
                st.rerun()

        st.divider()
        st.session_state.setdefault("redondear", False)
        redondear = st.checkbox("Redondear el valor final por pasajero", key="redondear")
        if redondear:
            modo_ui = st.radio(
                "Modo de redondeo",
                ["Hacia arriba (10.000 más cercano)", "Precio comercial (terminado en 999)"],
                key="modo_redondeo_ui",
            )
            # "modo_redondeo_valor" no es la key de ningún widget (solo el
            # radio de arriba lo es) — se puede reescribir libremente en
            # cada rerun, es lo que lee `cotizacion_ui._redondear_calc`.
            st.session_state["modo_redondeo_valor"] = (
                "arriba_10k" if modo_ui.startswith("Hacia arriba") else "psicologico_999"
            )
            st.caption("El redondeo solo aplica cuando el PDF se muestra en COP.")

    st.divider()
    with st.expander("⚙️ Datos de la cuenta"):
        auth.panel_editar_cuenta(cuenta)
        st.divider()
        auth.panel_cambiar_password(cuenta)
        st.divider()
        auth.panel_ajustes_exportacion(cuenta)

    if st.button("🚪 Cerrar sesión", use_container_width=True):
        auth.cerrar_sesion()

    st.divider()
    st.caption(f"Versión {APP_VERSION}")
    st.caption(
        "🌗 ¿Prefieres modo oscuro? Menú **≡** (arriba a la derecha) → "
        "**Configuración** → tema Claro/Oscuro/Usar tema del sistema."
    )

    # --- Aviso de actualización (si UPDATE_URL está configurada) ---
    @st.cache_data(ttl=3600, show_spinner=False)
    def _chequear_update(version, url):
        return buscar_actualizacion(version, url)

    _parche_listo = self_update.estado_parche_pendiente()
    if _parche_listo:
        st.success(
            f"✅ Actualización {_parche_listo.get('version', '')} descargada. "
            "Cierra y vuelve a abrir la app para aplicarla."
        )
    else:
        _info = _chequear_update(APP_VERSION, UPDATE_URL) if UPDATE_URL else None
        if _info:
            st.warning(f"Nueva versión disponible: {_info['version']}")
            if _info.get("notas"):
                st.caption(_info["notas"])
            _es_parche = _info.get("tipo") == "parche"
            if _es_parche and _info.get("url") and self_update.desktop_soporta_parches():
                if st.button("⬇️ Actualizar ahora", use_container_width=True):
                    with st.spinner("Descargando actualización..."):
                        _error = self_update.preparar_parche(_info)
                    if _error:
                        st.error(_error)
                    else:
                        st.rerun()
            elif _es_parche:
                # Este .exe es de antes de que existiera el auto-parcheo (o
                # quedó desactualizado): el .zip del parche no le serviría de
                # nada, así que se manda al instalador completo en su lugar.
                st.caption("Esta actualización requiere reinstalar (una sola vez más).")
                if hasattr(st, "link_button"):
                    st.link_button(
                        "⬇️ Descargar instalador", UPDATE_RELEASES_URL, use_container_width=True
                    )
                else:
                    st.markdown(f"[⬇️ Descargar instalador]({UPDATE_RELEASES_URL})")
            elif _info.get("url"):
                if hasattr(st, "link_button"):
                    st.link_button(
                        "⬇️ Descargar actualización", _info["url"], use_container_width=True
                    )
                else:
                    st.markdown(f"[⬇️ Descargar actualización]({_info['url']})")

    # --- Registro de errores ---
    with st.expander("🛠 Registro de errores"):
        st.caption(f"Archivo: {LOG_PATH}")
        try:
            _txt = LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.exists() else ""
        except Exception:
            _txt = ""
        if _txt.strip():
            _ultimas = "\n".join(_txt.strip().splitlines()[-40:])
            st.code(_ultimas, language="text")
            st.download_button(
                "Descargar log completo",
                _txt.encode("utf-8"),
                file_name="quotetrip.log",
                mime="text/plain",
                use_container_width=True,
            )
            if st.button("Vaciar registro", use_container_width=True):
                try:
                    LOG_PATH.write_text("", encoding="utf-8")
                    st.rerun()
                except Exception:
                    pass
        else:
            st.caption("Sin errores registrados. 🎉")

# --- Inyectar los colores en la interfaz ---
st.markdown(
    f"""
    <style>
      .stButton>button[kind="primary"] {{ background:{color_primario}; border:0; color:#fff; }}
      .stButton>button[kind="primary"]:hover {{ filter:brightness(0.9); }}
      h1, h2, h3 {{ color:{color_secundario}; }}
      [data-testid="stMetricValue"] {{ color:{color_secundario}; }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown("## Generador de Cotizaciones")

tab_cotiz, tab_hist, tab_plant, tab_ayuda = st.tabs(
    ["📝  Cotización", "📁  Historial", "🎨  Plantillas", "❓  Ayuda"]
)

# ----------------------------------------------------------------------
# TAB · COTIZACIÓN
# ----------------------------------------------------------------------
with tab_cotiz:
    render_tab_cotizacion(cuenta, cliente, fecha_cotiz, color_primario, color_secundario, compartir)

# ----------------------------------------------------------------------
# TAB · HISTORIAL
# ----------------------------------------------------------------------
with tab_hist:
    render_tab_historial()

# ----------------------------------------------------------------------
# TAB · PLANTILLAS
# ----------------------------------------------------------------------
with tab_plant:
    render_tab_plantillas(cuenta)

# ----------------------------------------------------------------------
# TAB · AYUDA
# ----------------------------------------------------------------------
with tab_ayuda:
    tutorial.tab_ayuda()
