# -*- coding: utf-8 -*-
"""Motor de render de plantillas — Fase 2 del sistema de plantillas PDF.

Cubre: los 5 presets generan PDF válido, una plantilla personalizada con
secciones ocultas/reordenadas funciona, cotizaciones largas (varias
páginas) no rompen, el layout de tabla de servicios funciona, y la firma
histórica sin `template` (regresión) sigue funcionando."""

import base64
import io

from PIL import Image
from pypdf import PdfReader

from quotetrip.pdf import construir_pdf
from quotetrip.pdf.engine.renderer import renderizar_plantilla
from quotetrip.pdf.models import ElementoLibre, SeccionConfig, TemplateDefinition, validar_plantilla
from quotetrip.pdf.presets import listar_presets, obtener_preset

# PNG 1x1 rojo válido — el mínimo necesario para ejercitar el camino real de
# `_dibujar_imagen` (decodificar base64 + `ImageReader`), sin depender de un
# archivo de fixture aparte.
_PNG_1X1_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgAAIAAAUAAen63NgAAAAASUVORK5CYII="
)


def _texto(pdf_bytes: bytes) -> str:
    lector = PdfReader(io.BytesIO(pdf_bytes))
    return " ".join(" ".join((p.extract_text() or "").split()) for p in lector.pages)


def _texto_por_pagina(pdf_bytes: bytes) -> list[str]:
    lector = PdfReader(io.BytesIO(pdf_bytes))
    return [" ".join((p.extract_text() or "").split()) for p in lector.pages]


def test_construir_pdf_sin_template_usa_clasica(glob_de_prueba, opcion_de_prueba):
    """Regresión: la firma histórica exacta de `cotizacion_ui.py:415` (sin
    argumento `template`) debe seguir funcionando tal cual."""
    pdf_bytes = construir_pdf(glob_de_prueba, [opcion_de_prueba()])
    assert pdf_bytes[:5] == b"%PDF-"


def test_todos_los_presets_generan_pdf_valido(glob_de_prueba, opcion_de_prueba):
    opciones = [opcion_de_prueba()]
    for preset in listar_presets():
        pdf_bytes = renderizar_plantilla(preset, glob_de_prueba, opciones)
        assert pdf_bytes[:5] == b"%PDF-", f"preset {preset.id} no generó un PDF válido"
        assert len(PdfReader(io.BytesIO(pdf_bytes)).pages) == 1


def test_preset_profesional_usa_tabla_de_servicios(glob_de_prueba, opcion_de_prueba):
    """El preset "Profesional" usa `layout: "table"` para servicios — debe
    incluir las descripciones de los servicios en el texto extraído
    (misma fuente de datos que el modo texto, solo cambia la presentación)."""
    profesional = obtener_preset("profesional")
    pdf_bytes = renderizar_plantilla(profesional, glob_de_prueba, [opcion_de_prueba()])
    texto = _texto(pdf_bytes)
    assert "Vuelos ida y vuelta" in texto
    assert "Traslados aeropuerto-hotel" in texto


def test_varias_opciones_generan_varias_paginas(glob_de_prueba, opcion_de_prueba):
    opciones = [
        opcion_de_prueba("Plan A", "Hotel Caribe", 2, 0, False),
        opcion_de_prueba("Plan B", "Hotel Decameron", 2, 1, True),
        opcion_de_prueba("Plan C", "Hotel Zuana", 4, 2, False),
    ]
    pdf_bytes = construir_pdf(glob_de_prueba, opciones)
    assert len(PdfReader(io.BytesIO(pdf_bytes)).pages) == 3


def test_cotizacion_larga_no_rompe(glob_de_prueba, opcion_de_prueba):
    """Una opción con una lista de servicios/inclusiones larga (texto que
    puede desbordar una página) debe seguir generando un PDF válido —
    Platypus reparte el contenido en más páginas automáticamente."""
    op = opcion_de_prueba()
    op["incluye"] = "Incluye: " + " + ".join(f"Servicio adicional número {i}" for i in range(80))
    pdf_bytes = construir_pdf(glob_de_prueba, [op])
    assert pdf_bytes[:5] == b"%PDF-"
    assert len(PdfReader(io.BytesIO(pdf_bytes)).pages) >= 1


