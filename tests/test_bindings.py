# -*- coding: utf-8 -*-
"""Catálogo de campos dinámicos para texto libre (`pdf/models/bindings.py`)
— Fase "Texto dinámico" del editor de plantillas."""

from quotetrip.pdf.models.bindings import CAMPOS_DINAMICOS, etiqueta_campo, resolver_campo


def test_resolver_campo_devuelve_el_dato_real(glob_de_prueba):
    assert resolver_campo("cliente.nombre", glob_de_prueba) == "Cliente de Prueba"
    assert resolver_campo("agencia.nit", glob_de_prueba) == glob_de_prueba["nit"]


def test_resolver_campo_clave_desconocida_devuelve_none(glob_de_prueba):
    assert resolver_campo("algo.inventado", glob_de_prueba) is None


def test_resolver_campo_dato_ausente_devuelve_none():
    """`glob` sin la clave (p.ej. una versión más vieja del código que no
    la incluía) no debe lanzar excepción."""
    assert resolver_campo("cliente.nombre", {}) is None
    assert resolver_campo("cliente.nombre", None) is None


def test_resolver_campo_nunca_lanza_con_datos_raros():
    """`glob` con un valor que no es ni str ni None (p.ej. un dict a medio
    migrar) no debe reventar `resolver_campo` — degradación elegante."""
    assert resolver_campo("cliente.nombre", {"cliente": {"raro": True}}) == "{'raro': True}"


def test_etiqueta_campo_clave_conocida_y_desconocida():
    assert "Cliente" in etiqueta_campo("cliente.nombre")
    assert etiqueta_campo("clave-que-no-existe") == "clave-que-no-existe"


def test_catalogo_no_esta_vacio_y_tiene_etiquetas_unicas():
    assert len(CAMPOS_DINAMICOS) >= 5
    etiquetas = [etiqueta_campo(k) for k in CAMPOS_DINAMICOS]
    assert len(etiquetas) == len(set(etiquetas))
