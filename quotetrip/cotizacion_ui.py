# -*- coding: utf-8 -*-
"""Pestañas "Cotización" e "Historial": servicios compartidos, opciones
(pasajeros, fechas, hotel, servicios), cálculo en vivo, los botones
"Previsualizar" y "Aplicar y Exportar" que arman el PDF (y lo guardan en el
historial / en disco), y la recarga de una cotización guardada para
editarla / recotizar."""

import base64
import binascii
import csv
import io
import json
import traceback
from datetime import date

import streamlit as st

from .calculos import (
    calcular_dias_noches,
    calcular_opcion,
    convertir_moneda,
    fecha_en_espanol,
    formato_cop,
    formato_moneda,
    nombre_archivo_seguro,
    redondear_precio,
    texto_pasajeros,
)
from .config import CLAVES_COMPARTIBLES, INCLUSIONES, LOG_PATH, PERSONALIZADO, PLANES_HOTEL, logger
from .db import (
    borrar_cotizacion,
    borrar_historial,
    guardar_cotizacion,
    obtener_historial,
    obtener_plantilla,
)
from .exportar import guardar_pdf
from .paste_uploader import bytes_pegados, imagen_pegable
from .pdf import construir_pdf
from .pdf.presets import PRESET_POR_DEFECTO, es_preset, obtener_preset
from .pdf.preview import rasterizar_pdf
from .pdf.resolver import listar_plantillas_disponibles, resolver_plantilla


def _bytes_lista(key):
    files = st.session_state.get(key) or []
    if not isinstance(files, list):
        files = [files]
    return [f.getvalue() for f in files if f is not None]


def _bytes_uno(key):
    f = st.session_state.get(key)
    return f.getvalue() if f else None


def _codificar_imagenes(lista_bytes):
    """Codifica una lista de bytes de imagen a base64 (texto), para poder
    guardarlas dentro del `datos_json` de la cotización — así sobreviven a
    una recotización, cosa que un `st.file_uploader` no permite por sí
    solo (ver `cargar_cotizacion_en_formulario`)."""
    return [base64.b64encode(b).decode("ascii") for b in lista_bytes if b]


def _decodificar_imagenes(lista_b64):
    resultado = []
    for b64 in lista_b64 or []:
        try:
            resultado.append(base64.b64decode(b64))
        except (ValueError, binascii.Error):
            pass
    return resultado


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


def _indice_por_defecto(key, opciones, valor_def):
    """Igual que `_valor_por_defecto`, pero para `st.selectbox` — que no
    acepta `value=`, solo `index=` (la posición dentro de `opciones`)."""
    if key in st.session_state:
        return {}
    try:
        return {"index": opciones.index(valor_def)}
    except ValueError:
        return {}


def _moneda_entrada():
    return st.session_state.get("moneda_entrada", "COP")


def _a_cop(valor):
    """Convierte un número tal como se escribió en el formulario (en la
    moneda de entrada elegida en la barra lateral) a COP, la moneda interna
    en la que trabajan `calcular_opcion` y el historial. Si la moneda de
    entrada es COP, o no hay TRM disponible, lo deja tal cual — nunca
    revienta por falta de TRM, simplemente no convierte.

    Limitación deliberada: esto NO reconvierte números ya escritos si se
    cambia la moneda de entrada a mitad de la cotización — cada número se
    interpreta con la moneda activa en el momento en que se lee (al calcular
    en vivo o al exportar), no en el momento en que se escribió."""
    if _moneda_entrada() == "USD":
        trm = st.session_state.get("trm_manual")
        if trm:
            return valor * trm
    return valor


def _plan_por_defecto(desc_def):
    """A qué plan de `PLANES_HOTEL` corresponde un texto de "Incluye" ya
    existente (con o sin el prefijo "Hotel X" delante, como el `desc_def`
    histórico "Hotel Todo Incluido") — "Personalizado" si no calza con
    ninguno. Misma lógica de detección que usa `_preset_servicio` al
    recargar una cotización guardada."""
    if not desc_def:
        return "Todo Incluido"
    for plan in PLANES_HOTEL:
        if plan == PERSONALIZADO:
            continue
        if desc_def == plan or desc_def.endswith(f" {plan}") or desc_def.endswith(f": {plan}"):
            return plan
    return PERSONALIZADO


