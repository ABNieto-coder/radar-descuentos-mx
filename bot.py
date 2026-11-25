import os
import re
import xml.etree.ElementTree as ET
import requests
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

TOKEN = os.environ["TELEGRAM_TOKEN"]
CANAL = "@RadarDescuentosMX247"
MATT_WORD = "charlysource"
MATT_TOOL = "29165755"

ARCHIVO_HISTORIAL = "publicados.txt"
MAX_POSTS_POR_CORRIDA = 2
RSS_URL = "https://www.promodescuentos.com/rss"

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

def extraer_url_ml_de_texto(texto):
    urls = re.findall(r'https?://[^\s"\'<>]+', texto or "")
    candidatos = []
    for u in urls:
        limpia = u.rstrip(").,;")
        baja = limpia.lower()
        if "mercadolibre.com.mx" in baja or "meli.la" in baja:
            candidatos.append(limpia.split("?")[0])

    # Prioriza enlaces de producto o publicación específica
    for c in candidatos:
        b = c.lower()
        if "/p/" in b or "mlm-" in b or "articulo.mercadolibre.com.mx" in b or "meli.la/" in b:
            return c

    return candidatos[0] if candidatos else ""

def buscar_ofertas_ml():
    ofertas = []
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
        }
        resp = requests.get(RSS_URL, headers=headers, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)

        for item in root.findall("./channel/item"):
            titulo = (item.findtext("title") or "").strip()
            link_rss = (item.findtext("link") or "").strip()
            guid = (item.findtext("guid") or link_rss).strip()
            descripcion = item.findtext("description") or ""

            texto_completo = f"{titulo} {descripcion}"
            if "mercado libre" not in texto_completo.lower() and "mercadolibre" not in texto_completo.lower():
                continue

            url_ml = extraer_url_ml_de_texto(f"{link_rss} {descripcion}")
            if not url_ml:
                url_ml = "https://www.mercadolibre.com.mx/ofertas"

            img_match = re.search(r'src=["\'](https?://[^"\']+)["\']', descripcion)
            imagen = img_match.group(1) if img_match else ""

            ofertas.append({
                "id": guid,
                "titulo": titulo,
                "url": convertir_a_afiliado(url_ml),
                "imagen": imagen
            })
    except Exception as e:
        print(f"Aviso RSS: {e}")

    return ofertas

def publicar_en_telegram(oferta):
    caption = (
        f"🔥 <b>{oferta['titulo']}</b>\n\n"
        f"🏪 <b>Tienda:</b> Mercado Libre México\n\n"
        f"<i>#Oferta #MercadoLibreMX #Descuento</i>"
    )
    botones = {
        "inline_keyboard": [[
            {"text": "🛒 Ver oferta en Mercado Libre", "url": oferta["url"]}
        ]]
    }

    if oferta["imagen"]:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
            json={
                "chat_id": CANAL,
                "photo": oferta["imagen"],
                "caption": caption,
                "parse_mode": "HTML",
                "reply_markup": botones
            },
            timeout=15
        )
        if r.json().get("ok"):
            return True

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
    ofertas = buscar_ofertas_ml()
    enviados = 0

    for oferta in ofertas:
        if enviados >= MAX_POSTS_POR_CORRIDA:
            break
        if not oferta["id"] or oferta["id"] in publicados:
            continue

        if publicar_en_telegram(oferta):
            guardar_publicado(oferta["id"])
            publicados.add(oferta["id"])
            enviados += 1
            print(f"Publicado: {oferta['titulo']}")

    print(f"Corrida terminada. Total publicados: {enviados}")

if __name__ == "__main__":
    main()
    
