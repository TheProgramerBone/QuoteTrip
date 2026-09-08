# -*- coding: utf-8 -*-
"""Pestaña "Plantillas": biblioteca de plantillas preestablecidas y
personalizadas (crear, duplicar, editar, renombrar, eliminar, marcar como
predeterminada) y el editor visual con vista previa en vivo.

Sigue los mismos patrones de UI que el resto de QuoteTrip: listas tipo
`st.expander`/columnas con botones de acción (`render_tab_historial` en
`cotizacion_ui.py`), mutación de `session_state` solo vía `on_click=`
cuando el widget afectado ya se renderizó antes en el mismo paso de
script, y confirmación en dos pasos para acciones destructivas
(`confirmar_borrado` en `cotizacion_ui.py`)."""

import base64
import uuid

import streamlit as st

from .db import (
    actualizar_cuenta,
    actualizar_plantilla,
    borrar_plantilla,
    crear_plantilla,
    obtener_plantilla,
    obtener_plantillas,
)
from .pdf.models import (
    AJUSTES_IMAGEN,
    ALINEACIONES,
    ELEMENTO_TAMANO_MAX_CM,
    ELEMENTO_TAMANO_MIN_CM,
    FORMAS_CATALOGO,
    FUENTE_POR_DEFECTO,
    FUENTES_CATALOGO,
    LAYOUTS_SERVICIOS,
    LOGO_ALTO_MAX_CM,
    LOGO_ALTO_MIN_CM,
    MARGEN_MAX_CM,
    MARGEN_MIN_CM,
    ORIENTACIONES,
    POSICIONES_LOGO,
    ROTACION_MAX_GRADOS,
    ROTACION_MIN_GRADOS,
    SECCIONES_BLOQUEADAS,
    TAMANO_FUENTE_MAX_PT,
    TAMANO_FUENTE_MIN_PT,
    TAMANOS_PAGINA,
    TIPOS_ELEMENTO,
    ElementoLibre,
    EncabezadoConfig,
    PaginaConfig,
    PieConfig,
    SeccionConfig,
    TemaConfig,
    TemplateDefinition,
    validar_plantilla,
)
from .pdf.presets import PRESET_POR_DEFECTO, listar_presets, obtener_preset
from .pdf.preview import renderizar_previsualizacion

ETIQUETAS_SECCION = {
    "fecha": "Fecha",
    "titulo": "Título",
    "etiqueta_opcion": "Nombre de la opción",
    "pasajeros": "Pasajeros",
    "hotel_fechas": "Hotel y fechas",
    "precios": "Precios",
    "servicios": "Servicios incluidos",
    "nota_legal": "Nota legal",
    "firma": "Firma",
    "anexos": "Anexos (vuelos/hotel)",
}

_ETIQUETAS_ALINEACION = {"izquierda": "Izquierda", "centro": "Centro", "derecha": "Derecha"}
_ETIQUETAS_POSICION_LOGO = {"izquierda": "Izquierda", "centro": "Centro", "derecha": "Derecha"}
_ETIQUETAS_ORIENTACION = {"vertical": "Vertical", "horizontal": "Horizontal"}
_ETIQUETAS_LAYOUT_SERVICIOS = {"text": "Como texto", "table": "Como tabla"}
_ETIQUETAS_TIPO_ELEMENTO = {"texto": "📝 Texto", "imagen": "🖼️ Imagen", "forma": "⬛ Forma"}
_ETIQUETAS_FORMA = {
    "rectangulo": "Rectángulo",
    "rectangulo_redondeado": "Rectángulo redondeado",
    "elipse": "Elipse / círculo",
    "linea": "Línea",
}
_ETIQUETAS_AJUSTE_IMAGEN = {
    "contain": "Ajustar sin recortar",
    "cover": "Rellenar la caja (recorta)",
    "stretch": "Estirar (puede deformar)",
}

# Campos de la cuenta que afectan a la vista previa — se usan como parte de
# la clave de caché (ver `_preview_cacheada`).
_CAMPOS_CUENTA_PREVIEW = (
    "razon_social",
    "nit",
    "rnt",
    "ciudad",
    "telefonos",
    "contacto",
    "logo_path",
    "color_primario",
    "color_secundario",
    "firma_nombre",
    "firma_cargo",
)


# ----------------------------------------------------------------------
# Entrada
# ----------------------------------------------------------------------
def esta_editando_plantilla() -> bool:
    """`True` mientras el editor de plantillas está abierto — `app.py` lo
    usa para decidir si mostrar el editor a pantalla completa (sin la
    barra de pestañas) en vez de las pestañas normales."""
    return bool(st.session_state.get("plantillas_editando_id"))


def render_tab_plantillas(cuenta: dict):
    """Pestaña "Plantillas": solo la biblioteca. El editor (cuando
    `esta_editando_plantilla()` es `True`) lo renderiza `app.py` a pantalla
    completa vía `render_editor_plantilla`, no aquí — así al editar no
    convive con Cotización/Historial/Ayuda detrás de una barra de
    pestañas, se siente como abrir una pantalla propia."""
    st.markdown("## 🎨 Plantillas")
    if st.session_state.pop("plantillas_guardado_ok", False):
        st.success("Plantilla guardada.")
    _render_biblioteca(cuenta)


