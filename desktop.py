# -*- coding: utf-8 -*-
"""
Lanzador de escritorio para QuoteTrip.

Arranca Streamlit como PROCESO APARTE (no en un hilo: Streamlit instala un
manejador de señales que solo funciona en el hilo principal) y muestra la app
dentro de una ventana nativa con pywebview. Si pywebview no está disponible,
abre la app en el navegador por defecto.

Funciona ejecutándose con Python normal/portable y dentro de un .exe de
PyInstaller.

Uso en desarrollo:   python desktop.py
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

TITULO = "QuoteTrip"

# Versión de la lógica de "aplicar parche" de ESTE desktop.py. Un parche
# nunca puede tocar este archivo (va compilado dentro del .exe, no como dato
# suelto — ver QuoteTrip.spec), así que solo sube en un release COMPLETO.
# self_update.desktop_soporta_parches() la compara contra
# CAPACIDAD_PARCHE_REQUERIDA para decidir si un exe ya instalado sabe
# aplicar el parche que ofrece version.json, o si haría falta reinstalar.
CAPACIDAD_PARCHE = 1


def _dir_recursos() -> Path:
    """Carpeta donde están app.py y assets (soporta PyInstaller)."""
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass) if meipass else Path(__file__).resolve().parent


def _dir_datos() -> Path:
    """Misma carpeta de datos persistentes que usa quotetrip/config.py
    (no se importa ese módulo aquí para no depender de código que un
    parche a medio aplicar podría dejar inconsistente)."""
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
        return base / "QuoteTrip"
    return Path(__file__).resolve().parent / "data"


def _aplicar_parche_pendiente() -> None:
    """Si `app.py` (desde la app en ejecución) dejó un parche descargado y
    listo en la carpeta de datos, lo aplica ahora, con el servidor todavía
    sin arrancar (nadie tiene los archivos abiertos).

    Reemplaza app.py/quotetrip/assets en la carpeta de instalación por los
    del staging, guardando los anteriores en update_backup por si algo sale
    mal. Nunca lanza excepción: si falla, deja el marker para reintentar en
    el próximo arranque en vez de dejar la app a medio actualizar."""
    dir_datos = _dir_datos()
    staging = dir_datos / "update_staging"
    marker = dir_datos / "update_staging.json"
    if not marker.exists() or not staging.exists():
        return

    try:
        info = json.loads(marker.read_text(encoding="utf-8"))
    except Exception:
        marker.unlink(missing_ok=True)
        return
    if not info.get("listo"):
        return

    dir_instalacion = _dir_recursos()
    backup = dir_datos / "update_backup"
    try:
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        backup.mkdir(parents=True, exist_ok=True)

        for nombre in ("app.py", "quotetrip", "assets"):
            origen = staging / nombre
            if not origen.exists():
                continue
            destino = dir_instalacion / nombre
            if destino.exists():
                shutil.move(str(destino), str(backup / nombre))
            shutil.move(str(origen), str(destino))
    except Exception:
        # Se deja el marker: se reintenta en el próximo arranque en vez de
        # arrancar con una mezcla de archivos viejos/nuevos.
        return

    shutil.rmtree(staging, ignore_errors=True)
    marker.unlink(missing_ok=True)


def _marcar_capacidad_parche() -> None:
    """Deja constancia en la carpeta de datos de qué CAPACIDAD_PARCHE trae
    este desktop.py compilado. app.py (que sí se actualiza por parche) lee
    esto para saber si puede ofrecer un parche o si este exe es de antes de
    que existiera este mecanismo -y por tanto nunca lo aplicaría, dejando el
    aviso de "reinicia para aplicar" en un loop sin efecto- y debe ofrecer el
    instalador completo en su lugar. Nunca lanza excepción."""
    try:
        marker = _dir_datos() / "desktop_capabilities.json"
        marker.write_text(json.dumps({"capacidad_parche": CAPACIDAD_PARCHE}), encoding="utf-8")
    except Exception:
        pass


def _puerto_libre() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    puerto = s.getsockname()[1]
    s.close()
    return puerto


def _esperar_servidor(puerto: int, timeout: int = 90) -> bool:
    fin = time.time() + timeout
    while time.time() < fin:
        try:
            with socket.create_connection(("127.0.0.1", puerto), 0.5):
                return True
        except OSError:
            time.sleep(0.4)
    return False


def _args_streamlit(app_path: str, puerto: int):
    return [
        "run",
        app_path,
        f"--server.port={puerto}",
        "--server.address=127.0.0.1",
        "--server.headless=true",
        "--global.developmentMode=false",
        "--server.fileWatcherType=none",
        "--server.runOnSave=false",
        "--browser.gatherUsageStats=false",
        # Oculta la barra propia de Streamlit ("Deploy" y el menú ⋮): esto es
        # una app de escritorio, no tiene sentido ofrecer deploy ni el menú.
        "--client.toolbarMode=minimal",
    ]


def _run_server_inproc(puerto: int):
    """Corre Streamlit en ESTE proceso (hilo principal del proceso hijo)."""
    app_path = str(_dir_recursos() / "app.py")
    sys.argv = ["streamlit"] + _args_streamlit(app_path, puerto)
    from streamlit.web import cli as stcli

    sys.exit(stcli.main())


def _lanzar_servidor(puerto: int) -> subprocess.Popen:
    """Lanza Streamlit como proceso hijo."""
    creationflags = 0
    if os.name == "nt":  # ocultar consola del hijo en Windows
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    if getattr(sys, "frozen", False):
        # Dentro del .exe: nos re-invocamos en modo servidor.
        cmd = [sys.executable, "--run-server", str(puerto)]
    else:
        # Python normal/portable: usamos el mismo intérprete con -m streamlit.
        app_path = str(_dir_recursos() / "app.py")
        cmd = [sys.executable, "-m", "streamlit"] + _args_streamlit(app_path, puerto)

    return subprocess.Popen(cmd, creationflags=creationflags)


def main():
    # Modo servidor (proceso hijo del ejecutable empaquetado)
    if "--run-server" in sys.argv:
        idx = sys.argv.index("--run-server")
        _run_server_inproc(int(sys.argv[idx + 1]))
        return

    # Si quedó un parche descargado y listo (desde la app en la sesión
    # anterior), aplicarlo ahora, antes de que nada tenga los archivos
    # abiertos.
    try:
        _aplicar_parche_pendiente()
    except Exception:
        pass

    # Marcar la capacidad de ESTE exe para aplicar parches, para que app.py
    # sepa si puede ofrecer uno (ver CAPACIDAD_PARCHE arriba).
    _marcar_capacidad_parche()

    puerto = _puerto_libre()
    proc = _lanzar_servidor(puerto)
    url = f"http://127.0.0.1:{puerto}"

    if not _esperar_servidor(puerto):
        try:
            proc.terminate()
        except Exception:
            pass
        print("No se pudo iniciar el servidor de la aplicación.")
        sys.exit(1)

    try:
        import webview

        webview.create_window(TITULO, url, width=1250, height=880)
        # private_mode=True es el default de pywebview y BORRA el perfil de
        # WebView2 (cookies/localStorage) al cerrar la ventana — por eso el
        # tema Claro/Oscuro que Streamlit guarda en localStorage del navegador
        # no sobrevivía a cerrar y volver a abrir la app. storage_path fija
        # el perfil a una carpeta persistente en vez del temporal por defecto.
        webview.start(
            private_mode=False,
            storage_path=str(_dir_datos() / "webview_profile"),
        )  # bloquea hasta que se cierra la ventana
    except Exception:
        import webbrowser

        webbrowser.open(url)
        try:
            proc.wait()
        except KeyboardInterrupt:
            pass
    finally:
        try:
            proc.terminate()
        except Exception:
            pass


if __name__ == "__main__":
    main()
