# Actualizaciones automáticas (avisar y descargar nuevas versiones)

**Sí es posible, y ya está activo.** Hay dos mecanismos, según el tipo de
cambio:

## 1. Parche liviano (`"tipo": "parche"`) — sin reinstalar

Para la mayoría de actualizaciones (features, fixes, ajustes de PDF/UI):
solo cambian `app.py` y `quotetrip/` (van como archivos sueltos dentro del
`.exe`, no compilados — ver nota en el spec de PyInstaller), así que no hace
falta bajar de nuevo Python/Streamlit/reportlab/pywebview.

1. La app tiene una versión (`APP_VERSION` en `quotetrip/config.py`, hoy
   `1.5.0`).
2. Al abrirse, consulta `version.json` publicado en internet (`UPDATE_URL`
   en `quotetrip/config.py`, apunta a `TheProgramerBone/QuoteTrip` en
   GitHub).
3. Si hay una versión más nueva y `"tipo": "parche"`, muestra un botón
   **"⬇️ Actualizar ahora"**. Al pulsarlo:
   - descarga el `.zip` de `url` (solo `app.py` + `quotetrip/` + `assets/`,
     unos pocos MB),
   - verifica su `sha256` contra el de `version.json`,
   - lo deja preparado en `%LOCALAPPDATA%\QuoteTrip\update_staging\`.
4. Al cerrar y volver a abrir la app, `desktop.py` (antes de lanzar el
   servidor, con nada teniendo los archivos abiertos) reemplaza
   `app.py`/`quotetrip`/`assets` de la instalación por los del staging,
   guardando los anteriores en `update_backup\` por si algo sale mal.

No hay instalador de por medio, ni SmartScreen, ni permisos de admin — solo
"descargar (dentro de la app) → cerrar → abrir".

## 2. Instalador completo (`"tipo": "completo"`, o el campo ausente)

Para cambios que sí tocan el runtime empaquetado (nueva versión de
Streamlit/reportlab/pywebview/pypdfium2, nuevas dependencias, cambios en
`QuoteTrip.spec`) el parche liviano **no alcanza** — hace falta el
`Setup.exe` de siempre:

1. Muestra el aviso **"Nueva versión disponible"** con un botón
   **Descargar actualización**, que enlaza al `QuoteTrip-Setup.exe`.
2. La persona lo descarga y lo ejecuta: como el instalador usa el mismo
   identificador (`AppId` en `installer.iss`, no cambia con el rebrand),
   **actualiza sobre lo instalado** y la cuenta + historial se conservan
   (están en `%LOCALAPPDATA%\QuoteTrip\`).

## Cada vez que quieras sacar una actualización

1. Haz tus cambios en el código.
2. Sube el número de versión en **dos** sitios (deben coincidir):
   - `quotetrip/config.py`  →  `APP_VERSION = "1.3.0"`
   - `installer.iss`  →  `#define MyAppVersion "1.3.0"`
3. Decide si es **parche** o **completa** (ver arriba: ¿tocaste
   dependencias/`QuoteTrip.spec`, o solo `app.py`/`quotetrip`/`assets`?).

   ⚠️ **Si tocaste `desktop.py`, tiene que ser completa.** `desktop.py` es el
   *entry point* que PyInstaller compila dentro del `.exe` (`Analysis`, en
   `QuoteTrip.spec`) — a diferencia de `app.py`, no va como dato suelto,
   así que un parche **nunca** puede actualizarlo. Instalaciones existentes
   se quedan con el `desktop.py` (y por tanto la lógica de aplicar parches)
   de cuando se instalaron por última vez con el `Setup.exe`.
   Consecuencia práctica: **la primera vez que sale una versión con este
   sistema de parches, tiene que ser completa** — si no, nadie con una
   instalación anterior tendría el código que sabe aplicar el parche.
   Por eso hay un chequeo de seguridad (`self_update.desktop_soporta_parches()`):
   si el `desktop.py` instalado nunca escribió su marker de capacidad (o lo
   escribió con un número menor a `CAPACIDAD_PARCHE_REQUERIDA` en
   `quotetrip/self_update.py`), la app ofrece el instalador completo en vez
   del botón de parche, aunque `version.json` diga `"parche"`. Si cambias la
   lógica de `_aplicar_parche_pendiente()` de forma incompatible, sube
   `CAPACIDAD_PARCHE` en `desktop.py` junto con `CAPACIDAD_PARCHE_REQUERIDA`
   en `self_update.py`.