def render_editor_plantilla(cuenta: dict):
    """Punto de entrada público del editor a pantalla completa (ver
    `esta_editando_plantilla`)."""
    _render_editor(cuenta)


# ----------------------------------------------------------------------
# Vista previa (cacheada)
# ----------------------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=300)
def _preview_desde_json(definicion_json: str, cuenta_valores: tuple) -> bytes:
    definicion = TemplateDefinition.from_json(definicion_json)
    cuenta = dict(zip(_CAMPOS_CUENTA_PREVIEW, cuenta_valores))
    return renderizar_previsualizacion(definicion, cuenta)


def _preview_cacheada(definicion: TemplateDefinition, cuenta: dict) -> bytes:
    cuenta_valores = tuple((cuenta or {}).get(c) for c in _CAMPOS_CUENTA_PREVIEW)
    return _preview_desde_json(definicion.to_json(), cuenta_valores)


# ----------------------------------------------------------------------
# Biblioteca
# ----------------------------------------------------------------------
def _render_biblioteca(cuenta: dict):
    predeterminada_id = cuenta.get("plantilla_predeterminada_id") or PRESET_POR_DEFECTO

    st.caption(
        "Elige el diseño de tus cotizaciones en PDF. Usa una plantilla "
        "preestablecida tal cual, o duplícala para crear la tuya propia y "
        "personalizarla — colores, tipografía, logo, orden de secciones."
    )

    st.markdown("### Preestablecidas")
    for preset in listar_presets():
        _fila_plantilla(
            preset,
            es_preset=True,
            es_predeterminada=(preset.id == predeterminada_id),
            cuenta=cuenta,
        )

    st.markdown("### Mis plantillas")
    filas_custom = obtener_plantillas()
    if not filas_custom:
        st.info(
            "Todavía no tienes plantillas propias. Duplica una preestablecida "
            "para empezar a personalizarla."
        )
    for fila in filas_custom:
        definicion = TemplateDefinition.from_json(fila["definicion_json"])
        _fila_plantilla(
            definicion,
            es_preset=False,
            es_predeterminada=(fila["id"] == predeterminada_id),
            cuenta=cuenta,
        )

    st.divider()
    st.markdown("### + Crear plantilla")
    opciones_base = {p.id: p.nombre for p in listar_presets()}
    st.selectbox(
        "Empezar a partir de",
        options=list(opciones_base.keys()),
        format_func=lambda k: opciones_base[k],
        key="nueva_plantilla_base",
    )
    st.button("Crear plantilla", on_click=_crear_desde_preset)


def _fila_plantilla(
    definicion: TemplateDefinition, es_preset: bool, es_predeterminada: bool, cuenta: dict
):
    with st.container(border=True):
        col_preview, col_info, col_acciones = st.columns([1, 2, 2])
        with col_preview:
            try:
                st.image(_preview_cacheada(definicion, cuenta), use_container_width=True)
            except Exception:
                st.caption("Vista previa no disponible")
        with col_info:
            estrella = "★ " if es_predeterminada else ""
            st.markdown(f"**{estrella}{definicion.nombre}**")
            st.caption("Preestablecida" if es_preset else "Personalizada")
        with col_acciones:
            if es_predeterminada:
                st.success("Predeterminada", icon="⭐")
            else:
                st.button(
                    "Usar como predeterminada",
                    key=f"pred_{definicion.id}",
                    on_click=_marcar_predeterminada,
                    args=(definicion.id,),
                    use_container_width=True,
                )
            st.button(
                "Duplicar",
                key=f"dup_{definicion.id}",
                on_click=_duplicar_plantilla,
                args=(definicion,),
                use_container_width=True,
            )
            if not es_preset:
                st.button(
                    "Editar",
                    key=f"edit_{definicion.id}",
                    on_click=_abrir_editor,
                    args=(definicion.id, False),
                    use_container_width=True,
                )
                _boton_eliminar(definicion)


def _boton_eliminar(definicion: TemplateDefinition):
    flag = f"confirmar_borrado_plantilla_{definicion.id}"
    if not st.session_state.get(flag):
        st.button(
            "Eliminar",
            key=f"del_{definicion.id}",
            on_click=_set_flag,
            args=(flag, True),
            use_container_width=True,
        )
        return
    st.warning(f"¿Eliminar «{definicion.nombre}»? No se puede deshacer.")
    c1, c2 = st.columns(2)
    with c1:
        st.button(
            "Sí, eliminar",
            key=f"delok_{definicion.id}",
            type="primary",
            on_click=_eliminar_plantilla,
            args=(definicion.id, flag),
            use_container_width=True,
        )
    with c2:
        st.button(
            "Cancelar",
            key=f"delcancel_{definicion.id}",
            on_click=_set_flag,
            args=(flag, False),
            use_container_width=True,
        )


# ----------------------------------------------------------------------
# Callbacks de la biblioteca (siempre `on_click=`, nunca dentro de un
# `if st.button(...):` — ver nota de módulo).
# ----------------------------------------------------------------------
def _set_flag(clave: str, valor: bool):
    st.session_state[clave] = valor


