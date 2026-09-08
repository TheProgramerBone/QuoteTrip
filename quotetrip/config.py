# -*- coding: utf-8 -*-
"""
Rutas, constantes de producto y utilidades de arranque (log, chequeo de
actualizaciones). Nada de esto depende de Streamlit ni de la BD.
"""

import json
import logging
import os
import shutil
import sys
import urllib.request
from pathlib import Path

# ----------------------------------------------------------------------
# Producto (la herramienta en sí) vs. cuenta (la agencia que la usa)
# ----------------------------------------------------------------------
PRODUCTO_NOMBRE = "QuoteTrip"
PRODUCTO_SLUG = "QuoteTrip"  # usado en nombres de carpeta/archivo, sin espacios

# Carpeta de datos de la instalación anterior (Travels Moreno Blanco), para
# migrar el historial una sola vez si existe y la nueva carpeta aún no.
_SLUG_LEGADO = "VoyTravel"


def _dir_recursos() -> Path:
    """Carpeta de recursos de solo lectura (assets).
    En un ejecutable de PyInstaller los archivos se extraen a sys._MEIPASS;
    en ejecución normal, en la raíz del proyecto (un nivel arriba de
    quotetrip/)."""
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass) if meipass else Path(__file__).resolve().parent.parent


def _dir_datos() -> Path:
    """Carpeta de escritura persistente (base de datos, logo de la cuenta).
    Empaquetado -> %LOCALAPPDATA%\\<PRODUCTO_SLUG> (sobrevive al cierre).
    Normal      -> ./data junto al proyecto.

    Si viene de una instalación previa con el nombre viejo ("VoyTravel") y
    la carpeta nueva todavía no existe, se copia una sola vez para no perder
    el historial de cotizaciones."""
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
        d = base / PRODUCTO_SLUG
        legado = base / _SLUG_LEGADO
        if not d.exists() and legado.exists():
            try:
                shutil.copytree(legado, d)
            except Exception:
                pass
    else:
        d = Path(__file__).resolve().parent.parent / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


BASE_DIR = _dir_recursos()
ASSETS_DIR = BASE_DIR / "assets"
DATA_DIR = _dir_datos()
DB_PATH = DATA_DIR / "cotizaciones.db"
LOGO_GENERICO_PATH = ASSETS_DIR / "logo_generico.png"
LOGO_CUENTA_PATH = DATA_DIR / "logo_cuenta.png"


def ruta_logo_cuenta(cuenta: dict) -> str | None:
    """Ruta del logo a mostrar: el propio de la cuenta si existe, si no el
    placeholder genérico del producto, si no None."""
    p = cuenta.get("logo_path") if cuenta else None
    if p and Path(p).exists():
        return p
    if LOGO_GENERICO_PATH.exists():
        return str(LOGO_GENERICO_PATH)
    return None


# --- Versión y actualizaciones ---
APP_VERSION = "1.4.7"
# Para habilitar el aviso de actualización, apunta esta URL a un archivo
# version.json publicado (por ejemplo en GitHub Releases). Déjalo vacío para
# desactivar la comprobación. Ver "README Actualizaciones.md".
UPDATE_URL = "https://raw.githubusercontent.com/TheProgramerBone/QuoteTrip/master/version.json"
# Fallback cuando hay un parche disponible pero este exe es de antes de que
# existiera el mecanismo de auto-parcheo (ver self_update.desktop_soporta_parches):
# no tiene sentido ofrecer el .zip del parche, así que se manda a la página de
# releases para que baje el instalador completo manualmente.
UPDATE_RELEASES_URL = "https://github.com/TheProgramerBone/QuoteTrip/releases/latest"

# --- Registro de errores (log) ---
LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "quotetrip.log"

logger = logging.getLogger("quotetrip")
if not logger.handlers:
    try:
        _h = logging.FileHandler(LOG_PATH, encoding="utf-8")
        _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(_h)
        logger.setLevel(logging.INFO)
    except Exception:
        pass


def buscar_actualizacion(version_actual: str, url: str, timeout: int = 6):
    """Consulta un version.json remoto y devuelve info si hay una versión nueva.
    Formato esperado:
    {"version": "1.3.0", "tipo": "parche"|"completo", "url": "...",
     "sha256": "...", "notas": "..."}.
    `tipo` "parche" apunta a un .zip liviano (solo código, sin instalador)
    aplicable sin reinstalar; "completo" (o ausente, por compatibilidad con
    version.json viejos) apunta al Setup.exe de siempre.
    Nunca lanza excepción: si algo falla (sin internet, etc.), devuelve None."""
    if not url:
        return None

    def _tupla(v):
        return tuple(int(x) for x in str(v).strip().split(".") if x.isdigit())

    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        ultima = str(data.get("version", "")).strip()
        if ultima and _tupla(ultima) > _tupla(version_actual):
            return {
                "version": ultima,
                "url": data.get("url", ""),
                "notas": data.get("notas", ""),
                "tipo": data.get("tipo", "completo"),
                "sha256": data.get("sha256", ""),
            }
    except Exception as e:
        logger.info("No se pudo comprobar actualizaciones: %s", e)
    return None


# --- Bloques de texto fijos (no son branding de una empresa) ---
# Cláusula legal exigida a agencias de turismo en Colombia (ley 679/2001).
NOTA_Y_LEGAL = (
    "Nota: El presente presupuesto no es válido para intercambiar por los "
    "servicios descritos. Todos los servicios están sujetos a disponibilidad "
    "y re-cotización a las tarifas vigentes. Es nuestro deber informar a todos "
    "nuestros usuarios y clientes el Artículo 17 de la ley 679/2001: La "
    "explotación y abuso sexual de menores de edad son sancionados penal y "
    "administrativamente en Colombia."
)

# --- Servicios: (clave, etiqueta, descripción por defecto) ---
INCLUSIONES = [
    ("vuelos", "Vuelos", "Vuelos"),
    ("hotel", "Hotel", "Hotel Todo Incluido"),
    ("traslados", "Traslados", "Traslados"),
    ("seguro", "Seguro", "Seguro de asistencia médica"),
    ("otros", "Otros", "Otros servicios"),
]
# Servicios que se pueden compartir entre todas las opciones
CLAVES_COMPARTIBLES = {"vuelos", "traslados"}

MESES_ES = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]

# --- Colores de fábrica (neutros; cada cuenta define los suyos al registrarse) ---
COLOR_PRIMARIO_DEF = "#2563EB"  # azul (acentos, líneas)
COLOR_SECUNDARIO_DEF = "#1E3A8A"  # azul oscuro (títulos, textos destacados)
