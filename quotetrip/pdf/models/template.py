# -*- coding: utf-8 -*-
"""Modelo de datos declarativo para las plantillas de PDF de QuoteTrip.

Una `TemplateDefinition` es 100% serializable a JSON y nunca contiene
código ejecutable (ni `eval`/`exec` en ningún punto del sistema de
plantillas). El motor de render (`quotetrip.pdf.engine`) la interpreta
para producir el PDF; el editor visual (`quotetrip.plantillas_ui`) la
construye y valida antes de guardar.

Las plantillas preestablecidas ("presets") viven como JSON en
`quotetrip/pdf/presets/*.json` y se cargan con `tipo="preset"`; las
plantillas personalizadas de una cuenta se guardan en la tabla SQLite
`plantillas` (ver `quotetrip/db.py`) con `tipo="custom"`.
"""

import dataclasses
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime

SCHEMA_VERSION = 4

# ----------------------------------------------------------------------
# Catálogos controlados — nunca se aceptan valores fuera de estas listas.
# ----------------------------------------------------------------------
SECCION_TIPOS = (
    "fecha",
    "titulo",
    "etiqueta_opcion",
    "pasajeros",
    "hotel_fechas",
    "precios",
    "servicios",
    "nota_legal",
    "firma",
    "anexos",
)

# Secciones que nunca pueden guardarse/renderizarse como ocultas: quitarlas
# produciría una cotización incompleta o, en el caso de `nota_legal`, un
# documento sin la cláusula exigida por la ley 679/2001 (Colombia). Esto es
# una constante de código a propósito — nunca un flag dentro del JSON de la
# plantilla, así un JSON manipulado a mano no puede desactivarlas.
SECCIONES_BLOQUEADAS = frozenset({"titulo", "precios", "servicios", "nota_legal"})

# Catálogo de fuentes: solo Base-14 de ReportLab en v1 (cero riesgo de
# licencia/empaquetado — ver notas de la Fase 2 del plan). Punto de
# extensión documentado para fuentes TTF empaquetadas en el futuro.
FUENTES_CATALOGO = {
    "helvetica": {
        "normal": "Helvetica",
        "bold": "Helvetica-Bold",
        "italica": "Helvetica-Oblique",
        "etiqueta": "Sans (Helvetica)",
    },
    "times": {
        "normal": "Times-Roman",
        "bold": "Times-Bold",
        "italica": "Times-Italic",
        "etiqueta": "Serif (Times)",
    },
    "courier": {
        "normal": "Courier",
        "bold": "Courier-Bold",
        "italica": "Courier-Oblique",
        "etiqueta": "Monoespaciada (Courier)",
    },
}
FUENTE_POR_DEFECTO = "helvetica"

TAMANOS_PAGINA = ("A4", "Carta")
ORIENTACIONES = ("vertical", "horizontal")
POSICIONES_LOGO = ("izquierda", "centro", "derecha")
ALINEACIONES = ("izquierda", "centro", "derecha")
PESOS = ("normal", "bold")
LAYOUTS_SERVICIOS = ("text", "table")

# Tamaño físico de página en cm, sin orientación aplicada — usado solo para
# advertir en validar_plantilla() si un elemento libre queda fuera de la
# página, nunca para el render real (eso lo hace engine/renderer.py con las
# constantes de reportlab.lib.pagesizes, la fuente de verdad).
_TAMANOS_PAGINA_CM = {"A4": (21.0, 29.7), "Carta": (21.59, 27.94)}

# Elementos libres (Fase 2 del editor: posición absoluta por formulario,
# sin canvas interactivo todavía — ver .claude/pendiente/ o el hilo de
# diseño para el porqué). Tipos mínimos pedidos: texto libre, imagen,
# formas básicas.
TIPOS_ELEMENTO = ("texto", "imagen", "forma")
FORMAS_CATALOGO = ("rectangulo", "rectangulo_redondeado", "elipse", "linea")
AJUSTES_IMAGEN = ("contain", "cover", "stretch")