# ----------------------------------------------------------------------
# Elementos libres (Fase 2 del editor de plantillas)
# ----------------------------------------------------------------------
def test_elemento_texto_aparece_en_el_pdf(glob_de_prueba, opcion_de_prueba):
    plantilla = obtener_preset("clasica")
    plantilla.elementos = [
        ElementoLibre(
            tipo="texto",
            x_cm=1,
            y_cm=1,
            ancho_cm=6,
            alto_cm=2,
            opciones={"texto": "Oferta de temporada"},
        )
    ]
    validar_plantilla(plantilla)
    pdf_bytes = renderizar_plantilla(plantilla, glob_de_prueba, [opcion_de_prueba()])
    assert "Oferta de temporada" in _texto(pdf_bytes)


def test_elemento_forma_e_imagen_no_rompen_el_pdf(glob_de_prueba, opcion_de_prueba):
    """Formas (con y sin colores) y una imagen válida en base64 se dibujan
    sin lanzar excepción — no hay forma sencilla de verificar píxeles desde
    `pypdf`, así que aquí solo se confirma que el PDF sigue siendo válido."""
    plantilla = obtener_preset("clasica")
    plantilla.elementos = [
        ElementoLibre(
            tipo="forma",
            rotacion_grados=10,
            opciones={
                "forma": "rectangulo_redondeado",
                "color_relleno": "#EEEEEE",
                "color_borde": "#2563EB",
            },
        ),
        ElementoLibre(tipo="forma", opciones={"forma": "linea", "color_borde": "#000000"}),
        ElementoLibre(
            tipo="forma", opciones={"forma": "elipse"}
        ),  # sin colores: no dibuja nada, no falla
        ElementoLibre(
            tipo="imagen", opacidad=0.4, opciones={"imagen_b64": _PNG_1X1_B64, "ajuste": "cover"}
        ),
    ]
    validar_plantilla(plantilla)
    pdf_bytes = renderizar_plantilla(plantilla, glob_de_prueba, [opcion_de_prueba()])
    assert pdf_bytes[:5] == b"%PDF-"


def test_elemento_imagen_con_datos_corruptos_se_omite(glob_de_prueba, opcion_de_prueba):
    """Un `imagen_b64` que no decodifica a una imagen válida no debe
    romper el PDF — degradación elegante, igual que el resto del motor."""
    plantilla = obtener_preset("clasica")
    plantilla.elementos = [
        ElementoLibre(tipo="imagen", opciones={"imagen_b64": "esto-no-es-base64-de-una-imagen"})
    ]
    pdf_bytes = renderizar_plantilla(plantilla, glob_de_prueba, [opcion_de_prueba()])
    assert pdf_bytes[:5] == b"%PDF-"


def test_elemento_texto_con_binding_resuelve_dato_real(glob_de_prueba, opcion_de_prueba):
    """Un elemento de texto con `binding` dibuja el dato real de `glob`
    («Cliente de Prueba» en el fixture), nunca el texto literal guardado
    (que aquí ni siquiera se puso, para dejar claro que no se usa)."""
    plantilla = obtener_preset("clasica")
    plantilla.elementos = [
        ElementoLibre(tipo="texto", opciones={"binding": "cliente.nombre"}),
    ]
    validar_plantilla(plantilla)
    pdf_bytes = renderizar_plantilla(plantilla, glob_de_prueba, [opcion_de_prueba()])
    assert "Cliente de Prueba" in _texto(pdf_bytes)


def test_elemento_texto_con_binding_desconocido_no_rompe(glob_de_prueba, opcion_de_prueba):
    """Un binding que `validar_plantilla` no limpió (p.ej. un JSON escrito
    a mano) simplemente no resuelve — no debe romper el PDF ni mostrar
    nada."""
    plantilla = obtener_preset("clasica")
    plantilla.elementos = [
        ElementoLibre(tipo="texto", opciones={"binding": "algo.inventado", "texto": "Fallback"}),
    ]
    pdf_bytes = renderizar_plantilla(plantilla, glob_de_prueba, [opcion_de_prueba()])
    assert pdf_bytes[:5] == b"%PDF-"
    assert "Fallback" not in _texto(pdf_bytes)  # binding manda, no cae al texto literal