def _desc_hotel(keyp, hotel_nombre, desc_def):
    """Campo "Incluye:" del hotel: un selectbox con los planes comerciales
    habituales (con un ⓘ explicándolos) + "Personalizado" para texto libre.
    Devuelve el texto final ya armado (con el nombre del hotel delante, como
    hacía el `desc_def` original)."""
    plan_def = _plan_por_defecto(desc_def)
    plan = st.selectbox(
        "Incluye:",
        PLANES_HOTEL,
        key=f"plan_{keyp}",
        help=(
            "Plan comercial del hotel. Elige el que aplica o "
            '"Personalizado" para escribir tu propio texto.'
        ),
        **_indice_por_defecto(f"plan_{keyp}", PLANES_HOTEL, plan_def),
    )
    if plan == PERSONALIZADO:
        libre = st.text_input(
            "Incluye: (personalizado)",
            key=f"desc_{keyp}",
            **_valor_por_defecto(f"desc_{keyp}", desc_def),
        )
        return libre.strip()
    return f"Hotel {hotel_nombre.strip()}: {plan}" if hotel_nombre.strip() else plan


def _comision_widgets(etiqueta, keyp, monto_cop):
    """Bloque de comisión de un servicio: % del precio (por defecto) o valor
    fijo, salvo que "ya tiene comisión" esté marcado, en cuyo caso no se
    añade nada. `monto_cop` ya debe venir convertido a COP. Devuelve
    (comision_cop, tipo, valor_tipo) — `valor_tipo` es el % o el monto fijo
    tal como lo escribió el usuario (en la moneda de entrada), para poder
    recomponer los mismos widgets al recargar una cotización guardada."""
    ya_tiene = st.checkbox(
        "Este precio ya incluye comisión",
        key=f"yatc_{keyp}",
        help="Actívalo si el precio ya trae tu comisión sumada — no se añade nada extra.",
    )
    if ya_tiene:
        return 0, "ninguna", 0.0

    cc1, cc2 = st.columns(2)
    with cc1:
        tipo_ui = st.radio(
            f"Comisión · {etiqueta}",
            ["% del precio", "Valor fijo"],
            key=f"comtipo_{keyp}",
            horizontal=True,
        )
    tipo = "pct" if tipo_ui.startswith("%") else "fijo"
    with cc2:
        if tipo == "pct":
            pct = st.number_input(
                "Comisión (%)",
                min_value=0.0,
                max_value=100.0,
                step=1.0,
                key=f"compct_{keyp}",
                **_valor_por_defecto(f"compct_{keyp}", 0.0),
            )
            comision = int(round(monto_cop * pct / 100))
            valor_tipo = float(pct)
        else:
            fijo = st.number_input(
                f"Comisión ({_moneda_entrada()})",
                min_value=0,
                step=10000,
                key=f"comfijo_{keyp}",
                **_valor_por_defecto(f"comfijo_{keyp}", 0),
            )
            comision = int(round(_a_cop(fijo)))
            valor_tipo = float(fijo)
    if comision:
        st.caption(f"Comisión aplicada: ${formato_cop(comision)}")
    return comision, tipo, valor_tipo


def fila_servicio(clave, etiqueta, desc_def, keyp, hotel_nombre=""):
    """Renderiza un servicio (check + descripción/dirección + precio +
    comisión + base). La comisión se suma al precio. Devuelve dict o None."""
    if not st.checkbox(etiqueta, key=f"chk_{keyp}"):
        return None

    direccion = ""
    if clave == "hotel":
        direccion = st.text_input(
            "Dirección",
            key=f"dir_{keyp}",
            **_valor_por_defecto(f"dir_{keyp}", ""),
        )
        if hotel_nombre.strip():
            desc_def = f"Hotel {hotel_nombre.strip()} Todo Incluido"
        desc = _desc_hotel(keyp, hotel_nombre, desc_def)
    else:
        desc = st.text_input(
            f"Descripción · {etiqueta}",
            key=f"desc_{keyp}",
            **_valor_por_defecto(f"desc_{keyp}", desc_def),
        )

    c1, c2 = st.columns(2)
    with c1:
        monto = st.number_input(
            f"Precio · {etiqueta} ({_moneda_entrada()})",
            min_value=0,
            step=50000,
            key=f"cost_{keyp}",
            **_valor_por_defecto(f"cost_{keyp}", 0),
        )
    with c2:
        base = st.selectbox(
            f"Base · {etiqueta}", ["Por pasajero adulto", "Total del grupo"], key=f"base_{keyp}"
        )
    monto_cop = int(round(_a_cop(monto)))
    comision, comision_tipo, comision_valor = _comision_widgets(etiqueta, keyp, monto_cop)
    return {
        "clave": clave,
        "etiqueta": etiqueta,
        "desc": desc.strip(),
        "direccion": direccion.strip(),
        "monto": monto_cop,
        "comision": int(comision),
        "comision_tipo": comision_tipo,
        "comision_valor": comision_valor,
        "base": "persona" if base.startswith("Por") else "total",
    }


