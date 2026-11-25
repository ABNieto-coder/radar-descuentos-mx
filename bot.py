import html
import os
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, unquote, quote
import requests

TOKEN = os.environ["TELEGRAM_TOKEN"]
CANAL = "@RadarDescuentosMX247"
LINK_CANAL = "https://t.me/RadarDescuentosMX247"
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

RUTAS_BLOQUEADAS = (
    "/ofertas",
    "/listado",
    "/tienda/",
    "/tiendas-oficiales",
    "/c/",
    "/gz/",
    "/ayuda",
    "/login",
    "/cuenta",
    "/carrito",
    "/perfil",
    "/cupones",
    "/mas-vendidos",
    "/l/",
)

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

PALABRAS_EXCLUIDAS = (
    "usado", "usada", "reacondicionado", "reacondicionada", "refurbished",
    "coca-cola", "coca cola", "pepsi", "refresco", "cerveza", "whisky",
    "tequila", "vino tinto", "café molido", "cafe molido", "café soluble",
    "leche ", "galletas", "cereal ", "atún", "atun", "aceite comestible",
    "croquetas", "alimento para perro", "alimento para gato", "despensa"
)

CATEGORIAS_RENTABLES = [
    {
        "nombre": "💄 Belleza y Perfumería",
        "prioridad": 100,
        "keywords": (
            "perfume", "eau de toilette", "eau de parfum", "edt", "edp",
            "fragancia", "sérum", "serum", "niacinamida", "ácido hialurónico",
            "bloqueador", "protector solar", "crema facial", "shampoo",
            "maquillaje", "labial", "skincare", "rasuradora", "afeitadora",
            "secadora de cabello", "plancha de cabello"
        ),
    },
    {
        "nombre": "👟 Tenis, Ropa y Accesorios",
        "prioridad": 95,
        "keywords": (
            "tenis", "calzado", "zapatos", "botas", "sandalias", "sudadera",
            "chamarra", "playera", "pantalón", "jeans", "mochila", "bolsa",
            "cartera", "reloj", "lentes de sol", "gorra", "nike", "adidas",
            "puma", "vans"
        ),
    },
    {
        "nombre": "🛠️ Herramientas y Autos",
        "prioridad": 90,
        "keywords": (
            "taladro", "rotomartillo", "esmeriladora", "hidrolavadora", "llave",
            "desarmador", "herramienta", "compresor", "soldadora", "llanta",
            "escáner automotriz", "escaner automotriz", "autoestéreo", "dashcam",
            "cámara reversa", "aceite sintético", "batería carro", "bosch",
            "dewalt", "makita", "truper"
        ),
    },
    {
        "nombre": "🏠 Hogar, Cocina y Smart Home",
        "prioridad": 85,
        "keywords": (
            "freidora de aire", "air fryer", "cafetera", "licuadora",
            "aspiradora", "robot aspirador", "sartén", "batería de cocina",
            "termo", "colchón", "almohada", "sábanas", "lámpara",
            "foco inteligente", "alexa", "echo dot", "cerradura inteligente",
            "organizador", "ventilador", "calefactor"
        ),
    },
    {
        "nombre": "📱 Tecnología, Audio y Gaming",
        "prioridad": 80,
        "keywords": (
            "audífonos", "audifonos", "bluetooth", "celular", "smartphone",
            "iphone", "samsung galaxy", "xiaomi", "motorola", "tablet", "ipad",
            "laptop", "monitor", "ssd", "memoria ram", "teclado", "mouse",
            "nintendo", "playstation", "ps5", "xbox", "control", "bocina",
            "smartwatch", "cámara"
        ),
    },
]


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


def es_articulo_ml_estricto(url):
    limpia = normalizar_url(url)
    if not limpia:
        return False

    partes = urlparse(limpia)
    host = (partes.netloc or "").lower()
    ruta = (partes.path or "").lower()

    if not host or not ruta or ruta == "/":
        return False

    if any(seg in ruta for seg in RUTAS_BLOQUEADAS):
        return False

    es_ml_mx = host == "mercadolibre.com.mx" or host.endswith(".mercadolibre.com.mx")
    if not es_ml_mx:
        return False

    mlm_id = extraer_mlm_id(ruta)
    if host.startswith("articulo.mercadolibre.com.mx") and mlm_id:
        return True
    if "/p/mlm" in ruta and mlm_id:
        return True
    if mlm_id and ("-_" in ruta or "/p/" in ruta or host.startswith("articulo.")):
        return True
    if re.search(r"/[a-z0-9-]+-mlm\d+", ruta):
        return True

    return False