def _marcar_predeterminada(id_: str):
    actualizar_cuenta({"plantilla_predeterminada_id": id_})


def _duplicar_plantilla(definicion: TemplateDefinition):
    copia = definicion.clonar(f"Copia de {definicion.nombre}")
    crear_plantilla(copia.id, copia.nombre, copia.base_id, copia.to_json())
    _abrir_editor(copia.id, False)


def _crear_desde_preset():
    id_preset = st.session_state.get("nueva_plantilla_base") or PRESET_POR_DEFECTO
    _duplicar_plantilla(obtener_preset(id_preset))


def _eliminar_plantilla(id_: str, flag: str):
    borrar_plantilla(id_)
    st.session_state[flag] = False


def _abrir_editor(id_: str, es_preset: bool):
    definicion = (
        obtener_preset(id_)
        if es_preset
        else TemplateDefinition.from_json(obtener_plantilla(id_)["definicion_json"])
    )
    _seed_editor_state(id_, definicion)


def _cerrar_editor():
    st.session_state["plantillas_editando_id"] = None


def _guardar_plantilla(id_: str, base_id: str | None):
    definicion = _construir_definicion_desde_widgets(id_, base_id)
    validar_plantilla(definicion)
    actualizar_plantilla(id_, nombre=definicion.nombre, definicion_json=definicion.to_json())
    st.session_state["plantillas_editando_id"] = None
    st.session_state["plantillas_guardado_ok"] = True


def _mover_seccion(id_: str, tipo: str, direccion: int):
    clave = f"pe_{id_}_orden"
    orden = st.session_state.get(clave, [])
    i = orden.index(tipo)
    j = i + direccion
    if 0 <= j < len(orden):
        orden[i], orden[j] = orden[j], orden[i]
    st.session_state[clave] = orden


def _mover_capa(id_: str, elemento_id: str, direccion: str):
    """Reordena `elementos_orden`, que es a la vez el orden del panel
    "Capas" Y el orden de dibujo (`z_index` se deriva de la posición, ver
    `_elementos_desde_widgets`): índice 0 = más atrás, último índice = más
    adelante (se dibuja al final, encima de los demás).

    `direccion`: "frente" (al final de la lista), "fondo" (al principio),
    "subir"/"bajar" (un nivel — intercambia con el vecino, hacia adelante/
    atrás respectivamente)."""
    clave = f"pe_{id_}_elementos_orden"
    orden = st.session_state.get(clave, [])
    if elemento_id not in orden:
        return
    i = orden.index(elemento_id)
    if direccion == "frente" and i != len(orden) - 1:
        orden.pop(i)
        orden.append(elemento_id)
    elif direccion == "fondo" and i != 0:
        orden.pop(i)
        orden.insert(0, elemento_id)
    elif direccion == "subir" and i < len(orden) - 1:
        orden[i + 1], orden[i] = orden[i], orden[i + 1]
    elif direccion == "bajar" and i > 0:
        orden[i - 1], orden[i] = orden[i], orden[i - 1]
    st.session_state[clave] = orden


# ----------------------------------------------------------------------
# Editor
# ----------------------------------------------------------------------
def _seed_editor_state(id_: str, definicion: TemplateDefinition):
    """Precarga en `session_state` un valor por cada widget del editor,
    ANTES de que esos widgets se rendericen (esta función solo se llama
    desde `on_click=`) — mutar las claves de widgets ya renderizados en el
    mismo paso de script lanzaría `StreamlitAPIException`."""
    st.session_state["plantillas_editando_id"] = id_
    p = f"pe_{id_}_"
    st.session_state[p + "nombre"] = definicion.nombre
    st.session_state[p + "cp_heredar"] = definicion.tema.color_primario is None
    st.session_state[p + "cp"] = definicion.tema.color_primario or "#2563EB"
    st.session_state[p + "cs_heredar"] = definicion.tema.color_secundario is None
    st.session_state[p + "cs"] = definicion.tema.color_secundario or "#1E3A8A"
    st.session_state[p + "fuente"] = definicion.tema.fuente_id
    st.session_state[p + "tam_base"] = float(definicion.tema.tamano_base_pt)
    st.session_state[p + "alin_titulos"] = definicion.tema.alineacion_titulos
    st.session_state[p + "pag_tam"] = definicion.pagina.tamano
    st.session_state[p + "pag_orient"] = definicion.pagina.orientacion
    st.session_state[p + "mS"] = float(definicion.pagina.margen_sup_cm)
    st.session_state[p + "mI"] = float(definicion.pagina.margen_inf_cm)
    st.session_state[p + "mIz"] = float(definicion.pagina.margen_izq_cm)
    st.session_state[p + "mD"] = float(definicion.pagina.margen_der_cm)
    st.session_state[p + "logo_mostrar"] = definicion.encabezado.mostrar_logo
    st.session_state[p + "logo_alto"] = float(definicion.encabezado.logo_alto_cm)
    st.session_state[p + "logo_pos"] = definicion.encabezado.logo_posicion
    st.session_state[p + "enc_linea"] = definicion.encabezado.mostrar_linea_separadora
    st.session_state[p + "pie_linea"] = definicion.pie.mostrar_linea_separadora
    st.session_state[p + "orden"] = [s.tipo for s in definicion.secciones]
    for s in definicion.secciones:
        st.session_state[p + f"vis_{s.tipo}"] = s.visible
    layout_servicios = next(
        (s.opciones.get("layout", "text") for s in definicion.secciones if s.tipo == "servicios"),
        "text",
    )
    st.session_state[p + "serv_layout"] = layout_servicios

    # El panel "Capas" usa el propio orden de la lista como orden de dibujo
    # (índice 0 = más atrás, último = más adelante) — al abrir el editor la
    # sembramos ordenada por el `z_index` ya guardado, para que el panel
    # refleje el apilado real de la plantilla tal como está hoy.
    elementos_por_capa = sorted(definicion.elementos, key=lambda e: e.z_index)
    st.session_state[p + "elementos_orden"] = [e.id for e in elementos_por_capa]
    for e in definicion.elementos:
        _seed_elemento(p, e.id, e.tipo, e)