def test_elemento_solo_en_primera_pagina(glob_de_prueba, opcion_de_prueba):
    """`aplicar_en="primera"` aprovecha onFirstPage/onLaterPages de
    ReportLab: aparece en la portada, no en las siguientes páginas."""
    plantilla = obtener_preset("clasica")
    plantilla.elementos = [
        ElementoLibre(tipo="texto", aplicar_en="primera", opciones={"texto": "SoloPortada"})
    ]
    validar_plantilla(plantilla)
    opciones = [
        opcion_de_prueba("Plan A"),
        opcion_de_prueba("Plan B"),
    ]
    pdf_bytes = construir_pdf(glob_de_prueba, opciones, template=plantilla)
    paginas = _texto_por_pagina(pdf_bytes)
    assert len(paginas) == 2
    assert "SoloPortada" in paginas[0]
    assert "SoloPortada" not in paginas[1]


def test_elemento_en_todas_menos_la_primera(glob_de_prueba, opcion_de_prueba):
    plantilla = obtener_preset("clasica")
    plantilla.elementos = [
        ElementoLibre(tipo="texto", aplicar_en="siguientes", opciones={"texto": "DesdePagina2"})
    ]
    validar_plantilla(plantilla)
    opciones = [opcion_de_prueba("Plan A"), opcion_de_prueba("Plan B")]
    pdf_bytes = construir_pdf(glob_de_prueba, opciones, template=plantilla)
    paginas = _texto_por_pagina(pdf_bytes)
    assert "DesdePagina2" not in paginas[0]
    assert "DesdePagina2" in paginas[1]


def test_elemento_en_todas_las_paginas_por_defecto(glob_de_prueba, opcion_de_prueba):
    plantilla = obtener_preset("clasica")
    plantilla.elementos = [ElementoLibre(tipo="texto", opciones={"texto": "SiempreVisible"})]
    validar_plantilla(plantilla)
    assert plantilla.elementos[0].aplicar_en == "todas"
    opciones = [opcion_de_prueba("Plan A"), opcion_de_prueba("Plan B")]
    pdf_bytes = construir_pdf(glob_de_prueba, opciones, template=plantilla)
    paginas = _texto_por_pagina(pdf_bytes)
    assert all("SiempreVisible" in p for p in paginas)


def test_elemento_oculto_no_se_dibuja(glob_de_prueba, opcion_de_prueba):
    plantilla = obtener_preset("clasica")
    plantilla.elementos = [
        ElementoLibre(tipo="texto", visible=False, opciones={"texto": "NoDeberiaAparecer"})
    ]
    pdf_bytes = renderizar_plantilla(plantilla, glob_de_prueba, [opcion_de_prueba()])
    assert "NoDeberiaAparecer" not in _texto(pdf_bytes)


def test_plantilla_sin_elementos_sigue_funcionando(glob_de_prueba, opcion_de_prueba):
    """Regresión: las plantillas ya guardadas antes de la Fase 2 (JSON sin
    `elementos`, cargado como lista vacía) siguen renderizando igual."""
    for preset in listar_presets():
        assert preset.elementos == []
        pdf_bytes = renderizar_plantilla(preset, glob_de_prueba, [opcion_de_prueba()])
        assert pdf_bytes[:5] == b"%PDF-"


def test_plantilla_custom_seccion_oculta_no_aparece(glob_de_prueba, opcion_de_prueba):
    base = obtener_preset("clasica")
    data = base.to_dict()
    for s in data["secciones"]:
        if s["tipo"] == "firma":
            s["visible"] = False
    custom = TemplateDefinition.from_dict(data)
    validar_plantilla(custom)  # "firma" no está bloqueada, debe respetarse

    pdf_bytes = renderizar_plantilla(custom, glob_de_prueba, [opcion_de_prueba()])
    texto = _texto(pdf_bytes)
    assert "Cordialmente" not in texto


