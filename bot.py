import html
import os
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, unquote, quote
import requests

TOKEN = os.environ["TELEGRAM_TOKEN"]
CANAL = "@RadarDescuentosMX247"
MATT_WORD = "charlysource"
MATT_TOOL = "29165755"

ARCHIVO_HISTORIAL = "publicados.txt"
MAX_LINEAS_HISTORIAL = 2000
MAX_POSTS_POR_CORRIDA = 5
RSS_URLS = [
    "https://www.promodescuentos.com/rss",
    "https://www.promodescuentos.com/rss/hot",
]

HEADERS_BROWSER = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
}

PARAMS_A_LIMPIAR = {
    "matt_word",
    "matt_tool",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "aff_id",
    "social_token",
    "tracking_id",
    "ref",
}


def cargar_publicados():
    if not os.path.exists(ARCHIVO_HISTORIAL):
        return set()
    with open(ARCHIVO_HISTORIAL, "r", encoding="utf-8") as f:
        lineas = [line.strip() for line in f if line.strip()]
    if len(lineas) > MAX_LINEAS_HISTORIAL:
        lineas = lineas[-MAX_LINEAS_HISTORIAL:]
        with open(ARCHIVO_HISTORIAL, "w", encoding="utf-8") as f:
            f.write("\n".join(lineas) + "\n")
    return set(lineas)


def guardar_publicado(clave):
    if not clave:
        return
    with open(ARCHIVO_HISTORIAL, "a", encoding="utf-8") as f:
        f.write(f"{clave}\n")


def normalizar_url(url_raw):
    if not url_raw:
        return ""
    limpia = unquote(html.unescape(url_raw.strip()))
    limpia = limpia.rstrip(").,;!?\"'\\]>")
    limpia = limpia.split("#")[0].strip()
    if limpia.startswith("http://"):
        limpia = "https://" + limpia[7:]
    if not limpia.startswith("https://"):
        return ""
    return limpia


def extraer_mlm_id(url):
    match = re.search(r"\b(MLM-?\d{6,14})\b", url or "", flags=re.IGNORECASE)
    if match:
        return match.group(1).upper().replace("-", "")
    return ""


def es_url_ml_valida(url):
    limpia = normalizar_url(url)
    if not limpia:
        return False
    host = (urlparse(limpia).netloc or "").lower()
    return (
        host == "mercadolibre.com.mx"
        or host.endswith(".mercadolibre.com.mx")
        or host == "meli.la"
        or host.endswith(".meli.la")
    )


def es_articulo_especifico(url):
    limpia = normalizar_url(url)
    if not es_url_ml_valida(limpia):
        return False
    partes = urlparse(limpia)
    host = (partes.netloc or "").lower()
    ruta = (partes.path or "").lower()
    if host.endswith("meli.la"):
        return bool(ruta.strip("/"))
    if extraer_mlm_id(ruta) or "/p/" in ruta or "-_jm" in ruta:
        return True
    return False


def blindar_link_afiliado(url_destino):
    limpia = normalizar_url(url_destino)
    if not es_url_ml_valida(limpia):
        limpia = "https://www.mercadolibre.com.mx/ofertas"

    partes = urlparse(limpia)
    params_previos = parse_qs(partes.query, keep_blank_values=False)
    params_limpios = {
        k: v for k, v in params_previos.items()
        if k.lower() not in PARAMS_A_LIMPIAR
    }
    params_limpios["matt_word"] = [MATT_WORD]
    params_limpios["matt_tool"] = [MATT_TOOL]

    return urlunparse((
        "https",
        partes.netloc.lower(),
        partes.path or "/",
        "",
        urlencode(params_limpios, doseq=True),
        ""
    ))


def extraer_urls_candidatas(texto):
    decodificado = unquote(html.unescape(texto or ""))
    encontrados = []
    for match in re.findall(r"https?://[^\s\"'<>)\]]+", decodificado, flags=re.IGNORECASE):
        limpia = normalizar_url(match)
        if limpia and limpia not in encontrados:
            encontrados.append(limpia)
    return encontrados


def resolver_enlace_ml(link_rss, descripcion, xml_item, titulo):
    candidatos = extraer_urls_candidatas(f"{link_rss} {descripcion} {xml_item}")

    # 1. Prioriza enlace directo a artículo o acortador meli.la
    for cand in candidatos:
        if es_articulo_especifico(cand):
            return cand

    # 2. Intenta resolver redirecciones desde link_rss o candidatos de ML / Promodescuentos
    for cand in [link_rss] + candidatos:
        u = normalizar_url(cand)
        if not u:
            continue
        host = (urlparse(u).netloc or "").lower()
        if "mercadolibre.com.mx" in host or "meli.la" in host or "promodescuentos.com" in host:
            try:
                resp = requests.get(u, headers=HEADERS_BROWSER, allow_redirects=True, timeout=10)
                final_u = normalizar_url(resp.url)
                if es_articulo_especifico(final_u):
                    return final_u
                for interna in extraer_urls_candidatas(resp.text or ""):
                    if es_articulo_especifico(interna):
                        return interna
                if es_url_ml_valida(final_u):
                    return final_u
            except Exception:
                continue

    # 3. Si ya venía alguna URL directa de mercadolibre.com.mx, úsala
    for cand in candidatos:
        if es_url_ml_valida(cand):
            return cand

    # 4. Búsqueda por título en Mercado Libre México como respaldo útil
    titulo_limpio = re.sub(r"(?i)mercado\s*libre\s*:?", "", titulo or "").strip()[:85]
    if titulo_limpio:
        return f"https://listado.mercadolibre.com.mx/{quote(titulo_limpio)}"

    return "https://www.mercadolibre.com.mx/ofertas"