def _seed_elemento(p: str, elemento_id: str, tipo: str, e: ElementoLibre | None = None):
    """Precarga las claves de un elemento libre (nuevo si `e` es `None`,
    o desde una `ElementoLibre` existente al abrir el editor)."""
    ep = p + f"el_{elemento_id}_"
    op = (e.opciones if e else None) or {}
    st.session_state[ep + "tipo"] = tipo
    st.session_state[ep + "x"] = float(e.x_cm) if e else 2.0
    st.session_state[ep + "y"] = float(e.y_cm) if e else 2.0
    st.session_state[ep + "ancho"] = float(e.ancho_cm) if e else 5.0
    st.session_state[ep + "alto"] = float(e.alto_cm) if e else 2.0
    st.session_state[ep + "rot"] = float(e.rotacion_grados) if e else 0.0
    st.session_state[ep + "vis"] = bool(e.visible) if e else True
    st.session_state[ep + "bloqueado"] = bool(e.bloqueado) if e else False
    st.session_state[ep + "opacidad"] = float(e.opacidad) if e else 1.0
    if tipo == "texto":
        st.session_state[ep + "texto"] = op.get("texto", "Texto")
        st.session_state[ep + "fuente"] = op.get("fuente_id", FUENTE_POR_DEFECTO)
        st.session_state[ep + "tam"] = float(op.get("tamano_pt", 10.5))
        st.session_state[ep + "peso"] = op.get("peso", "normal")
        st.session_state[ep + "color"] = op.get("color") or "#000000"
        st.session_state[ep + "alin"] = op.get("alineacion", "izquierda")
        st.session_state[ep + "interlineado"] = float(op.get("interlineado", 1.15))
    elif tipo == "forma":
        st.session_state[ep + "forma"] = op.get("forma", "rectangulo")
        st.session_state[ep + "rel_on"] = op.get("color_relleno") is not None
        st.session_state[ep + "rel"] = op.get("color_relleno") or "#2563EB"
        st.session_state[ep + "bor_on"] = op.get("color_borde") is not None
        st.session_state[ep + "bor"] = op.get("color_borde") or "#1E3A8A"
        st.session_state[ep + "grosor"] = float(op.get("grosor_borde_pt", 1.0))
        st.session_state[ep + "radio"] = float(op.get("radio_cm", 0.3))
    elif tipo == "imagen":
        st.session_state[ep + "imagen_b64"] = op.get("imagen_b64")
        st.session_state[ep + "ajuste"] = op.get("ajuste", "contain")


def _agregar_elemento(id_: str, tipo: str):
    p = f"pe_{id_}_"
    nuevo_id = uuid.uuid4().hex
    orden = st.session_state.get(p + "elementos_orden", [])
    orden.append(nuevo_id)
    st.session_state[p + "elementos_orden"] = orden
    _seed_elemento(p, nuevo_id, tipo)


def _eliminar_elemento(id_: str, elemento_id: str):
    p = f"pe_{id_}_"
    orden = st.session_state.get(p + "elementos_orden", [])
    if elemento_id in orden:
        orden.remove(elemento_id)
    st.session_state[p + "elementos_orden"] = orden
    ep = p + f"el_{elemento_id}_"
    for clave in [k for k in st.session_state if k.startswith(ep)]:
        del st.session_state[clave]


