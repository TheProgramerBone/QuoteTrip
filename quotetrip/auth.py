# -*- coding: utf-8 -*-
"""Pantallas de acceso: registro de cuenta (una vez por instalación), login,
recuperación de contraseña, y los paneles de "editar cuenta"/"cambiar
contraseña" que se usan ya autenticado."""

import streamlit as st

from .config import (
    COLOR_PRIMARIO_DEF,
    COLOR_SECUNDARIO_DEF,
    LOGO_CUENTA_PATH,
    PRODUCTO_NOMBRE,
)
from .db import (
    actualizar_cuenta,
    crear_cuenta,
    generar_codigo_recuperacion,
    hash_secreto,
    verificar_codigo_recuperacion,
    verificar_password,
    verificar_respuesta_seguridad,
)
from .exportar import elegir_carpeta
from .pdf import guardar_logo_cuenta

_CAMPOS_OBLIGATORIOS_REGISTRO = [
    "razon_social",
    "nit",
    "ciudad",
    "telefonos",
    "contacto",
    "firma_nombre",
    "firma_cargo",
    "usuario",
    "pregunta_seguridad",
    "respuesta",
]


def pantalla_registro():
    st.title(f"Crear cuenta · {PRODUCTO_NOMBRE}")
    st.caption(
        "Regístrate una vez con los datos de tu agencia. Quedan guardados en este "
        "equipo y se usan para generar tus cotizaciones en PDF."
    )

    with st.form("form_registro"):
        st.markdown("#### Datos de la agencia")
        c1, c2 = st.columns(2)
        with c1:
            razon_social = st.text_input("Razón social *", placeholder="Ej: Viajes Ejemplo S.A.S.")
            nit = st.text_input("NIT *", placeholder="Ej: NIT 900.123.456-7")
            rnt = st.text_input("RNT (opcional)", placeholder="Ej: RNT Nº 12345")
            ciudad = st.text_area(
                "Ciudad / dirección *",
                placeholder="Ej: Floridablanca – Colombia\nCalle 1 # 2-34, Oficina 5",
                height=68,
            )
        with c2:
            telefonos = st.text_area(
                "Teléfonos *",
                placeholder="Ej: Teléfonos: +57 3xx xxx xxxx\n+1 7xx xxx xxxx",
                height=68,
            )
            contacto = st.text_area(
                "Contacto (email / web / redes) *",
                placeholder="Ej: Email: contacto@agencia.com\n@agencia · www.agencia.com",
                height=68,
            )
            firma_nombre = st.text_input("Nombre de quien firma las cotizaciones *")
            firma_cargo = st.text_input("Cargo *", value="Gerente")
        logo_file = st.file_uploader(
            "Logo de tu agencia (opcional)", type=["png", "jpg", "jpeg", "webp"]
        )

        st.markdown("#### Colores de marca")
        cc1, cc2 = st.columns(2)
        with cc1:
            color_primario = st.color_picker("Color primario", value=COLOR_PRIMARIO_DEF)
        with cc2:
            color_secundario = st.color_picker("Color secundario", value=COLOR_SECUNDARIO_DEF)

        st.markdown("#### Acceso")
        st.caption(
            "Un solo usuario/contraseña por agencia — lo comparten todos los que usen este equipo."
        )
        u1, u2 = st.columns(2)
        with u1:
            usuario = st.text_input("Usuario *")
            password = st.text_input("Contraseña * (mínimo 6 caracteres)", type="password")
        with u2:
            pregunta_seguridad = st.text_input(
                "Pregunta de seguridad *", placeholder="Ej: ¿Nombre de tu primera mascota?"
            )
            password2 = st.text_input("Confirmar contraseña *", type="password")
        respuesta = st.text_input("Respuesta *")
        st.caption(
            "La pregunta de seguridad es para recuperar el acceso si olvidas la "
            "contraseña. Al terminar también recibirás un código de recuperación de "
            "respaldo — no hay forma de recuperar la cuenta si pierdes ambos."
        )

        enviado = st.form_submit_button("Crear cuenta", type="primary", use_container_width=True)

    if not enviado:
        return

    campos = {
        "razon_social": razon_social,
        "nit": nit,
        "ciudad": ciudad,
        "telefonos": telefonos,
        "contacto": contacto,
        "firma_nombre": firma_nombre,
        "firma_cargo": firma_cargo,
        "usuario": usuario,
        "pregunta_seguridad": pregunta_seguridad,
        "respuesta": respuesta,
    }
    faltantes = [c for c in _CAMPOS_OBLIGATORIOS_REGISTRO if not campos[c].strip()]
    if faltantes:
        st.error("Completa todos los campos obligatorios (*).")
        return
    if len(password) < 6:
        st.error("La contraseña debe tener al menos 6 caracteres.")
        return
    if password != password2:
        st.error("Las contraseñas no coinciden.")
        return

    logo_path = None
    if logo_file is not None:
        logo_path = guardar_logo_cuenta(logo_file.getvalue(), LOGO_CUENTA_PATH)

    hash_password, salt_password = hash_secreto(password)
    hash_respuesta, salt_respuesta = hash_secreto(respuesta)
    codigo = generar_codigo_recuperacion()
    hash_codigo, salt_codigo = hash_secreto(codigo.replace("-", ""))

    crear_cuenta(
        {
            "razon_social": razon_social.strip(),
            "nit": nit.strip(),
            "rnt": rnt.strip(),
            "ciudad": ciudad.strip(),
            "telefonos": telefonos.strip(),
            "contacto": contacto.strip(),
            "logo_path": logo_path,
            "color_primario": color_primario,
            "color_secundario": color_secundario,
            "firma_nombre": firma_nombre.strip(),
            "firma_cargo": firma_cargo.strip(),
            "usuario": usuario.strip(),
            "hash_password": hash_password,
            "salt_password": salt_password,
            "pregunta_seguridad": pregunta_seguridad.strip(),
            "hash_respuesta": hash_respuesta,
            "salt_respuesta": salt_respuesta,
            "hash_codigo_recup": hash_codigo,
            "salt_codigo_recup": salt_codigo,
        }
    )

    st.session_state["autenticado"] = True
    st.session_state["cuenta_nueva"] = True
    st.session_state["codigo_recuperacion_mostrado"] = codigo
    st.rerun()