# Rangos seguros para validar_plantilla().
MARGEN_MIN_CM, MARGEN_MAX_CM = 1.0, 5.0
TAMANO_FUENTE_MIN_PT, TAMANO_FUENTE_MAX_PT = 6.0, 24.0
LOGO_ALTO_MIN_CM, LOGO_ALTO_MAX_CM = 0.8, 5.0
ELEMENTO_TAMANO_MIN_CM, ELEMENTO_TAMANO_MAX_CM = 0.3, 50.0
ROTACION_MIN_GRADOS, ROTACION_MAX_GRADOS = -180.0, 180.0


def _hex_valido(valor) -> bool:
    if not isinstance(valor, str):
        return False
    s = valor.strip()
    if not s.startswith("#") or len(s) != 7:
        return False
    try:
        int(s[1:], 16)
        return True
    except ValueError:
        return False


def _construir(cls, data: dict | None):
    """Instancia `cls` (un dataclass) a partir de `data`, ignorando
    silenciosamente claves desconocidas — así un JSON de una versión
    futura/antigua del esquema no revienta al deserializar."""
    campos = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: v for k, v in (data or {}).items() if k in campos})


# ----------------------------------------------------------------------
# Dataclasses
# ----------------------------------------------------------------------
@dataclass
class PaginaConfig:
    tamano: str = "A4"
    orientacion: str = "vertical"
    margen_sup_cm: float = 3.1
    margen_inf_cm: float = 2.9
    margen_izq_cm: float = 2.2
    margen_der_cm: float = 2.2


@dataclass
class TemaConfig:
    color_primario: str | None = None  # None = heredar el de la cuenta
    color_secundario: str | None = None  # None = heredar el de la cuenta
    fuente_id: str = FUENTE_POR_DEFECTO
    tamano_base_pt: float = 10.5
    peso_titulos: str = "bold"
    alineacion_titulos: str = "centro"


@dataclass
class EncabezadoConfig:
    mostrar_logo: bool = True
    logo_alto_cm: float = 2.0
    logo_posicion: str = "izquierda"
    lineas_derecha: list[str] = field(default_factory=lambda: ["razon_social", "nit", "rnt"])
    mostrar_linea_separadora: bool = True


@dataclass
class PieConfig:
    lineas: list[str] = field(default_factory=lambda: ["ciudad", "telefonos", "contacto"])
    mostrar_linea_separadora: bool = True


@dataclass
class EstiloSeccion:
    """Override opcional de estilo para una sección concreta. Todos los
    campos `None` significan "heredar del tema"."""

    tamano_pt: float | None = None
    alineacion: str | None = None
    color: str | None = None
    peso: str | None = None
    espacio_antes_cm: float | None = None
    espacio_despues_cm: float | None = None


@dataclass
class SeccionConfig:
    tipo: str
    visible: bool = True
    estilo: EstiloSeccion = field(default_factory=EstiloSeccion)
    # Configuración específica del tipo de sección (p.ej. para "servicios":
    # {"layout": "text"|"table", "mostrar_comision": bool, "mostrar_base": bool}).
    opciones: dict = field(default_factory=dict)


