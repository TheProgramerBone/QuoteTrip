# -*- coding: utf-8 -*-
"""Widget de "pegar una imagen del portapapeles" (Ctrl+V) para las fotos de
hotel y capturas de itinerarios de vuelos — alternativa a tener que guardar
la imagen a disco primero y subirla con `st.file_uploader`.

Es un componente estático casero (`st.components.v1.declare_component`
apuntando a `static/paste_uploader/index.html`), sin ninguna dependencia
nueva ni build de JS/npm: habla a mano el protocolo clásico de componentes
de Streamlit (`streamlit:componentReady` / `streamlit:render` /
`streamlit:setComponentValue`), que sigue intacto en 1.58 (verificado en el
bundle del frontend). `index.html` va dentro de `quotetrip/`, así que
PyInstaller ya lo empaqueta junto con el resto del paquete sin tocar
`QuoteTrip.spec`.
"""

import base64
import binascii
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

_DIR = Path(__file__).parent / "static" / "paste_uploader"
_component = components.declare_component("paste_uploader", path=str(_DIR))


def _decodificar(data_url):
    """`data_url` es un `"data:image/png;base64,...."` que llega tal cual
    del navegador, o `None`/vacío si no hay nada pegado."""
    if not data_url:
        return None
    try:
        _, b64 = data_url.split(",", 1)
        return base64.b64decode(b64)
    except (ValueError, binascii.Error):
        return None


def imagen_pegable(key):
    """Renderiza el recuadro de pegar/arrastrar/seleccionar una imagen
    (clave `key`) y devuelve sus bytes, o `None` si está vacío. El valor
    crudo queda en `st.session_state[key]` como cualquier widget con `key`,
    así que se puede releer más tarde sin volver a renderizar con
    `bytes_pegados(key)`."""
    data_url = _component(key=key, default=None, value=st.session_state.get(key))
    return _decodificar(data_url)


def bytes_pegados(key):
    """Relee (sin renderizar de nuevo) lo que ya se pegó en `key`."""
    return _decodificar(st.session_state.get(key))