def pantalla_codigo_recuperacion(codigo: str):
    st.title("Guarda tu código de recuperación")
    st.warning(
        "Este código solo se muestra **una vez**. Si en el futuro olvidas la "
        "contraseña y también la respuesta de seguridad, es la única forma de "
        "recuperar el acceso a esta cuenta — no hay forma de restablecerla sin él."
    )
    st.code(codigo, language=None)
    if st.button("Ya lo guardé, continuar", type="primary", use_container_width=True):
        del st.session_state["codigo_recuperacion_mostrado"]
        st.rerun()


def pantalla_login(cuenta: dict):
    st.title(f"Iniciar sesión · {PRODUCTO_NOMBRE}")
    if cuenta.get("razon_social"):
        st.caption(cuenta["razon_social"])

    with st.form("form_login"):
        usuario = st.text_input("Usuario")
        password = st.text_input("Contraseña", type="password")
        recordar = st.checkbox("Recordarme en este equipo", value=True)
        enviado = st.form_submit_button("Entrar", type="primary", use_container_width=True)

    if enviado:
        usuario_ok = usuario.strip() == (cuenta.get("usuario") or "").strip()
        if usuario_ok and verificar_password(cuenta, password):
            actualizar_cuenta({"sesion_recordada": 1 if recordar else 0})
            st.session_state["autenticado"] = True
            st.rerun()
        else:
            st.error("Usuario o contraseña incorrectos.")

    with st.expander("¿Olvidaste tu usuario o tu contraseña?"):
        _flujo_recuperacion(cuenta)


def _flujo_recuperacion(cuenta: dict):
    st.caption(
        "Verifica tu identidad respondiendo la pregunta de seguridad o con el "
        "código de recuperación que se te mostró al crear la cuenta. Te "
        "recordamos tu usuario y, si quieres, puedes definir una contraseña "
        "nueva ahí mismo."
    )
    metodo = st.radio(
        "¿Cómo quieres verificar tu identidad?",
        ["Responder la pregunta de seguridad", "Usar el código de recuperación"],
        key="metodo_recuperacion",
    )
    with st.form("form_recuperar"):
        if metodo.startswith("Responder"):
            st.write(f"**Pregunta:** {cuenta.get('pregunta_seguridad') or '—'}")
            intento = st.text_input("Tu respuesta", key="recup_respuesta")
        else:
            intento = st.text_input("Código de recuperación", key="recup_codigo")
        st.divider()
        st.caption("Deja esto en blanco si solo quieres recuperar tu usuario.")
        nueva1 = st.text_input("Nueva contraseña (opcional)", type="password", key="recup_pass1")
        nueva2 = st.text_input(
            "Confirmar nueva contraseña (opcional)", type="password", key="recup_pass2"
        )
        enviado = st.form_submit_button("Verificar identidad")

    if not enviado:
        return

    ok = (
        verificar_respuesta_seguridad(cuenta, intento)
        if metodo.startswith("Responder")
        else verificar_codigo_recuperacion(cuenta, intento)
    )
    if not ok:
        st.error("No coincide con lo registrado. Revisa e intenta de nuevo.")
        return

    st.success(f"Tu usuario es: **{cuenta.get('usuario') or '—'}**")

    if not nueva1 and not nueva2:
        return
    if len(nueva1) < 6:
        st.error("La contraseña debe tener al menos 6 caracteres.")
        return
    if nueva1 != nueva2:
        st.error("Las contraseñas no coinciden.")
        return

    hash_password, salt_password = hash_secreto(nueva1)
    actualizar_cuenta({"hash_password": hash_password, "salt_password": salt_password})
    st.success("Contraseña actualizada también. Ya puedes iniciar sesión arriba.")