def blindar_link_afiliado(url_articulo):
    limpia = normalizar_url(url_articulo)
    if not es_articulo_ml_estricto(limpia):
        return ""

    partes = urlparse(limpia)
    params_previos = parse_qs(partes.query, keep_blank_values=False)

    params_limpios = {
        k: v for k, v in params_previos.items()
        if k.lower() not in PARAMS_A_LIMPIAR
    }
    params_limpios["matt_word"] = [MATT_WORD]
    params_limpios["matt_tool"] = [MATT_TOOL]

    query_blindado = urlencode(params_limpios, doseq=True)
    url_blindada = urlunparse((
        "https",
        partes.netloc.lower(),
        partes.path,
        "",
        query_blindado,
        ""
    ))

    parsed_check = urlparse(url_blindada)
    qs_check = parse_qs(parsed_check.query)

    if (
        parsed_check.scheme == "https"
        and es_articulo_ml_estricto(url_blindada)
        and qs_check.get("matt_word") == [MATT_WORD]
        and qs_check.get("matt_tool") == [MATT_TOOL]
    ):
        return url_blindada

    return ""


def clasificar_y_puntuar_oferta(titulo, descripcion, descuento_str):
    texto = f"{titulo} {descripcion}".lower()

    if any(p in texto for p in PALABRAS_EXCLUIDAS):
        return None, 0

    categoria_elegida = "🔥 Oferta Destacada"
    puntaje = 50

    for cat in CATEGORIAS_RENTABLES:
        if any(kw in texto for kw in cat["keywords"]):
            categoria_elegida = cat["nombre"]
            puntaje = cat["prioridad"]
            break

    if descuento_str:
        puntaje += 15

    return categoria_elegida, puntaje


def extraer_urls_candidatas(texto):
    decodificado = unquote(html.unescape(texto or ""))
    encontrados = []
    for match in re.findall(r"https?://[^\s\"'<>)\]]+", decodificado, flags=re.IGNORECASE):
        limpia = normalizar_url(match)
        if limpia and limpia not in encontrados:
            encontrados.append(limpia)
    return encontrados


def peticion_con_reintento(url, timeout=10):
    ultimo_error = None
    for intento in range(2):
        try:
            return requests.get(
                url,
                headers=HEADERS_BROWSER,
                allow_redirects=True,
                timeout=timeout,
            )
        except Exception as e:
            ultimo_error = e
            if intento == 0:
                time.sleep(0.5)
    raise ultimo_error


def resolver_hasta_articulo_estricto(url_inicial, profundidad=0):
    if profundidad > 3:
        return ""

    limpia = normalizar_url(url_inicial)
    if not limpia:
        return ""

    if es_articulo_ml_estricto(limpia):
        return limpia

    host = (urlparse(limpia).netloc or "").lower()
    dominio_permitido = (
        "mercadolibre.com.mx" in host
        or "meli.la" in host
        or "promodescuentos.com" in host
    )
    if not dominio_permitido:
        return ""

    try:
        resp = peticion_con_reintento(limpia, timeout=11)
        if resp.status_code >= 400:
            return ""

        final_url = normalizar_url(resp.url)
        if es_articulo_ml_estricto(final_url):
            return final_url

        cuerpo = resp.text or ""
        candidatos = extraer_urls_candidatas(cuerpo)

        for cand in candidatos:
            if es_articulo_ml_estricto(cand):
                return cand

        for cand in candidatos:
            h = (urlparse(cand).netloc or "").lower()
            if "meli.la" in h or ("promodescuentos.com" in h and "/visit/" in cand.lower()):
                resuelta = resolver_hasta_articulo_estricto(cand, profundidad + 1)
                if resuelta and es_articulo_ml_estricto(resuelta):
                    return resuelta
    except Exception:
        pass

    return ""


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


