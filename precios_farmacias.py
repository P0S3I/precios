"""
Seguimiento de precios de farmacias -> Telegram

Qué hace:
  - Lee el precio de cada farmacia y avisa SOLO cuando cambia alguno,
    con el comparativo completo y el costo de 30 cápsulas.
  - Guarda un historial diario de precios (historial.json).
  - Avisa si una farmacia lleva varios días sin poder leerse.

Modos:
  python precios_farmacias.py              normal (avisa solo si hay cambios)
  python precios_farmacias.py --test       consulta manual: envía el comparativo siempre
  python precios_farmacias.py --historial  envía el resumen del historial (no consulta las webs)

Instalación:  pip install requests beautifulsoup4
Variables de entorno (no escribas el token en el código):
  TELEGRAM_TOKEN      token de tu bot (BotFather)
  TELEGRAM_CHAT_ID    tu chat id

Prueba local en Windows:
  set TELEGRAM_TOKEN=...
  set TELEGRAM_CHAT_ID=...
"""
import html
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

PRODUCTO = "Acnotin 20 mg"
MONEDA = "Bs"
ZONA = timezone(timedelta(hours=-4))  # hora de Bolivia

# Cantidad de cápsulas para el cálculo de compra (los precios se toman por cápsula)
CAPSULAS = 30

# Descuentos que NO aparecen en la web y se aplican en caja sobre el total de la factura.
# dia: 0=lunes, 1=martes, 2=miércoles, 3=jueves, 4=viernes, 5=sábado, 6=domingo
# Si la promoción termina, borra la entrada.
DESCUENTOS = {
    "Hipermaxi SD": {"dia": 3, "texto": "jueves", "pct": 10},
}

# Días seguidos sin poder leer una farmacia antes de avisarte
DIAS_FALLO = 3
# Días de historial que se conservan
DIAS_HISTORIAL = 180

SITIOS = [
    {
        "nombre": "Farmacorp",
        "url": "https://farmacorp.com/products/255691?_pos=6&_sid=2d3d400e1&_ss=r",
        "selector": r"#shopify-section-static-product > section > article > div.product-main > div.product-details > div.product-pricing > div > div.price--main > span",
    },
    {
        "nombre": "Hipermaxi SD",
        "url": "https://www.hipermaxi.com/santa-cruz/farmacia-santos-dumont/producto/217980/acnotin-20mg-x-1-cap-blanda-isotretinoina",
        "selector": r"body > div.flex.flex-col > main > article > div.grid.grid-cols-1.gap-8.md\:grid-cols-2.lg\:gap-12.xl\:gap-16 > section > div > div:nth-child(4) > div > span",
    },
    {
        "nombre": "Farmacia Chavez",
        "url": "https://www.farmaciaschavez.com.bo/p/acnotin-20-mg-isotretinoina-x-capsula-blanda-2083",
        "selector": r"#home-wrapper__container > div > div > div > div > div > div > div.product__main__info > div.product__info__wrapper > div > footer > div.cart__actions__price__wrapper > div.cart__actions__price > div > div > p.base__price",
    },
]

CARPETA = os.path.dirname(os.path.abspath(__file__))
ESTADO = os.path.join(CARPETA, "precios_previos.json")
HISTORIAL = os.path.join(CARPETA, "historial.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}


# ---------- Archivos ----------

def cargar_json(ruta, defecto):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return defecto


def guardar_json(ruta, datos):
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2, sort_keys=True)


def cargar_historial():
    h = cargar_json(HISTORIAL, {})
    h.setdefault("dias", {})
    h.setdefault("fallos", {})
    return h


# ---------- Lectura de precios ----------

def obtener_precio(sitio):
    """Devuelve el precio como float, o None si falla."""
    try:
        r = requests.get(sitio["url"], headers=HEADERS, timeout=20)
        r.raise_for_status()
        el = BeautifulSoup(r.text, "html.parser").select_one(sitio["selector"])
        if not el:
            print(f"  [{sitio['nombre']}] selector no encontró nada")
            return None
        m = re.search(r"\d+(?:[.,]\d+)?", el.get_text())
        if not m:
            print(f"  [{sitio['nombre']}] sin número en: {el.get_text(strip=True)!r}")
            return None
        return float(m.group().replace(",", "."))
    except Exception as e:
        print(f"  [{sitio['nombre']}] error: {e}")
        return None


