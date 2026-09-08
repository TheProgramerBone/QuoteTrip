# -*- coding: utf-8 -*-
"""Round-trip JSON y validación de `TemplateDefinition` — Fase 1 del
sistema de plantillas PDF."""

from quotetrip.pdf.models import (
    SECCIONES_BLOQUEADAS,
    ElementoLibre,
    SeccionConfig,
    TemplateDefinition,
    validar_plantilla,
)


def _plantilla_minima(**overrides) -> TemplateDefinition:
    datos = dict(
        id="t1",
        nombre="Prueba",
        tipo="custom",
        secciones=[SeccionConfig(tipo=t) for t in SECCIONES_BLOQUEADAS],
    )
    datos.update(overrides)
    return TemplateDefinition(**datos)


def test_round_trip_json():
    original = _plantilla_minima()
    original.tema.color_primario = "#2563EB"
    texto = original.to_json()
    restaurada = TemplateDefinition.from_json(texto)
    assert restaurada.to_dict() == original.to_dict()


def test_from_dict_ignora_claves_desconocidas():
    """Un JSON de una versión futura del esquema con campos nuevos no debe
    reventar al deserializar en una versión anterior del código."""
    data = _plantilla_minima().to_dict()
    data["campo_del_futuro"] = "algo"
    data["tema"]["otro_campo_futuro"] = 123
    restaurada = TemplateDefinition.from_dict(data)
    assert restaurada.id == "t1"


def test_clonar_desacopla_del_original():
    original = _plantilla_minima(tipo="preset")
    original.tema.color_primario = "#111111"
    copia = original.clonar("Mi copia")

    assert copia.id != original.id
    assert copia.tipo == "custom"
    assert copia.base_id == original.id

    # Editar la copia no debe afectar al original.
    copia.tema.color_primario = "#222222"
    assert original.tema.color_primario == "#111111"


def test_validar_fuerza_secciones_bloqueadas_visibles():
    plantilla = _plantilla_minima(
        secciones=[SeccionConfig(tipo=t, visible=False) for t in SECCIONES_BLOQUEADAS]
    )
    avisos = validar_plantilla(plantilla)
    assert avisos  # hubo advertencias
    assert all(s.visible for s in plantilla.secciones if s.tipo in SECCIONES_BLOQUEADAS)


def test_validar_anade_seccion_bloqueada_faltante():
    plantilla = _plantilla_minima(secciones=[])
    validar_plantilla(plantilla)
    tipos = {s.tipo for s in plantilla.secciones}
    assert SECCIONES_BLOQUEADAS <= tipos


def test_validar_corrige_color_invalido():
    plantilla = _plantilla_minima()
    plantilla.tema.color_primario = "no-es-un-color"
    avisos = validar_plantilla(plantilla)
    assert plantilla.tema.color_primario is None
    assert any("color" in a.lower() for a in avisos)


def test_validar_corrige_margen_fuera_de_rango():
    plantilla = _plantilla_minima()
    plantilla.pagina.margen_izq_cm = 50.0
    avisos = validar_plantilla(plantilla)
    assert 1.0 <= plantilla.pagina.margen_izq_cm <= 5.0
    assert avisos


def test_validar_corrige_fuente_desconocida():
    plantilla = _plantilla_minima()
    plantilla.tema.fuente_id = "comic-sans-pirata"
    validar_plantilla(plantilla)
    assert plantilla.tema.fuente_id == "helvetica"


def test_validar_ignora_tipo_de_seccion_desconocido():
    plantilla = _plantilla_minima(
        secciones=[SeccionConfig(tipo=t) for t in SECCIONES_BLOQUEADAS]
        + [SeccionConfig(tipo="algo_inventado")]
    )
    validar_plantilla(plantilla)
    assert "algo_inventado" not in {s.tipo for s in plantilla.secciones}


def test_round_trip_json_con_elementos_libres():
    original = _plantilla_minima(
        elementos=[
            ElementoLibre(
                tipo="texto",
                x_cm=2.0,
                y_cm=3.0,
                rotacion_grados=15.0,
                opciones={"texto": "Hola", "color": "#112233"},
            ),
            ElementoLibre(tipo="forma", opciones={"forma": "elipse", "color_relleno": "#2563EB"}),
        ]
    )
    restaurada = TemplateDefinition.from_json(original.to_json())
    assert restaurada.to_dict() == original.to_dict()
    assert len(restaurada.elementos) == 2
    assert restaurada.elementos[0].opciones["texto"] == "Hola"


