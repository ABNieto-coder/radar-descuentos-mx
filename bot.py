import html
import os
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, unquote, quote
import requests

from reel_publisher import publicar_reel_en_instagram

TOKEN = os.environ["TELEGRAM_TOKEN"]
CANAL = "@RadarDescuentosMX247"
MATT_WORD = "charlysource"
MATT_TOOL = "29165755"

ARCHIVO_HISTORIAL = "publicados.txt"
MAX_LINEAS_HISTORIAL = 2000
MAX_POSTS_POR_CORRIDA = 5
MAX_LISTADOS_POR_CORRIDA = 1  # Cambia a 0 si NO quieres publicar ningún listado
MAX_POSTS_IG_POR_CORRIDA = 2

RSS_URLS = [
    "https://www.promodescuentos.com/rss",
    "https://www.promodescuentos.com/rss/hot",
]
API_MLM_SEARCH = "https://api.mercadolibre.com/sites/MLM/search"

HEADERS_BROWSER = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
}

HEADERS_API = {
    "User-Agent": "Mozilla/5.0 (compatible; RadarDescuentosMX/1.0)",
    "Accept": "application/json",
}

PARAMS_A_LIMPIAR = {
    "matt_word", "matt_tool", "utm_source", "utm_medium", "utm_campaign",
    "utm_term", "utm_content", "gclid", "fbclid", "aff_id", "social_token",
    "tracking_id", "ref",
}

SENALES_LISTADO = (
    "toda la tienda", "varios modelos", "varias tallas", "selección de",
    "seleccion de", "productos participantes", "artículos participantes",
    "articulos participantes", "cupones", "cupón", "cupon", "bonificación",
    "bonificacion", "hasta 50%", "hasta 60%", "hasta 40%", "hasta 70%",
)

PALABRAS_CERO_COMISION = (
    "coca-cola", "coca cola", "pepsi", "refresco", "cerveza", "whisky",
    "tequila", "vino tinto", "café molido", "cafe molido", "café soluble",
    "leche ", "galletas", "cereal ", "atún", "atun", "aceite comestible",
    "croquetas", "alimento para perro", "alimento para gato", "despensa",
)


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
    if clave:
        with open(ARCHIVO_HISTORIAL, "a", encoding="utf-8") as f:
            f.write(f"{clave}\n")


def normalizar_url(url_raw):
    if not url_raw:
        return ""
    limpia = unquote(html.unescape(url_raw.strip()))
    limpia = limpia.rstrip(").,;!?\"'\\]>").split("#")[0].strip()
    if limpia.startswith("http://"):
        limpia = "https://" + limpia[7:]
    return limpia if limpia.startswith("https://") else ""


def extraer_mlm_id(url):
    match = re.search(r"\b(MLM-?\d{6,14})\b", url or "", flags=re.IGNORECASE)
    return match.group(1).upper().replace("-", "") if match else ""


def es_url_producto_exacto(url):
    limpia = normalizar_url(url)
    if not limpia:
        return False
    partes = urlparse(limpia)
    host = (partes.netloc or "").lower()
    ruta = (partes.path or "").lower()

    if not (host == "mercadolibre.com.mx" or host.endswith(".mercadolibre.com.mx")):
        return False
    if any(seg in ruta for seg in ("/ofertas", "/listado", "/tienda/", "/c/", "/gz/")):
        return False

    return bool(
        extraer_mlm_id(ruta)
        or "/p/" in ruta
        or "-_jm" in ruta
        or host.startswith("articulo.mercadolibre.com.mx")
    )


