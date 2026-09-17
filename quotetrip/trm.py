# -*- coding: utf-8 -*-
"""TRM (Tasa Representativa del Mercado, COP por USD) para la conversión de
moneda de las cotizaciones. Se consulta el dataset oficial de la
Superfinanciera publicado en datos.gov.co (Socrata, id `32sa-8pi3`) y se
guarda en caché local (un archivo JSON en la carpeta de datos) para no
depender de internet en cada apertura de la app — igual de tolerante a
fallos que `config.buscar_actualizacion`: nunca lanza excepción."""

import json
import urllib.request
from datetime import date

from .config import DATA_DIR, logger

TRM_CACHE_PATH = DATA_DIR / "trm_cache.json"
TRM_URL = (
    "https://www.datos.gov.co/resource/32sa-8pi3.json"
    "?$select=valor,vigenciadesde&$order=vigenciadesde DESC&$limit=1"
)


def _leer_cache() -> dict | None:
    try:
        return json.loads(TRM_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def _guardar_cache(valor: float, fecha: str) -> None:
    try:
        TRM_CACHE_PATH.write_text(json.dumps({"valor": valor, "fecha": fecha}), encoding="utf-8")
    except Exception:
        pass


def obtener_trm(forzar: bool = False, timeout: int = 6) -> dict | None:
    """Devuelve {"valor": float, "fecha": "YYYY-MM-DD", "de_cache": bool} o
    `None` si nunca se ha podido obtener (ni por API ni por caché) — en ese
    caso la UI debe pedir la TRM manualmente. `valor` son los COP que vale
    1 USD.

    Sin `forzar`, si ya hay una TRM en caché de HOY no vuelve a llamar a la
    API (la TRM solo cambia una vez al día en Colombia)."""
    cache = _leer_cache()
    hoy = date.today().isoformat()
    if not forzar and cache and cache.get("fecha") == hoy:
        return {"valor": cache["valor"], "fecha": cache["fecha"], "de_cache": True}

    try:
        with urllib.request.urlopen(TRM_URL, timeout=timeout) as r:
            datos = json.loads(r.read().decode("utf-8"))
        if datos:
            valor = float(datos[0]["valor"])
            fecha = str(datos[0].get("vigenciadesde") or hoy)[:10]
            _guardar_cache(valor, fecha)
            return {"valor": valor, "fecha": fecha, "de_cache": False}
    except Exception as e:
        logger.info("No se pudo obtener la TRM: %s", e)

    if cache:
        return {"valor": cache["valor"], "fecha": cache["fecha"], "de_cache": True}
    return None
