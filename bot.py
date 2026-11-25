import os
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, quote_plus
import requests

TOKEN = os.environ["TELEGRAM_TOKEN"]
CANAL = "@RadarDescuentosMX247"
MATT_WORD = "charlysource"
MATT_TOOL = "29165755"

ARCHIVO_HISTORIAL = "publicados.txt"
MAX_POSTS_POR_CORRIDA = 5
RSS_URL = "https://www.promodescuentos.com/rss"
URL_RESPALDO_OFERTAS = "https://www.mercadolibre.com.mx/ofertas"

HEADERS_BROWSER = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 14; Pixel 10) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Mobile Safari/537.36"
    )
}


def cargar_publicados():
    if not os.path.exists(ARCHIVO_HISTORIAL):
        return set()
    with open(ARCHIVO_HISTORIAL, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def guardar_publicado(item_id):
    with open(ARCHIVO_HISTORIAL, "a", encoding="utf-8") as f:
        f.write(f"{item_id}\n")


def convertir_a_afiliado(url_producto):
    base = (url_producto or "").strip()
    if not base.startswith(("http://", "https://")):
        base = URL_RESPALDO_OFERTAS

    partes = urlparse(base)
    if not partes.netloc:
        partes = urlparse(URL_RESPALDO_OFERTAS)

    params = parse_qs(partes.query)
    params["matt_word"] = [MATT_WORD]
    params["matt_tool"] = [MATT_TOOL]
    nuevo_query = urlencode(params, doseq=True)
    return urlunparse((
        partes.scheme or "https",
        partes.netloc,
        partes.path or "/",
        partes.params,
        nuevo_query,
        ""
    ))


def extraer_url_ml_de_texto(texto):
    urls = re.findall(r'https?://[^\s"\'<>]+', texto or "")
    candidatos = []
    for u in urls:
        limpia = u.rstrip(").,;!?\"'")
        baja = limpia.lower()
        if "mercadolibre.com.mx" in baja or "meli.la" in baja:
            candidatos.append(limpia.split("?")[0])

    for c in candidatos:
        b = c.lower()
        if "/p/" in b or "mlm-" in b or "articulo.mercadolibre.com.mx" in b or "meli.la/" in b:
            return c

    return candidatos[0] if candidatos else ""


def intentar_resolver_redireccion(url_rss):
    if not url_rss or not url_rss.startswith(("http://", "https://")):
        return ""
    try:
        resp = requests.get(url_rss, headers=HEADERS_BROWSER, allow_redirects=True, timeout=8)
        final_url = (resp.url or "").strip()
        baja = final_url.lower()
        if "mercadolibre.com.mx" in baja or "meli.la" in baja:
            return final_url.split("?")[0]
    except Exception:
        pass
    return ""


def limpiar_titulo_busqueda(titulo):
    limpio = re.sub(r"(?i)mercado\s*libre\s*:?", "", titulo or "").strip()
    limpio = re.sub(r"\s+", " ", limpio)
    return limpio[:90]


def asegurar_link(titulo, link_rss, descripcion):
    # 1. Enlace directo extraído del RSS/descripción
    url_ml = extraer_url_ml_de_texto(f"{link_rss} {descripcion}")

    # 2. Intentar resolver redirección si no venía directo
    if not url_ml:
        url_ml = intentar_resolver_redireccion(link_rss)

    # 3. Búsqueda en Mercado Libre MX con el título del producto
    if not url_ml:
        consulta = limpiar_titulo_busqueda(titulo)
        if consulta:
            url_ml = f"https://listado.mercadolibre.com.mx/{quote_plus(consulta)}"

    # 4. Respaldo final garantizado
    if not url_ml:
        url_ml = URL_RESPALDO_OFERTAS

    return convertir_a_afiliado(url_ml)


def buscar_ofertas_ml():
    ofertas = []
    try:
        resp = requests.get(RSS_URL, headers=HEADERS_BROWSER, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)

        for idx, item in enumerate(root.findall("./channel/item"), start=1):
            titulo = (item.findtext("title") or "").strip() or f"Oferta Mercado Libre #{idx}"
            link_rss = (item.findtext("link") or "").strip()
            guid = (item.findtext("guid") or link_rss or f"oferta-{idx}-{titulo[:30]}").strip()
            descripcion = item.findtext("description") or ""

            texto_completo = f"{titulo} {descripcion} {link_rss}".lower()
            if (
                "mercado libre" not in texto_completo
                and "mercadolibre" not in texto_completo
                and "meli.la" not in texto_completo
            ):
                continue

            url_afiliado = asegurar_link(titulo, link_rss, descripcion)

            img_match = re.search(r'src=["\'](https?://[^"\']+)["\']', descripcion)
            imagen = img_match.group(1) if img_match else ""

            ofertas.append({
                "id": guid,
                "titulo": titulo,
                "url": url_afiliado,
                "imagen": imagen
            })
    except Exception as e:
        print(f"Aviso RSS: {e}")

    return ofertas


def publicar_en_telegram(oferta):
    url_segura = convertir_a_afiliado(oferta.get("url", ""))
    titulo_seguro = (oferta.get("titulo") or "Oferta de Mercado Libre").strip()

    caption = (
        f"🔥 <b>{titulo_seguro}</b>\n\n"
        f"🏪 <b>Tienda:</b> Mercado Libre México\n\n"
        f"<i>#Oferta #MercadoLibreMX #Descuento</i>"
    )
    botones = {
        "inline_keyboard": [[
            {"text": "🛒 Ver oferta en Mercado Libre", "url": url_segura}
        ]]
    }

    if oferta.get("imagen"):
        try:
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
            if r.ok and r.json().get("ok"):
                return True
        except Exception:
            pass

    try:
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
        return bool(r.ok and r.json().get("ok", False))
    except Exception as e:
        print(f"Error enviando a Telegram: {e}")
        return False


def main():
    publicados = cargar_publicados()
    ofertas = buscar_ofertas_ml()
    enviados = 0

    for oferta in ofertas:
        if enviados >= MAX_POSTS_POR_CORRIDA:
            break
        if oferta["id"] in publicados:
            continue

        if publicar_en_telegram(oferta):
            guardar_publicado(oferta["id"])
            publicados.add(oferta["id"])
            enviados += 1
            print(f"Publicado: {oferta['titulo']} -> {oferta['url']}")

    print(f"Corrida terminada. Total publicados: {enviados}")


if __name__ == "__main__":
    main()
    