def test_plantilla_custom_no_puede_ocultar_seccion_bloqueada(glob_de_prueba, opcion_de_prueba):
    """Aunque el JSON de la plantilla diga `visible: false` para una
    sección bloqueada (p.ej. la nota legal), `validar_plantilla()` la
    fuerza visible antes de renderizar — nunca debe poder generarse un PDF
    sin la cláusula legal."""
    base = obtener_preset("clasica")
    data = base.to_dict()
    for s in data["secciones"]:
        if s["tipo"] == "nota_legal":
            s["visible"] = False
    custom = TemplateDefinition.from_dict(data)
    validar_plantilla(custom)

    pdf_bytes = renderizar_plantilla(custom, glob_de_prueba, [opcion_de_prueba()])
    texto = _texto(pdf_bytes)
    assert "679" in texto  # referencia a la ley 679/2001 en NOTA_Y_LEGAL


def test_plantilla_custom_reordenada(glob_de_prueba, opcion_de_prueba):
    """Cambiar el orden de las secciones cambia el orden del contenido —
    el modelo confía en el orden de la lista, sin un campo `orden` aparte."""
    base = obtener_preset("clasica")
    custom = TemplateDefinition.from_dict(base.to_dict())
    # Mueve "servicios" al principio de la lista.
    servicios = next(s for s in custom.secciones if s.tipo == "servicios")
    custom.secciones.remove(servicios)
    custom.secciones.insert(0, servicios)

    pdf_bytes = renderizar_plantilla(custom, glob_de_prueba, [opcion_de_prueba()])
    texto = _texto(pdf_bytes)
    # "Incluye:" (texto de servicios) debe aparecer antes que "COTIZACIÓN"
    # (título) en el texto extraído, si el reordenamiento se respetó.
    assert texto.index("Incluye") < texto.index("COTIZACIÓN")


def test_plantilla_sin_lista_servicios_cruda_cae_a_texto(glob_de_prueba, opcion_de_prueba):
    """Si se pide layout de tabla pero la opción no trae la lista
    `servicios` cruda (cotizaciones/plantillas de antes de la Fase 5),
    debe degradar a texto en vez de romper."""
    profesional = obtener_preset("profesional")
    op = opcion_de_prueba(con_servicios_crudos=False)
    pdf_bytes = renderizar_plantilla(profesional, glob_de_prueba, [op])
    assert pdf_bytes[:5] == b"%PDF-"
    assert "Incluye" in _texto(pdf_bytes)


def test_pagina_carta_y_horizontal_no_rompen(glob_de_prueba, opcion_de_prueba):
    base = obtener_preset("clasica")
    data = base.to_dict()
    data["id"] = "t_carta"
    data["pagina"]["tamano"] = "Carta"
    data["pagina"]["orientacion"] = "horizontal"
    custom = TemplateDefinition.from_dict(data)
    pdf_bytes = renderizar_plantilla(custom, glob_de_prueba, [opcion_de_prueba()])
    assert pdf_bytes[:5] == b"%PDF-"


def test_plantilla_sin_secciones_se_autocompleta_con_bloqueadas(glob_de_prueba, opcion_de_prueba):
    custom = TemplateDefinition(id="vacia", nombre="Vacía", tipo="custom", secciones=[])
    validar_plantilla(custom)
    pdf_bytes = renderizar_plantilla(custom, glob_de_prueba, [opcion_de_prueba()])
    assert pdf_bytes[:5] == b"%PDF-"


def test_seccion_config_opciones_layout_por_defecto_es_texto():
    s = SeccionConfig(tipo="servicios")
    assert s.opciones.get("layout", "text") == "text"


# ----------------------------------------------------------------------
# Clásica: foto de hotel lateral + encabezado/pie (parecido al diseño
# original en referencias/)
# ----------------------------------------------------------------------
_PNG_1X1_BYTES = base64.b64decode(_PNG_1X1_B64)


def _img_bytes(ancho, alto, color=(120, 130, 140)):
    """PNG de prueba con una proporción realista (a diferencia del PNG 1x1,
    que al escalarlo a ancho/alto completos produce un cuadrado gigante
    poco representativo de una foto o una captura de itinerario real)."""
    buf = io.BytesIO()
    Image.new("RGB", (ancho, alto), color).save(buf, format="PNG")
    return buf.getvalue()


