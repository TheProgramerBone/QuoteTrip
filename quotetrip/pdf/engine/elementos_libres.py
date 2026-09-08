# -*- coding: utf-8 -*-
"""Dibuja los `ElementoLibre` (texto/imagen/forma de posición libre) de una
plantilla sobre el canvas, en cada página — mismo punto de enganche que
encabezado/pie (`engine/encabezado.py`): `onFirstPage`/`onLaterPages`.

Por eso, igual que el encabezado/pie, los elementos libres quedan siempre
DETRÁS del contenido de la cotización (ReportLab dibuja primero el canvas
de la página, el `story` de Platypus se pinta encima) — `z_index` solo
ordena entre elementos libres entre sí, ver `ElementoLibre` en
`quotetrip.pdf.models.template`.

Coordenadas: `x_cm`/`y_cm` vienen medidas desde la esquina superior
izquierda de la página (ver esa misma docstring); aquí es donde se
convierten al sistema nativo de ReportLab (origen inferior izquierdo)."""

import base64
import io

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Frame, Paragraph

from ..models.bindings import resolver_campo
from .fonts import nombre_fuente

_ALINEACION_A_TA = {"izquierda": TA_LEFT, "centro": TA_CENTER, "derecha": TA_RIGHT}


def _rect_reportlab(el, alto_pagina_pt: float):
    """(x, y, ancho, alto) en puntos, sistema ReportLab (origen inferior
    izquierdo) — a partir de x_cm/y_cm (origen superior izquierdo)."""
    ancho = el.ancho_cm * cm
    alto = el.alto_cm * cm
    x = el.x_cm * cm
    y = alto_pagina_pt - (el.y_cm * cm) - alto
    return x, y, ancho, alto


def _dibujar_texto(c, el, x, y, ancho, alto, datos):
    op = el.opciones or {}
    fuente = nombre_fuente(op.get("fuente_id"), "bold" if op.get("peso") == "bold" else "normal")
    tamano = float(op.get("tamano_pt") or 10.5)
    estilo = ParagraphStyle(
        "qt_elemento_texto",
        fontName=fuente,
        fontSize=tamano,
        leading=tamano * float(op.get("interlineado") or 1.15),
        alignment=_ALINEACION_A_TA.get(op.get("alineacion"), TA_LEFT),
        textColor=colors.HexColor(op.get("color") or "#000000"),
    )
    # Un dato dinámico (binding) tiene prioridad sobre el texto libre — ver
    # `ElementoLibre` en `pdf/models/template.py`. Si no resuelve (falta el
    # dato, o `datos` no llegó — p.ej. una llamada vieja sin ese
    # parámetro), se dibuja vacío, nunca el texto literal: mostrar
    # "{{cliente.nombre}}" tal cual sería peor que no mostrar nada.
    binding = op.get("binding")
    texto = (resolver_campo(binding, datos) or "") if binding else (op.get("texto") or "").strip()
    if not texto:
        return
    frame = Frame(
        x,
        y,
        ancho,
        alto,
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
        showBoundary=0,
    )
    # Texto que no cabe en la caja se recorta (degradación elegante: nunca
    # rompe el PDF, y `validar_plantilla` no puede saber si cabrá sin medir
    # texto real — es responsabilidad del usuario agrandar la caja si lo ve
    # cortado en la vista previa).
    frame.addFromList([Paragraph(texto, estilo)], c)


def _dibujar_forma(c, el, x, y, ancho, alto, datos):
    op = el.opciones or {}
    forma = op.get("forma", "rectangulo")
    relleno = op.get("color_relleno")
    borde = op.get("color_borde")
    hay_relleno = bool(relleno)
    hay_borde = bool(borde)
    if not hay_relleno and not hay_borde:
        return
    if hay_relleno:
        c.setFillColor(colors.HexColor(relleno))
    if hay_borde:
        c.setStrokeColor(colors.HexColor(borde))
        c.setLineWidth(float(op.get("grosor_borde_pt") or 1.0))

    if forma == "linea":
        c.setStrokeColor(colors.HexColor(borde or relleno))
        c.setLineWidth(float(op.get("grosor_borde_pt") or 1.0))
        c.line(x, y, x + ancho, y + alto)
    elif forma == "elipse":
        c.ellipse(x, y, x + ancho, y + alto, fill=hay_relleno, stroke=hay_borde)
    elif forma == "rectangulo_redondeado":
        radio = min(float(op.get("radio_cm") or 0.3) * cm, ancho / 2, alto / 2)
        c.roundRect(x, y, ancho, alto, radio, fill=hay_relleno, stroke=hay_borde)
    else:
        c.rect(x, y, ancho, alto, fill=hay_relleno, stroke=hay_borde)


