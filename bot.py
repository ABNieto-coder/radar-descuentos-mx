import html
import os
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, unquote, quote
import requests

from reel_publisher import publicar_reel_en_instagram

TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CANAL = "@RadarDescuentosMX247"
MATT_WORD = "charlysource"
MATT_TOOL = "29165755"

ARCHIVO_HISTORIAL = "publicados.txt"
MAX_LINEAS_HISTORIAL = 2000
MAX_POSTS_POR_CORRIDA = 5
MAX_LISTADOS_POR_CORRIDA = 1
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

PALABRAS_NICHO_TECH = (
    "audífonos", "audifonos", "earbuds", "tws", "diadema gamer",
    "monitor", "ssd", "nvme", "disco duro", "disco externo",
    "unidad de estado sólido", "unidad de estado solido",
    "usb", "memoria usb", "pendrive", "hub usb", "adaptador usb",
    "gamer", "gaming", "oled", "qled", "mini led", "hz",
    "teclado", "teclado mecánico", "teclado mecanico", "mouse",
    "smartwatch", "reloj inteligente", "banda inteligente",
    "cargador", "cargador rápido", "cargador rapido", "power bank",
    "bocina", "altavoz", "barra de sonido", "soundbar",
    "webcam", "cámara web", "camara web", "router", "mesh",
    "tarjeta gráfica", "tarjeta grafica", "gpu", "procesador",
    "laptop", "notebook", "chromebook", "tablet", "ipad",
    "impresora", "proyector", "micrófono", "microfono", "capturadora",
    "cámara", "camara", "dron",
)