def extraer_precio_y_descuento(titulo, descripcion):
    texto = html.unescape(f"{titulo} {descripcion}")
    precios = re.findall(r"\$\s?[\d,]+(?:\.\d{1,2})?", texto)
    descuento = re.search(
        r"(\d{1,2}\s?%\s?(?:OFF|de descuento|dto)?)",
        texto,
        flags=re.IGNORECASE,
    )
    precio_str = precios[0].replace(" ", "") if precios else ""
    desc_str = descuento.group(1).strip() if descuento else ""
    return precio_str, desc_str


def escapar_html(texto):
    return html.escape(html.unescape(texto or "").strip())


def buscar_ofertas():
    ofertas = []
    vistos_corrida = set()

    for feed_url in RSS_URLS:
        try:
            resp = requests.get(feed_url, headers=HEADERS_BROWSER, timeout=15)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
        except Exception as e:
            print(f"Aviso leyendo RSS {feed_url}: {e}")
            continue

        for idx, item in enumerate(root.findall("./channel/item"), start=1):
            titulo = (item.findtext("title") or "").strip()
            link_rss = (item.findtext("link") or "").strip()
            guid = (item.findtext("guid") or link_rss or f"item-{idx}").strip()
            descripcion = item.findtext("description") or ""

            if not titulo:
                continue

            texto_busqueda = f"{titulo} {descripcion} {link_rss}".lower()
            if (
                "mercado libre" not in texto_busqueda
                and "mercadolibre" not in texto_busqueda
                and "meli.la" not in texto_busqueda
            ):
                continue

            xml_item = ET.tostring(item, encoding="unicode", method="xml") or ""
            url_resuelta = resolver_enlace_ml(link_rss, descripcion, xml_item, titulo)
            url_afiliado = blindar_link_afiliado(url_resuelta)
            mlm_id = extraer_mlm_id(url_afiliado)

            clave_dedup = mlm_id or guid
            if clave_dedup in vistos_corrida:
                continue
            vistos_corrida.add(clave_dedup)

            precio, descuento = extraer_precio_y_descuento(titulo, descripcion)
            img_match = re.search(r'src=["\'](https?://[^"\']+)["\']', descripcion)
            imagen = normalizar_url(img_match.group(1)) if img_match else ""

            ofertas.append({
                "guid": guid,
                "mlm_id": mlm_id,
                "titulo": titulo,
                "precio": precio,
                "descuento": descuento,
                "url": url_afiliado,
                "imagen": imagen,
            })

    return ofertas


def construir_link_compartir(titulo, url_afiliado):
    texto_compartir = (
        f"🔥 ¡Mira esta oferta en Mercado Libre México!\n"
        f"{titulo}\n\n"
        f"👉 Más descuentos diarios en {CANAL}"
    )
    return f"https://t.me/share/url?url={quote(url_afiliado)}&text={quote(texto_compartir)}"


def publicar_en_telegram(oferta):
    url_afiliado = blindar_link_afiliado(oferta.get("url", ""))
    titulo_crudo = (oferta.get("titulo") or "").strip()
    if not url_afiliado or not titulo_crudo:
        return False

    titulo_seguro = escapar_html(titulo_crudo)
    lineas = [f"🔥 <b>{titulo_seguro}</b>", ""]

    if oferta.get("precio") or oferta.get("descuento"):
        detalle = []
        if oferta.get("precio"):
            detalle.append(f"💰 <b>Precio:</b> {escapar_html(oferta['precio'])}")
        if oferta.get("descuento"):
            detalle.append(f"🏷️ <b>Ahorro:</b> {escapar_html(oferta['descuento'])}")
        lineas.append("  |  ".join(detalle))
        lineas.append("")

    lineas.extend([
        "🛒 <b>Tienda:</b> Mercado Libre México",
        "⚡ <i>Oferta por tiempo limitado / sujeto a stock</i>",
        "",
        f"📲 <b>Únete y comparte:</b> {CANAL}",
        "<i>#OfertasMX #MercadoLibre #Descuentos</i>",
    ])
    caption = "\n".join(lineas)

    link_compartir = construir_link_compartir(titulo_crudo, url_afiliado)
    botones = {
        "inline_keyboard": [
            [{"text": "🛒 Ver oferta en Mercado Libre", "url": url_afiliado}],
            [{"text": "📤 Compartir oferta con un amigo", "url": link_compartir}],
        ]
    }

    if oferta.get("imagen") and oferta["imagen"].startswith("https://"):
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
                json={
                    "chat_id": CANAL,
                    "photo": oferta["imagen"],
                    "caption": caption,
                    "parse_mode": "HTML",
                    "reply_markup": botones,
                },
                timeout=15,
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
                "reply_markup": botones,
            },
            timeout=15,
        )
        return bool(r.ok and r.json().get("ok", False))
    except Exception as e:
        print(f"Error enviando a Telegram: {e}")
        return False


def main():
    publicados = cargar_publicados()
    ofertas = buscar_ofertas()
    enviados = 0

    for oferta in ofertas:
        if enviados >= MAX_POSTS_POR_CORRIDA:
            break

        guid = oferta["guid"]
        mlm_id = oferta["mlm_id"]

        if guid in publicados or (mlm_id and mlm_id in publicados):
            continue

        if publicar_en_telegram(oferta):
            guardar_publicado(guid)
            publicados.add(guid)
            if mlm_id:
                guardar_publicado(mlm_id)
                publicados.add(mlm_id)
            enviados += 1
            print(f"Publicado: {oferta['titulo']} -> {oferta['url']}")

    print(f"Corrida terminada. Total publicados: {enviados}")


if __name__ == "__main__":
    main()
    