def blindar_link_afiliado(url_destino):
    limpia = normalizar_url(url_destino)
    partes = urlparse(limpia)
    host = (partes.netloc or "").lower()

    if not (host == "mercadolibre.com.mx" or host.endswith(".mercadolibre.com.mx")):
        return ""

    params_previos = parse_qs(partes.query, keep_blank_values=False)
    params_limpios = {
        k: v for k, v in params_previos.items()
        if k.lower() not in PARAMS_A_LIMPIAR
    }
    params_limpios["matt_word"] = [MATT_WORD]
    params_limpios["matt_tool"] = [MATT_TOOL]

    return urlunparse((
        "https",
        host,
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


def seguir_redireccion(url, timeout=10):
    try:
        resp = requests.get(url, headers=HEADERS_BROWSER, allow_redirects=True, timeout=timeout)
        if resp.status_code < 400:
            return normalizar_url(resp.url), resp.text or ""
    except Exception:
        pass
    return "", ""


def limpiar_titulo_para_busqueda(titulo):
    limpio = html.unescape(titulo or "")
    limpio = re.sub(r"(?i)mercado\s*libre\s*:?", "", limpio)
    limpio = re.sub(r"\$\s?[\d,]+(?:\.\d{1,2})?", "", limpio)
    limpio = re.sub(r"\b\d{1,2}\s?%\s?(?:off|descuento|dto)\b", "", limpio, flags=re.IGNORECASE)
    limpio = re.sub(r"(?i)\b(envío gratis|envio gratis|full|msi|meses sin intereses)\b", "", limpio)
    limpio = re.sub(r"[^\w\sáéíóúñÁÉÍÓÚÑ-]", " ", limpio)
    limpio = re.sub(r"\s+", " ", limpio).strip()
    return limpio[:75]


def buscar_permalink_ml_api(consulta):
    """Consulta segura a la API pública de Mercado Libre MX con respaldo silencioso."""
    if not consulta:
        return ""
    try:
        resp = requests.get(
            API_MLM_SEARCH,
            params={"q": consulta, "limit": 3},
            headers=HEADERS_API,
            timeout=6,
        )
        if resp.status_code != 200:
            return ""
        data = resp.json()
        resultados = data.get("results") if isinstance(data, dict) else []
        if not isinstance(resultados, list):
            return ""
        for item in resultados:
            if not isinstance(item, dict):
                continue
            permalink = normalizar_url(item.get("permalink", ""))
            if es_url_producto_exacto(permalink):
                return permalink
    except Exception:
        return ""
    return ""


def resolver_oferta_con_nivel(link_rss, descripcion, xml_item, titulo):
    candidatos = extraer_urls_candidatas(f"{link_rss} {descripcion} {xml_item}")

    for cand in candidatos:
        if es_url_producto_exacto(cand):
            return cand, 1, "rss"

    for cand in candidatos:
        if "meli.la/" in cand.lower():
            final_u, cuerpo = seguir_redireccion(cand)
            if es_url_producto_exacto(final_u):
                return final_u, 1, "meli.la"
            for interna in extraer_urls_candidatas(cuerpo):
                if es_url_producto_exacto(interna):
                    return interna, 1, "meli.la-html"

    match_thread = re.search(r"-(\d{5,9})(?:[/?#]|$)", link_rss or "")
    if match_thread and "promodescuentos.com" in (link_rss or "").lower():
        thread_id = match_thread.group(1)
        visit_url = f"https://www.promodescuentos.com/visit/threadmain/{thread_id}"
        final_u, cuerpo = seguir_redireccion(visit_url)
        if es_url_producto_exacto(final_u):
            return final_u, 1, "visit"
        for interna in extraer_urls_candidatas(cuerpo):
            if es_url_producto_exacto(interna):
                return interna, 1, "visit-html"

    if link_rss and "promodescuentos.com" in link_rss.lower():
        _, cuerpo_post = seguir_redireccion(link_rss)
        for interna in extraer_urls_candidatas(cuerpo_post):
            if es_url_producto_exacto(interna):
                return interna, 1, "post-html"
            if "meli.la/" in interna.lower():
                final_meli, _ = seguir_redireccion(interna)
                if es_url_producto_exacto(final_meli):
                    return final_meli, 1, "post-meli"

    titulo_bajo = (titulo or "").lower()
    if any(s in titulo_bajo for s in SENALES_LISTADO):
        return "", 99, "descartado"

    consulta = limpiar_titulo_para_busqueda(titulo)

    permalink_api = buscar_permalink_ml_api(consulta)
    if permalink_api and es_url_producto_exacto(permalink_api):
        return permalink_api, 1, "api-ml"

    if len(consulta) >= 8:
        return f"https://listado.mercadolibre.com.mx/{quote(consulta)}", 2, "listado"

    return "", 99, "sin-link"


def extraer_precio_y_descuento(titulo, descripcion):
    texto = html.unescape(f"{titulo} {descripcion}")
    precios = re.findall(r"\$\s?[\d,]+(?:\.\d{1,2})?", texto)
    descuento = re.search(r"(\d{1,2}\s?%\s?(?:OFF|de descuento|dto)?)", texto, flags=re.IGNORECASE)
    return (
        precios[0].replace(" ", "") if precios else "",
        descuento.group(1).strip() if descuento else "",
    )


def escapar_html(texto):
    return html.escape(html.unescape(texto or "").strip())


def buscar_ofertas_curadas():
    ofertas = []
    vistos_corrida = set()

    for feed_url in RSS_URLS:
        try:
            resp = requests.get(feed_url, headers=HEADERS_BROWSER, timeout=15)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
        except Exception as e:
            print(f"Aviso RSS {feed_url}: {e}")
            continue

        for idx, item in enumerate(root.findall("./channel/item"), start=1):
            titulo = (item.findtext("title") or "").strip()
            link_rss = (item.findtext("link") or "").strip()
            guid = (item.findtext("guid") or link_rss or f"item-{idx}").strip()
            descripcion = item.findtext("description") or ""

            if not titulo:
                continue

            texto_bajo = f"{titulo} {descripcion} {link_rss}".lower()
            if (
                "mercado libre" not in texto_bajo
                and "mercadolibre" not in texto_bajo
                and "meli.la" not in texto_bajo
            ):
                continue

            if any(p in texto_bajo for p in PALABRAS_CERO_COMISION):
                continue

            xml_item = ET.tostring(item, encoding="unicode", method="xml") or ""
            url_cruda, tier, origen = resolver_oferta_con_nivel(link_rss, descripcion, xml_item, titulo)
            if tier > 2 or not url_cruda:
                continue

            url_afiliado = blindar_link_afiliado(url_cruda)
            if not url_afiliado:
                continue

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
                "tier": tier,
                "origen": origen,
                "titulo": titulo,
                "precio": precio,
                "descuento": descuento,
                "url": url_afiliado,
                "imagen": imagen,
            })

    ofertas.sort(key=lambda x: (x["tier"], 0 if x["descuento"] else 1))
    return ofertas