def test_clasica_foto_hotel_va_junto_al_texto_no_duplicada(glob_de_prueba, opcion_de_prueba):
    """En Clásica, con foto de hotel Y captura de vuelos, la foto del hotel
    no debe repetirse (ya se muestra junto al texto vía
    `hotel_fechas.opciones.foto_lateral`; la sección "anexos" reubicada
    debajo del hotel solo aporta la captura de vuelos) — 2 imágenes en
    total, no 3."""
    clasica = obtener_preset("clasica")
    op = opcion_de_prueba()
    op["img_hotel_bytes"] = _img_bytes(1200, 800)
    op["imgs_vuelos_bytes"] = [_img_bytes(1600, 300)]
    pdf_bytes = renderizar_plantilla(clasica, glob_de_prueba, [op])
    assert pdf_bytes[:5] == b"%PDF-"
    lector = PdfReader(io.BytesIO(pdf_bytes))
    assert sum(len(list(p.images)) for p in lector.pages) == 2


def test_clasica_vuelos_van_entre_hotel_y_precio_sin_titulo_anexos(
    glob_de_prueba, opcion_de_prueba
):
    """En Clásica, la sección "anexos" queda reubicada justo debajo del
    bloque de hotel (antes de precios/servicios/nota/firma, como en el
    original) y sin el rótulo "Anexos"/"Itinerario de vuelos" — el
    original no lo tiene, es solo la tabla de vuelos sola."""
    clasica = obtener_preset("clasica")
    op = opcion_de_prueba()
    op["imgs_vuelos_bytes"] = [_img_bytes(1600, 300)]
    pdf_bytes = renderizar_plantilla(clasica, glob_de_prueba, [op])
    texto = _texto(pdf_bytes)
    assert "Anexos" not in texto
    assert "Itinerario de vuelos" not in texto
    # "Noches:" (última línea del bloque de hotel) antes que "VALOR TOTAL"
    # (precios) — los vuelos (imagen, sin texto propio) quedan entre medio.
    assert texto.index("Noches:") < texto.index("VALOR TOTAL")
    # La firma sigue siendo lo último, después de precios/servicios/nota.
    assert texto.index("VALOR TOTAL") < texto.index("Cordialmente")


def test_clasica_sin_foto_hotel_sigue_funcionando(glob_de_prueba, opcion_de_prueba):
    """Sin `img_hotel_bytes`, el comportamiento de `hotel_fechas` es
    idéntico al de siempre (texto centrado, sin tabla de 2 columnas)."""
    clasica = obtener_preset("clasica")
    pdf_bytes = renderizar_plantilla(clasica, glob_de_prueba, [opcion_de_prueba()])
    assert pdf_bytes[:5] == b"%PDF-"
    assert len(PdfReader(io.BytesIO(pdf_bytes)).pages) == 1


def test_preset_profesional_sigue_mostrando_foto_hotel_en_anexos(glob_de_prueba, opcion_de_prueba):
    """Regresión: un preset sin `foto_lateral`/`incluir_foto_hotel`
    configurados (todos menos Clásica) no cambia de comportamiento — la
    foto del hotel se sigue mostrando en "Anexos", como siempre."""
    profesional = obtener_preset("profesional")
    op = opcion_de_prueba()
    op["img_hotel_bytes"] = _PNG_1X1_BYTES
    pdf_bytes = renderizar_plantilla(profesional, glob_de_prueba, [op])
    texto = _texto(pdf_bytes)
    assert "Hotel" in texto.split("Anexos", 1)[-1]


def test_clasica_pasajeros_se_fusiona_con_habitaciones(glob_de_prueba, opcion_de_prueba):
    """En Clásica, la sección "pasajeros" separada va oculta — la cantidad
    de habitaciones y los pasajeros se fusionan en una sola línea junto al
    hotel, como en el diseño original ("1 habitación, 1 adulto, 1
    menor"), no con el texto de `pasajeros_txt` (que trae "Pasajeros: "/
    "· N pasajeros", pensado para la sección independiente)."""
    clasica = obtener_preset("clasica")
    op = opcion_de_prueba(adultos=2, menores=1)
    op["hotel_habitaciones"] = 2
    pdf_bytes = renderizar_plantilla(clasica, glob_de_prueba, [op])
    texto = _texto(pdf_bytes)
    assert "Pasajeros:" not in texto  # la sección "pasajeros" está oculta en Clásica
    assert "2 habitaciones, 2 adultos, 1 menor" in texto