def _leer_servicio(clave, etiqueta, desc_def, keyp, hotel_nombre=""):
    b = st.session_state.get(f"base_{keyp}", "Por pasajero adulto")
    monto_cop = int(round(_a_cop(int(st.session_state.get(f"cost_{keyp}", 0)))))

    if clave == "hotel":
        plan = st.session_state.get(f"plan_{keyp}", "Todo Incluido")
        if plan == PERSONALIZADO:
            desc = (st.session_state.get(f"desc_{keyp}", desc_def) or "").strip()
        else:
            desc = f"Hotel {hotel_nombre.strip()}: {plan}" if hotel_nombre.strip() else plan
        direccion = (st.session_state.get(f"dir_{keyp}", "") or "").strip()
    else:
        desc = (st.session_state.get(f"desc_{keyp}", desc_def) or "").strip()
        direccion = ""

    if st.session_state.get(f"yatc_{keyp}", False):
        comision, comision_tipo, comision_valor = 0, "ninguna", 0.0
    else:
        tipo_ui = st.session_state.get(f"comtipo_{keyp}", "% del precio")
        if tipo_ui.startswith("%"):
            comision_tipo = "pct"
            comision_valor = float(st.session_state.get(f"compct_{keyp}", 0.0))
            comision = int(round(monto_cop * comision_valor / 100))
        else:
            comision_tipo = "fijo"
            comision_valor = float(st.session_state.get(f"comfijo_{keyp}", 0))
            comision = int(round(_a_cop(comision_valor)))

    return {
        "clave": clave,
        "etiqueta": etiqueta,
        "desc": desc,
        "direccion": direccion,
        "monto": monto_cop,
        "comision": comision,
        "comision_tipo": comision_tipo,
        "comision_valor": comision_valor,
        "base": "persona" if b.startswith("Por") else "total",
    }


# ----------------------------------------------------------------------
# Moneda de salida, redondeo y ajuste manual del valor final — se aplican,
# en ese orden, sobre el `calc` en COP que devuelve `calcular_opcion`.
# `_finalizar_calc` es la versión "muda" (sin dibujar nada), usada tanto
# para el cálculo en vivo como para exportar/previsualizar, así el número
# final es siempre el mismo por los dos caminos; `_resumen_y_ajuste_ui`
# dibuja el expander correspondiente (solo tiene sentido en vivo).
# ----------------------------------------------------------------------
def _convertir_calc(calc_cop, moneda_salida, trm):
    calc = dict(calc_cop)
    for k in (
        "valor_pasajero",
        "valor_pasajero_menor",
        "total_grupo",
        "costo_total",
        "comision_total",
    ):
        calc[k] = convertir_moneda(calc[k], moneda_salida, trm)
    return calc


def _redondear_calc(calc, moneda_salida):
    # El redondeo a "múltiplo de 10.000" solo tiene sentido en COP — en USD
    # sería una granularidad absurda para precios de viajes, así que se
    # ignora en ese caso (nunca falla, solo no redondea).
    if st.session_state.get("redondear") and moneda_salida == "COP":
        modo = st.session_state.get("modo_redondeo_valor", "arriba_10k")
        calc = dict(calc)
        for k in ("valor_pasajero", "valor_pasajero_menor", "total_grupo"):
            calc[k] = redondear_precio(calc[k], modo)
    return calc


def _aplicar_ajuste_manual(oid, calc, personas):
    ajuste_on_key, ajuste_key = f"ajuste_on_{oid}", f"ajuste_{oid}"
    if not (st.session_state.get(ajuste_on_key) and ajuste_key in st.session_state):
        return calc
    calc = dict(calc)
    valor_calculado = calc["total_grupo"] if personas > 1 else calc["valor_pasajero"]
    valor_ajustado = int(st.session_state[ajuste_key])
    factor = (valor_ajustado / valor_calculado) if valor_calculado else 1
    if personas > 1:
        calc["total_grupo"] = valor_ajustado
        calc["valor_pasajero"] = valor_ajustado / personas
    else:
        calc["valor_pasajero"] = valor_ajustado
        calc["total_grupo"] = valor_ajustado
    calc["valor_pasajero_menor"] = calc.get("valor_pasajero_menor", 0) * factor
    return calc