def cerrar_sesion():
    """Cierra la sesión actual y olvida el "recordarme" de este equipo — la
    próxima vez que se abra la app, vuelve a pedir usuario y contraseña."""
    actualizar_cuenta({"sesion_recordada": 0})
    st.session_state["autenticado"] = False
    st.rerun()


# ----------------------------------------------------------------------
# Paneles de la app ya autenticada (sidebar)
# ----------------------------------------------------------------------
def panel_editar_cuenta(cuenta: dict):
    with st.form("form_editar_cuenta"):
        razon_social = st.text_input("Razón social", value=cuenta.get("razon_social") or "")
        nit = st.text_input("NIT", value=cuenta.get("nit") or "")
        rnt = st.text_input("RNT (opcional)", value=cuenta.get("rnt") or "")
        ciudad = st.text_area("Ciudad / dirección", value=cuenta.get("ciudad") or "", height=68)
        telefonos = st.text_area("Teléfonos", value=cuenta.get("telefonos") or "", height=68)
        contacto = st.text_area(
            "Contacto (email / web / redes)", value=cuenta.get("contacto") or "", height=68
        )
        firma_nombre = st.text_input(
            "Nombre de quien firma", value=cuenta.get("firma_nombre") or ""
        )
        firma_cargo = st.text_input("Cargo", value=cuenta.get("firma_cargo") or "")
        logo_file = st.file_uploader("Cambiar logo (opcional)", type=["png", "jpg", "jpeg", "webp"])
        guardar = st.form_submit_button(
            "Guardar datos de la cuenta", type="primary", use_container_width=True
        )

    if not guardar:
        return

    campos = {
        "razon_social": razon_social.strip(),
        "nit": nit.strip(),
        "rnt": rnt.strip(),
        "ciudad": ciudad.strip(),
        "telefonos": telefonos.strip(),
        "contacto": contacto.strip(),
        "firma_nombre": firma_nombre.strip(),
        "firma_cargo": firma_cargo.strip(),
    }
    if logo_file is not None:
        campos["logo_path"] = guardar_logo_cuenta(logo_file.getvalue(), LOGO_CUENTA_PATH)
    actualizar_cuenta(campos)
    st.success("Datos actualizados.")
    st.rerun()


def panel_cambiar_password(cuenta: dict):
    with st.form("form_cambiar_password"):
        actual = st.text_input("Contraseña actual", type="password")
        nueva1 = st.text_input("Nueva contraseña", type="password")
        nueva2 = st.text_input("Confirmar nueva contraseña", type="password")
        guardar = st.form_submit_button("Cambiar contraseña", use_container_width=True)

    if not guardar:
        return
    if not verificar_password(cuenta, actual):
        st.error("La contraseña actual no es correcta.")
        return
    if len(nueva1) < 6:
        st.error("La contraseña debe tener al menos 6 caracteres.")
        return
    if nueva1 != nueva2:
        st.error("Las contraseñas no coinciden.")
        return

    hash_password, salt_password = hash_secreto(nueva1)
    actualizar_cuenta({"hash_password": hash_password, "salt_password": salt_password})
    st.success("Contraseña actualizada.")


def panel_ajustes_exportacion(cuenta: dict):
    """Carpeta donde guardar los PDF sin preguntar cada vez. Vacío (por
    defecto) = siempre abrir el diálogo nativo de "Guardar como"."""
    st.markdown("**📤 Exportación**")
    actual = cuenta.get("carpeta_exportacion") or ""
    st.caption(
        "Carpeta predeterminada para guardar las cotizaciones en PDF. "
        "Si la dejas vacía, cada vez se pregunta dónde guardar."
    )
    st.text_input("Carpeta", value=actual or "(preguntar siempre)", disabled=True)
    c1, c2 = st.columns(2)
    with c1:
        if st.button("📁 Elegir carpeta...", use_container_width=True):
            carpeta = elegir_carpeta(actual)
            if carpeta:
                actualizar_cuenta({"carpeta_exportacion": carpeta})
                st.rerun()
    with c2:
        if actual and st.button("Quitar (preguntar siempre)", use_container_width=True):
            actualizar_cuenta({"carpeta_exportacion": None})
            st.rerun()
