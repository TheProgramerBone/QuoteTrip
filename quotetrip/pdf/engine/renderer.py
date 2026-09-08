# -*- coding: utf-8 -*-
"""Motor de render: interpreta una `TemplateDefinition`
(`quotetrip.pdf.models`) sobre `glob`/`opciones` (misma forma que siempre —
ver `quotetrip/pdf/legacy.py` y `quotetrip/cotizacion_ui.py` para el
contrato exacto) y produce el PDF final con ReportLab Platypus."""

import io
import tempfile

from reportlab.lib.pagesizes import A4, LETTER, landscape
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, SimpleDocTemplate

from .context import RenderContext
from .elementos_libres import dibujar_elementos_libres
from .encabezado import construir_encabezado_pie
from .registry import SECTION_RENDERERS
from .styles import construir_estilos

_TAMANOS_PAGINA = {"A4": A4, "Carta": LETTER}


def _resolver_pagesize(pagina):
    base = _TAMANOS_PAGINA.get(pagina.tamano, A4)
    return landscape(base) if pagina.orientacion == "horizontal" else base


def renderizar_plantilla(template, glob: dict, opciones: list) -> bytes:
    """Genera el PDF de la cotización según `template` (instancia de
    `TemplateDefinition`, ya validada — ver
    `quotetrip.pdf.models.validar_plantilla`)."""
    buffer = io.BytesIO()
    pagesize = _resolver_pagesize(template.pagina)
    doc = SimpleDocTemplate(
        buffer,
        pagesize=pagesize,
        topMargin=template.pagina.margen_sup_cm * cm,
        bottomMargin=template.pagina.margen_inf_cm * cm,
        leftMargin=template.pagina.margen_izq_cm * cm,
        rightMargin=template.pagina.margen_der_cm * cm,
        title=f"Cotización - {glob['cliente']}",
        author=glob.get("razon_social") or "",
    )
    ancho_util = doc.width

    estilos = construir_estilos(template, glob)
    color_primario = template.tema.color_primario or glob["color_primario"]
    color_secundario = template.tema.color_secundario or glob["color_secundario"]

    secciones_visibles = [s for s in template.secciones if s.visible]
    varias = len(opciones) > 1
    story = []

    with tempfile.TemporaryDirectory() as tmpdir:
        for i, op in enumerate(opciones):
            if i > 0:
                story.append(PageBreak())
            ctx = RenderContext(
                glob=glob,
                op=op,
                estilos=estilos,
                fuente_id=template.tema.fuente_id,
                color_primario=color_primario,
                color_secundario=color_secundario,
                ancho_util=ancho_util,
                varias=varias,
                indice=i,
                tmpdir=tmpdir,
            )
            for seccion in secciones_visibles:
                render_fn = SECTION_RENDERERS.get(seccion.tipo)
                if render_fn is None:
                    continue  # tipo desconocido: validar_plantilla() ya lo filtra
                story.extend(render_fn(ctx, seccion))

        dibujar_encabezado_pie = construir_encabezado_pie(glob, template)

        def _dibujar(canvas, doc, es_primera_pagina: bool):
            # Elementos libres primero (quedan de fondo), encabezado/pie
            # encima — ambos se pintan antes que el `story` de la
            # cotización, que ReportLab dibuja por su cuenta sobre esto.
            # `glob` es el mismo en todas las páginas (nivel documento, no
            # por-opción) — ver el alcance deliberado documentado en
            # `pdf/models/bindings.py`.
            dibujar_elementos_libres(
                canvas, template, doc.pagesize[1], datos=glob, es_primera_pagina=es_primera_pagina
            )
            dibujar_encabezado_pie(canvas, doc)

        # Dos hooks en vez de uno: son el punto donde ReportLab YA sabe
        # distinguir portada de las siguientes páginas sin que nosotros
        # tengamos que rastrear a qué opción pertenece cada una — ver
        # `aplicar_en` en `ElementoLibre` (pdf/models/template.py).
        doc.build(
            story,
            onFirstPage=lambda c, d: _dibujar(c, d, es_primera_pagina=True),
            onLaterPages=lambda c, d: _dibujar(c, d, es_primera_pagina=False),
        )

    buffer.seek(0)
    return buffer.getvalue()