def _finalizar_calc(oid, calc_cop, personas):
    moneda_salida = st.session_state.get("moneda_salida", "COP")
    trm = st.session_state.get("trm_manual")
    calc = _convertir_calc(calc_cop, moneda_salida, trm)
    calc = _redondear_calc(calc, moneda_salida)
    calc = _aplicar_ajuste_manual(oid, calc, personas)
    return calc


def _resumen_y_ajuste_ui(oid, calc_sin_ajuste, personas):
    """Dibuja el expander "Resumen y ajuste final" de una opción: costo,
    comisión/ganancia, y el valor final editable a mano con aviso si el
    ajuste implica ceder comisión. `calc_sin_ajuste` ya viene convertido a
    la moneda de salida y redondeado, pero SIN el ajuste manual — así el
    resumen y el valor por defecto del campo siempre reflejan el cálculo
    real, nunca un ajuste anterior arrastrado."""
    moneda_salida = st.session_state.get("moneda_salida", "COP")
    ajuste_on_key, ajuste_key = f"ajuste_on_{oid}", f"ajuste_{oid}"
    paso = 10000 if moneda_salida == "COP" else 10
    valor_calculado = (
        calc_sin_ajuste["total_grupo"] if personas > 1 else calc_sin_ajuste["valor_pasajero"]
    )
    with st.expander("💰 Resumen y ajuste final de precios"):
        costo_txt = formato_moneda(calc_sin_ajuste["costo_total"], moneda_salida)
        comision_txt = formato_moneda(calc_sin_ajuste["comision_total"], moneda_salida)
        st.write(f"Costo (proveedores): {costo_txt}")
        st.write(f"Comisión / ganancia: {comision_txt}")
        st.checkbox("Ajustar manualmente el valor final", key=ajuste_on_key)
        if st.session_state.get(ajuste_on_key):
            st.number_input(
                "Valor final" + (" (total del grupo)" if personas > 1 else " (por pasajero)"),
                min_value=0,
                step=paso,
                key=ajuste_key,
                **_valor_por_defecto(ajuste_key, int(round(valor_calculado))),
            )
            valor_ajustado = int(st.session_state.get(ajuste_key, valor_calculado))
            perdida = valor_calculado - valor_ajustado
            if perdida > 0:
                comision_disp = calc_sin_ajuste["comision_total"]
                if perdida >= comision_disp:
                    perdida_extra_txt = formato_moneda(perdida - comision_disp, moneda_salida)
                    st.warning(
                        "⚠️ Con este ajuste pierdes toda tu comisión "
                        f"({formato_moneda(comision_disp, moneda_salida)}) y además "
                        f"{perdida_extra_txt} de tu costo base."
                    )
                else:
                    st.warning(
                        "⚠️ Con este ajuste tu comisión baja de "
                        f"{formato_moneda(comision_disp, moneda_salida)} a "
                        f"{formato_moneda(comision_disp - perdida, moneda_salida)}."
                    )


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


def _armar_glob(cuenta, cliente, fecha_cotiz, color_primario, color_secundario):
    return {
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
        "moneda_salida": st.session_state.get("moneda_salida", "COP"),
    }


def _leer_servicios_compartidos(compartir):
    serv_comp = []
    if compartir:
        for clave, etiqueta, desc_def in INCLUSIONES:
            if clave in CLAVES_COMPARTIBLES and st.session_state.get(f"chk_{clave}_shared"):
                serv_comp.append(_leer_servicio(clave, etiqueta, desc_def, f"{clave}_shared"))
    return serv_comp