# ---------- Historial y fallos ----------

def registrar_lecturas(hist, leidos, hoy):
    """Guarda un registro por día (si hay varias lecturas el mismo día, queda la última)."""
    dia = hist["dias"].setdefault(hoy.isoformat(), {})
    for nombre, precio in leidos.items():
        if precio is not None:
            dia[nombre] = precio
    for f in sorted(hist["dias"])[:-DIAS_HISTORIAL]:
        del hist["dias"][f]


def actualizar_fallos(hist, leidos, hoy):
    """Devuelve los avisos técnicos a enviar (fallo prolongado o recuperación)."""
    fallos = hist["fallos"]
    avisos = []
    for nombre, precio in leidos.items():
        n = html.escape(nombre)
        if precio is None:
            f = fallos.setdefault(nombre, {"desde": hoy.isoformat(), "alertado": False})
            desde = date.fromisoformat(f["desde"])
            if (hoy - desde).days >= DIAS_FALLO and not f["alertado"]:
                f["alertado"] = True
                avisos.append(
                    f"<b>Aviso técnico · {n}</b>\n"
                    f"No se ha podido leer el precio desde el {desde.strftime('%d/%m')}. "
                    "Es probable que la página haya cambiado su estructura. "
                    "Mientras tanto se muestra el último precio conocido."
                )
        else:
            f = fallos.pop(nombre, None)
            if f and f["alertado"]:
                avisos.append(
                    f"<b>Aviso técnico · {n}</b>\nLa lectura del precio se ha restablecido."
                )
    return avisos


# ---------- Mensajes ----------

def bs(valor):
    return f"{MONEDA} {valor:.2f}"


def construir_mensaje(leidos, previos, cambios, manual=False):
    """
    leidos:  {nombre: precio actual o None si falló la lectura}
    previos: {nombre: último precio guardado}
    cambios: {nombre: precio anterior} solo de las farmacias que cambiaron
    """
    filas = []
    for s in SITIOS:
        n = s["nombre"]
        actual = leidos.get(n)
        desactualizado = False
        if actual is None and previos.get(n) is not None:
            actual = previos[n]
            desactualizado = True
        filas.append({"sitio": s, "precio": actual, "desactualizado": desactualizado})

    # Ordenar de menor a mayor; sin dato al final
    filas.sort(key=lambda f: (f["precio"] is None, f["precio"] or 0))

    ahora = datetime.now(ZONA).strftime("%d/%m/%Y, %H:%M")
    etiqueta = "Consulta manual" if manual else "Variación detectada"
    lineas = [
        f"<b>{html.escape(PRODUCTO)} · Comparativo de precios</b>",
        f"<i>{etiqueta} · {ahora} (hora de Bolivia)</i>",
        "",
    ]

    for f in filas:
        s, p = f["sitio"], f["precio"]
        nombre = f'<a href="{html.escape(s["url"], quote=True)}">{html.escape(s["nombre"])}</a>'

        if p is None:
            lineas.append(f"•  {nombre}: sin datos")
            continue

        if s["nombre"] in cambios:
            antes = cambios[s["nombre"]]
            dif = p - antes
            pct = dif / antes * 100 if antes else 0
            flecha = "▲" if dif > 0 else "▼"
            lineas.append(f"{flecha}  <b>{nombre}: {bs(p)}</b>")
            lineas.append(
                f"      Anterior: {bs(antes)}  ({dif:+.2f} {MONEDA} / {pct:+.1f}%)"
            )
        else:
            extra = "  <i>(último dato disponible)</i>" if f["desactualizado"] else ""
            lineas.append(f"•  {nombre}: {bs(p)}{extra}")

    # Cálculo de compra (por cápsula x cantidad)
    compras = {f["sitio"]["nombre"]: f["precio"] * CAPSULAS for f in filas if f["precio"] is not None}
    if compras:
        n_min = min(compras, key=compras.get)
        p_unit = compras[n_min] / CAPSULAS
        lineas += [
            "",
            f"<b>Compra de {CAPSULAS} cápsulas</b>",
            f"Más económico: {html.escape(n_min)} · {bs(compras[n_min])}",
            f"<i>({bs(p_unit)} x {CAPSULAS})</i>",
        ]

        # Descuentos por día: se muestran solo si dejarían a esa farmacia como la más barata
        hoy = datetime.now(ZONA).weekday()
        for n, d in DESCUENTOS.items():
            base = compras.get(n)
            if base is None:
                continue
            con_desc = base * (1 - d["pct"] / 100)
            otros = [t for m, t in compras.items() if m != n]
            if otros and con_desc > min(otros):
                continue
            ahorro = base - con_desc
            vigencia = "vigente hoy" if hoy == d["dia"] else f"solo {d['texto']}"
            lineas += [
                "",
                f"<b>{html.escape(n)} con {d['pct']}% de descuento</b> ({vigencia})",
                f"Total: {bs(con_desc)} · ahorro de {bs(ahorro)}",
                "<i>El descuento se aplica en caja; no figura en el sitio web.</i>",
            ]

    return "\n".join(lineas)


