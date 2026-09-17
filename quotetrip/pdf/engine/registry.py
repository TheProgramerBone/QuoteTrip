# -*- coding: utf-8 -*-
"""Catálogo controlado de tipos de sección y sus funciones de render.

Cada función recibe un `RenderContext` (datos ya resueltos de la opción
actual + estilos) y la `SeccionConfig` de la plantilla (para leer
`config.opciones`, la configuración específica del tipo — p.ej.
`{"layout": "table"}` para "servicios") y devuelve una lista de Flowables
de ReportLab Platypus.

Estas funciones asumen que la plantilla ya pasó por
`quotetrip.pdf.models.validar_plantilla()` — no vuelven a comprobar que las
secciones bloqueadas (`SECCIONES_BLOQUEADAS`) sigan visibles, eso es
responsabilidad exclusiva de la validación, no del render."""

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from ...calculos import formato_moneda
from ...config import NOTA_Y_LEGAL
from ..images import _imagen_flowable, preparar_imagen
from .fonts import nombre_fuente
from .styles import construir_tabla_servicios_style


def _render_fecha(ctx, cfg):
    return [Paragraph(ctx.glob["fecha_cotiz_txt"], ctx.estilos["fecha"])]


def _render_titulo(ctx, cfg):
    return [Paragraph("COTIZACIÓN", ctx.estilos["titulo"])]


def _render_etiqueta_opcion(ctx, cfg):
    flowables = []
    if ctx.varias:
        etiqueta = ctx.op.get("nombre") or f"Opción {ctx.indice + 1}"
        if ctx.op.get("hotel"):
            etiqueta += f" — {ctx.op['hotel']}"
        flowables.append(Paragraph(etiqueta, ctx.estilos["etiqueta_opcion"]))
    # Espaciado fijo tras el bloque de título/etiqueta, haya una opción o
    # varias — igual que el motor legado (`Spacer` incondicional).
    flowables.append(Spacer(1, 0.35 * cm))
    return flowables


def _render_pasajeros(ctx, cfg):
    return [Paragraph(ctx.op["pasajeros_txt"], ctx.estilos["pasajeros"])]