@dataclass
class ElementoLibre:
    """Elemento de posición libre (texto/imagen/forma) sobre la página,
    editado por formulario (x/y/ancho/alto/rotación/capas en campos
    numéricos) — sin canvas de arrastre todavía, esa es la Fase 3.

    `x_cm`/`y_cm` se miden desde la esquina SUPERIOR IZQUIERDA de la
    página, con Y creciendo hacia abajo (igual convención que los
    márgenes de `PaginaConfig`, más intuitiva en un formulario que el
    origen inferior izquierdo nativo de ReportLab — la conversión vive en
    `engine/elementos_libres.py`, nunca aquí).

    `opciones` guarda los campos específicos de `tipo` (mismo patrón que
    `SeccionConfig.opciones`, para no inflar esta dataclase con campos que
    no aplican a los otros tipos):
      - "texto": {texto, fuente_id, tamano_pt, peso, color, alineacion,
        interlineado}
      - "imagen": {imagen_b64, ajuste} — se guarda la imagen ya codificada
        en base64 dentro del JSON (igual filosofía que el snapshot de la
        plantilla en cada cotización: autocontenido, nunca depende de un
        archivo externo que después podría borrarse o cambiar).
      - "forma": {forma, color_relleno, color_borde, grosor_borde_pt,
        radio_cm} — colores `None` = sin relleno/borde.

    Importante: por cómo ReportLab/Platypus dibuja la página (el
    encabezado/pie y estos elementos se pintan primero, como fondo de
    página; el contenido de la cotización se dibuja encima), los
    elementos libres quedan siempre DETRÁS del contenido principal —
    `z_index` solo ordena entre elementos libres, no contra el contenido
    de la cotización. Sirven para fondos, marcas de agua, decoración o
    bloques de texto propio, no para superponerse a los datos.

    `z_index` (0 = más atrás) ya no se edita como campo numérico suelto en
    el editor (Fase "Capas"): se deriva de la posición del elemento en el
    panel de capas — `plantillas_ui._elementos_desde_widgets` la calcula
    a partir del orden de la lista, no de un valor introducido a mano.
    Sigue viviendo aquí porque el renderer (`engine/elementos_libres.py`)
    necesita un número con el que ordenar, y JSONs antiguos ya lo traían.

    `bloqueado` es una protección solo del editor (evita mover/redimensionar/
    eliminar por accidente, p.ej. un logo o un fondo ya bien puesto) — el
    renderer la ignora por completo, un elemento bloqueado se dibuja igual
    que uno sin bloquear.

    `grupo_id` (Fase de "Grupos"): elementos con el mismo `grupo_id` no
    nulo se tratan como una unidad en el editor (agrupar/desagrupar/
    duplicar/bloquear juntos desde el panel Capas, ver `plantillas_ui`) —
    es una etiqueta de conveniencia del editor, sin ningún significado
    para el renderer (no anida ni transforma nada; cada elemento del
    grupo se sigue dibujando con sus propias x/y/ancho/alto de siempre)."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    tipo: str = "texto"
    x_cm: float = 1.0
    y_cm: float = 1.0
    ancho_cm: float = 5.0
    alto_cm: float = 2.0
    rotacion_grados: float = 0.0
    z_index: int = 0
    visible: bool = True
    bloqueado: bool = False
    opacidad: float = 1.0
    grupo_id: str | None = None
    opciones: dict = field(default_factory=dict)


@dataclass
class TemplateDefinition:
    id: str
    nombre: str
    tipo: str  # "preset" | "custom"
    base_id: str | None = None
    schema_version: int = SCHEMA_VERSION
    pagina: PaginaConfig = field(default_factory=PaginaConfig)
    tema: TemaConfig = field(default_factory=TemaConfig)
    encabezado: EncabezadoConfig = field(default_factory=EncabezadoConfig)
    pie: PieConfig = field(default_factory=PieConfig)
    secciones: list[SeccionConfig] = field(default_factory=list)
    elementos: list[ElementoLibre] = field(default_factory=list)
    creado_en: str | None = None
    actualizado_en: str | None = None

    # -- Serialización --
    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> "TemplateDefinition":
        data = migrar_definicion(dict(data))
        secciones = [
            SeccionConfig(
                tipo=s.get("tipo", ""),
                visible=bool(s.get("visible", True)),
                estilo=_construir(EstiloSeccion, s.get("estilo")),
                opciones=dict(s.get("opciones") or {}),
            )
            for s in data.get("secciones", [])
        ]
        elementos = [
            ElementoLibre(
                id=e.get("id") or uuid.uuid4().hex,
                tipo=e.get("tipo", "texto"),
                x_cm=e.get("x_cm", 1.0),
                y_cm=e.get("y_cm", 1.0),
                ancho_cm=e.get("ancho_cm", 5.0),
                alto_cm=e.get("alto_cm", 2.0),
                rotacion_grados=e.get("rotacion_grados", 0.0),
                z_index=e.get("z_index", 0),
                visible=bool(e.get("visible", True)),
                bloqueado=bool(e.get("bloqueado", False)),
                opacidad=e.get("opacidad", 1.0),
                grupo_id=e.get("grupo_id"),
                opciones=dict(e.get("opciones") or {}),
            )
            for e in data.get("elementos", [])
        ]
        return cls(
            id=data["id"],
            nombre=data.get("nombre", ""),
            tipo=data.get("tipo", "custom"),
            base_id=data.get("base_id"),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            pagina=_construir(PaginaConfig, data.get("pagina")),
            tema=_construir(TemaConfig, data.get("tema")),
            encabezado=_construir(EncabezadoConfig, data.get("encabezado")),
            pie=_construir(PieConfig, data.get("pie")),
            secciones=secciones,
            elementos=elementos,
            creado_en=data.get("creado_en"),
            actualizado_en=data.get("actualizado_en"),
        )

    @classmethod
    def from_json(cls, texto: str) -> "TemplateDefinition":
        return cls.from_dict(json.loads(texto))

    # -- Duplicación --
    def clonar(self, nuevo_nombre: str) -> "TemplateDefinition":
        """Duplica esta plantilla como una nueva plantilla `custom`,
        completamente desacoplada del original: es una copia profunda de
        los datos, no una referencia. Si más adelante se actualiza el
        preset/plantilla original, esta copia NO cambia. `base_id` queda
        apuntando al id del original solo como dato informativo de
        procedencia (nunca una referencia viva/FK)."""
        data = self.to_dict()
        data["id"] = uuid.uuid4().hex
        data["nombre"] = nuevo_nombre
        data["tipo"] = "custom"
        data["base_id"] = self.id
        ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data["creado_en"] = ahora
        data["actualizado_en"] = ahora
        return TemplateDefinition.from_dict(data)


# ----------------------------------------------------------------------
# Migración de esquema (del JSON, no de la BD — ver `_asegurar_columnas*`
# en quotetrip/db.py para la migración de columnas de la BD).
# ----------------------------------------------------------------------
def migrar_definicion(data: dict) -> dict:
    """Sube `data` (dict crudo, recién deserializado de JSON) a la versión
    de esquema actual. Cadena de migraciones incrementales: cada paso futuro
    sube en +1 `schema_version`. La v2 (elementos libres) no necesita un
    paso de migración real: un JSON v1 sin la clave "elementos" ya cae en
    la lista vacía por defecto de `TemplateDefinition.from_dict()`. La v3
    (panel de capas + bloqueo) tampoco: un `ElementoLibre` v2 sin
    "bloqueado" cae en `False` por defecto, y su `z_index` guardado se
    interpreta tal cual como orden de capa (0 = más atrás) — mismo
    significado de siempre, solo que ahora el editor lo deriva del panel
    en vez de un campo numérico. La v4 (grupos) tampoco: sin "grupo_id"
    cae en `None` (sin grupo). Todas son no-ops que solo actualizan el
    número, pero dejan el punto de extensión listo para cuando un cambio
    de esquema sí necesite tocar los datos."""
    # version = data.get("schema_version", 1)
    # if version < 5:
    #     data = _migrar_v4_a_v5(data)
    data["schema_version"] = SCHEMA_VERSION
    return data


# ----------------------------------------------------------------------
# Validación — corrige con advertencia siempre que sea seguro; solo lanza
# excepción ante un caso realmente irrecuperable.
# ----------------------------------------------------------------------
def validar_plantilla(template: TemplateDefinition) -> list[str]:
    """Corrige `template` in-place (clamps/fallbacks) y devuelve la lista
    de advertencias generadas. Preferimos degradación elegante sobre un PDF
    roto: valores fuera de rango se ajustan silenciosamente con aviso, y
    solo el caso genuinamente irrecuperable (ninguna sección visible)
    lanza `ValueError` — no debería poder ocurrir dado el resto de esta
    función, pero es la última línea de defensa antes de renderizar."""
    avisos: list[str] = []

    # --- Página ---
    p = template.pagina
    if p.tamano not in TAMANOS_PAGINA:
        avisos.append(f"Tamaño de página «{p.tamano}» no reconocido; se usa A4.")
        p.tamano = "A4"
    if p.orientacion not in ORIENTACIONES:
        avisos.append(f"Orientación «{p.orientacion}» no reconocida; se usa vertical.")
        p.orientacion = "vertical"
    for campo in ("margen_sup_cm", "margen_inf_cm", "margen_izq_cm", "margen_der_cm"):
        valor = getattr(p, campo)
        if not isinstance(valor, (int, float)) or not (MARGEN_MIN_CM <= valor <= MARGEN_MAX_CM):
            base = valor if isinstance(valor, (int, float)) else 2.5
            setattr(p, campo, min(max(base, MARGEN_MIN_CM), MARGEN_MAX_CM))
            avisos.append(f"Margen «{campo}» fuera de rango; se ajustó a un valor seguro.")

    # --- Tema ---
    t = template.tema
    if t.color_primario is not None and not _hex_valido(t.color_primario):
        avisos.append("Color primario inválido; se hereda el de la cuenta.")
        t.color_primario = None
    if t.color_secundario is not None and not _hex_valido(t.color_secundario):
        avisos.append("Color secundario inválido; se hereda el de la cuenta.")
        t.color_secundario = None
    if t.fuente_id not in FUENTES_CATALOGO:
        avisos.append(f"Fuente «{t.fuente_id}» no disponible; se usa {FUENTE_POR_DEFECTO}.")
        t.fuente_id = FUENTE_POR_DEFECTO
    if not isinstance(t.tamano_base_pt, (int, float)) or not (
        TAMANO_FUENTE_MIN_PT <= t.tamano_base_pt <= TAMANO_FUENTE_MAX_PT
    ):
        base = t.tamano_base_pt if isinstance(t.tamano_base_pt, (int, float)) else 10.5
        t.tamano_base_pt = min(max(base, TAMANO_FUENTE_MIN_PT), TAMANO_FUENTE_MAX_PT)
        avisos.append("Tamaño de fuente base fuera de rango; se ajustó.")
    if t.peso_titulos not in PESOS:
        t.peso_titulos = "bold"
    if t.alineacion_titulos not in ALINEACIONES:
        t.alineacion_titulos = "centro"

    # --- Encabezado ---
    e = template.encabezado
    if not isinstance(e.logo_alto_cm, (int, float)) or not (
        LOGO_ALTO_MIN_CM <= e.logo_alto_cm <= LOGO_ALTO_MAX_CM
    ):
        base = e.logo_alto_cm if isinstance(e.logo_alto_cm, (int, float)) else 2.0
        e.logo_alto_cm = min(max(base, LOGO_ALTO_MIN_CM), LOGO_ALTO_MAX_CM)
        avisos.append("Tamaño del logo fuera de rango; se ajustó.")
    if e.logo_posicion not in POSICIONES_LOGO:
        e.logo_posicion = "izquierda"

    # --- Secciones: tipos válidos, sin duplicados, bloqueadas siempre visibles ---
    tipos_vistos: set[str] = set()
    secciones_validas: list[SeccionConfig] = []
    for s in template.secciones:
        if s.tipo not in SECCION_TIPOS:
            avisos.append(f"Se ignoró una sección de tipo desconocido «{s.tipo}».")
            continue
        if s.tipo in tipos_vistos:
            avisos.append(f"Sección «{s.tipo}» duplicada; se ignoró la repetición.")
            continue
        tipos_vistos.add(s.tipo)
        if s.tipo in SECCIONES_BLOQUEADAS and not s.visible:
            avisos.append(f"La sección «{s.tipo}» es obligatoria y no puede ocultarse.")
            s.visible = True
        secciones_validas.append(s)
    for tipo in SECCIONES_BLOQUEADAS:
        if tipo not in tipos_vistos:
            avisos.append(f"Faltaba la sección obligatoria «{tipo}»; se añadió.")
            secciones_validas.append(SeccionConfig(tipo=tipo, visible=True))
    template.secciones = secciones_validas

    if not any(s.visible for s in template.secciones):
        raise ValueError("La plantilla no tiene ninguna sección visible.")

    # --- Elementos libres ---
    ancho_pag_cm, alto_pag_cm = _TAMANOS_PAGINA_CM.get(p.tamano, _TAMANOS_PAGINA_CM["A4"])
    if p.orientacion == "horizontal":
        ancho_pag_cm, alto_pag_cm = alto_pag_cm, ancho_pag_cm

    ids_vistos: set[str] = set()
    elementos_validos: list[ElementoLibre] = []
    for el in template.elementos:
        if el.tipo not in TIPOS_ELEMENTO:
            avisos.append(f"Se ignoró un elemento de tipo desconocido «{el.tipo}».")
            continue
        if not el.id or el.id in ids_vistos:
            el.id = uuid.uuid4().hex
        ids_vistos.add(el.id)
        if el.grupo_id is not None and not isinstance(el.grupo_id, str):
            el.grupo_id = None

        for campo, minimo, maximo in (
            ("ancho_cm", ELEMENTO_TAMANO_MIN_CM, ELEMENTO_TAMANO_MAX_CM),
            ("alto_cm", ELEMENTO_TAMANO_MIN_CM, ELEMENTO_TAMANO_MAX_CM),
        ):
            valor = getattr(el, campo)
            if not isinstance(valor, (int, float)) or not (minimo <= valor <= maximo):
                base = valor if isinstance(valor, (int, float)) else 5.0
                setattr(el, campo, min(max(base, minimo), maximo))
                avisos.append(f"Tamaño de un elemento («{campo}») fuera de rango; se ajustó.")
        if not isinstance(el.rotacion_grados, (int, float)):
            el.rotacion_grados = 0.0
        else:
            el.rotacion_grados = min(
                max(el.rotacion_grados, ROTACION_MIN_GRADOS), ROTACION_MAX_GRADOS
            )
        if not isinstance(el.opacidad, (int, float)) or not (0.0 <= el.opacidad <= 1.0):
            el.opacidad = min(
                max(el.opacidad if isinstance(el.opacidad, (int, float)) else 1.0, 0.0), 1.0
            )
        if not isinstance(el.z_index, int):
            try:
                el.z_index = int(el.z_index)
            except (TypeError, ValueError):
                el.z_index = 0
        if not isinstance(el.x_cm, (int, float)):
            el.x_cm = 1.0
        if not isinstance(el.y_cm, (int, float)):
            el.y_cm = 1.0
        if (
            el.x_cm + el.ancho_cm < 0
            or el.x_cm > ancho_pag_cm
            or el.y_cm + el.alto_cm < 0
            or el.y_cm > alto_pag_cm
        ):
            avisos.append(
                f"Un elemento «{el.tipo}» queda completamente fuera de la página; "
                "no se verá en el PDF."
            )

        op = el.opciones if isinstance(el.opciones, dict) else {}
        if el.tipo == "texto":
            if op.get("color") is not None and not _hex_valido(op["color"]):
                op["color"] = None
            if op.get("fuente_id", FUENTE_POR_DEFECTO) not in FUENTES_CATALOGO:
                op["fuente_id"] = FUENTE_POR_DEFECTO
        elif el.tipo == "forma":
            if op.get("forma", "rectangulo") not in FORMAS_CATALOGO:
                op["forma"] = "rectangulo"
                avisos.append("Forma no reconocida en un elemento; se usó rectángulo.")
            for campo_color in ("color_relleno", "color_borde"):
                if op.get(campo_color) is not None and not _hex_valido(op[campo_color]):
                    op[campo_color] = None
        elif el.tipo == "imagen":
            if op.get("ajuste", "contain") not in AJUSTES_IMAGEN:
                op["ajuste"] = "contain"
        el.opciones = op

        elementos_validos.append(el)
    template.elementos = elementos_validos

    return avisos