def _construir_definicion_desde_widgets(id_: str, base_id: str | None) -> TemplateDefinition:
    """Lee los valores actuales de los widgets del editor (ya en
    `session_state` por su propio `key=`) y arma una `TemplateDefinition`
    — usada tanto para la vista previa en vivo (en cada rerun) como al
    guardar."""
    p = f"pe_{id_}_"
    ss = st.session_state
    orden = ss.get(p + "orden", [])
    secciones = []
    for tipo in orden:
        opciones = {}
        if tipo == "servicios":
            opciones["layout"] = ss.get(p + "serv_layout", "text")
        secciones.append(
            SeccionConfig(
                tipo=tipo, visible=bool(ss.get(p + f"vis_{tipo}", True)), opciones=opciones
            )
        )
    return TemplateDefinition(
        id=id_,
        nombre=(ss.get(p + "nombre") or "Sin nombre").strip() or "Sin nombre",
        tipo="custom",
        base_id=base_id,
        pagina=PaginaConfig(
            tamano=ss.get(p + "pag_tam", "A4"),
            orientacion=ss.get(p + "pag_orient", "vertical"),
            margen_sup_cm=ss.get(p + "mS", 3.1),
            margen_inf_cm=ss.get(p + "mI", 2.9),
            margen_izq_cm=ss.get(p + "mIz", 2.2),
            margen_der_cm=ss.get(p + "mD", 2.2),
        ),
        tema=TemaConfig(
            color_primario=None if ss.get(p + "cp_heredar", True) else ss.get(p + "cp"),
            color_secundario=None if ss.get(p + "cs_heredar", True) else ss.get(p + "cs"),
            fuente_id=ss.get(p + "fuente", "helvetica"),
            tamano_base_pt=ss.get(p + "tam_base", 10.5),
            peso_titulos="bold",
            alineacion_titulos=ss.get(p + "alin_titulos", "centro"),
        ),
        encabezado=EncabezadoConfig(
            mostrar_logo=ss.get(p + "logo_mostrar", True),
            logo_alto_cm=ss.get(p + "logo_alto", 2.0),
            logo_posicion=ss.get(p + "logo_pos", "izquierda"),
            mostrar_linea_separadora=ss.get(p + "enc_linea", True),
        ),
        pie=PieConfig(mostrar_linea_separadora=ss.get(p + "pie_linea", True)),
        secciones=secciones,
        elementos=_elementos_desde_widgets(p),
    )


def _elementos_desde_widgets(p: str) -> list[ElementoLibre]:
    ss = st.session_state
    elementos = []
    for i, eid in enumerate(ss.get(p + "elementos_orden", [])):
        ep = p + f"el_{eid}_"
        if ep + "tipo" not in ss:
            continue  # se eliminó en este mismo paso de edición
        tipo = ss.get(ep + "tipo", "texto")
        if tipo == "texto":
            opciones = {
                "texto": ss.get(ep + "texto", ""),
                "fuente_id": ss.get(ep + "fuente", FUENTE_POR_DEFECTO),
                "tamano_pt": ss.get(ep + "tam", 10.5),
                "peso": ss.get(ep + "peso", "normal"),
                "color": ss.get(ep + "color") or "#000000",
                "alineacion": ss.get(ep + "alin", "izquierda"),
                "interlineado": ss.get(ep + "interlineado", 1.15),
            }
        elif tipo == "forma":
            opciones = {
                "forma": ss.get(ep + "forma", "rectangulo"),
                "color_relleno": ss.get(ep + "rel") if ss.get(ep + "rel_on") else None,
                "color_borde": ss.get(ep + "bor") if ss.get(ep + "bor_on") else None,
                "grosor_borde_pt": ss.get(ep + "grosor", 1.0),
                "radio_cm": ss.get(ep + "radio", 0.3),
            }
        else:  # "imagen"
            opciones = {
                "imagen_b64": ss.get(ep + "imagen_b64"),
                "ajuste": ss.get(ep + "ajuste", "contain"),
            }
        elementos.append(
            ElementoLibre(
                id=eid,
                tipo=tipo,
                x_cm=ss.get(ep + "x", 1.0),
                y_cm=ss.get(ep + "y", 1.0),
                ancho_cm=ss.get(ep + "ancho", 5.0),
                alto_cm=ss.get(ep + "alto", 2.0),
                rotacion_grados=ss.get(ep + "rot", 0.0),
                # z_index ya no es un campo que el usuario edite a mano:
                # es la posición del elemento en `elementos_orden`, que el
                # panel "Capas" reordena (0 = más atrás, ver _mover_capa).
                z_index=i,
                visible=bool(ss.get(ep + "vis", True)),
                bloqueado=bool(ss.get(ep + "bloqueado", False)),
                opacidad=ss.get(ep + "opacidad", 1.0),
                opciones=opciones,
            )
        )
    return elementos


def _etiqueta_capa(ep: str, tipo: str) -> str:
    """Descripción corta de un elemento para el panel "Capas" — el icono
    de su tipo más un fragmento de su contenido, para poder distinguir
    varios elementos del mismo tipo sin abrir cada uno."""
    ss = st.session_state
    icono = _ETIQUETAS_TIPO_ELEMENTO.get(tipo, tipo)
    if tipo == "texto":
        texto = (ss.get(ep + "texto") or "").strip().replace("\n", " ")
        detalle = f"«{texto[:28]}…»" if len(texto) > 28 else (f"«{texto}»" if texto else "(vacío)")
    elif tipo == "imagen":
        detalle = "con imagen" if ss.get(ep + "imagen_b64") else "sin imagen todavía"
    else:  # "forma"
        forma = ss.get(ep + "forma", "rectangulo")
        detalle = _ETIQUETAS_FORMA.get(forma, forma)
    return f"{icono} — {detalle}"