def test_clasica_una_habitacion_y_sin_menores(glob_de_prueba, opcion_de_prueba):
    clasica = obtener_preset("clasica")
    op = opcion_de_prueba(adultos=3, menores=0)  # sin hotel_habitaciones -> default 1
    pdf_bytes = renderizar_plantilla(clasica, glob_de_prueba, [op])
    texto = _texto(pdf_bytes)
    assert "1 habitación, 3 adultos, sin menores" in texto


def test_clasica_noches_en_su_propia_linea(glob_de_prueba, opcion_de_prueba):
    clasica = obtener_preset("clasica")
    op = opcion_de_prueba()
    pdf_bytes = renderizar_plantilla(clasica, glob_de_prueba, [op])
    texto = _texto(pdf_bytes)
    assert f"Noches: {op['noches']}" in texto
    # Ya no va fusionado en la misma línea que el rango de fechas.
    assert f"Días / {op['noches']} Noches" not in texto


def test_clasica_acomodacion_aparece_si_esta_presente(glob_de_prueba, opcion_de_prueba):
    clasica = obtener_preset("clasica")
    op = opcion_de_prueba()
    op["hotel_acomodacion"] = "Doble Estándar"
    pdf_bytes = renderizar_plantilla(clasica, glob_de_prueba, [op])
    assert "Doble Estándar" in _texto(pdf_bytes)


def test_clasica_sin_acomodacion_no_rompe(glob_de_prueba, opcion_de_prueba):
    clasica = obtener_preset("clasica")
    pdf_bytes = renderizar_plantilla(clasica, glob_de_prueba, [opcion_de_prueba()])
    assert pdf_bytes[:5] == b"%PDF-"


def test_otro_preset_conserva_seccion_pasajeros_y_formato_compacto(
    glob_de_prueba, opcion_de_prueba
):
    """Regresión: fuera de Clásica, "pasajeros" sigue visible y
    "hotel_fechas" sigue en su formato compacto de una sola línea."""
    profesional = obtener_preset("profesional")
    op = opcion_de_prueba()
    pdf_bytes = renderizar_plantilla(profesional, glob_de_prueba, [op])
    texto = _texto(pdf_bytes)
    assert "Pasajeros:" in texto
    assert f"{op['dias']} Días / {op['noches']} Noches" in texto


def test_pie_de_pagina_admite_varias_lineas_por_campo(glob_de_prueba, opcion_de_prueba):
    """Un campo de cuenta con saltos de línea reales (ej. dos oficinas)
    debe dibujarse como varias líneas del pie, no como una sola con el
    `\\n` literal perdido."""
    glob_de_prueba["ciudad"] = "Oficina Bucaramanga\nOficina Miami"
    clasica = obtener_preset("clasica")
    pdf_bytes = renderizar_plantilla(clasica, glob_de_prueba, [opcion_de_prueba()])
    texto = _texto(pdf_bytes)
    assert "Oficina Bucaramanga" in texto
    assert "Oficina Miami" in texto


def test_encabezado_etiqueta_nit_rnt_sin_duplicar(glob_de_prueba, opcion_de_prueba):
    """NIT/RNT llevan su etiqueta si el dato no la trae ya, y no se
    duplica si el dato ya la incluye (convención sugerida por el
    placeholder de `auth.py`)."""
    clasica = obtener_preset("clasica")
    glob_de_prueba["nit"] = "901.216.427-8"  # sin la palabra "NIT"
    glob_de_prueba["rnt"] = "RNT 12345"  # ya la trae
    pdf_bytes = renderizar_plantilla(clasica, glob_de_prueba, [opcion_de_prueba()])
    texto = _texto(pdf_bytes)
    assert "NIT: 901.216.427-8" in texto
    assert "RNT 12345" in texto
    assert "NIT: RNT 12345" not in texto


def test_clasica_nombre_empresa_usa_color_primario():
    """`color_razon_social` de Clásica es "primario" — otros presets no lo
    fijan y mantienen el default "secundario"."""
    clasica = obtener_preset("clasica")
    assert clasica.encabezado.color_razon_social == "primario"
    for preset_id in ("profesional", "minimalista", "premium", "travel"):
        assert obtener_preset(preset_id).encabezado.color_razon_social == "secundario"