def _dibujar_imagen(c, el, x, y, ancho, alto, datos):
    op = el.opciones or {}
    datos_b64 = op.get("imagen_b64")
    if not datos_b64:
        return
    try:
        ir = ImageReader(io.BytesIO(base64.b64decode(datos_b64)))
        iw, ih = ir.getSize()
    except Exception:
        return  # imagen corrupta/ilegible: se omite, nunca rompe el PDF
    if not iw or not ih:
        return

    ajuste = op.get("ajuste", "contain")
    if ajuste == "stretch":
        c.drawImage(ir, x, y, width=ancho, height=alto, mask="auto")
        return

    ratio_caja = ancho / alto if alto else 1.0
    ratio_img = iw / ih
    if ajuste == "cover":
        draw_w, draw_h = (
            (alto * ratio_img, alto) if ratio_img > ratio_caja else (ancho, ancho / ratio_img)
        )
        c.saveState()
        recorte = c.beginPath()
        recorte.rect(x, y, ancho, alto)
        c.clipPath(recorte, stroke=0, fill=0)
        c.drawImage(
            ir,
            x + (ancho - draw_w) / 2,
            y + (alto - draw_h) / 2,
            width=draw_w,
            height=draw_h,
            mask="auto",
        )
        c.restoreState()
    else:  # "contain" (por defecto): nunca deforma ni recorta
        draw_w, draw_h = (
            (ancho, ancho / ratio_img) if ratio_img > ratio_caja else (alto * ratio_img, alto)
        )
        c.drawImage(
            ir,
            x + (ancho - draw_w) / 2,
            y + (alto - draw_h) / 2,
            width=draw_w,
            height=draw_h,
            mask="auto",
        )


_DIBUJANTES = {"texto": _dibujar_texto, "forma": _dibujar_forma, "imagen": _dibujar_imagen}


def dibujar_elementos_libres(
    c,
    template,
    alto_pagina_pt: float,
    datos: dict | None = None,
    es_primera_pagina: bool = True,
) -> None:
    """Dibuja `template.elementos` visibles, en orden de `z_index`
    ascendente (los de mayor z_index quedan encima de los demás elementos
    libres — nunca encima del contenido de la cotización, ver docstring
    del módulo). Un elemento roto (imagen ilegible, color corrupto que
    `validar_plantilla` no haya limpiado, etc.) se omite sin tumbar el PDF.

    `datos`: el `glob` de la cotización (ver `renderer.renderizar_plantilla`),
    para resolver los `binding` de texto dinámico — ver `_dibujar_texto` y
    `pdf/models/bindings.py`. `None` (el default) hace que cualquier
    binding quede sin resolver (texto vacío), nunca una excepción.

    `es_primera_pagina`: filtra por `el.aplicar_en` ("todas" siempre pasa;
    "primera" solo si es `True`; "siguientes" solo si es `False`) — ver
    `APLICAR_EN_CATALOGO` en `pdf/models/template.py`. `renderer.py` llama
    esta función una vez por cada hook `onFirstPage`/`onLaterPages` de
    ReportLab, pasando el valor correspondiente."""
    visibles = [
        e
        for e in template.elementos
        if e.visible
        and (
            e.aplicar_en == "todas"
            or (e.aplicar_en == "primera" and es_primera_pagina)
            or (e.aplicar_en == "siguientes" and not es_primera_pagina)
        )
    ]
    for el in sorted(visibles, key=lambda e: e.z_index):
        dibujante = _DIBUJANTES.get(el.tipo)
        if dibujante is None:
            continue
        x, y, ancho, alto = _rect_reportlab(el, alto_pagina_pt)
        if ancho <= 0 or alto <= 0:
            continue
        c.saveState()
        try:
            opacidad = el.opacidad if isinstance(el.opacidad, (int, float)) else 1.0
            c.setFillAlpha(min(max(opacidad, 0.0), 1.0))
            c.setStrokeAlpha(min(max(opacidad, 0.0), 1.0))
            if el.rotacion_grados:
                cx, cy = x + ancho / 2, y + alto / 2
                c.translate(cx, cy)
                c.rotate(el.rotacion_grados)
                c.translate(-cx, -cy)
            dibujante(c, el, x, y, ancho, alto, datos)
        except Exception:
            pass
        finally:
            c.restoreState()