def _render_panel_capas(id_: str):
    """Panel de gestión de capas: una fila por elemento libre, con la
    de más adelante (se dibuja encima) arriba del todo — al revés de
    `elementos_orden` (que guarda 0 = más atrás, ver `_mover_capa`).
    Visibilidad y bloqueo se controlan aquí; posición/tamaño/estilo se
    editan en "Elementos libres" más abajo."""
    p = f"pe_{id_}_"
    orden = st.session_state.get(p + "elementos_orden", [])
    if not orden:
        st.caption("Todavía no hay elementos libres — añade uno en «Elementos libres», abajo.")
        return

    total = len(orden)
    for pos in range(total):
        i = total - 1 - pos  # índice real en `orden`; pos=0 es la capa más adelante
        eid = orden[i]
        ep = p + f"el_{eid}_"
        if ep + "tipo" not in st.session_state:
            continue
        tipo = st.session_state.get(ep + "tipo", "texto")
        c_nombre, c_vis, c_lock, c_frente, c_sube, c_baja, c_fondo = st.columns(
            [4, 1, 1, 1, 1, 1, 1]
        )
        with c_nombre:
            st.caption(_etiqueta_capa(ep, tipo))
        with c_vis:
            st.checkbox("👁", key=ep + "vis", help="Visible")
        with c_lock:
            st.checkbox(
                "🔒",
                key=ep + "bloqueado",
                help="Bloquear (protege de mover/redimensionar/eliminar)",
            )
        with c_frente:
            st.button(
                "⤒",
                key=p + f"capa_frente_{eid}",
                disabled=(i == total - 1),
                help="Traer al frente",
                use_container_width=True,
                on_click=_mover_capa,
                args=(id_, eid, "frente"),
            )
        with c_sube:
            st.button(
                "▲",
                key=p + f"capa_sube_{eid}",
                disabled=(i == total - 1),
                help="Subir un nivel",
                use_container_width=True,
                on_click=_mover_capa,
                args=(id_, eid, "subir"),
            )
        with c_baja:
            st.button(
                "▼",
                key=p + f"capa_baja_{eid}",
                disabled=(i == 0),
                help="Bajar un nivel",
                use_container_width=True,
                on_click=_mover_capa,
                args=(id_, eid, "bajar"),
            )
        with c_fondo:
            st.button(
                "⤓",
                key=p + f"capa_fondo_{eid}",
                disabled=(i == 0),
                help="Enviar al fondo",
                use_container_width=True,
                on_click=_mover_capa,
                args=(id_, eid, "fondo"),
            )


def _render_elemento(id_: str, eid: str, indice: int):
    p = f"pe_{id_}_"
    ep = p + f"el_{eid}_"
    tipo = st.session_state.get(ep + "tipo", "texto")
    etiqueta = _ETIQUETAS_TIPO_ELEMENTO.get(tipo, tipo)
    bloqueado = st.session_state.get(ep + "bloqueado", False)
    with st.container(border=True):
        st.markdown(f"**{etiqueta} #{indice + 1}**")
        if bloqueado:
            st.caption(
                "🔒 Bloqueado — posición y tamaño protegidos. Desbloquéalo en "
                "el panel **Capas** para moverlo, redimensionarlo o eliminarlo."
            )

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.number_input(
                "X (cm, desde la izquierda)",
                0.0,
                60.0,
                key=ep + "x",
                step=0.1,
                disabled=bloqueado,
            )
        with c2:
            st.number_input(
                "Y (cm, desde arriba)",
                0.0,
                60.0,
                key=ep + "y",
                step=0.1,
                disabled=bloqueado,
            )
        with c3:
            st.number_input(
                "Ancho (cm)",
                ELEMENTO_TAMANO_MIN_CM,
                ELEMENTO_TAMANO_MAX_CM,
                key=ep + "ancho",
                step=0.1,
                disabled=bloqueado,
            )
        with c4:
            st.number_input(
                "Alto (cm)",
                ELEMENTO_TAMANO_MIN_CM,
                ELEMENTO_TAMANO_MAX_CM,
                key=ep + "alto",
                step=0.1,
                disabled=bloqueado,
            )

        c5, c6 = st.columns(2)
        with c5:
            st.number_input(
                "Rotación (°)",
                ROTACION_MIN_GRADOS,
                ROTACION_MAX_GRADOS,
                key=ep + "rot",
                step=1.0,
                disabled=bloqueado,
            )
        with c6:
            st.slider("Opacidad", 0.0, 1.0, key=ep + "opacidad", step=0.05)

        if tipo == "texto":
            st.text_area("Texto", key=ep + "texto", height=80)
            t1, t2, t3 = st.columns(3)
            with t1:
                st.selectbox(
                    "Fuente",
                    options=list(FUENTES_CATALOGO.keys()),
                    format_func=lambda k: FUENTES_CATALOGO[k]["etiqueta"],
                    key=ep + "fuente",
                )
                st.selectbox(
                    "Peso",
                    options=["normal", "bold"],
                    format_func=lambda w: "Negrita" if w == "bold" else "Normal",
                    key=ep + "peso",
                )
            with t2:
                st.number_input("Tamaño (pt)", 6.0, 72.0, key=ep + "tam", step=0.5)
                st.number_input("Interlineado", 0.8, 3.0, key=ep + "interlineado", step=0.05)
            with t3:
                st.color_picker("Color", key=ep + "color")
                st.selectbox(
                    "Alineación",
                    options=list(ALINEACIONES),
                    format_func=lambda a: _ETIQUETAS_ALINEACION.get(a, a),
                    key=ep + "alin",
                )
        elif tipo == "forma":
            st.selectbox(
                "Forma",
                options=list(FORMAS_CATALOGO),
                format_func=lambda f: _ETIQUETAS_FORMA.get(f, f),
                key=ep + "forma",
            )
            f1, f2, f3 = st.columns(3)
            with f1:
                st.checkbox("Con relleno", key=ep + "rel_on")
                if st.session_state[ep + "rel_on"]:
                    st.color_picker("Color de relleno", key=ep + "rel")
            with f2:
                st.checkbox("Con borde", key=ep + "bor_on")
                if st.session_state[ep + "bor_on"]:
                    st.color_picker("Color de borde", key=ep + "bor")
                    st.number_input(
                        "Grosor del borde (pt)", 0.25, 10.0, key=ep + "grosor", step=0.25
                    )
            with f3:
                if st.session_state.get(ep + "forma") == "rectangulo_redondeado":
                    st.number_input("Radio de esquina (cm)", 0.0, 5.0, key=ep + "radio", step=0.1)
        else:  # "imagen"
            archivo = st.file_uploader("Imagen", type=["png", "jpg", "jpeg"], key=ep + "upload")
            if archivo is not None:
                st.session_state[ep + "imagen_b64"] = base64.b64encode(archivo.read()).decode(
                    "ascii"
                )
            if st.session_state.get(ep + "imagen_b64"):
                st.image(
                    base64.b64decode(st.session_state[ep + "imagen_b64"]),
                    caption="Imagen actual",
                    width=150,
                )
            else:
                st.caption("Sin imagen todavía — no se dibujará hasta que subas una.")
            st.selectbox(
                "Ajuste dentro de la caja",
                options=list(AJUSTES_IMAGEN),
                format_func=lambda a: _ETIQUETAS_AJUSTE_IMAGEN.get(a, a),
                key=ep + "ajuste",
            )

        st.button(
            "🗑️ Eliminar elemento",
            key=p + f"del_el_{eid}",
            disabled=bloqueado,
            help="Desbloquéalo en el panel «Capas» para poder eliminarlo." if bloqueado else None,
            on_click=_eliminar_elemento,
            args=(id_, eid),
        )


