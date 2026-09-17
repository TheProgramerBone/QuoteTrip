# -*- coding: utf-8 -*-
"""Construye el dibujante de encabezado y pie de página (el "membrete" que
ReportLab repite en cada página vía `onFirstPage`/`onLaterPages`),
parametrizado por `EncabezadoConfig`/`PieConfig` de la plantilla en vez de
estar hardcodeado como en el motor legado (`quotetrip/pdf/legacy.py`)."""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader

# clave en `EncabezadoConfig.lineas_derecha` -> (clave en `glob`, es la línea
# principal/en negrita). Solo "razon_social" es principal — coincide con el
# motor legado, donde razón social siempre iba en negrita y NIT/RNT en gris.
_CAMPOS_ENCABEZADO = {
    "razon_social": ("razon_social", True),
    "nit": ("nit", False),
    "rnt": ("rnt", False),
}
# Etiqueta a anteponer al valor de las líneas no principales — un NIT/RNT
# sin etiquetar es ambiguo en cualquier plantilla, así que esto aplica
# siempre, no solo en "Clásica".
_ETIQUETAS_ENCABEZADO = {"nit": "NIT", "rnt": "RNT"}
_CAMPOS_PIE = {"ciudad": "ciudad", "telefonos": "telefonos", "contacto": "contacto"}


def construir_encabezado_pie(glob: dict, template):
    """Devuelve la función `dibujar(canvas, doc)` que ReportLab invoca en
    cada página (`SimpleDocTemplate.build(..., onFirstPage=dibujar,
    onLaterPages=dibujar)`)."""
    tema = template.tema
    encabezado = template.encabezado
    pie = template.pie
    c_prim = colors.HexColor(tema.color_primario or glob["color_primario"])
    c_sec = colors.HexColor(tema.color_secundario or glob["color_secundario"])
    logo_path = glob.get("logo_path")

    def dibujar(canvas, doc):
        ancho, alto = doc.pagesize
        canvas.saveState()

        # ---- Logo ----
        if encabezado.mostrar_logo and logo_path and Path(logo_path).exists():
            try:
                ir = ImageReader(str(logo_path))
                iw, ih = ir.getSize()
                logo_h = encabezado.logo_alto_cm * cm
                logo_w = logo_h * (iw / ih) if ih else 0
                if encabezado.logo_posicion == "derecha":
                    x = ancho - doc.rightMargin - logo_w
                elif encabezado.logo_posicion == "centro":
                    x = (ancho - logo_w) / 2.0
                else:
                    x = doc.leftMargin
                canvas.drawImage(
                    ir,
                    x,
                    alto - 2.35 * cm,
                    width=logo_w,
                    height=logo_h,
                    mask="auto",
                    preserveAspectRatio=True,
                )
            except Exception:
                pass

        # ---- Datos de la cuenta (bloque alineado a la derecha) ----
        top_y = alto - 1.35 * cm
        linea_actual = 0
        for clave in encabezado.lineas_derecha:
            info = _CAMPOS_ENCABEZADO.get(clave)
            if not info:
                continue
            campo, es_principal = info
            valor = glob.get(campo)
            if not valor:
                continue
            etiqueta = _ETIQUETAS_ENCABEZADO.get(clave)
            # Algunas cuentas ya escriben la etiqueta como parte del propio
            # dato (ej. "NIT 900.123.456-7", como sugiere el placeholder de
            # `auth.py`); otras guardan solo el número pelado. Evita
            # duplicarla ("NIT: NIT 900...") cuando ya está presente.
            if etiqueta and not valor.strip().upper().startswith(etiqueta.upper()):
                texto = f"{etiqueta}: {valor}"
            else:
                texto = valor
            if es_principal:
                color_principal = c_prim if encabezado.color_razon_social == "primario" else c_sec
                canvas.setFillColor(color_principal)
                canvas.setFont("Helvetica-Bold", 10)
            else:
                canvas.setFillColor(colors.HexColor("#333333"))
                canvas.setFont("Helvetica", 9)
            canvas.drawRightString(ancho - doc.rightMargin, top_y - linea_actual * 0.42 * cm, texto)
            linea_actual += 1

        if encabezado.mostrar_linea_separadora:
            canvas.setStrokeColor(c_prim)
            canvas.setLineWidth(1.0)
            canvas.line(doc.leftMargin, alto - 2.75 * cm, ancho - doc.rightMargin, alto - 2.75 * cm)

        # ---- Pie: línea separadora + datos de contacto centrados ----
        if pie.mostrar_linea_separadora:
            canvas.setStrokeColor(c_prim)
            canvas.setLineWidth(1.0)
            canvas.line(doc.leftMargin, 2.45 * cm, ancho - doc.rightMargin, 2.45 * cm)
        canvas.setFillColor(colors.HexColor("#444444"))
        canvas.setFont("Helvetica", 8.5)
        cy = 2.05 * cm
        # Cada campo puede traer varias líneas reales (\n) — p.ej. una
        # cuenta que quiera mostrar dos oficinas o el bloque completo de
        # contacto del diseño original, no solo un dato por campo.
        lineas_pie = []
        for c in pie.lineas:
            valor = glob.get(_CAMPOS_PIE.get(c))
            if not valor:
                continue
            lineas_pie.extend(sub.strip() for sub in valor.split("\n") if sub.strip())
        paso = (
            min(0.38 * cm, 1.2 * cm / max(1, len(lineas_pie) - 1))
            if len(lineas_pie) > 4
            else 0.38 * cm
        )
        for i, linea in enumerate(lineas_pie):
            canvas.drawCentredString(ancho / 2.0, cy - i * paso, linea)

        canvas.restoreState()

    return dibujar