def _reconstruir_opciones(compartir, serv_comp, imgs_vuelos_compartidas):
    """Reconstruye todas las opciones desde `session_state`: valida fechas y
    que cada una tenga servicios, calcula sus importes (convertidos a la
    moneda de salida, con redondeo/ajuste si aplica) y arma tanto los datos
    para el PDF como el snapshot para el historial. La usan tanto
    "Previsualizar" como "Aplicar y Exportar" — mismo camino, para que lo
    que se previsualiza sea exactamente lo que se exporta.

    Devuelve (opciones_pdf, opciones_snapshot, hoteles, valores_desde, error);
    con `error` no vacío, las otras cuatro vienen vacías."""
    opciones_pdf, opciones_snapshot = [], []
    hoteles, valores_desde = [], []

    for i, op in enumerate(st.session_state["opciones"]):
        oid = op["id"]
        nombre = st.session_state.get(f"nom_{oid}", f"Opción {i + 1}")
        ida = st.session_state.get(f"ida_{oid}")
        reg = st.session_state.get(f"reg_{oid}")
        if ida and reg and reg < ida:
            return (
                [],
                [],
                [],
                [],
                f"La opción «{nombre}» tiene la fecha de regreso antes que la de ida.",
            )
        dias, noches = calcular_dias_noches(ida, reg)
        adultos = int(st.session_state.get(f"ad_{oid}", 1))
        menores = int(st.session_state.get(f"me_{oid}", 0))
        personas = adultos + menores
        hotel = (st.session_state.get(f"hotel_{oid}", "") or "").strip()
        tarifa_menor_dif = bool(st.session_state.get(f"tmd_{oid}", False))
        valor_menor = int(round(_a_cop(int(st.session_state.get(f"vm_{oid}", 0)))))

        serv = []
        for clave, etiqueta, desc_def in INCLUSIONES:
            if compartir and clave in CLAVES_COMPARTIBLES:
                continue
            if st.session_state.get(f"chk_{clave}_{oid}"):
                serv.append(
                    _leer_servicio(
                        clave,
                        etiqueta,
                        desc_def,
                        f"{clave}_{oid}",
                        hotel_nombre=hotel if clave == "hotel" else "",
                    )
                )

        servicios = serv_comp + serv
        if not servicios:
            return [], [], [], [], f"La opción «{nombre}» no tiene servicios marcados."

        calc_cop = calcular_opcion(adultos, menores, tarifa_menor_dif, valor_menor, servicios)
        calc = _finalizar_calc(oid, calc_cop, personas)

        imgs_vuelos = (
            imgs_vuelos_compartidas
            if compartir
            else _bytes_lista(f"upv_{oid}") + _pegadas_vuelo(f"upv_{oid}")
        )
        img_hotel = _bytes_uno(f"uph_{oid}") or bytes_pegados(f"pegar_uph_{oid}")
        hotel_direccion = next(
            (s["direccion"] for s in servicios if s["clave"] == "hotel" and s.get("direccion")),
            "",
        )
        moneda_salida = st.session_state.get("moneda_salida", "COP")
        trm_actual = st.session_state.get("trm_manual")
        servicios_mostrar = [
            {
                **s,
                "monto": convertir_moneda(s["monto"], moneda_salida, trm_actual),
                "comision": convertir_moneda(s["comision"], moneda_salida, trm_actual),
            }
            for s in servicios
        ]

        opciones_pdf.append(
            {
                "nombre": nombre,
                "hotel": hotel,
                "hotel_direccion": hotel_direccion,
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
                # Lista cruda de servicios (no solo el texto "Incluye: ..."
                # de `calc`) — habilita el layout de tabla de servicios en
                # el motor de plantillas. Ya en la moneda de salida elegida.
                "servicios": servicios_mostrar,
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
                # Imágenes de esta opción, para que sobrevivan a una
                # recotización — se guardan recién aquí (al exportar).
                "imgs_vuelos_b64": _codificar_imagenes(
                    [] if compartir else (_bytes_lista(f"upv_{oid}") + _pegadas_vuelo(f"upv_{oid}"))
                ),
                "img_hotel_b64": (_codificar_imagenes([img_hotel])[0] if img_hotel else None),
            }
        )
        if hotel:
            hoteles.append(hotel)
        # "Desde" del historial: siempre en COP y sin redondeo/ajuste
        # manual, para que sea comparable entre cotizaciones sin importar
        # en qué moneda se exportó cada una — solo ordena/muestra el
        # historial, no es lo que ve el cliente en el PDF.
        valores_desde.append(int(round(calc_cop["valor_pasajero"])) or calc_cop["total_grupo"])

    return opciones_pdf, opciones_snapshot, hoteles, valores_desde, None


