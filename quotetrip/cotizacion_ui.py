# -*- coding: utf-8 -*-
"""Pestañas "Cotización" e "Historial": servicios compartidos, opciones
(pasajeros, fechas, hotel, servicios), cálculo en vivo, el botón "Aplicar y
Exportar" que arma el PDF y lo guarda en el historial, y la recarga de una
cotización guardada para editarla / recotizar."""

import csv
import io
import json
import traceback
from datetime import date

import streamlit as st

from .calculos import (
    calcular_dias_noches,
    calcular_opcion,
    fecha_en_espanol,
    formato_cop,
    nombre_archivo_seguro,
    texto_pasajeros,
)
from .config import CLAVES_COMPARTIBLES, INCLUSIONES, LOG_PATH, logger
from .db import borrar_historial, guardar_cotizacion, obtener_historial, obtener_plantilla
from .paste_uploader import bytes_pegados, imagen_pegable
from .pdf import construir_pdf
from .pdf.presets import PRESET_POR_DEFECTO, es_preset, obtener_preset
from .pdf.resolver import listar_plantillas_disponibles, resolver_plantilla


def _bytes_lista(key):
    files = st.session_state.get(key) or []
    if not isinstance(files, list):
        files = [files]
    return [f.getvalue() for f in files if f is not None]


def _bytes_uno(key):
    f = st.session_state.get(key)
    return f.getvalue() if f else None


def _render_pegar_vuelos(base_key):
    """Recuadro de "pegar captura de vuelo": a diferencia de la foto del
    hotel, aquí puede haber varias, así que cada pegado nuevo (distinto del
    último visto) se va sumando a una lista acumulada en `session_state`
    en vez de reemplazar la anterior."""
    pegar_key = f"pegar_{base_key}"
    lista_key = f"{pegar_key}__lista"
    visto_key = f"{pegar_key}__visto"
    lista = st.session_state.setdefault(lista_key, [])
    nueva = imagen_pegable(pegar_key)
    if nueva is not None and nueva != st.session_state.get(visto_key):
        lista.append(nueva)
        st.session_state[visto_key] = nueva
    if lista:
        st.caption(f"{len(lista)} captura{'s' if len(lista) != 1 else ''} pegada(s):")
        cols = st.columns(min(len(lista), 6))
        for idx, img in enumerate(lista):
            cols[idx % len(cols)].image(img, use_container_width=True)
        if st.button("🗑 Vaciar capturas pegadas", key=f"{pegar_key}_vaciar"):
            st.session_state[lista_key] = []
            st.session_state[visto_key] = None
            st.rerun()


def _pegadas_vuelo(base_key):
    """Relee (sin renderizar) las capturas ya pegadas para `base_key`."""
    return list(st.session_state.get(f"pegar_{base_key}__lista", []))


def _valor_por_defecto(key, valor_def):
    """Evita el warning de Streamlit ("created with a default value but also
    had its value set via Session State") cuando `cargar_cotizacion_en_formulario`
    ya preestableció esta key: si ya existe en session_state, no se pasa
    `value=` al widget (session_state manda)."""
    return {} if key in st.session_state else {"value": valor_def}


