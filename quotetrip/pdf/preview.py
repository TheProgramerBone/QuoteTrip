# -*- coding: utf-8 -*-
"""Vista previa del editor de plantillas: genera el PDF de muestra con el
MISMO motor que el PDF final (`quotetrip.pdf.engine.renderizar_plantilla`
— nunca un segundo sistema de layout independiente) y lo rasteriza a PNG
con `pypdfium2` para mostrarlo en Streamlit vía `st.image`.

Los datos de muestra son ficticios (cliente/destino/fechas de ejemplo),
pero la identidad visual (logo, colores, razón social, NIT/RNT, firma) es
la real de la cuenta, para que la vista previa se sienta representativa."""

import io
from datetime import date

import pypdfium2 as pdfium

from ..calculos import calcular_opcion, fecha_en_espanol, texto_pasajeros
from .engine.renderer import renderizar_plantilla

_SERVICIOS_MUESTRA = [
    {
        "clave": "vuelos",
        "etiqueta": "Vuelos",
        "desc": "Vuelos ida y vuelta Bogotá - Cartagena",
        "monto": 850000,
        "comision": 0,
        "base": "persona",
    },
    {
        "clave": "hotel",
        "etiqueta": "Hotel",
        "desc": "Hotel Ejemplo Todo Incluido",
        "monto": 1200000,
        "comision": 0,
        "base": "persona",
    },
    {
        "clave": "traslados",
        "etiqueta": "Traslados",
        "desc": "Traslados aeropuerto-hotel",
        "monto": 120000,
        "comision": 0,
        "base": "total",
    },
]


def _glob_de_muestra(cuenta: dict) -> dict:
    cuenta = cuenta or {}
    return {
        "cliente": "Cliente de ejemplo",
        "fecha_cotiz_txt": fecha_en_espanol(date.today()),
        "color_primario": cuenta.get("color_primario") or "#2563EB",
        "color_secundario": cuenta.get("color_secundario") or "#1E3A8A",
        "razon_social": cuenta.get("razon_social") or "Tu agencia de viajes",
        "nit": cuenta.get("nit") or "",
        "rnt": cuenta.get("rnt") or "",
        "ciudad": cuenta.get("ciudad") or "",
        "telefonos": cuenta.get("telefonos") or "",
        "contacto": cuenta.get("contacto") or "",
        "logo_path": cuenta.get("logo_path"),
        "firma_nombre": cuenta.get("firma_nombre") or "Nombre del asesor",
        "firma_cargo": cuenta.get("firma_cargo") or "Asesor de viajes",
    }


def _opciones_de_muestra() -> list:
    calc = calcular_opcion(2, 0, False, 0, _SERVICIOS_MUESTRA)
    return [
        {
            "nombre": "Plan Cartagena Clásico",
            "hotel": "Hotel Ejemplo",
            "ida": date.today(),
            "regreso": date.today(),
            "dias": 5,
            "noches": 4,
            "adultos": 2,
            "menores": 0,
            "tarifa_menor_dif": False,
            "pasajeros_txt": texto_pasajeros(2, 0),
            "imgs_vuelos_bytes": [],
            "img_hotel_bytes": None,
            "servicios": _SERVICIOS_MUESTRA,
            **calc,
        }
    ]


def _rasterizar_pagina(pdf_bytes: bytes, pagina: int, dpi: int) -> bytes:
    documento = pdfium.PdfDocument(pdf_bytes)
    try:
        n_paginas = len(documento)
        indice = max(0, min(pagina, n_paginas - 1))
        bitmap = documento[indice].render(scale=dpi / 72.0)
        imagen = bitmap.to_pil()
        buf = io.BytesIO()
        imagen.save(buf, format="PNG")
        return buf.getvalue()
    finally:
        documento.close()


def renderizar_previsualizacion(template, cuenta: dict, pagina: int = 0, dpi: int = 110) -> bytes:
    """Devuelve PNG bytes de la página `pagina` (0-indexada) del PDF de
    muestra generado con `template` y los datos de la cuenta. Misma fuente
    de verdad que el PDF final: si esto se ve bien, el PDF exportado se ve
    igual."""
    pdf_bytes = renderizar_plantilla(template, _glob_de_muestra(cuenta), _opciones_de_muestra())
    return _rasterizar_pagina(pdf_bytes, pagina, dpi)


def rasterizar_pdf(pdf_bytes: bytes, dpi: int = 110) -> list[bytes]:
    """Rasteriza TODAS las páginas de un PDF ya generado (el real, no uno de
    muestra) a una lista de PNG bytes — usado por el botón "Previsualizar"
    antes de exportar, para mostrar exactamente lo que va a salir sin tener
    que guardarlo primero."""
    documento = pdfium.PdfDocument(pdf_bytes)
    try:
        paginas_png = []
        for pagina in documento:
            bitmap = pagina.render(scale=dpi / 72.0)
            buf = io.BytesIO()
            bitmap.to_pil().save(buf, format="PNG")
            paginas_png.append(buf.getvalue())
        return paginas_png
    finally:
        documento.close()
