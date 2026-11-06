"""
Rastreador de precios -> Telegram, SOLO cuando cambia un precio

Instalación:  pip install requests beautifulsoup4
Variables de entorno necesarias (NO las escribas en el código):
  TELEGRAM_TOKEN    token de tu bot (BotFather)
  TELEGRAM_CHAT_ID  tu chat id

Prueba local (Windows):   set TELEGRAM_TOKEN=...   y   set TELEGRAM_CHAT_ID=...
Prueba local (Linux/Mac): export TELEGRAM_TOKEN=... y export TELEGRAM_CHAT_ID=...
Luego:                    python precios_farmacias.py
"""
import json
import os
import re
import requests
from bs4 import BeautifulSoup

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
MONEDA = "Bs"

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


def enviar(texto):
    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": texto, "disable_web_page_preview": True},
        timeout=20,
    )
    if not r.ok:
        print("Error enviando a Telegram:", r.text)


if __name__ == "__main__":
    previos = cargar_estado()
    actuales = dict(previos)
    avisos = []

    for s in SITIOS:
        nombre = s["nombre"]
        precio = obtener_precio(s)
        print(f"{nombre}: {precio}")
        if precio is None:
            continue  # fallo puntual: se conserva el precio anterior
        antes = previos.get(nombre)
        if antes is None:
            actuales[nombre] = precio  # primera lectura: solo se guarda
        elif precio != antes:
            flecha = "⬇️" if precio < antes else "⬆️"
            avisos.append(
                f"{flecha} {nombre}: {antes:.2f} {MONEDA} → {precio:.2f} {MONEDA}\n{s['url']}"
            )
            actuales[nombre] = precio

    guardar_estado(actuales)
    if avisos:
        enviar("Cambio de precios:\n\n" + "\n\n".join(avisos))