def fila_servicio(clave, etiqueta, desc_def, keyp, hotel_nombre=""):
    """Renderiza un servicio (check + descripción + precio + comisión + base).
    La comisión se suma al precio. Devuelve dict o None."""
    if not st.checkbox(etiqueta, key=f"chk_{keyp}"):
        return None
    if clave == "hotel" and hotel_nombre.strip():
        desc_def = f"Hotel {hotel_nombre.strip()} Todo Incluido"
    desc = st.text_input(
        f"Descripción · {etiqueta}",
        key=f"desc_{keyp}",
        **_valor_por_defecto(f"desc_{keyp}", desc_def),
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        monto = st.number_input(
            f"Precio · {etiqueta} (COP)",
            min_value=0,
            step=50000,
            key=f"cost_{keyp}",
            **_valor_por_defecto(f"cost_{keyp}", 0),
        )
    with c2:
        comision = st.number_input(
            f"Comisión · {etiqueta} (COP)",
            min_value=0,
            step=10000,
            key=f"com_{keyp}",
            help="Se suma al precio de este servicio.",
            **_valor_por_defecto(f"com_{keyp}", 0),
        )
    with c3:
        base = st.selectbox(
            f"Base · {etiqueta}", ["Por pasajero adulto", "Total del grupo"], key=f"base_{keyp}"
        )
    return {
        "clave": clave,
        "etiqueta": etiqueta,
        "desc": desc.strip(),
        "monto": int(monto),
        "comision": int(comision),
        "base": "persona" if base.startswith("Por") else "total",
    }


def _leer_servicio(clave, etiqueta, desc_def, keyp):
    b = st.session_state.get(f"base_{keyp}", "Por pasajero adulto")
    return {
        "clave": clave,
        "etiqueta": etiqueta,
        "desc": (st.session_state.get(f"desc_{keyp}", desc_def) or "").strip(),
        "monto": int(st.session_state.get(f"cost_{keyp}", 0)),
        "comision": int(st.session_state.get(f"com_{keyp}", 0)),
        "base": "persona" if b.startswith("Por") else "total",
    }


def _nombre_plantilla_historial(plantilla_id: str | None) -> str:
    """Nombre a mostrar en el historial para el `plantilla_id` guardado en
    una cotización. `None` = guardada antes de que existiera el sistema de
    plantillas (usó el diseño que hoy es el preset "Clásica"). Si era una
    plantilla personalizada que luego se borró, lo indica en vez de fallar
    — el snapshot completo sigue en `plantilla_snapshot_json`, esto es
    solo la etiqueta visible."""
    if not plantilla_id:
        return "Clásica (histórico)"
    if es_preset(plantilla_id):
        return obtener_preset(plantilla_id).nombre
    fila = obtener_plantilla(plantilla_id)
    if fila:
        return fila["nombre"]
    return "Personalizada (eliminada)"


def render_tab_cotizacion(
    cuenta, cliente, fecha_cotiz, color_primario, color_secundario, compartir
):
    # -------- Estado inicial de las opciones --------
    if "opciones" not in st.session_state:
        st.session_state["opciones"] = [{"id": 1}]
        st.session_state["next_opt_id"] = 2

    # -------- Bloque compartido de vuelos y traslados --------
    servicios_compartidos = []
    if compartir:
        with st.expander(
            "✈️ Vuelos y traslados compartidos (aplican a todas las opciones)", expanded=True
        ):
            for clave, etiqueta, desc_def in INCLUSIONES:
                if clave in CLAVES_COMPARTIBLES:
                    s = fila_servicio(clave, etiqueta, desc_def, keyp=f"{clave}_shared")
                    if s:
                        servicios_compartidos.append(s)
            st.markdown("**Capturas de itinerarios de vuelos (compartidas)**")
            st.file_uploader(
                "Subir itinerarios de vuelos",
                type=["png", "jpg", "jpeg", "webp"],
                accept_multiple_files=True,
                key="upv_shared",
                label_visibility="collapsed",
            )
            _render_pegar_vuelos("upv_shared")
        imgs_vuelos_compartidas = _bytes_lista("upv_shared") + _pegadas_vuelo("upv_shared")
    else:
        imgs_vuelos_compartidas = []

    # -------- Controles para agregar / quitar opciones --------
    cA, cB = st.columns([3, 1])
    with cA:
        st.markdown("### Opciones de la cotización")
    with cB:
        if st.button("➕  Agregar opción", use_container_width=True):
            nid = st.session_state["next_opt_id"]
            st.session_state["opciones"].append({"id": nid})
            st.session_state["next_opt_id"] += 1
            st.rerun()

    opciones = st.session_state["opciones"]
    etiquetas = [f"Opción {i + 1}" for i in range(len(opciones))]
    tabs_op = st.tabs(etiquetas)

    # -------- Render de cada opción --------
    for i, (op, tab) in enumerate(zip(opciones, tabs_op)):
        oid = op["id"]
        with tab:
            top1, top2 = st.columns([3, 1])
            with top1:
                st.text_input(
                    "Nombre de la opción",
                    key=f"nom_{oid}",
                    **_valor_por_defecto(f"nom_{oid}", f"Opción {i + 1}"),
                )
            with top2:
                st.write("")
                if len(opciones) > 1 and st.button(
                    "🗑 Eliminar", key=f"del_{oid}", use_container_width=True
                ):
                    st.session_state["opciones"] = [o for o in opciones if o["id"] != oid]
                    st.rerun()

            # Fechas de esta opción
            f1, f2 = st.columns(2)
            with f1:
                st.date_input(
                    "Fecha de ida",
                    format="DD/MM/YYYY",
                    key=f"ida_{oid}",
                    **_valor_por_defecto(f"ida_{oid}", date(date.today().year, 1, 1)),
                )
            with f2:
                st.date_input(
                    "Fecha de regreso",
                    format="DD/MM/YYYY",
                    key=f"reg_{oid}",
                    **_valor_por_defecto(f"reg_{oid}", date(date.today().year, 1, 5)),
                )
            ida = st.session_state[f"ida_{oid}"]
            reg = st.session_state[f"reg_{oid}"]
            dias, noches = calcular_dias_noches(ida, reg)
            if reg < ida:
                st.warning("La fecha de regreso es anterior a la de ida.")
            else:
                m1, m2 = st.columns(2)
                m1.metric("Días", dias)
                m2.metric("Noches", noches)

            # Pasajeros de esta opción
            p1, p2 = st.columns(2)
            with p1:
                adultos = int(
                    st.number_input(
                        "Adultos (mayores de 12 años)",
                        min_value=1,
                        step=1,
                        key=f"ad_{oid}",
                        **_valor_por_defecto(f"ad_{oid}", 2),
                    )
                )
            with p2:
                menores = int(
                    st.number_input(
                        "Menores (12 años o menos)",
                        min_value=0,
                        step=1,
                        key=f"me_{oid}",
                        **_valor_por_defecto(f"me_{oid}", 0),
                    )
                )
            personas = adultos + menores
            st.caption(
                f"Se considera **adulto** a los mayores de 12 años. "
                f"Total: **{personas} pasajero{'s' if personas != 1 else ''}**."
            )

            # Hotel
            hotel = st.text_input(
                "Nombre del hotel", key=f"hotel_{oid}", placeholder="Ej: Hotel Riu Palace"
            )

            # Servicios de esta opción (los compartidos no se repiten aquí)
            st.markdown("**Servicios**")
            st.caption(
                "Marca cada servicio, ingresa su precio y comisión, "
                "e indica si es por pasajero o total del grupo."
            )
            servicios_opcion = []
            for clave, etiqueta, desc_def in INCLUSIONES:
                if compartir and clave in CLAVES_COMPARTIBLES:
                    continue
                s = fila_servicio(
                    clave, etiqueta, desc_def, keyp=f"{clave}_{oid}", hotel_nombre=hotel
                )
                if s:
                    servicios_opcion.append(s)

            # Tarifa de menores
            tarifa_menor_dif = False
            valor_menor = 0
            if menores > 0:
                tarifa_menor_dif = st.checkbox(
                    "Los menores pagan una tarifa diferente", key=f"tmd_{oid}"
                )
                if tarifa_menor_dif:
                    valor_menor = int(
                        st.number_input(
                            "Valor por menor (COP)",
                            min_value=0,
                            step=50000,
                            key=f"vm_{oid}",
                            **_valor_por_defecto(f"vm_{oid}", 0),
                        )
                    )

            # Imagen del hotel de esta opción
            st.file_uploader(
                "Foto del hotel",
                type=["png", "jpg", "jpeg", "webp"],
                accept_multiple_files=False,
                key=f"uph_{oid}",
            )
            imagen_pegable(f"pegar_uph_{oid}")

            # Imágenes de vuelos propias (solo si NO se comparten)
            if not compartir:
                st.file_uploader(
                    "Capturas de itinerarios de vuelos",
                    type=["png", "jpg", "jpeg", "webp"],
                    accept_multiple_files=True,
                    key=f"upv_{oid}",
                )
                _render_pegar_vuelos(f"upv_{oid}")

            # ----- Cálculo y resumen en vivo de la opción -----
            servicios = servicios_compartidos + servicios_opcion
            calc = calcular_opcion(adultos, menores, tarifa_menor_dif, valor_menor, servicios)

            st.divider()
            r1, r2 = st.columns(2)
            with r1:
                st.metric("Valor por pasajero", f"${formato_cop(calc['valor_pasajero'])}")
            with r2:
                if personas > 1:
                    st.metric(
                        f"Valor total ({personas} pasajeros)",
                        f"${formato_cop(calc['total_grupo'])}",
                    )
            if tarifa_menor_dif and menores > 0:
                st.caption(
                    f"Valor por pasajero menor: ${formato_cop(calc['valor_pasajero_menor'])}"
                )
            st.info(calc["incluye"])

    st.divider()

    # -------- Selector de plantilla de diseño --------
    plantillas_disponibles = listar_plantillas_disponibles(cuenta)
    ids_disponibles = [p.id for p in plantillas_disponibles]
    predeterminada_id = cuenta.get("plantilla_predeterminada_id") or PRESET_POR_DEFECTO
    if predeterminada_id not in ids_disponibles:
        predeterminada_id = PRESET_POR_DEFECTO
    kwargs_indice = (
        {}
        if "plantilla_exportar_id" in st.session_state
        else {"index": ids_disponibles.index(predeterminada_id)}
    )
    st.selectbox(
        "Plantilla de diseño",
        options=ids_disponibles,
        format_func=lambda id_: next(
            (p.nombre for p in plantillas_disponibles if p.id == id_), id_
        ),
        key="plantilla_exportar_id",
        help=(
            "Se usa la plantilla predeterminada de tu cuenta automáticamente; "
            "elige otra aquí solo para esta cotización. Personalízalas en la "
            "pestaña 🎨 Plantillas."
        ),
        **kwargs_indice,
    )

    # -------- Botón: generar y exportar --------
    if st.button("💾  Aplicar y Exportar", type="primary", use_container_width=True):
        if not cliente.strip():
            st.error("Ingresa el **nombre del cliente** en la barra lateral antes de exportar.")
        else:
            try:
                # Servicios compartidos: iguales para todas las opciones, se leen una sola vez
                serv_comp = []
                if compartir:
                    for clave, etiqueta, desc_def in INCLUSIONES:
                        if clave in CLAVES_COMPARTIBLES and st.session_state.get(
                            f"chk_{clave}_shared"
                        ):
                            serv_comp.append(
                                _leer_servicio(clave, etiqueta, desc_def, f"{clave}_shared")
                            )

                # Reconstruir todas las opciones desde session_state
                opciones_pdf = []
                opciones_snapshot = []
                hoteles, valores_desde = [], []
                error = None

                for i, op in enumerate(st.session_state["opciones"]):
                    oid = op["id"]
                    nombre = st.session_state.get(f"nom_{oid}", f"Opción {i + 1}")
                    ida = st.session_state.get(f"ida_{oid}")
                    reg = st.session_state.get(f"reg_{oid}")
                    if ida and reg and reg < ida:
                        error = (
                            f"La opción «{nombre}» tiene la fecha de regreso antes que la de ida."
                        )
                        break
                    dias, noches = calcular_dias_noches(ida, reg)
                    adultos = int(st.session_state.get(f"ad_{oid}", 1))
                    menores = int(st.session_state.get(f"me_{oid}", 0))
                    hotel = (st.session_state.get(f"hotel_{oid}", "") or "").strip()
                    tarifa_menor_dif = bool(st.session_state.get(f"tmd_{oid}", False))
                    valor_menor = int(st.session_state.get(f"vm_{oid}", 0))

                    # Servicios propios
                    serv = []
                    for clave, etiqueta, desc_def in INCLUSIONES:
                        if compartir and clave in CLAVES_COMPARTIBLES:
                            continue
                        if st.session_state.get(f"chk_{clave}_{oid}"):
                            serv.append(_leer_servicio(clave, etiqueta, desc_def, f"{clave}_{oid}"))

                    servicios = serv_comp + serv
                    if not servicios:
                        error = f"La opción «{nombre}» no tiene servicios marcados."
                        break

                    calc = calcular_opcion(
                        adultos, menores, tarifa_menor_dif, valor_menor, servicios
                    )

                    imgs_vuelos = (
                        imgs_vuelos_compartidas
                        if compartir
                        else _bytes_lista(f"upv_{oid}") + _pegadas_vuelo(f"upv_{oid}")
                    )
                    img_hotel = _bytes_uno(f"uph_{oid}") or bytes_pegados(f"pegar_uph_{oid}")

                    opciones_pdf.append(
                        {
                            "nombre": nombre,
                            "hotel": hotel,
                            "ida": ida,
                            "regreso": reg,
                            "dias": dias,
                            "noches": noches,
                            "adultos": adultos,
                            "menores": menores,
                            "tarifa_menor_dif": tarifa_menor_dif,
                            "pasajeros_txt": texto_pasajeros(adultos, menores),
                            "imgs_vuelos_bytes": imgs_vuelos,
                            "img_hotel_bytes": img_hotel,
                            # Lista cruda de servicios (no solo el texto
                            # "Incluye: ..." de `calc`) — habilita el layout
                            # de tabla de servicios en el motor de plantillas.
                            "servicios": servicios,
                            **calc,
                        }
                    )
                    opciones_snapshot.append(
                        {
                            "nombre": nombre,
                            "ida": ida.isoformat() if ida else None,
                            "regreso": reg.isoformat() if reg else None,
                            "adultos": adultos,
                            "menores": menores,
                            "hotel": hotel,
                            "tarifa_menor_dif": tarifa_menor_dif,
                            "valor_menor": valor_menor,
                            "servicios": serv,
                        }
                    )
                    if hotel:
                        hoteles.append(hotel)
                    valores_desde.append(int(round(calc["valor_pasajero"])) or calc["total_grupo"])

                if error:
                    st.error(error)
                else:
                    glob = {
                        "cliente": cliente.strip(),
                        "fecha_cotiz_txt": fecha_en_espanol(fecha_cotiz),
                        "color_primario": color_primario,
                        "color_secundario": color_secundario,
                        "razon_social": cuenta.get("razon_social") or "",
                        "nit": cuenta.get("nit") or "",
                        "rnt": cuenta.get("rnt") or "",
                        "ciudad": cuenta.get("ciudad") or "",
                        "telefonos": cuenta.get("telefonos") or "",
                        "contacto": cuenta.get("contacto") or "",
                        "logo_path": cuenta.get("logo_path"),
                        "firma_nombre": cuenta.get("firma_nombre") or "",
                        "firma_cargo": cuenta.get("firma_cargo") or "",
                    }
                    plantilla = resolver_plantilla(
                        cuenta, st.session_state.get("plantilla_exportar_id")
                    )
                    pdf_bytes = construir_pdf(glob, opciones_pdf, template=plantilla)
                    snapshot = {
                        "cliente": cliente.strip(),
                        "fecha_cotiz": fecha_cotiz.isoformat(),
                        "color_primario": color_primario,
                        "color_secundario": color_secundario,
                        "compartir": compartir,
                        "servicios_compartidos": serv_comp,
                        "opciones": opciones_snapshot,
                    }
                    guardar_cotizacion(
                        cliente.strip(),
                        glob["fecha_cotiz_txt"],
                        len(opciones_pdf),
                        "; ".join(hoteles) if hoteles else "-",
                        min(valores_desde) if valores_desde else 0,
                        datos_json=json.dumps(snapshot),
                        plantilla_id=plantilla.id,
                        plantilla_snapshot_json=plantilla.to_json(),
                    )
                    st.session_state["pdf_bytes"] = pdf_bytes
                    st.session_state["pdf_nombre"] = (
                        f"Cotizacion_{nombre_archivo_seguro(cliente)}.pdf"
                    )
                    logger.info(
                        "PDF generado para '%s' con %d opción(es).",
                        cliente.strip(),
                        len(opciones_pdf),
                    )
                    st.success(
                        f"Cotización con {len(opciones_pdf)} opción(es) generada y guardada."
                    )
            except Exception as e:
                tb = traceback.format_exc()
                logger.error("Error al generar la cotización: %s\n%s", e, tb)
                st.error(f"Ocurrió un error al generar el PDF: {e}")
                with st.expander("Ver detalle del error (para soporte)"):
                    st.code(tb, language="text")
                st.caption(f"El error también quedó guardado en el registro: {LOG_PATH}")

    if st.session_state.get("pdf_bytes"):
        st.download_button(
            "⬇️  Exportar PDF",
            data=st.session_state["pdf_bytes"],
            file_name=st.session_state["pdf_nombre"],
            mime="application/pdf",
            use_container_width=True,
        )


# ----------------------------------------------------------------------
# Recargar una cotización del historial para editarla / recotizar
# ----------------------------------------------------------------------
def _preset_servicio(keyp, s, desc_def):
    """Preestablece en session_state las claves de un servicio (o lo deja
    desmarcado si `s` es None) ANTES de que el widget correspondiente se
    vuelva a instanciar en el próximo rerun."""
    st.session_state[f"chk_{keyp}"] = s is not None
    if s is not None:
        st.session_state[f"desc_{keyp}"] = s.get("desc") or desc_def
        st.session_state[f"cost_{keyp}"] = int(s.get("monto") or 0)
        st.session_state[f"com_{keyp}"] = int(s.get("comision") or 0)
        st.session_state[f"base_{keyp}"] = (
            "Por pasajero adulto" if s.get("base") == "persona" else "Total del grupo"
        )


def cargar_cotizacion_en_formulario(datos_json_str: str):
    """Repuebla session_state con una cotización guardada, para editarla o
    recotizar a partir de ella. Reemplaza las opciones actuales del
    formulario (no se combinan).

    Limitación de Streamlit: las capturas de vuelos/hotel que se subieron NO
    se pueden re-adjuntar por código a un `file_uploader` — si la
    recotización las necesita, hay que volver a subirlas."""
    datos = json.loads(datos_json_str)

    st.session_state["cliente"] = datos.get("cliente") or ""
    if datos.get("fecha_cotiz"):
        st.session_state["fecha_cotiz"] = date.fromisoformat(datos["fecha_cotiz"])
    if datos.get("color_primario"):
        st.session_state["cp"] = datos["color_primario"]
    if datos.get("color_secundario"):
        st.session_state["cs"] = datos["color_secundario"]
    st.session_state["compartir"] = bool(datos.get("compartir"))

    servicios_compartidos = {s["clave"]: s for s in datos.get("servicios_compartidos") or []}
    for clave, etiqueta, desc_def in INCLUSIONES:
        if clave in CLAVES_COMPARTIBLES:
            _preset_servicio(f"{clave}_shared", servicios_compartidos.get(clave), desc_def)

    nuevas_opciones = []
    next_id = st.session_state.get("next_opt_id", 2)
    hoy = date.today().year
    for op in datos.get("opciones") or []:
        oid = next_id
        next_id += 1
        nuevas_opciones.append({"id": oid})

        st.session_state[f"nom_{oid}"] = op.get("nombre") or "Opción"
        st.session_state[f"ida_{oid}"] = (
            date.fromisoformat(op["ida"]) if op.get("ida") else date(hoy, 1, 1)
        )
        st.session_state[f"reg_{oid}"] = (
            date.fromisoformat(op["regreso"]) if op.get("regreso") else date(hoy, 1, 5)
        )
        st.session_state[f"ad_{oid}"] = int(op.get("adultos") or 1)
        st.session_state[f"me_{oid}"] = int(op.get("menores") or 0)
        st.session_state[f"hotel_{oid}"] = op.get("hotel") or ""
        st.session_state[f"tmd_{oid}"] = bool(op.get("tarifa_menor_dif"))
        st.session_state[f"vm_{oid}"] = int(op.get("valor_menor") or 0)

        servicios_opcion = {s["clave"]: s for s in op.get("servicios") or []}
        for clave, etiqueta, desc_def in INCLUSIONES:
            if clave not in CLAVES_COMPARTIBLES:
                _preset_servicio(f"{clave}_{oid}", servicios_opcion.get(clave), desc_def)

    st.session_state["opciones"] = nuevas_opciones or [{"id": next_id}]
    st.session_state["next_opt_id"] = next_id + (0 if nuevas_opciones else 1)
    # Limpia el PDF de una exportación previa para no confundirlo con esta recotización
    st.session_state.pop("pdf_bytes", None)
    st.session_state.pop("pdf_nombre", None)
    st.session_state["cotizacion_cargada"] = True
    # NOTA: esta función solo puede llamarse como `on_click` de un botón (no
    # después de un `if st.button(...):`) — muta claves que ya son de otros
    # widgets (cliente, fecha_cotiz, cp/cs, compartir, etc.), y Streamlit
    # prohíbe tocarlas una vez que esos widgets ya se instanciaron en el
    # mismo run. `on_click` corre ANTES de que el run siguiente los vuelva a
    # instanciar, que es el único momento en que esto es válido.


# ----------------------------------------------------------------------
# Pestaña "Historial": agrupado por cliente ("carpetas"), con recotización
# ----------------------------------------------------------------------
def render_tab_historial():
    st.subheader("Historial de cotizaciones")

    if st.session_state.pop("cotizacion_cargada", False):
        st.success(
            "Cotización cargada. Ve a la pestaña **📝 Cotización** para verla, editarla "
            "y volver a exportarla. Si tenía capturas de vuelos u hotel, hay que "
            "volver a subirlas — Streamlit no permite re-adjuntarlas por código."
        )

    registros = obtener_historial()
    if not registros:
        st.info("Todavía no hay cotizaciones guardadas.")
        return

    # -------- Agrupado por cliente ("carpetas") --------
    grupos = {}
    for r in registros:
        grupos.setdefault(r["cliente"] or "Sin nombre", []).append(r)
    orden = sorted(grupos.items(), key=lambda kv: max(f["creado_en"] for f in kv[1]), reverse=True)

    for nombre_cliente, filas in orden:
        valores = [f.get("valor_desde") or 0 for f in filas]
        desde_txt = f"${formato_cop(min(valores))}" if valores else "-"
        plural = "es" if len(filas) != 1 else ""
        with st.expander(
            f"📁 {nombre_cliente} — {len(filas)} cotización{plural} · desde {desde_txt}"
        ):
            for f in filas:
                c1, c2 = st.columns([4, 1])
                with c1:
                    st.markdown(
                        f"**{f['fecha_cotiz']}** · {f.get('num_opciones') or 1} opción(es) · "
                        f"{f.get('hoteles') or '-'} · desde ${formato_cop(f.get('valor_desde') or 0)}"
                    )
                    nombre_plantilla = _nombre_plantilla_historial(f.get("plantilla_id"))
                    st.caption(f"Generada: {f['creado_en']} · Plantilla: {nombre_plantilla}")
                with c2:
                    if f.get("datos_json"):
                        # on_click (no `if st.button(...):`) — ver nota en
                        # cargar_cotizacion_en_formulario sobre por qué.
                        st.button(
                            "🔄 Cargar para editar",
                            key=f"cargar_{f['id']}",
                            use_container_width=True,
                            on_click=cargar_cotizacion_en_formulario,
                            args=(f["datos_json"],),
                        )
                    else:
                        st.caption("No editable (antigua)")
                st.divider()

    # -------- Tabla completa + CSV + vaciar historial --------
    st.divider()
    tabla = [
        {
            "ID": r["id"],
            "Cliente": r["cliente"],
            "Fecha": r["fecha_cotiz"],
            "Opciones": r.get("num_opciones") or 1,
            "Hoteles": r.get("hoteles") or "-",
            "Desde (x pasajero)": f"${formato_cop(r.get('valor_desde') or 0)}",
            "Generada": r["creado_en"],
        }
        for r in registros
    ]
    st.dataframe(tabla, use_container_width=True, hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(tabla[0].keys()))
        w.writeheader()
        w.writerows(tabla)
        st.download_button(
            "⬇️  Descargar historial (CSV)",
            data=buf.getvalue().encode("utf-8-sig"),
            file_name="historial_cotizaciones.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with c2:
        if st.button("🗑️  Vaciar historial", use_container_width=True):
            st.session_state["confirmar_borrado"] = True

    if st.session_state.get("confirmar_borrado"):
        st.warning("¿Seguro que deseas eliminar **todo** el historial?")
        cb1, cb2 = st.columns(2)
        if cb1.button("Sí, borrar todo", type="primary", use_container_width=True):
            borrar_historial()
            st.session_state["confirmar_borrado"] = False
            st.rerun()
        if cb2.button("Cancelar", use_container_width=True):
            st.session_state["confirmar_borrado"] = False
            st.rerun()