def _render_hotel_fechas(ctx, cfg):
    op = ctx.op
    detallado = (cfg.opciones or {}).get("foto_lateral", False)

    # Sin el formato detallado (todos los presets salvo Clásica): mismo
    # comportamiento de siempre, heredado tal cual del motor legado.
    if not detallado:
        partes = []
        if op.get("hotel"):
            partes.append(op["hotel"])
        if op.get("ida") and op.get("regreso"):
            partes.append(
                f"{op['ida'].strftime('%d/%m/%Y')} al {op['regreso'].strftime('%d/%m/%Y')}"
            )
        if op.get("dias"):
            partes.append(f"{op['dias']} Días / {op['noches']} Noches")
        flowables = []
        if partes:
            flowables.append(Paragraph("  ·  ".join(partes), ctx.estilos["hotel_fechas"]))
        if op.get("hotel_direccion"):
            flowables.append(
                Paragraph(f"Dirección: {op['hotel_direccion']}", ctx.estilos["pasajeros"])
            )
        flowables.append(Spacer(1, 0.2 * cm))
        return flowables

    # Formato detallado (Clásica): línea por línea, fiel al diseño original
    # (referencias/*.pdf, sin contar "PDF ACTUAL.pdf") — nombre del hotel y
    # acomodación en negrita y color secundario, el resto en el tono de
    # texto normal, todo alineado a la izquierda. La sección "pasajeros" va
    # oculta en Clásica (`clasica.json`) porque su texto se fusiona aquí en
    # la misma línea que la cantidad de habitaciones, como en el original
    # ("1 habitación, 1 adulto, 1 menor") — se lee `op["pasajeros_txt"]`
    # directamente en vez de depender de que esa sección se haya renderizado
    # (ambas secciones leen el mismo `ctx.op`, no hay acoplamiento real).
    estilo_texto = ctx.estilos["hotel_fechas"].clone("qt_hf_texto", alignment=TA_LEFT)
    estilo_destacado = estilo_texto.clone(
        "qt_hf_destacado",
        textColor=colors.HexColor(ctx.color_secundario),
        fontName=nombre_fuente(ctx.fuente_id, "bold"),
    )

    columna_texto = []
    if op.get("hotel"):
        columna_texto.append(Paragraph(op["hotel"], estilo_destacado))
    if op.get("hotel_direccion"):
        columna_texto.append(Paragraph(f"Dirección: {op['hotel_direccion']}", estilo_texto))
    if op.get("adultos") is not None:
        # Frase reconstruida a mano (no `op["pasajeros_txt"]`, que trae el
        # prefijo "Pasajeros: " y el conteo total "· N pasajeros" pensados
        # para la sección "pasajeros" independiente, no para fusionarse en
        # esta línea) — misma redacción que el diseño original: "N
        # adulto(s), M menor(es)" o "..., sin menores" si no hay menores.
        adultos, menores = op["adultos"], op.get("menores", 0)
        detalle = [f"{adultos} adulto" + ("s" if adultos != 1 else "")]
        detalle.append(
            f"{menores} menor" + ("es" if menores != 1 else "") if menores else "sin menores"
        )
        habitaciones = op.get("hotel_habitaciones") or 1
        sufijo = "habitación" if habitaciones == 1 else "habitaciones"
        columna_texto.append(
            Paragraph(f"{habitaciones} {sufijo}, {', '.join(detalle)}", estilo_texto)
        )
    if op.get("ida") and op.get("regreso"):
        rango = f"{op['ida'].strftime('%d/%m/%Y')} al {op['regreso'].strftime('%d/%m/%Y')}"
        if op.get("dias"):
            rango += f" · {op['dias']} Días"
        columna_texto.append(Paragraph(rango, estilo_texto))
    if op.get("noches") is not None:
        columna_texto.append(Paragraph(f"Noches: {op['noches']}", estilo_texto))
    if op.get("hotel_acomodacion"):
        columna_texto.append(Paragraph(op["hotel_acomodacion"], estilo_destacado))

    img_hotel_bytes = op.get("img_hotel_bytes")
    if not img_hotel_bytes:
        return columna_texto + [Spacer(1, 0.2 * cm)]

    # Con foto: la foto del hotel va a la derecha, como en el original.
    ruta_hotel = preparar_imagen(img_hotel_bytes, ctx.tmpdir)
    ancho_col_texto = ctx.ancho_util * 0.58
    ancho_col_img = ctx.ancho_util * 0.38
    columna_img = [_imagen_flowable(ruta_hotel, ancho_col_img, alto_max=7 * cm)]

    tabla = Table([[columna_texto, columna_img]], colWidths=[ancho_col_texto, ancho_col_img])
    tabla.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 0.4 * cm),
                ("LEFTPADDING", (1, 0), (1, 0), 0),
                ("RIGHTPADDING", (1, 0), (1, 0), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return [tabla, Spacer(1, 0.2 * cm)]


def _render_precios(ctx, cfg):
    op = ctx.op
    moneda = ctx.glob.get("moneda_salida", "COP")
    flowables = []
    tarifa_dif = op.get("tarifa_menor_dif") and op.get("menores", 0) > 0
    if tarifa_dif:
        flowables.append(
            Paragraph(
                f"Valor por pasajero adulto: {formato_moneda(op['valor_pasajero'], moneda)}",
                ctx.estilos["precios"],
            )
        )
        flowables.append(
            Paragraph(
                f"Valor por pasajero menor (12 años o menos): "
                f"{formato_moneda(op['valor_pasajero_menor'], moneda)}",
                # Reutiliza el estilo "pasajeros" (gris, centrado, pequeño):
                # visualmente idéntico al `est_sub` que usaba el motor
                # legado para esta misma línea.
                ctx.estilos["pasajeros"],
            )
        )
    else:
        flowables.append(
            Paragraph(
                f"VALOR TOTAL X PASAJERO: {formato_moneda(op['valor_pasajero'], moneda)}",
                ctx.estilos["precios"],
            )
        )
    if op["personas"] > 1:
        flowables.append(
            Paragraph(
                f"VALOR TOTAL {op['personas']} PASAJEROS: "
                f"{formato_moneda(op['total_grupo'], moneda)}",
                ctx.estilos["precios_grupo"],
            )
        )
    return flowables


def _render_servicios(ctx, cfg):
    op = ctx.op
    moneda = ctx.glob.get("moneda_salida", "COP")
    layout = (cfg.opciones or {}).get("layout", "text")
    servicios = op.get("servicios")
    if layout == "table" and servicios:
        filas = [["Servicio", "Valor"]]
        for s in servicios:
            monto_total = s.get("monto", 0) + s.get("comision", 0)
            desc = s.get("desc") or s.get("etiqueta") or ""
            filas.append([desc, formato_moneda(monto_total, moneda)])
        tabla = Table(filas, colWidths=[ctx.ancho_util * 0.72, ctx.ancho_util * 0.28])
        tabla.setStyle(construir_tabla_servicios_style(ctx.color_primario))
        return [tabla, Spacer(1, 10)]
    # Modo texto (por defecto), o degradación elegante si se pidió "table"
    # pero no hay lista `servicios` cruda disponible (cotizaciones/
    # plantillas de antes de que ese campo existiera) — nunca rompe el PDF
    # por faltar ese dato, solo se pierde la tabla.
    return [Paragraph(op.get("incluye", "Incluye: —"), ctx.estilos["servicios"])]


def _render_nota_legal(ctx, cfg):
    return [Paragraph(NOTA_Y_LEGAL, ctx.estilos["nota_legal"])]


def _render_firma(ctx, cfg):
    glob = ctx.glob
    estilo = ctx.estilos["firma"]
    estilo_bold = estilo.clone("qt_firma_bold", fontName=nombre_fuente(ctx.fuente_id, "bold"))
    return [
        Spacer(1, 0.4 * cm),
        Paragraph("Cordialmente,", estilo),
        Spacer(1, 1.0 * cm),
        Paragraph(glob.get("firma_nombre") or "", estilo_bold),
        Paragraph(glob.get("firma_cargo") or "", estilo),
    ]


def _render_anexos(ctx, cfg):
    op = ctx.op
    opciones = cfg.opciones or {}
    incluir_foto_hotel = opciones.get("incluir_foto_hotel", True)
    # Clásica reubica esta sección justo debajo del bloque de hotel (antes
    # de precios/servicios/nota/firma, como en el original) y ahí no hay
    # encabezado "Anexos"/"Itinerario de vuelos" — es la tabla de vuelos
    # sola, sin rótulo. Otros presets (donde esta sección sigue al final,
    # como "anexo" de verdad) conservan el título por defecto.
    mostrar_titulo = opciones.get("mostrar_titulo", True)
    alto_max_cm = opciones.get("alto_max_imagen_cm")
    alto_max = alto_max_cm * cm if alto_max_cm else 19 * cm

    rutas_vuelos = [preparar_imagen(b, ctx.tmpdir) for b in op.get("imgs_vuelos_bytes", [])]
    ruta_hotel = (
        preparar_imagen(op["img_hotel_bytes"], ctx.tmpdir)
        if incluir_foto_hotel and op.get("img_hotel_bytes")
        else None
    )
    if not rutas_vuelos and not ruta_hotel:
        return []

    if mostrar_titulo:
        flowables = [Spacer(1, 0.4 * cm), Paragraph("Anexos", ctx.estilos["anexos"])]
    else:
        flowables = [Spacer(1, 0.2 * cm)]
    if rutas_vuelos:
        if mostrar_titulo:
            titulo = "Itinerario de vuelos" if len(rutas_vuelos) == 1 else "Itinerarios de vuelos"
            flowables.append(Paragraph(titulo, ctx.estilos["anexos_caption"]))
        for ruta in rutas_vuelos:
            flowables.append(_imagen_flowable(ruta, ctx.ancho_util, alto_max=alto_max))
            flowables.append(Spacer(1, 0.3 * cm))
    if ruta_hotel:
        if mostrar_titulo:
            flowables.append(Paragraph("Hotel", ctx.estilos["anexos_caption"]))
        flowables.append(_imagen_flowable(ruta_hotel, ctx.ancho_util, alto_max=alto_max))
    return flowables


SECTION_RENDERERS = {
    "fecha": _render_fecha,
    "titulo": _render_titulo,
    "etiqueta_opcion": _render_etiqueta_opcion,
    "pasajeros": _render_pasajeros,
    "hotel_fechas": _render_hotel_fechas,
    "precios": _render_precios,
    "servicios": _render_servicios,
    "nota_legal": _render_nota_legal,
    "firma": _render_firma,
    "anexos": _render_anexos,
}
