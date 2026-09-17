# -*- coding: utf-8 -*-
"""Funciones puras de formato y cálculo (sin Streamlit, sin BD) — fáciles de
probar solas."""

import math
import re
from datetime import date

from .config import MESES_ES


def formato_cop(valor) -> str:
    """2470000 -> '2.470.000'."""
    try:
        return f"{int(round(float(valor))):,}".replace(",", ".")
    except (ValueError, TypeError):
        return "0"


def formato_moneda(valor, moneda: str = "COP") -> str:
    """Formatea `valor` (ya expresado en `moneda`) con el símbolo y estilo de
    esa moneda: COP sin decimales y punto de miles ('$1.234.567'), USD con
    dos decimales y coma de miles ('US$ 1,234.56')."""
    if moneda == "USD":
        try:
            return f"US$ {float(valor):,.2f}"
        except (ValueError, TypeError):
            return "US$ 0.00"
    return f"${formato_cop(valor)}"


def convertir_moneda(valor_cop, moneda_destino: str, trm: float | None):
    """Convierte un valor en COP a `moneda_destino`. Si es COP o no hay TRM
    disponible, devuelve el valor tal cual (nunca lanza por división por
    cero ni por TRM ausente — degrada al valor en COP sin convertir)."""
    if moneda_destino == "USD" and trm:
        return valor_cop / trm
    return valor_cop


def redondear_precio(valor, modo: str = "arriba_10k") -> int:
    """Redondea un precio (en COP) hacia arriba al múltiplo de 10.000 más
    cercano; con `modo='psicologico_999'` le resta 1 a ese resultado para
    dejarlo en un precio "comercial" terminado en 999 (ej. 1.567.025 ->
    1.570.000, o 1.569.999 en modo psicológico). Nunca baja del valor
    original en el modo por defecto — así nunca se pierde margen solo por
    redondear."""
    try:
        valor = float(valor)
    except (ValueError, TypeError):
        return 0
    subido = int(math.ceil(valor / 10_000) * 10_000)
    if modo == "psicologico_999":
        return max(subido - 1, 0)
    return subido


def fecha_en_espanol(d: date) -> str:
    """date(2026,6,26) -> '26 de junio del 2026'."""
    return f"{d.day} de {MESES_ES[d.month - 1]} del {d.year}"


def calcular_dias_noches(ida: date, regreso: date):
    """Devuelve (dias, noches). Convención de viajes: días = noches + 1."""
    if not ida or not regreso or regreso < ida:
        return 0, 0
    noches = (regreso - ida).days
    return noches + 1, noches


def nombre_archivo_seguro(nombre: str) -> str:
    """Limpia el nombre del cliente para usarlo como nombre de archivo."""
    limpio = re.sub(r"[^\w\sáéíóúñ-]", "", (nombre or "").strip(), flags=re.IGNORECASE)
    limpio = re.sub(r"\s+", "_", limpio)
    return limpio or "Cliente"


def texto_pasajeros(adultos: int, menores: int) -> str:
    """(2,1) -> 'Pasajeros: 2 adultos + 1 menor · 3 pasajeros'."""
    partes = [f"{adultos} adulto" + ("s" if adultos != 1 else "")]
    if menores > 0:
        partes.append(f"{menores} menor" + ("es" if menores != 1 else ""))
    total = adultos + menores
    return (
        "Pasajeros: " + " + ".join(partes) + f"  ·  {total} pasajero" + ("s" if total != 1 else "")
    )


def calcular_opcion(adultos, menores, tarifa_menor_dif, valor_menor, servicios):
    """
    Calcula los importes de una opción a partir de sus servicios.
    Cada servicio tiene: monto + comisión (que se suma), y base 'persona' (por
    pasajero adulto) o 'total' (cobrado al grupo una sola vez).

      · suma_persona = servicios cobrados por pasajero (monto + comisión)
      · suma_total   = servicios cobrados por grupo (monto + comisión)
      · total_grupo  = suma_persona*adultos + menor_pp*menores + suma_total
      · valor_pasajero = lo que paga CADA pasajero, prorrateando lo del grupo
        (así nunca queda en 0 aunque todo sea 'total del grupo').
      · costo_total/comision_total = el mismo total_grupo descompuesto en lo
        que se paga a proveedores vs. lo que es margen de la agencia — para
        el resumen de "ganancia". Si hay tarifa de menor diferenciada, ese
        valor es un monto fijo aparte que no se descompone (no sabemos cuánto
        de `valor_menor` es costo vs. comisión), así que no aporta a
        `comision_total`: es una simplificación deliberada, no un olvido.
    """

    def monto_de(s):
        return int(s.get("monto", 0))

    def comision_de(s):
        return int(s.get("comision", 0))

    def efectivo(s):
        return monto_de(s) + comision_de(s)

    suma_persona = sum(efectivo(s) for s in servicios if s["base"] == "persona")
    suma_persona_comision = sum(comision_de(s) for s in servicios if s["base"] == "persona")
    suma_total = sum(efectivo(s) for s in servicios if s["base"] == "total")
    suma_total_comision = sum(comision_de(s) for s in servicios if s["base"] == "total")
    personas = adultos + menores
    menor_pp = valor_menor if (tarifa_menor_dif and menores > 0) else suma_persona
    total_grupo = suma_persona * adultos + menor_pp * menores + suma_total

    # Prorrateo de los servicios de grupo entre todos los pasajeros
    grupo_por_cabeza = (suma_total / personas) if personas else 0
    valor_pasajero = suma_persona + grupo_por_cabeza  # adulto (todo incluido)
    valor_pasajero_menor = menor_pp + grupo_por_cabeza  # menor (todo incluido)

    menores_en_comision = 0 if (tarifa_menor_dif and menores > 0) else menores
    comision_total = suma_persona_comision * adultos + suma_total_comision
    comision_total += suma_persona_comision * menores_en_comision
    costo_total = total_grupo - comision_total

    items = [s["desc"] for s in servicios if s["desc"]]
    incluye = "Incluye: " + " + ".join(items) if items else "Incluye: —"

    return {
        "suma_persona": suma_persona,
        "suma_total": suma_total,
        "personas": personas,
        "menor_pp": menor_pp,
        "total_grupo": total_grupo,
        "valor_pasajero": valor_pasajero,
        "valor_pasajero_menor": valor_pasajero_menor,
        "costo_total": costo_total,
        "comision_total": comision_total,
        "incluye": incluye,
    }