PALABRAS_NICHO_CUIDADO = (
    "protector solar", "protectores solares", "bloqueador solar",
    "bloqueador", "fps", "spf", "uv defender", "anthelios",
    "sérum", "serum", "vitamina c", "retinol", "ácido salicílico",
    "acido salicilico", "ácido hialurónico", "acido hialuronico",
    "niacinamida", "limpiador facial", "gel limpiador",
    "espuma limpiadora", "agua micelar", "tónico facial", "tonico facial",
    "crema facial", "hidratante facial", "contorno de ojos",
    "cuidado facial", "cuidado de la piel", "skincare",
    "bálsamo labial", "balsamo labial", "desodorante", "antitranspirante",
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
    if not limpia.startswith("https://"):
        return ""
    sin_esquema = limpia[8:]
    host_candidato = sin_esquema.split("/", 1)[0].split("?", 1)[0]
    if "[" in host_candidato or "]" in host_candidato:
        return ""
    try:
        partes = urlparse(limpia)
        if "/glossary" in (partes.path or "").lower():
            return ""
    except ValueError:
        return ""
    return limpia


def extraer_mlm_id(url):
    match = re.search(r"\b(MLM-?\d{6,14})\b", url or "", flags=re.IGNORECASE)
    return match.group(1).upper().replace("-", "") if match else ""


def mlm_desde_url(url):
    """Extrae el identificador MLM desde una URL de producto o enlace de afiliado."""
    return extraer_mlm_id(url)


def es_url_producto_exacto(url):
    try:
        limpia = normalizar_url(url)
        if not limpia:
            return False
        partes = urlparse(limpia)
        host = (partes.netloc or "").lower()
        ruta = (partes.path or "").lower()

        if not (host == "mercadolibre.com.mx" or host.endswith(".mercadolibre.com.mx")):
            return False
        if any(seg in ruta for seg in ("/glossary", "/ofertas", "/listado", "/tienda/", "/c/", "/gz/")):
            return False

        return bool(
            extraer_mlm_id(ruta)
            or re.search(r"/p/mlm\d+", ruta)
            or "-_jm" in ruta
            or host.startswith("articulo.mercadolibre.com.mx")
        )
    except ValueError:
        return False


def destino_publicable(url, tier):
    """Valida si una URL y nivel (tier 1 o 2) son seguros y elegibles para publicar."""
    try:
        if tier not in (1, 2):
            return False
        limpia = normalizar_url(url)
        if not limpia:
            return False
        partes = urlparse(limpia)
        host = (partes.netloc or "").lower()
        ruta = (partes.path or "").lower()

        if not (host == "mercadolibre.com.mx" or host.endswith(".mercadolibre.com.mx")):
            return False
        if "/glossary" in ruta:
            return False

        if tier == 1:
            return es_url_producto_exacto(limpia)
        return bool(ruta and ruta != "/")
    except ValueError:
        return False


def blindar_link_afiliado(url_destino):
    try:
        limpia = normalizar_url(url_destino)
        if not limpia:
            return ""
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
    except ValueError:
        return ""


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
    limpio = re.sub(r"^\s*\d+\s*°\s*[-–—:]?\s*", "", limpio)
    limpio = re.sub(r"(?i)mercado\s*libre\s*:?", "", limpio)
    limpio = re.sub(r"\$\s?[\d,]+(?:\.\d{1,2})?", "", limpio)
    limpio = re.sub(r"\b\d{1,2}\s?%\s?(?:off|descuento|dto)\b", "", limpio, flags=re.IGNORECASE)
    limpio = re.sub(r"(?i)\b(envío gratis|envio gratis|full|msi|meses sin intereses)\b", "", limpio)
    limpio = re.sub(r"[^\w\sáéíóúñÁÉÍÓÚÑ-]", " ", limpio)
    limpio = re.sub(r"\s+", " ", limpio).strip()
    return limpio[:75]


def limpiar_titulo_simple(titulo):
    limpio = html.unescape((titulo or "").strip())
    limpio = re.sub(r"^\s*\d+\s*°\s*[-–—:]?\s*", "", limpio)
    limpio = re.sub(r"(?i)^mercado\s*libre\s*:?\s*", "", limpio)
    limpio = re.sub(r"\s*\|\s*MercadoLibre.*$", "", limpio, flags=re.IGNORECASE)
    limpio = re.sub(r"\s+", " ", limpio).strip()
    return limpio or "Oferta disponible"


def _corregir_cantidad_contradictoria(titulo: str, url: str) -> str:
    limpio = limpiar_titulo_simple(titulo)
    url_baja = (url or "").lower()
    if "paquete-de-6" in url_baja or "de-6" in url_baja:
        limpio = re.sub(
            r"(?i)\bpaquete\s+de\s+\d+\s+(.*?)\s+(?:de|paquete\s+de)\s+6\b",
            r"Paquete De 6 \1",
            limpio,
        )
    return re.sub(r"\s+", " ", limpio).strip()


def formatear_precio_mxn(valor):
    try:
        num = float(str(valor).replace(",", "").strip())
        if num <= 0:
            return ""
        if num.is_integer():
            return f"${int(num):,}"
        return f"${num:,.2f}"
    except Exception:
        return ""


def _normalizar_precio_visible(precio_raw: str) -> str:
    limpio = (precio_raw or "").strip()
    if not limpio:
        return ""
    fmt = formatear_precio_mxn(re.sub(r"[^\d.]", "", limpio))
    return fmt or limpio


def _imagen_es_valida(url_img: str) -> bool:
    limpia = normalizar_url(url_img)
    if not limpia or not limpia.startswith("https://"):
        return False
    try:
        with requests.get(limpia, headers=HEADERS_BROWSER, stream=True, timeout=8) as r:
            if not r.ok:
                return False
            ctype = (r.headers.get("Content-Type") or "").lower()
            primeros_bytes = b""
            for chunk in r.iter_content(chunk_size=1024):
                if chunk:
                    primeros_bytes += chunk
                    if len(primeros_bytes) >= 64:
                        break
        if len(primeros_bytes) < 32:
            return False
        if "image/" in ctype:
            return True
        return (
            primeros_bytes[:3] == b"\xff\xd8\xff"
            or primeros_bytes[:8] == b"\x89PNG\r\n\x1a\n"
            or b"WEBP" in primeros_bytes[:16]
        )
    except Exception:
        return False


def _extraer_datos_html_ml(url_producto: str) -> dict:
    datos = {}
    if not url_producto:
        return datos
    try:
        resp = requests.get(url_producto, headers=HEADERS_BROWSER, timeout=10)
        if not resp.ok or not resp.text:
            return datos
        cuerpo = resp.text

        m_title = re.search(
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
            cuerpo,
            flags=re.IGNORECASE,
        )
        if m_title:
            titulo_limpio = limpiar_titulo_simple(m_title.group(1))
            if len(titulo_limpio) >= 6:
                datos["titulo"] = titulo_limpio

        m_img = re.search(
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            cuerpo,
            flags=re.IGNORECASE,
        )
        if m_img:
            img_limpia = normalizar_url(m_img.group(1))
            if img_limpia:
                datos["imagen"] = img_limpia

        patrones_precio = (
            r'<meta[^>]+(?:property|name)=["\'](?:product:price:amount|twitter:data1)["\'][^>]+content=["\']([^"\']+)["\']',
            r'"price"\s*:\s*([0-9]+(?:\.[0-9]{1,2})?)\s*,\s*"currency_id"\s*:\s*"MXN"',
            r'"lowPrice"\s*:\s*"?([0-9]+(?:\.[0-9]{1,2})?)"?',
            r'"price"\s*:\s*"?([0-9]+(?:\.[0-9]{1,2})?)"?',
        )
        for pat in patrones_precio:
            m_price = re.search(pat, cuerpo, flags=re.IGNORECASE)
            if m_price:
                precio_fmt = formatear_precio_mxn(re.sub(r"[^\d.]", "", m_price.group(1)))
                if precio_fmt:
                    datos["precio"] = precio_fmt
                    break

        m_desc = re.search(r"\b(\d{1,2}\s?%\s?OFF)\b", cuerpo, flags=re.IGNORECASE)
        if m_desc:
            datos["descuento"] = m_desc.group(1).upper()
    except Exception as e:
        print(f"Aviso leyendo metadatos HTML ML: {e}")

    return datos


def enriquecer_oferta_con_ml(oferta: dict) -> dict:
    if oferta.get("tier") != 1:
        return oferta

    mlm_id = (oferta.get("mlm_id") or "").strip().upper()
    precio_api = ""

    if mlm_id:
        try:
            resp = requests.get(
                f"https://api.mercadolibre.com/items/{mlm_id}",
                headers=HEADERS_API,
                timeout=8,
            )
            if resp.ok:
                data = resp.json() if isinstance(resp.json(), dict) else {}
                titulo_ml = limpiar_titulo_simple(data.get("title") or "")
                if len(titulo_ml) >= 6:
                    oferta["titulo"] = titulo_ml

                precio_fmt = formatear_precio_mxn(data.get("price"))
                if precio_fmt:
                    precio_api = precio_fmt
                    oferta["precio"] = precio_fmt

                original_price = data.get("original_price")
                price = data.get("price")
                if original_price and price and float(original_price) > float(price):
                    pct = round((1 - (float(price) / float(original_price))) * 100)
                    if 1 <= pct <= 95:
                        oferta["descuento"] = f"{pct}% OFF"

                pictures = data.get("pictures") or []
                if isinstance(pictures, list) and pictures:
                    pic_url = pictures[0].get("secure_url") if isinstance(pictures[0], dict) else ""
                    if pic_url:
                        oferta["imagen"] = normalizar_url(pic_url)
        except Exception as e:
            print(f"Aviso enriqueciendo oferta {mlm_id} desde API ML: {e}")

    url_limpia = (oferta.get("url") or "").split("?")[0]
    datos_html = _extraer_datos_html_ml(url_limpia)
    if datos_html.get("precio"):
        oferta["precio"] = datos_html["precio"]
    elif precio_api:
        oferta["precio"] = precio_api

    if not oferta.get("titulo") and datos_html.get("titulo"):
        oferta["titulo"] = datos_html["titulo"]
    if not oferta.get("imagen") and datos_html.get("imagen"):
        oferta["imagen"] = datos_html["imagen"]
    if datos_html.get("descuento"):
        oferta["descuento"] = datos_html["descuento"]

    return oferta


def blindar_datos_oferta(oferta: dict) -> dict:
    oferta["titulo"] = _corregir_cantidad_contradictoria(
        oferta.get("titulo") or "",
        oferta.get("url") or "",
    )
    oferta = enriquecer_oferta_con_ml(oferta)
    oferta["titulo"] = _corregir_cantidad_contradictoria(
        oferta.get("titulo") or "",
        oferta.get("url") or "",
    )

    precio_limpio = _normalizar_precio_visible(oferta.get("precio") or "")
    if precio_limpio:
        oferta["precio"] = precio_limpio

    imagen_actual = normalizar_url(oferta.get("imagen") or "")
    if imagen_actual and _imagen_es_valida(imagen_actual):
        oferta["imagen"] = imagen_actual
        return oferta

    mlm_id = (oferta.get("mlm_id") or "").strip().upper()
    if mlm_id:
        try:
            resp = requests.get(
                f"https://api.mercadolibre.com/items/{mlm_id}",
                headers=HEADERS_API,
                timeout=8,
            )
            if resp.ok and isinstance(resp.json(), dict):
                data = resp.json()
                candidatas = []
                for pic in (data.get("pictures") or []):
                    if isinstance(pic, dict) and pic.get("secure_url"):
                        candidatas.append(normalizar_url(pic["secure_url"]))
                for thumb_key in ("secure_thumbnail", "thumbnail"):
                    if data.get(thumb_key):
                        candidatas.append(normalizar_url(data[thumb_key]))
                for cand in candidatas:
                    if cand and _imagen_es_valida(cand):
                        oferta["imagen"] = cand
                        return oferta
        except Exception as e:
            print(f"Aviso validando imagen ML para {mlm_id}: {e}")

    oferta["imagen"] = ""
    return oferta


def detectar_nicho_oferta(titulo: str, url: str = "") -> str:
    texto = f"{titulo or ''} {url or ''}".lower()
    if any(p in texto for p in PALABRAS_NICHO_CUIDADO):
        return "cuidado_personal"
    if any(p in texto for p in PALABRAS_NICHO_TECH):
        return "tecnologia"
    return "general"


def buscar_permalink_ml_api(consulta):
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


def buscar_ofertas_filtradas():
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

            if re.search(r"(?i)^\s*(?:cup[oó]n\s+de\b|bonificaci[oó]n\b)", limpiar_titulo_simple(titulo)):
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
            if tier > 2 or not url_cruda or not destino_publicable(url_cruda, tier):
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
    titulo_limpio = limpiar_titulo_simple(titulo)
    texto = (
        f"Oferta en {CANAL}:\n"
        f"{titulo_limpio}\n\n"
        f"{url_afiliado}"
    )
    return f"https://t.me/share/url?url={quote(url_afiliado)}&text={quote(texto)}"


def publicar_en_telegram(oferta):
    if not TOKEN:
        print("Error: TELEGRAM_TOKEN no configurado.")
        return False

    url_afiliado = blindar_link_afiliado(oferta.get("url", ""))
    titulo_crudo = (oferta.get("titulo") or "").strip()
    if not url_afiliado or not titulo_crudo:
        return False

    titulo_limpio = limpiar_titulo_simple(titulo_crudo)
    titulo_seguro = escapar_html(titulo_limpio)
    etiqueta = "OFERTA DIRECTA" if oferta.get("tier") == 1 else "OFERTA DESTACADA"

    lineas = [
        f"<code>{etiqueta}</code>",
        f"<b>{titulo_seguro}</b>",
    ]

    if oferta.get("precio") or oferta.get("descuento"):
        lineas.append("")
        if oferta.get("precio"):
            lineas.append(f"<b>{escapar_html(oferta['precio'])}</b>")
        if oferta.get("descuento"):
            lineas.append(f"Descuento: <b>{escapar_html(oferta['descuento'])}</b>")

    lineas.extend([
        "",
        f"Mercado Libre México  •  {CANAL}",
        "<i>Precios y disponibilidad sujetos a cambio.</i>",
    ])
    caption = "\n".join(lineas)

    texto_boton = "Ver producto" if oferta.get("tier") == 1 else "Ver oferta"
    botones = {
        "inline_keyboard": [
            [{"text": texto_boton, "url": url_afiliado}],
            [{"text": "Compartir", "url": construir_link_compartir(titulo_crudo, url_afiliado)}],
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
    ofertas = buscar_ofertas_filtradas()
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

        oferta = blindar_datos_oferta(oferta)
        nicho = detectar_nicho_oferta(oferta.get("titulo") or "", oferta.get("url") or "")
        oferta["nicho"] = nicho

        if publicar_en_telegram(oferta):
            guardar_publicado(guid)
            publicados.add(guid)
            if mlm_id:
                guardar_publicado(mlm_id)
                publicados.add(mlm_id)
            enviados += 1
            if oferta["tier"] == 2:
                listados_enviados += 1
            print(f"Publicado [Tier {oferta['tier']}/{oferta['origen']}/{nicho}]: {oferta['titulo']} ({oferta.get('precio', '')}) -> {oferta['url']}")

            if oferta["tier"] == 1 and ig_enviados < MAX_POSTS_IG_POR_CORRIDA:
                if publicar_reel_en_instagram(oferta):
                    ig_enviados += 1

    print(f"Corrida terminada. Telegram: {enviados} (Listados: {listados_enviados}) | Instagram Reels: {ig_enviados}")


if __name__ == "__main__":
    main()