def _agregar_opcion():
    """Callback de "➕ Agregar opción". Tiene que ser `on_click` (no un
    `if st.button(...): ...; st.rerun()`): ese patrón MUTABA session_state y
    llamaba a `st.rerun()` ANTES de que el resto del formulario (las demás
    opciones, sus widgets) se hubiera vuelto a dibujar en esa misma pasada
    — `st.rerun()` aborta la pasada ahí mismo, así que Streamlit trataba
    esos widgets todavía no visitados como "huérfanos" y BORRABA su valor de
    session_state, perdiendo los datos ya cargados en las demás opciones.
    Un callback `on_click` corre ANTES de que el próximo rerun (automático,
    disparado por el propio click) vuelva a instanciar los widgets, que es
    el único momento seguro para esto — mismo patrón que
    `cargar_cotizacion_en_formulario`.

    De paso sincroniza las fechas con las de la última opción existente: al
    crear la opción, arrancan iguales (evita reescribirlas cada vez); una
    vez creada, cada opción es independiente — si luego se cambian a mano,
    no se vuelven a tocar entre sí."""
    nid = st.session_state["next_opt_id"]
    anteriores = st.session_state["opciones"]
    if anteriores:
        oid_previo = anteriores[-1]["id"]
        if f"ida_{oid_previo}" in st.session_state:
            st.session_state[f"ida_{nid}"] = st.session_state[f"ida_{oid_previo}"]
        if f"reg_{oid_previo}" in st.session_state:
            st.session_state[f"reg_{nid}"] = st.session_state[f"reg_{oid_previo}"]
    st.session_state["opciones"].append({"id": nid})
    st.session_state["next_opt_id"] += 1


