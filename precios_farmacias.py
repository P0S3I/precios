"""
Rastreador de precios -> WhatsApp (CallMeBot) SOLO cuando cambia un precio

Instalación:  pip install requests beautifulsoup4
Uso:          python precios_farmacias.py
Programar:    cron, ej. cada 2 h ->  0 */2 * * * python /ruta/precios_farmacias.py

CallMeBot (gratis, solo a tu número):
  1. Guarda el contacto +34 644 51 95 23 (consulta callmebot.com por si cambió)
  2. Envíale por WhatsApp: "I allow callmebot to send me messages"
  3. Te responde con tu APIKEY.
"""
import json
import os
import re
import requests
from bs4 import BeautifulSoup

PHONE = os.environ.get("PHONE", "34XXXXXXXXX")   # tu número con prefijo, sin +
APIKEY = os.environ.get("APIKEY", "TU_APIKEY")

# Rellena con tus 4 farmacias: URL del producto y selector CSS del precio.
SITIOS = [
    {"nombre": "Farmacia 1", "url": "https://...", "selector": ".price"},
    {"nombre": "Farmacia 2", "url": "https://...", "selector": "span.precio"},
    {"nombre": "Farmacia 3", "url": "https://...", "selector": "#product-price"},
    {"nombre": "Farmacia 4", "url": "https://...", "selector": ".current-price"},
]

# Guarda los últimos precios junto al script
ESTADO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "precios_previos.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}


def obtener_precio(sitio):
    """Devuelve el precio como float, o None si falla."""
    try:
        r = requests.get(sitio["url"], headers=HEADERS, timeout=20)
        r.raise_for_status()
        el = BeautifulSoup(r.text, "html.parser").select_one(sitio["selector"])
        if not el:
            return None
        m = re.search(r"\d+(?:[.,]\d+)?", el.get_text())
        return float(m.group().replace(",", ".")) if m else None
    except Exception:
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


def enviar_whatsapp(texto):
    requests.get(
        "https://api.callmebot.com/whatsapp.php",
        params={"phone": PHONE, "text": texto, "apikey": APIKEY},
        timeout=20,
    )


if __name__ == "__main__":
    previos = cargar_estado()
    actuales = dict(previos)
    avisos = []

    for s in SITIOS:
        nombre = s["nombre"]
        precio = obtener_precio(s)
        if precio is None:
            continue  # fallo puntual: no cuenta como cambio y se conserva el anterior
        antes = previos.get(nombre)
        if antes is None:
            actuales[nombre] = precio  # primera lectura: solo se guarda
        elif precio != antes:
            flecha = "⬇️" if precio < antes else "⬆️"
            avisos.append(f"{flecha} {nombre}: {antes:.2f} € → {precio:.2f} € ({s['url']})")
            actuales[nombre] = precio

    guardar_estado(actuales)
    if avisos:
        enviar_whatsapp("Cambio de precios:\n" + "\n".join(avisos))
