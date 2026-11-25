import os
import random
import requests
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

TOKEN = os.environ["TELEGRAM_TOKEN"]
CANAL = "@RadarDescuentosMX247"
MATT_WORD = "charlysource"
MATT_TOOL = "29165755"

ARCHIVO_HISTORIAL = "publicados.txt"
DESCUENTO_MINIMO = 20  # Porcentaje mínimo de descuento real
MAX_POSTS_POR_CORRIDA = 2

# Categorías populares en Mercado Libre MX (Celulares, Computación, Electrónica, Hogar)
CATEGORIAS = ["MLM1051", "MLM1648", "MLM1000", "MLM1574"]

def cargar_publicados():
    if not os.path.exists(ARCHIVO_HISTORIAL):
        return set()
    with open(ARCHIVO_HISTORIAL, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def guardar_publicado(item_id):
    with open(ARCHIVO_HISTORIAL, "a", encoding="utf-8") as f:
        f.write(f"{item_id}\n")

def convertir_a_afiliado(url_producto):
    partes = urlparse(url_producto)
    params = parse_qs(partes.query)
    params["matt_word"] = [MATT_WORD]
    params["matt_tool"] = [MATT_TOOL]
    nuevo_query = urlencode(params, doseq=True)
    return urlunparse((partes.scheme, partes.netloc, partes.path, partes.params, nuevo_query, ""))

def buscar_ofertas():
    categoria = random.choice(CATEGORIAS)
    url = f"https://api.mercadolibre.com/sites/MLM/search?category={categoria}&limit=50"
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json().get("results", [])

def publicar_en_telegram(item, descuento):
    titulo = item["title"]
    precio = item["price"]
    precio_original = item["original_price"]
    url_afiliado = convertir_a_afiliado(item["permalink"])
    # Mejora la calidad de la miniatura de Mercado Libre
    imagen = item.get("thumbnail", "").replace("-I.jpg", "-O.jpg")

    caption = (
        f"🔥 <b>{titulo}</b>\n\n"
        f"💰 <b>Ahora:</b> ${precio:,.0f} MXN\n"
        f"❌ <b>Antes:</b> <s>${precio_original:,.0f} MXN</s>\n"
        f"📉 <b>Descuento:</b> {descuento}% OFF\n\n"
        f"<i>#Oferta #MercadoLibreMX #Descuento</i>"
    )

    botones = {
        "inline_keyboard": [[
            {"text": "🛒 Ver oferta en Mercado Libre", "url": url_afiliado}
        ]]
    }

    if imagen:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
            json={
                "chat_id": CANAL,
                "photo": imagen,
                "caption": caption,
                "parse_mode": "HTML",
                "reply_markup": botones
            },
            timeout=15
        )
        if r.json().get("ok"):
            return True

    # Respaldo solo texto si la imagen falla
    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={
            "chat_id": CANAL,
            "text": caption,
            "parse_mode": "HTML",
            "reply_markup": botones
        },
        timeout=15
    )
    return r.json().get("ok", False)

def main():
    publicados = cargar_publicados()
    items = buscar_ofertas()
    enviados = 0

    for item in items:
        if enviados >= MAX_POSTS_POR_CORRIDA:
            break

        item_id = item.get("id")
        precio = item.get("price")
        original = item.get("original_price")

        if not item_id or item_id in publicados:
            continue
        if not precio or not original or original <= precio:
            continue

        descuento = round(((original - precio) / original) * 100)
        if descuento < DESCUENTO_MINIMO:
            continue

        if publicar_en_telegram(item, descuento):
            guardar_publicado(item_id)
            publicados.add(item_id)
            enviados += 1
            print(f"Publicado: {item_id} ({descuento}% OFF)")

    print(f"Corrida terminada. Total publicados: {enviados}")

if __name__ == "__main__":
    main()
