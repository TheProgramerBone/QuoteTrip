# -*- mode: python ; coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Spec de PyInstaller 6.x para QuoteTrip (Windows, carpeta única).
# Genera dist/QuoteTrip/QuoteTrip.exe
#
# Construir con:   python -m PyInstaller --noconfirm --clean QuoteTrip.spec
# ---------------------------------------------------------------------------
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

datas = [("app.py", "."), ("assets", "assets"), ("quotetrip", "quotetrip")]
binaries = []
hiddenimports = []

# El punto de entrada es desktop.py, que NO importa reportlab, PIL ni
# pypdfium2 (esos los usa app.py, que va como dato). Por eso hay que
# recolectarlos explícitamente, junto con Streamlit. pypdfium2 (motor de
# rasterizado de la vista previa del editor de plantillas, quotetrip/pdf/
# preview.py) trae un binario nativo de PDFium — collect_all asegura que
# viaje empaquetado igual que reportlab.
for paquete in ("streamlit", "reportlab", "pypdfium2"):
    try:
        d, b, h = collect_all(paquete)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

# Imports que usa app.py y que deben estar sí o sí
hiddenimports += ["PIL", "PIL.Image"]
hiddenimports += collect_submodules("reportlab")

# tkinter (quotetrip/exportar.py: diálogo nativo de "Guardar como" y de
# "Elegir carpeta") — de la librería estándar, pero como quotetrip/ viaja
# como dato suelto (ver nota arriba sobre app.py), PyInstaller no lo detecta
# solo. Declararlo aquí basta para que su hook incluido bundle Tcl/Tk.
hiddenimports += ["tkinter", "tkinter.filedialog"]

# Metadata que Streamlit y compañía consultan por importlib.metadata
for paquete in ("streamlit", "click", "rich", "packaging", "protobuf",
                "tornado", "watchdog", "gitpython", "blinker", "cachetools",
                "pillow", "reportlab", "pywebview", "pypdfium2"):
    try:
        datas += copy_metadata(paquete)
    except Exception:
        pass

# Icono opcional: úsalo solo si existe assets/logo.ico
_icono = os.path.join("assets", "logo.ico")
icon_arg = _icono if os.path.exists(_icono) else None


a = Analysis(
    ["desktop.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pandas.tests", "pyarrow.tests", "numpy.tests", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="QuoteTrip",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # sin ventana de consola (ver README para depurar)
    icon=icon_arg,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="QuoteTrip",
)