def test_from_dict_sin_elementos_no_revienta():
    """Un JSON guardado antes de la Fase 2 (sin la clave "elementos") debe
    seguir cargando, con la lista vacía por defecto — compatibilidad hacia
    atrás obligatoria (ver `migrar_definicion`)."""
    data = _plantilla_minima().to_dict()
    del data["elementos"]
    restaurada = TemplateDefinition.from_dict(data)
    assert restaurada.elementos == []


def test_validar_ignora_elemento_de_tipo_desconocido():
    plantilla = _plantilla_minima(elementos=[ElementoLibre(tipo="video")])
    validar_plantilla(plantilla)
    assert plantilla.elementos == []


def test_validar_corrige_tamano_de_elemento_fuera_de_rango():
    plantilla = _plantilla_minima(elementos=[ElementoLibre(tipo="texto", ancho_cm=999.0)])
    avisos = validar_plantilla(plantilla)
    assert plantilla.elementos[0].ancho_cm <= 50.0
    assert avisos


def test_validar_corrige_opacidad_invalida():
    plantilla = _plantilla_minima(elementos=[ElementoLibre(tipo="forma", opacidad=5.0)])
    validar_plantilla(plantilla)
    assert 0.0 <= plantilla.elementos[0].opacidad <= 1.0


def test_validar_reasigna_ids_duplicados():
    plantilla = _plantilla_minima(
        elementos=[ElementoLibre(id="dup", tipo="texto"), ElementoLibre(id="dup", tipo="forma")]
    )
    validar_plantilla(plantilla)
    ids = [e.id for e in plantilla.elementos]
    assert len(ids) == len(set(ids))


def test_validar_corrige_forma_desconocida():
    plantilla = _plantilla_minima(
        elementos=[ElementoLibre(tipo="forma", opciones={"forma": "estrella"})]
    )
    avisos = validar_plantilla(plantilla)
    assert plantilla.elementos[0].opciones["forma"] == "rectangulo"
    assert avisos


def test_round_trip_json_con_elemento_bloqueado():
    original = _plantilla_minima(elementos=[ElementoLibre(tipo="texto", bloqueado=True)])
    restaurada = TemplateDefinition.from_json(original.to_json())
    assert restaurada.elementos[0].bloqueado is True


def test_from_dict_sin_bloqueado_no_revienta():
    """Un JSON guardado antes del panel de capas (sin la clave "bloqueado"
    en el elemento) debe cargar con `bloqueado=False` por defecto."""
    data = _plantilla_minima(elementos=[ElementoLibre(tipo="texto")]).to_dict()
    del data["elementos"][0]["bloqueado"]
    restaurada = TemplateDefinition.from_dict(data)
    assert restaurada.elementos[0].bloqueado is False


def test_validar_avisa_elemento_fuera_de_pagina():
    plantilla = _plantilla_minima(
        elementos=[ElementoLibre(tipo="texto", x_cm=500.0, y_cm=500.0, ancho_cm=2.0, alto_cm=2.0)]
    )
    avisos = validar_plantilla(plantilla)
    assert any("fuera de la página" in a for a in avisos)
    # No se elimina el elemento, solo se avisa — el usuario puede querer
    # moverlo después en vez de perder lo que ya configuró.
    assert len(plantilla.elementos) == 1


def test_validar_garantiza_siempre_al_menos_una_seccion_visible():
    """El auto-relleno de secciones bloqueadas (visibles por diseño) hace
    que `validar_plantilla` nunca pueda dejar una plantilla sin ninguna
    sección visible, incluso partiendo de una lista vacía o de solo
    secciones ocultas — el `ValueError` interno para ese caso es una
    última línea de defensa que hoy es inalcanzable por diseño, no un
    camino que deba dispararse en uso normal."""
    for secciones_iniciales in ([], [SeccionConfig(tipo="fecha", visible=False)]):
        plantilla = _plantilla_minima(secciones=secciones_iniciales)
        validar_plantilla(plantilla)  # no debe lanzar
        assert any(s.visible for s in plantilla.secciones)