def fecha_corta(iso):
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m")


def construir_historial(hist):
    dias = hist.get("dias", {})
    if not dias:
        return (
            f"<b>{html.escape(PRODUCTO)} · Historial de precios</b>\n\n"
            "Todavía no hay registros. El historial comienza a acumularse con la próxima lectura."
        )

    fechas = sorted(dias)
    lineas = [
        f"<b>{html.escape(PRODUCTO)} · Historial de precios</b>",
        f"<i>Registro de {len(fechas)} día(s): {fecha_corta(fechas[0])} – {fecha_corta(fechas[-1])}</i>",
    ]

    for s in SITIOS:
        n = s["nombre"]
        serie = [(f, dias[f][n]) for f in fechas if n in dias[f]]
        nombre = f'<a href="{html.escape(s["url"], quote=True)}">{html.escape(n)}</a>'
        lineas += ["", f"<b>{nombre}</b>"]
        if not serie:
            lineas.append("Sin registros")
            continue

        actual = serie[-1][1]
        f_min, p_min = min(serie, key=lambda x: x[1])
        f_max, p_max = max(serie, key=lambda x: x[1])
        prom = sum(p for _, p in serie) / len(serie)

        lineas.append(f"Actual: {bs(actual)}")
        lineas.append(f"Mínimo: {bs(p_min)} ({fecha_corta(f_min)}) · Máximo: {bs(p_max)} ({fecha_corta(f_max)})")
        if len(serie) >= 3:
            pct = (actual - prom) / prom * 100 if prom else 0
            lineas.append(f"Promedio: {bs(prom)} · actual {pct:+.1f}% respecto al promedio")
        else:
            lineas.append("<i>Pocos registros para calcular un promedio fiable.</i>")

    return "\n".join(lineas)


def enviar(texto):
    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data={
            "chat_id": CHAT_ID,
            "text": texto,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    if not r.ok:
        print("Error enviando a Telegram:", r.text)


# ---------- Programa principal ----------

if __name__ == "__main__":
    # Modo historial: solo lee el archivo, no consulta las webs
    if "--historial" in sys.argv:
        enviar(construir_historial(cargar_historial()))
        sys.exit(0)

    modo_prueba = "--test" in sys.argv
    hoy = datetime.now(ZONA).date()

    previos = cargar_json(ESTADO, {})
    actuales = dict(previos)
    leidos = {}
    cambios = {}

    for s in SITIOS:
        n = s["nombre"]
        precio = obtener_precio(s)
        leidos[n] = precio
        print(f"{n}: {precio}")
        if precio is None:
            continue  # fallo puntual: se conserva el precio anterior
        antes = previos.get(n)
        if antes is None:
            actuales[n] = precio  # primera lectura: solo se guarda
        elif precio != antes:
            cambios[n] = antes
            actuales[n] = precio

    guardar_json(ESTADO, actuales)

    hist = cargar_historial()
    registrar_lecturas(hist, leidos, hoy)
    avisos_tecnicos = actualizar_fallos(hist, leidos, hoy)
    guardar_json(HISTORIAL, hist)

    if cambios or modo_prueba:
        enviar(construir_mensaje(leidos, previos, cambios, manual=modo_prueba))
    for aviso in avisos_tecnicos:
        enviar(aviso)
