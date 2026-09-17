# -*- coding: utf-8 -*-
"""Guardado del PDF en disco con el diálogo nativo de Windows.

`desktop.py` lanza Streamlit como un proceso normal de escritorio (no
headless a nivel de sistema operativo, solo `--server.headless` que es un
flag propio de Streamlit para no abrir el navegador) — así que este mismo
proceso puede mostrar diálogos nativos de Tk sin necesidad de un puente
pywebview/JS entre procesos. `tkinter` es de la librería estándar (no es una
dependencia nueva), pero como `quotetrip/` viaja como dato suelto de
PyInstaller (ver nota en `QuoteTrip.spec`), su import no se detecta en el
análisis estático — por eso el .spec declara `tkinter` a mano en
`hiddenimports`.

Todo aquí está envuelto en try/except: si Tk no está disponible (por
ejemplo, un exe donde el bundling de Tcl/Tk fallara, o si algún día esto se
corre en un entorno sin pantalla), se degrada devolviendo `None` y quien
llama cae al `st.download_button` de siempre — nunca rompe el flujo de
exportar."""

from pathlib import Path

# Sentinela para distinguir "Tk no disponible" de "el usuario canceló el
# diálogo" (ambos casos internos pueden devolver `None` desde `fn`) — quien
# llama necesita esa distinción: sin Tk debe caer al `st.download_button`,
# pero un cancelado no debe disparar ningún fallback, solo no hacer nada.
_TK_NO_DISPONIBLE = object()


def _con_dialogo_tk(fn):
    """Ejecuta `fn(root)` con una ventana Tk oculta y siempre al frente (para
    que el diálogo no quede detrás de la ventana de la app), y la destruye al
    salir. Devuelve el resultado de `fn`, o `_TK_NO_DISPONIBLE` si Tk no está
    disponible o algo falla al crear la ventana."""
    try:
        import tkinter as tk

        root = tk.Tk()
    except Exception:
        return _TK_NO_DISPONIBLE
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        return fn(root)
    except Exception:
        return _TK_NO_DISPONIBLE
    finally:
        root.destroy()


def tk_disponible() -> bool:
    """Prueba rápida y barata de si se puede mostrar un diálogo nativo."""
    return _con_dialogo_tk(lambda root: True) is True


def elegir_carpeta(inicial: str | None = None) -> str | None:
    """Diálogo nativo "Seleccionar carpeta". `None` si se cancela o si Tk no
    está disponible."""

    def _fn(root):
        from tkinter import filedialog

        carpeta = filedialog.askdirectory(
            parent=root,
            title="Elegir carpeta para guardar las cotizaciones",
            initialdir=inicial if inicial and Path(inicial).is_dir() else None,
        )
        return carpeta or None

    resultado = _con_dialogo_tk(_fn)
    return None if resultado is _TK_NO_DISPONIBLE else resultado


def guardar_pdf(pdf_bytes: bytes, nombre_sugerido: str, carpeta_predeterminada: str | None):
    """Guarda `pdf_bytes` en disco.

    - Si hay `carpeta_predeterminada` configurada (y existe), guarda ahí
      directamente con `nombre_sugerido`, sin preguntar — evita el diálogo
      en el flujo del día a día.
    - Si no, abre el diálogo nativo "Guardar como" para que el usuario elija
      dónde.

    Devuelve (estado, ruta_o_error) con `estado` uno de:
      · "ok"        — guardado; `ruta_o_error` es la ruta final.
      · "error"     — falló la escritura; `ruta_o_error` es el mensaje.
      · "cancelado" — el usuario cerró el diálogo sin elegir nada.
      · "sin_tk"    — no hay diálogo nativo disponible; quien llama debe
                       caer al `st.download_button` de siempre."""
    if carpeta_predeterminada and Path(carpeta_predeterminada).is_dir():
        ruta = Path(carpeta_predeterminada) / nombre_sugerido
        try:
            ruta.write_bytes(pdf_bytes)
            return "ok", str(ruta)
        except Exception as e:
            return "error", f"No se pudo guardar en la carpeta predeterminada: {e}"

    def _fn(root):
        from tkinter import filedialog

        return filedialog.asksaveasfilename(
            parent=root,
            title="Guardar cotización en PDF",
            initialfile=nombre_sugerido,
            defaultextension=".pdf",
            filetypes=[("Documento PDF", "*.pdf")],
        )

    resultado = _con_dialogo_tk(_fn)
    if resultado is _TK_NO_DISPONIBLE:
        return "sin_tk", ""
    if not resultado:
        return "cancelado", ""
    try:
        Path(resultado).write_bytes(pdf_bytes)
        return "ok", resultado
    except Exception as e:
        return "error", f"No se pudo guardar el archivo: {e}"
