# -*- coding: utf-8 -*-
"""Catálogo controlado de campos dinámicos que un elemento de texto libre
puede referenciar (Fase "Texto dinámico" del editor visual). Nunca eval/
exec: cada clave del catálogo mapea a una función que solo hace un
`dict.get()` sobre `glob` — el mismo diccionario que ya recibe todo el
motor de render (ver `RenderContext`/`renderer.renderizar_plantilla`), no
un sistema nuevo de acceso a datos.

Alcance deliberado: solo campos de nivel documento (cliente, agencia,
fecha de la cotización) — NO de una opción concreta (destino, fechas de
viaje, hotel, precios...). Encabezado/pie/elementos libres se dibujan
mediante los hooks `onFirstPage`/`onLaterPages` de ReportLab, con el MISMO
callback en todas las páginas del documento; hoy no hay forma de saber ahí
"esta página es la opción 2 de 3" sin una reescritura mayor de
`renderer.py` (mapear páginas reales de Platypus, generadas en su propio
pase de layout dentro de `doc.build()`, a la opción que las originó). Ver
plan de fases — cuando exista esa arquitectura, aquí es donde se añadirían
los campos por-opción."""

CAMPOS_DINAMICOS: dict[str, tuple[str, "callable"]] = {
    "cliente.nombre": ("Cliente ▸ Nombre", lambda glob: glob.get("cliente")),
    "cotizacion.fecha": ("Cotización ▸ Fecha", lambda glob: glob.get("fecha_cotiz_txt")),
    "agencia.razon_social": ("Agencia ▸ Razón social", lambda glob: glob.get("razon_social")),
    "agencia.nit": ("Agencia ▸ NIT", lambda glob: glob.get("nit")),
    "agencia.rnt": ("Agencia ▸ RNT", lambda glob: glob.get("rnt")),
    "agencia.ciudad": ("Agencia ▸ Ciudad", lambda glob: glob.get("ciudad")),
    "agencia.telefonos": ("Agencia ▸ Teléfonos", lambda glob: glob.get("telefonos")),
    "agencia.contacto": ("Agencia ▸ Contacto", lambda glob: glob.get("contacto")),
    "agencia.firma_nombre": (
        "Agencia ▸ Nombre del firmante",
        lambda glob: glob.get("firma_nombre"),
    ),
    "agencia.firma_cargo": ("Agencia ▸ Cargo del firmante", lambda glob: glob.get("firma_cargo")),
}


def etiqueta_campo(clave: str) -> str:
    """Nombre amigable de una clave del catálogo (la propia clave si no
    está registrada — p.ej. un JSON de una versión futura con un campo
    que esta versión todavía no conoce)."""
    entrada = CAMPOS_DINAMICOS.get(clave)
    return entrada[0] if entrada else clave


def resolver_campo(clave: str, glob: dict) -> str | None:
    """Valor real del campo `clave` a partir de `glob`, o `None` si la
    clave no existe en el catálogo, el dato no está presente, o la
    resolución falla por cualquier motivo — nunca lanza excepción (misma
    filosofía de degradación elegante que el resto del motor de render:
    un dato dinámico que no resuelve se omite, no rompe el PDF)."""
    entrada = CAMPOS_DINAMICOS.get(clave)
    if not entrada:
        return None
    try:
        valor = entrada[1](glob or {})
    except Exception:
        return None
    return str(valor) if valor not in (None, "") else None
