"""
Seguimiento de precios de farmacias -> Telegram
Avisa SOLO cuando cambia algún precio, mostrando el comparativo completo.

Instalación:  pip install requests beautifulsoup4
Variables de entorno (no escribas el token en el código):
  TELEGRAM_TOKEN      token de tu bot (BotFather)
  TELEGRAM_CHAT_ID    tu chat id

Uso normal:           python precios_farmacias.py
Enviar comparativo
aunque no haya
cambios (prueba):     python precios_farmacias.py --test

Prueba local en Windows:
  set TELEGRAM_TOKEN=...
  set TELEGRAM_CHAT_ID=...
"""
import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

PRODUCTO = "Acnotin 20 mg"
MONEDA = "Bs"
ZONA = timezone(timedelta(hours=-4))  # hora de Bolivia

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

ESTADO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "precios_previos.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}


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


def cargar_estado():
    try:
        with open(ESTADO, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def guardar_estado(estado):
    with open(ESTADO, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


# ---------- Mensaje ----------

def bs(valor):
    return f"{MONEDA} {valor:.2f}"


def construir_mensaje(leidos, previos, cambios):
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

    con_precio = [f["precio"] for f in filas if f["precio"] is not None]
    minimo = min(con_precio) if con_precio else None

    ahora = datetime.now(ZONA).strftime("%d/%m/%Y, %H:%M")
    lineas = [
        f"<b>{html.escape(PRODUCTO)} · Comparativo de precios</b>",
        f"<i>Variación detectada · {ahora} (hora de Bolivia)</i>",
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

    if minimo is not None:
        mejores = [f["sitio"]["nombre"] for f in filas if f["precio"] == minimo]
        lineas += ["", f"<b>Precio más bajo:</b> {html.escape(' / '.join(mejores))} ({bs(minimo)})"]

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
    modo_prueba = "--test" in sys.argv

    previos = cargar_estado()
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

    guardar_estado(actuales)

    if cambios or modo_prueba:
        enviar(construir_mensaje(leidos, previos, cambios))