def _eliminar_opcion(oid):
    """Callback de "🗑 Eliminar" (por la misma razón que `_agregar_opcion`
    debe ser `on_click`, no `if st.button(...): ...; st.rerun()`)."""
    st.session_state["opciones"] = [o for o in st.session_state["opciones"] if o["id"] != oid]


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
        st.button("➕  Agregar opción", use_container_width=True, on_click=_agregar_opcion)

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
                if len(opciones) > 1:
                    st.button(
                        "🗑 Eliminar",
                        key=f"del_{oid}",
                        use_container_width=True,
                        on_click=_eliminar_opcion,
                        args=(oid,),
                    )

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
                            f"Valor por menor ({_moneda_entrada()})",
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
            calc_cop = calcular_opcion(adultos, menores, tarifa_menor_dif, valor_menor, servicios)
            moneda_salida = st.session_state.get("moneda_salida", "COP")
            trm = st.session_state.get("trm_manual")
            calc_convertido = _redondear_calc(
                _convertir_calc(calc_cop, moneda_salida, trm), moneda_salida
            )
            calc = _aplicar_ajuste_manual(oid, calc_convertido, personas)

            st.divider()
            r1, r2 = st.columns(2)
            with r1:
                st.metric(
                    "Valor por pasajero", formato_moneda(calc["valor_pasajero"], moneda_salida)
                )
            with r2:
                if personas > 1:
                    st.metric(
                        f"Valor total ({personas} pasajeros)",
                        formato_moneda(calc["total_grupo"], moneda_salida),
                    )
            if tarifa_menor_dif and menores > 0:
                st.caption(
                    f"Valor por pasajero menor: "
                    f"{formato_moneda(calc['valor_pasajero_menor'], moneda_salida)}"
                )
            st.info(calc["incluye"])
            _resumen_y_ajuste_ui(oid, calc_convertido, personas)

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

    # -------- Botones: previsualizar / generar y exportar --------
    bcol1, bcol2 = st.columns(2)
    with bcol1:
        previsualizar_clic = st.button("👁️  Previsualizar PDF", use_container_width=True)
    with bcol2:
        exportar_clic = st.button(
            "💾  Aplicar y Exportar",
            type="primary",
            use_container_width=True,
            help=(
                "Si en Ajustes de la cuenta configuraste una carpeta predeterminada, "
                "el PDF se guarda ahí directo sin preguntar; si no, se abre el "
                "diálogo de Windows para elegir dónde guardarlo."
            ),
        )

    if previsualizar_clic:
        if not cliente.strip():
            st.error(
                "Ingresa el **nombre del cliente** en la barra lateral antes de previsualizar."
            )
        else:
            try:
                serv_comp = _leer_servicios_compartidos(compartir)
                opciones_pdf, _, _, _, error = _reconstruir_opciones(
                    compartir, serv_comp, imgs_vuelos_compartidas
                )
                if error:
                    st.error(error)
                else:
                    glob = _armar_glob(
                        cuenta, cliente, fecha_cotiz, color_primario, color_secundario
                    )
                    plantilla = resolver_plantilla(
                        cuenta, st.session_state.get("plantilla_exportar_id")
                    )
                    pdf_bytes = construir_pdf(glob, opciones_pdf, template=plantilla)
                    st.session_state["pdf_preview_paginas"] = rasterizar_pdf(pdf_bytes)
            except Exception as e:
                tb = traceback.format_exc()
                logger.error("Error al previsualizar la cotización: %s\n%s", e, tb)
                st.error(f"Ocurrió un error al generar la vista previa: {e}")

    if st.session_state.get("pdf_preview_paginas"):
        with st.expander("👁️ Vista previa del PDF", expanded=True):
            for idx, png in enumerate(st.session_state["pdf_preview_paginas"]):
                st.image(png, use_container_width=True, caption=f"Página {idx + 1}")
            if st.button("Cerrar vista previa"):
                st.session_state.pop("pdf_preview_paginas", None)
                st.rerun()

    if exportar_clic:
        if not cliente.strip():
            st.error("Ingresa el **nombre del cliente** en la barra lateral antes de exportar.")
        else:
            try:
                serv_comp = _leer_servicios_compartidos(compartir)
                opciones_pdf, opciones_snapshot, hoteles, valores_desde, error = (
                    _reconstruir_opciones(compartir, serv_comp, imgs_vuelos_compartidas)
                )
                if error:
                    st.error(error)
                else:
                    glob = _armar_glob(
                        cuenta, cliente, fecha_cotiz, color_primario, color_secundario
                    )
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
                        "vuelos_compartidos_b64": (
                            _codificar_imagenes(imgs_vuelos_compartidas) if compartir else []
                        ),
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
                    logger.info(
                        "PDF generado para '%s' con %d opción(es).",
                        cliente.strip(),
                        len(opciones_pdf),
                    )
                    st.session_state.pop("pdf_preview_paginas", None)

                    nombre_archivo = f"Cotizacion_{nombre_archivo_seguro(cliente)}.pdf"
                    carpeta_predet = cuenta.get("carpeta_exportacion")
                    estado, resultado = guardar_pdf(pdf_bytes, nombre_archivo, carpeta_predet)
                    if estado == "ok":
                        st.success(
                            f"Cotización con {len(opciones_pdf)} opción(es) generada y "
                            f"guardada en:\n\n`{resultado}`"
                        )
                        st.session_state.pop("pdf_bytes", None)
                        st.session_state.pop("pdf_nombre", None)
                    elif estado == "cancelado":
                        st.info(
                            "Guardado cancelado. La cotización ya quedó en el historial; "
                            "puedes descargar el PDF abajo."
                        )
                        st.session_state["pdf_bytes"] = pdf_bytes
                        st.session_state["pdf_nombre"] = nombre_archivo
                    elif estado == "sin_tk":
                        st.success(
                            f"Cotización con {len(opciones_pdf)} opción(es) generada y guardada."
                        )
                        st.session_state["pdf_bytes"] = pdf_bytes
                        st.session_state["pdf_nombre"] = nombre_archivo
                    else:  # "error"
                        st.error(resultado)
                        st.session_state["pdf_bytes"] = pdf_bytes
                        st.session_state["pdf_nombre"] = nombre_archivo
            except Exception as e:
                tb = traceback.format_exc()
                logger.error("Error al generar la cotización: %s\n%s", e, tb)
                st.error(f"Ocurrió un error al generar el PDF: {e}")
                with st.expander("Ver detalle del error (para soporte)"):
                    st.code(tb, language="text")
                st.caption(f"El error también quedó guardado en el registro: {LOG_PATH}")

    if st.session_state.get("pdf_bytes"):
        st.download_button(
            "⬇️  Descargar PDF",
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
    if s is None:
        return

    st.session_state[f"cost_{keyp}"] = int(s.get("monto") or 0)
    st.session_state[f"base_{keyp}"] = (
        "Por pasajero adulto" if s.get("base") == "persona" else "Total del grupo"
    )

    if s.get("clave") == "hotel":
        st.session_state[f"dir_{keyp}"] = s.get("direccion") or ""
        desc_guardado = s.get("desc") or desc_def
        # Si el texto guardado coincide con uno de los planes comerciales
        # (con o sin el prefijo "Hotel X: " delante), se restaura ese plan
        # en el selectbox en vez de caer siempre en "Personalizado".
        plan_detectado = _plan_por_defecto(desc_guardado)
        st.session_state[f"plan_{keyp}"] = plan_detectado
        if plan_detectado == PERSONALIZADO:
            st.session_state[f"desc_{keyp}"] = desc_guardado
    else:
        st.session_state[f"desc_{keyp}"] = s.get("desc") or desc_def

    # Comisión: `comision_tipo` no existe en cotizaciones guardadas antes de
    # esta función (solo tenían un valor fijo en COP) — se restauran como
    # "Valor fijo" con ese mismo monto, que es exactamente lo que hacían.
    comision_tipo = s.get("comision_tipo") or ("fijo" if s.get("comision") else "pct")
    if comision_tipo == "ninguna":
        st.session_state[f"yatc_{keyp}"] = True
    else:
        st.session_state[f"yatc_{keyp}"] = False
        st.session_state[f"comtipo_{keyp}"] = (
            "% del precio" if comision_tipo == "pct" else "Valor fijo"
        )
        if comision_tipo == "pct":
            st.session_state[f"compct_{keyp}"] = float(s.get("comision_valor") or 0.0)
        else:
            st.session_state[f"comfijo_{keyp}"] = int(
                s.get("comision_valor") or s.get("comision") or 0
            )


def _restaurar_imagenes_lista(base_key, lista_b64):
    """Repuebla el acumulado de "capturas pegadas" de `base_key` con
    imágenes ya guardadas — de aquí en adelante quedan representadas como
    si se hubieran pegado, que es el único canal de `session_state` que se
    puede preestablecer por código sin depender de un `file_uploader`
    (imposible de rellenar programáticamente en Streamlit)."""
    imgs = _decodificar_imagenes(lista_b64)
    st.session_state[f"pegar_{base_key}__lista"] = imgs
    st.session_state[f"pegar_{base_key}__visto"] = imgs[-1] if imgs else None


def _restaurar_imagen_hotel(oid, img_b64):
    if img_b64:
        st.session_state[f"pegar_uph_{oid}"] = f"data:image/png;base64,{img_b64}"


def cargar_cotizacion_en_formulario(datos_json_str: str):
    """Repuebla session_state con una cotización guardada, para editarla o
    recotizar a partir de ella. Reemplaza las opciones actuales del
    formulario (no se combinan). Las imágenes que tenía (capturas de vuelos,
    foto de hotel) se restauran automáticamente si se guardaron con la
    cotización — las guardadas antes de que existiera esto quedan sin
    imagen, hay que volver a adjuntarlas."""
    datos = json.loads(datos_json_str)

    st.session_state["cliente"] = datos.get("cliente") or ""
    if datos.get("fecha_cotiz"):
        st.session_state["fecha_cotiz"] = date.fromisoformat(datos["fecha_cotiz"])
    if datos.get("color_primario"):
        st.session_state["cp"] = datos["color_primario"]
    if datos.get("color_secundario"):
        st.session_state["cs"] = datos["color_secundario"]
    compartir = bool(datos.get("compartir"))
    st.session_state["compartir"] = compartir
    if compartir:
        _restaurar_imagenes_lista("upv_shared", datos.get("vuelos_compartidos_b64"))

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
        if not compartir:
            _restaurar_imagenes_lista(f"upv_{oid}", op.get("imgs_vuelos_b64"))
        _restaurar_imagen_hotel(oid, op.get("img_hotel_b64"))

        servicios_opcion = {s["clave"]: s for s in op.get("servicios") or []}
        for clave, etiqueta, desc_def in INCLUSIONES:
            if clave not in CLAVES_COMPARTIBLES:
                _preset_servicio(f"{clave}_{oid}", servicios_opcion.get(clave), desc_def)

    st.session_state["opciones"] = nuevas_opciones or [{"id": next_id}]
    st.session_state["next_opt_id"] = next_id + (0 if nuevas_opciones else 1)
    # Limpia el PDF/vista previa de una exportación previa para no
    # confundirlo con esta recotización
    st.session_state.pop("pdf_bytes", None)
    st.session_state.pop("pdf_nombre", None)
    st.session_state.pop("pdf_preview_paginas", None)
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
            "y volver a exportarla. Las imágenes que tenía (si se guardaron con ella) "
            "ya quedaron restauradas."
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
                    if st.button("🗑 Borrar", key=f"borrar_{f['id']}", use_container_width=True):
                        st.session_state[f"confirmar_borrar_{f['id']}"] = True

                if st.session_state.get(f"confirmar_borrar_{f['id']}"):
                    st.warning(
                        f"¿Borrar la cotización del {f['fecha_cotiz']}? No se puede deshacer."
                    )
                    cd1, cd2 = st.columns(2)
                    if cd1.button(
                        "Sí, borrar",
                        key=f"borrar_si_{f['id']}",
                        type="primary",
                        use_container_width=True,
                    ):
                        borrar_cotizacion(f["id"])
                        st.session_state.pop(f"confirmar_borrar_{f['id']}", None)
                        st.rerun()
                    if cd2.button("Cancelar", key=f"borrar_no_{f['id']}", use_container_width=True):
                        st.session_state.pop(f"confirmar_borrar_{f['id']}", None)
                        st.rerun()
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