def _render_editor(cuenta: dict):
    id_ = st.session_state["plantillas_editando_id"]
    fila = obtener_plantilla(id_)
    if not fila:
        st.markdown("## ✏️ Editor de plantilla")
        st.warning("Esta plantilla ya no existe (puede que se haya eliminado en otra pestaña).")
        st.button("← Volver a Plantillas", on_click=_cerrar_editor)
        return
    base_id = fila["base_id"]
    p = f"pe_{id_}_"

    st.caption("🎨 Plantillas")
    st.markdown(f"## ✏️ Editando: {st.session_state.get(p + 'nombre') or fila['nombre']}")

    col_izq, col_der = st.columns([3, 2])

    with col_izq:
        st.text_input("Nombre de la plantilla", key=p + "nombre")

        with st.expander("Tema", expanded=True):
            c1, c2 = st.columns(2)
            with c1:
                st.checkbox("Usar el color primario de la cuenta", key=p + "cp_heredar")
                if not st.session_state[p + "cp_heredar"]:
                    st.color_picker("Color primario", key=p + "cp")
            with c2:
                st.checkbox("Usar el color secundario de la cuenta", key=p + "cs_heredar")
                if not st.session_state[p + "cs_heredar"]:
                    st.color_picker("Color secundario", key=p + "cs")
            st.selectbox(
                "Tipografía",
                options=list(FUENTES_CATALOGO.keys()),
                format_func=lambda k: FUENTES_CATALOGO[k]["etiqueta"],
                key=p + "fuente",
            )
            st.slider(
                "Tamaño de letra base (pt)",
                TAMANO_FUENTE_MIN_PT,
                TAMANO_FUENTE_MAX_PT,
                key=p + "tam_base",
                step=0.5,
            )
            st.selectbox(
                "Alineación de títulos",
                options=list(ALINEACIONES),
                format_func=lambda a: _ETIQUETAS_ALINEACION.get(a, a),
                key=p + "alin_titulos",
            )

        with st.expander("Página"):
            c1, c2 = st.columns(2)
            with c1:
                st.selectbox("Tamaño", options=list(TAMANOS_PAGINA), key=p + "pag_tam")
            with c2:
                st.selectbox(
                    "Orientación",
                    options=list(ORIENTACIONES),
                    format_func=lambda o: _ETIQUETAS_ORIENTACION.get(o, o),
                    key=p + "pag_orient",
                )
            c3, c4 = st.columns(2)
            with c3:
                st.number_input(
                    "Margen superior (cm)", MARGEN_MIN_CM, MARGEN_MAX_CM, key=p + "mS", step=0.1
                )
                st.number_input(
                    "Margen izquierdo (cm)", MARGEN_MIN_CM, MARGEN_MAX_CM, key=p + "mIz", step=0.1
                )
            with c4:
                st.number_input(
                    "Margen inferior (cm)", MARGEN_MIN_CM, MARGEN_MAX_CM, key=p + "mI", step=0.1
                )
                st.number_input(
                    "Margen derecho (cm)", MARGEN_MIN_CM, MARGEN_MAX_CM, key=p + "mD", step=0.1
                )

        with st.expander("Encabezado y pie"):
            st.checkbox("Mostrar logo", key=p + "logo_mostrar")
            if st.session_state[p + "logo_mostrar"]:
                st.slider(
                    "Tamaño del logo (cm)",
                    LOGO_ALTO_MIN_CM,
                    LOGO_ALTO_MAX_CM,
                    key=p + "logo_alto",
                    step=0.1,
                )
                st.selectbox(
                    "Posición del logo",
                    options=list(POSICIONES_LOGO),
                    format_func=lambda pos: _ETIQUETAS_POSICION_LOGO.get(pos, pos),
                    key=p + "logo_pos",
                )
            st.checkbox("Línea separadora bajo el encabezado", key=p + "enc_linea")
            st.checkbox("Línea separadora sobre el pie de página", key=p + "pie_linea")

        with st.expander("Estructura (orden y secciones)", expanded=True):
            st.caption(
                "Activa o desactiva secciones y cambia su orden con las flechas. "
                "Las marcadas como obligatorias no se pueden ocultar."
            )
            orden = st.session_state[p + "orden"]
            for i, tipo in enumerate(orden):
                bloqueada = tipo in SECCIONES_BLOQUEADAS
                c_check, c_up, c_down = st.columns([5, 1, 1])
                with c_check:
                    if bloqueada:
                        st.checkbox(
                            f"{ETIQUETAS_SECCION.get(tipo, tipo)} (obligatoria)",
                            value=True,
                            disabled=True,
                            key=p + f"vis_disp_{tipo}",
                        )
                        st.session_state[p + f"vis_{tipo}"] = True
                    else:
                        st.checkbox(ETIQUETAS_SECCION.get(tipo, tipo), key=p + f"vis_{tipo}")
                with c_up:
                    st.button(
                        "▲",
                        key=p + f"up_{tipo}",
                        disabled=(i == 0),
                        on_click=_mover_seccion,
                        args=(id_, tipo, -1),
                        use_container_width=True,
                    )
                with c_down:
                    st.button(
                        "▼",
                        key=p + f"down_{tipo}",
                        disabled=(i == len(orden) - 1),
                        on_click=_mover_seccion,
                        args=(id_, tipo, 1),
                        use_container_width=True,
                    )
                if tipo == "servicios":
                    st.selectbox(
                        "Cómo mostrar los servicios incluidos",
                        options=list(LAYOUTS_SERVICIOS),
                        format_func=lambda layout: _ETIQUETAS_LAYOUT_SERVICIOS.get(layout, layout),
                        key=p + "serv_layout",
                    )

        with st.expander("Capas", expanded=bool(st.session_state.get(p + "elementos_orden"))):
            st.caption(
                "Orden de apilado de los elementos libres (arriba = más "
                "adelante). Aquí se controla visibilidad, bloqueo y capa; "
                "la posición, tamaño y estilo de cada uno se editan en "
                "«Elementos libres», justo abajo."
            )
            _render_panel_capas(id_)

        with st.expander("Elementos libres (texto, imágenes, formas)"):
            st.caption(
                "Añade bloques de texto propio, imágenes o formas decorativas en "
                "cualquier posición de la página (x/y desde la esquina superior "
                "izquierda). Quedan siempre detrás del contenido de la "
                "cotización — son para fondos, marcas de agua o decoración, no "
                "para taparla."
            )
            orden_el = st.session_state[p + "elementos_orden"]
            for i, eid in enumerate(orden_el):
                _render_elemento(id_, eid, i)

            st.markdown("**+ Añadir elemento**")
            c_tipo, c_add = st.columns([3, 1])
            with c_tipo:
                st.selectbox(
                    "Tipo de elemento nuevo",
                    options=list(TIPOS_ELEMENTO),
                    format_func=lambda t: _ETIQUETAS_TIPO_ELEMENTO.get(t, t),
                    key=p + "nuevo_elemento_tipo",
                    label_visibility="collapsed",
                )
            with c_add:
                st.button(
                    "Añadir",
                    key=p + "btn_add_elemento",
                    use_container_width=True,
                    on_click=_agregar_elemento,
                    args=(id_, st.session_state.get(p + "nuevo_elemento_tipo", "texto")),
                )

        st.divider()
        c_guardar, c_volver = st.columns(2)
        with c_guardar:
            st.button(
                "💾 Guardar",
                type="primary",
                use_container_width=True,
                on_click=_guardar_plantilla,
                args=(id_, base_id),
            )
        with c_volver:
            st.button("← Volver a Plantillas", use_container_width=True, on_click=_cerrar_editor)

    with col_der:
        st.markdown("#### Vista previa")
        definicion_actual = _construir_definicion_desde_widgets(id_, base_id)
        avisos = validar_plantilla(definicion_actual)
        for aviso in avisos:
            st.warning(aviso)
        try:
            st.image(_preview_cacheada(definicion_actual, cuenta), use_container_width=True)
        except Exception as e:
            st.error(f"No se pudo generar la vista previa: {e}")