def construir_link_compartir(titulo, url_afiliado):
    texto = (
        f"🔥 ¡Mira esta oferta en Mercado Libre México!\n"
        f"{titulo}\n\n"
        f"👉 Más descuentos diarios en {CANAL}"
    )
    return f"https://t.me/share/url?url={quote(url_afiliado)}&text={quote(texto)}"


def publicar_en_telegram(oferta):
    url_afiliado = blindar_link_afiliado(oferta.get("url", ""))
    titulo_crudo = (oferta.get("titulo") or "").strip()
    if not url_afiliado or not titulo_crudo:
        return False

    titulo_seguro = escapar_html(titulo_crudo)
    etiqueta_tipo = "✅ <b>Producto Directo</b>" if oferta.get("tier") == 1 else "🔎 <b>Oferta Destacada</b>"

    lineas = [
        etiqueta_tipo,
        f"🔥 <b>{titulo_seguro}</b>",
        "",
    ]

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
        f"📲 <b>Únete y comparte:</b> {CANAL}",
        "<i>#OfertasMX #MercadoLibre #Descuentos</i>",
    ])
    caption = "\n".join(lineas)

    texto_boton = "🛒 Ver producto en Mercado Libre" if oferta.get("tier") == 1 else "🔎 Ver oferta en Mercado Libre"
    botones = {
        "inline_keyboard": [
            [{"text": texto_boton, "url": url_afiliado}],
            [{"text": "📤 Compartir oferta con un amigo", "url": construir_link_compartir(titulo_crudo, url_afiliado)}],
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
    ofertas = buscar_ofertas_curadas()
    enviados = 0
    listados_enviados = 0
    ig_enviados = 0

    for oferta in ofertas:
        if enviados >= MAX_POSTS_POR_CORRIDA:
            break

        if oferta["tier"] == 2 and listados_enviados >= MAX_LISTADOS_POR_CORRIDA:
            continue

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
            if oferta["tier"] == 2:
                listados_enviados += 1
            print(f"Publicado [Tier {oferta['tier']}/{oferta['origen']}]: {oferta['titulo']} -> {oferta['url']}")

            if oferta["tier"] == 1 and ig_enviados < MAX_POSTS_IG_POR_CORRIDA:
                if publicar_reel_en_instagram(oferta):
                    ig_enviados += 1

    print(f"Corrida terminada. Telegram: {enviados} (Listados: {listados_enviados}) | Instagram Reels: {ig_enviados}")


if __name__ == "__main__":
    main()
    