def buscar_ofertas_blindadas():
    ofertas = []
    vistos_corrida = set()

    for feed_url in RSS_URLS:
        try:
            resp = peticion_con_reintento(feed_url, timeout=15)
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

            precio, descuento = extraer_precio_y_descuento(titulo, descripcion)
            categoria, puntaje = clasificar_y_puntuar_oferta(titulo, descripcion, descuento)
            if categoria is None:
                continue

            xml_item = ET.tostring(item, encoding="unicode", method="xml") or ""
            url_articulo = ""

            for cand in extraer_urls_candidatas(f"{link_rss} {descripcion} {xml_item}"):
                if es_articulo_ml_estricto(cand):
                    url_articulo = cand
                    break

            if not url_articulo:
                url_articulo = resolver_hasta_articulo_estricto(link_rss)

            url_blindada = blindar_link_afiliado(url_articulo)
            if not url_blindada:
                continue

            mlm_id = extraer_mlm_id(url_blindada)
            clave_dedup = mlm_id or url_blindada
            if clave_dedup in vistos_corrida:
                continue
            vistos_corrida.add(clave_dedup)

            img_match = re.search(r'src=["\'](https?://[^"\']+)["\']', descripcion)
            imagen = normalizar_url(img_match.group(1)) if img_match else ""

            ofertas.append({
                "guid": guid,
                "mlm_id": mlm_id,
                "titulo": titulo,
                "categoria": categoria,
                "puntaje": puntaje,
                "precio": precio,
                "descuento": descuento,
                "url": url_blindada,
                "imagen": imagen,
            })

    ofertas.sort(key=lambda x: x["puntaje"], reverse=True)
    return ofertas


def auditar_y_blindar_oferta(oferta):
    if not isinstance(oferta, dict):
        return ""
    titulo = (oferta.get("titulo") or "").strip()
    if not titulo:
        return ""
    return blindar_link_afiliado(oferta.get("url", ""))


def construir_link_compartir(titulo, url_blindada):
    texto_compartir = (
        f"🔥 ¡Mira esta oferta en Mercado Libre México!\n"
        f"{titulo}\n\n"
        f"👉 Más descuentos diarios en {CANAL}"
    )
    return f"https://t.me/share/url?url={quote(url_blindada)}&text={quote(texto_compartir)}"


def publicar_en_telegram(oferta):
    url_blindada = auditar_y_blindar_oferta(oferta)
    if not url_blindada:
        return False

    titulo_crudo = (oferta.get("titulo") or "").strip()
    titulo_seguro = escapar_html(titulo_crudo)
    categoria_segura = escapar_html(oferta.get("categoria") or "🔥 Oferta Destacada")

    lineas = [
        f"<b>{categoria_segura}</b>",
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
        "⚡ <i>Oferta por tiempo limitado / sujeto a stock</i>",
        "",
        f"📲 <b>Únete y comparte:</b> {CANAL}",
        "<i>#OfertasMX #MercadoLibre #Descuentos</i>",
    ])
    caption = "\n".join(lineas)

    link_compartir = construir_link_compartir(titulo_crudo, url_blindada)
    botones = {
        "inline_keyboard": [
            [{"text": "🛒 Ver producto en Mercado Libre", "url": url_blindada}],
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
    ofertas = buscar_ofertas_blindadas()
    enviados = 0

    for oferta in ofertas:
        if enviados >= MAX_POSTS_POR_CORRIDA:
            break

        guid = oferta["guid"]
        mlm_id = oferta["mlm_id"]
        url_blindada = auditar_y_blindar_oferta(oferta)

        if not url_blindada:
            continue

        if (
            guid in publicados
            or (mlm_id and mlm_id in publicados)
            or url_blindada in publicados
        ):
            continue

        if publicar_en_telegram(oferta):
            for clave in (guid, mlm_id, url_blindada):
                if clave and clave not in publicados:
                    guardar_publicado(clave)
                    publicados.add(clave)
            enviados += 1
            print(f"Publicado [{oferta['categoria']}] [{mlm_id or 'ART'}]: {oferta['titulo']} -> {url_blindada}")

    print(f"Corrida terminada. Total publicados: {enviados}")


if __name__ == "__main__":
    main()
        