### Si es parche

1. Genera el `.zip`:  `build_patch.bat`  →  `Output\QuoteTrip-Patch.zip`
   (imprime también el `sha256`, y lo deja en
   `Output\QuoteTrip-Patch.sha256.txt`).
2. Crea un *release* en GitHub (`TheProgramerBone/QuoteTrip`) y sube
   `QuoteTrip-Patch.zip`.
3. Actualiza `version.json` (raíz del repo, rama `master`):

   ```json
   {
     "version": "1.3.0",
     "tipo": "parche",
     "url": "https://github.com/TheProgramerBone/QuoteTrip/releases/latest/download/QuoteTrip-Patch.zip",
     "sha256": "<el que imprimió build_patch.bat>",
     "notas": "Novedades de esta versión."
   }
   ```

### Si es completa

1. Genera el instalador:  `build_installer.bat`  → `Output\QuoteTrip-Setup.exe`
2. Crea el *release* en GitHub y sube `QuoteTrip-Setup.exe`.
3. Actualiza `version.json`:

   ```json
   {
     "version": "1.3.0",
     "tipo": "completo",
     "url": "https://github.com/TheProgramerBone/QuoteTrip/releases/latest/download/QuoteTrip-Setup.exe",
     "notas": "Novedades de esta versión."
   }
   ```

Con eso, la próxima vez que alguien abra la app, verá el aviso y podrá
actualizar. (La comprobación se cachea 1 hora para no consultar en cada
acción.)

## Si en algún momento quieres apuntar a otro repositorio

Cambia la constante en `quotetrip/config.py`:

```python
UPDATE_URL = "https://raw.githubusercontent.com/USUARIO/REPO/master/version.json"
```

Debe quedar puesto **antes** de compilar la versión que vas a repartir; si no,
las instalaciones existentes no sabrán dónde mirar. Dejar `UPDATE_URL = ""`
desactiva por completo la comprobación.

## Notas

- Si no hay internet o el `version.json` no responde, la app simplemente no
  muestra aviso y sigue funcionando normal.
- El parche liviano no borra archivos que ya no existan en la nueva versión
  fuera de `app.py`/`quotetrip`/`assets` — muy raro que eso importe, pero si
  alguna vez eliminas un módulo entero de `quotetrip/` y quieres asegurar
  que no quede el `.py` viejo huérfano, saca esa versión como completa.
- Si el parche falla a mitad de camino (raro: disco lleno, permisos), el
  marker (`update_staging.json`) queda tal cual y `desktop.py` reintenta
  aplicarlo en el siguiente arranque en vez de dejar la app con una mezcla
  de archivos viejos/nuevos.
- Un parche corrupto o con hash inválido nunca se aplica (se verifica
  `sha256` antes de extraer).
- Si un `desktop.py` viejo (sin soporte de parches) ve `"tipo": "parche"`,
  no muestra el botón "Actualizar ahora": muestra "Esta actualización
  requiere reinstalar" con un link a la página de *releases* en GitHub
  (`UPDATE_RELEASES_URL` en `quotetrip/config.py`), no al `.zip` del parche
  (que no le serviría de nada).
- SmartScreen puede advertir sobre el instalador sin firma (ver
  `README Instalador.md`) — el parche liviano, al no ser un instalador, no
  pasa por SmartScreen.
