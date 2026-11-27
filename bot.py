import html
import json
import os
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, unquote, quote

import requests

from reel_publisher import publicar_reel_en_instagram, contar_reels_por_nicho

TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CANAL = "@RadarDescuentosMX247"
MATT_WORD = "charlysource"
MATT_TOOL = "29165755"

ARCHIVO_HISTORIAL = "publicados.txt"
MAX_LINEAS_HISTORIAL = 2000
MAX_POSTS_POR_EJECUCION = 5
MAX_LISTADOS_POR_EJECUCION = 1
MAX_POSTS_IG_POR_EJECUCION = 2
MAX_CANDIDATAS = 30
PRESUPUESTO_BUSQUEDA_SEG = 240
NICHOS_EXPERIMENTO = ("tecnologia", "cuidado_personal")

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

PARAMS_REDIRECCION = {
    "url", "u", "go", "target", "dest", "destination", "redirect",
    "redirect_url", "redirect_uri", "next", "to", "link", "out",
}

HOSTS_PRODUCTO = {
    "mercadolibre.com.mx",
    "www.mercadolibre.com.mx",
    "articulo.mercadolibre.com.mx",
    "m.mercadolibre.com.mx",
}

RUTAS_NO_PRODUCTO = (
    "/glossary", "/ofertas", "/listado", "/tienda/", "/c/", "/gz/", "/categorias",
    "/mas-vendidos", "/cupones", "/supermercado", "/ayuda", "/help", "/social/",
    "/perfil", "/vendedor", "/mis-compras", "/checkout", "/carrito", "/cart",
    "/login", "/registration", "/promotions", "/deals", "/navigation",
)

RUTAS_DESTINO_MUERTO = ("/glossary", "/ofertas", "/categorias", "/mas-vendidos")

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
    "gamer", "gaming", "oled", "qled", "mini led",
    "teclado", "teclado mecánico", "teclado mecanico", "mouse",
    "smartwatch", "reloj inteligente", "banda inteligente",
    "cargador", "cargador rápido", "cargador rapido", "power bank",
    "bocina", "altavoz", "barra de sonido", "soundbar",
    "webcam", "cámara web", "camara web", "router", "mesh",
    "tarjeta gráfica", "tarjeta grafica", "gpu", "procesador",
    "laptop", "notebook", "chromebook", "tablet", "ipad",
    "impresora", "proyector", "micrófono", "microfono", "capturadora",
)

PALABRAS_NICHO_CUIDADO = (
    "protector solar", "protectores solares", "bloqueador solar",
    "bloqueador", "uv defender", "anthelios",
    "sérum", "serum", "vitamina c", "retinol", "ácido salicílico",
    "acido salicilico", "ácido hialurónico", "acido hialuronico",
    "niacinamida", "limpiador facial", "gel limpiador",
    "espuma limpiadora", "agua micelar", "tónico facial", "tonico facial",
    "crema facial", "hidratante facial", "contorno de ojos",
    "cuidado facial", "cuidado de la piel", "skincare",
    "bálsamo labial", "balsamo labial", "desodorante", "antitranspirante",
)

PATRON_PROTECCION_SOLAR = re.compile(r"(?<!\d)(?<!\d\s)(?:fps|spf)\s*[-:]?\s*\d{2,3}\+?(?!\d)")
PATRON_DATO_TECNICO = re.compile(r"(?<!\w)\d{2,3}\s?(?:hz|fps)(?!\w)")

INVISIBLES = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u00ad\u2063]")
PATRON_MLM = re.compile(r"(?<![A-Za-z0-9])(MLM-?\d{6,14})(?!\d)", re.IGNORECASE)


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
    limpia = INVISIBLES.sub("", limpia)
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
        urlparse(limpia)
    except ValueError:
        return ""
    return limpia


def desempaquetar_url(url_raw, max_profundidad=3):
    actual = normalizar_url(url_raw)
    visitadas = set()
    for _ in range(max_profundidad):
        if not actual or actual in visitadas:
            break
        visitadas.add(actual)
        try:
            partes = urlparse(actual)
            qs = parse_qs(partes.query, keep_blank_values=False)
        except ValueError:
            break

        siguiente = ""
        for k, vals in qs.items():
            if k.lower() in PARAMS_REDIRECCION and vals:
                candidata = normalizar_url(vals[0])
                if candidata and candidata not in visitadas:
                    siguiente = candidata
                    break
        if not siguiente:
            break
        actual = siguiente
    return actual


def extraer_mlm_id(texto):
    match = PATRON_MLM.search(texto or "")
    return match.group(1).upper().replace("-", "") if match else ""


def mlm_desde_url(url):
    try:
        return extraer_mlm_id(urlparse(url or "").path)
    except ValueError:
        return ""


def es_url_producto_exacto(url):
    try:
        limpia = desempaquetar_url(url)
        if not limpia:
            return False
        partes = urlparse(limpia)
        host = (partes.netloc or "").lower().split(":")[0]
        ruta = (partes.path or "").lower()

        if host not in HOSTS_PRODUCTO:
            return False
        if any(seg in ruta for seg in RUTAS_NO_PRODUCTO):
            return False
        return bool(extraer_mlm_id(ruta))
    except ValueError:
        return False


def destino_publicable(url, tier):
    try:
        limpia = desempaquetar_url(url)
        if not limpia:
            return False
        if tier == 1:
            return es_url_producto_exacto(limpia)
        if tier == 2:
            partes = urlparse(limpia)
            host = (partes.netloc or "").lower().split(":")[0]
            return host == "listado.mercadolibre.com.mx" and len((partes.path or "").strip("/")) >= 3
        return False
    except ValueError:
        return False


def blindar_link_afiliado(url_destino):
    try:
        limpia = desempaquetar_url(url_destino)
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
            quote(partes.path or "/", safe="/-_.~%"),
            "",
            urlencode(params_limpios, doseq=True),
            ""
        ))
    except ValueError:
        return ""


def verificar_destino_vivo(url, timeout=10):
    base = (url or "").split("?")[0]
    if not base:
        return False
    try:
        resp = requests.get(base, headers=HEADERS_BROWSER, allow_redirects=True, timeout=timeout)
    except requests.RequestException:
        return True

    if resp.status_code in (404, 410):
        print(f"Descartada: el producto ya no existe (HTTP {resp.status_code}) -> {base}")
        return False
    try:
        final = desempaquetar_url(resp.url)
        if final:
            partes = urlparse(final)
            host = (partes.netloc or "").lower().split(":")[0]
            ruta = (partes.path or "").lower()
            if host == "listado.mercadolibre.com.mx":
                print(f"Descartada: redirige a un listado -> {final}")
                return False
            if host.endswith("mercadolibre.com.mx") and any(seg in ruta for seg in RUTAS_DESTINO_MUERTO):
                print(f"Descartada: redirige a una página que no es un producto -> {final}")
                return False
    except ValueError:
        return True
    return True


def extraer_urls_candidatas(texto):
    bruto = html.unescape(texto or "")
    variantes = (bruto, unquote(bruto))
    encontrados = []
    for fuente in variantes:
        for match in re.findall(r"https?://[^\s\"'<>)\]]+", fuente, flags=re.IGNORECASE):
            for cand in (normalizar_url(match), desempaquetar_url(match)):
                if cand and cand not in encontrados:
                    encontrados.append(cand)
    return encontrados


def seguir_redireccion(url, timeout=10):
    try:
        resp = requests.get(url, headers=HEADERS_BROWSER, allow_redirects=True, timeout=timeout)
        if resp.status_code < 400:
            return desempaquetar_url(resp.url), resp.text or ""
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
    limpio = INVISIBLES.sub("", limpio.replace("\u00a0", " "))
    limpio = re.sub(r"^\s*\d+\s*°\s*[-–—:]?\s*", "", limpio)
    limpio = re.sub(r"(?i)^mercado\s*libre\s*:?\s*", "", limpio)
    limpio = re.sub(r"\s*\[|\]\s*Mercado\s*Libre.*$", "", limpio, flags=re.IGNORECASE)
    limpio = re.sub(r"\$\s?[\d,]+(?:\.\d{1,2})?", " ", limpio)
    limpio = re.sub(r"\b\d{1,2}\s?%\s?(?:off|de descuento|descuento|dto)\b", " ", limpio, flags=re.IGNORECASE)
    limpio = re.sub(r"\s+[-–|:,]\s*$", "", re.sub(r"\s+", " ", limpio).strip())
    return limpio.strip(" -–|:,") or "Oferta disponible"


def _ajustar_cantidad_contradictoria(titulo: str, url: str) -> str:
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


def _a_pesos(texto):
    limpio = re.sub(r"[^\d.]", "", str(texto or ""))
    try:
        valor = float(limpio)
    except ValueError:
        return 0
    return int(round(valor)) if valor > 0 else 0


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


def _buscar_precio_json(nodo, profundidad=0):
    if profundidad > 6:
        return ""
    if isinstance(nodo, dict):
        if nodo.get("offers"):
            precio = _buscar_precio_json(nodo["offers"], profundidad + 1)
            if precio:
                return precio
        if "price" in nodo:
            precio = formatear_precio_mxn(nodo["price"])
            if precio:
                return precio
        for valor in nodo.values():
            if isinstance(valor, (dict, list)):
                precio = _buscar_precio_json(valor, profundidad + 1)
                if precio:
                    return precio
    elif isinstance(nodo, list):
        for elemento in nodo:
            precio = _buscar_precio_json(elemento, profundidad + 1)
            if precio:
                return precio
    return ""


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
            r'<meta[^>]+(?:property|name)=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
            cuerpo,
            flags=re.IGNORECASE,
        )
        if m_title:
            titulo_limpio = limpiar_titulo_simple(m_title.group(1))
            if len(titulo_limpio) >= 6:
                datos["titulo"] = titulo_limpio

        m_img = re.search(
            r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            cuerpo,
            flags=re.IGNORECASE,
        )
        if m_img:
            img_limpia = normalizar_url(m_img.group(1))
            if img_limpia:
                datos["imagen"] = img_limpia

        for bloque in re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            cuerpo,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            try:
                precio_fmt = _buscar_precio_json(json.loads(bloque.strip()))
            except ValueError:
                continue
            if precio_fmt:
                datos["precio"] = precio_fmt
                break

        if "precio" not in datos:
            m_price = re.search(
                r'<meta[^>]+(?:property|name)=["\'](?:product:price:amount|twitter:data1)["\'][^>]+content=["\']([^"\']+)["\']',
                cuerpo,
                flags=re.IGNORECASE,
            )
            if m_price:
                precio_fmt = formatear_precio_mxn(re.sub(r"[^\d.]", "", m_price.group(1)))
                if precio_fmt:
                    datos["precio"] = precio_fmt

        if "precio" not in datos:
            m_state = re.search(
                r'"price"\s*:\s*(\d+(?:\.\d{1,2})?)\s*,\s*"currency_id"\s*:\s*"MXN"',
                cuerpo,
            )
            if m_state:
                precio_fmt = formatear_precio_mxn(m_state.group(1))
                if precio_fmt:
                    datos["precio"] = precio_fmt

        m_orig = re.search(r'"original_price"\s*:\s*(\d+(?:\.\d{1,2})?)', cuerpo)
        if m_orig:
            orig_fmt = formatear_precio_mxn(m_orig.group(1))
            if orig_fmt:
                datos["precio_anterior"] = orig_fmt
    except Exception as e:
        print(f"Aviso leyendo metadatos HTML ML: {type(e).__name__}")

    return datos


def enriquecer_oferta_con_ml(oferta: dict) -> dict:
    if oferta.get("tier") != 1:
        return oferta

    oferta.setdefault("imagen_fuente", "rss" if oferta.get("imagen") else "")
    mlm_id = (oferta.get("mlm_id") or "").strip().upper()
    api_ok = False

    if mlm_id:
        try:
            resp = requests.get(
                f"https://api.mercadolibre.com/items/{mlm_id}",
                headers=HEADERS_API,
                timeout=8,
            )
            data = resp.json() if resp.ok else {}
            if isinstance(data, dict) and data.get("id"):
                titulo_ml = limpiar_titulo_simple(data.get("title") or "")
                if len(titulo_ml) >= 6:
                    oferta["titulo"] = titulo_ml
                    api_ok = True

                precio_fmt = formatear_precio_mxn(data.get("price"))
                if precio_fmt:
                    oferta["precio"] = precio_fmt
                    api_ok = True

                original_price = data.get("original_price")
                price = data.get("price")
                if original_price and price and float(original_price) > float(price):
                    pct = round((1 - (float(price) / float(original_price))) * 100)
                    if 1 <= pct <= 95:
                        oferta["descuento"] = f"{pct}% OFF"
                        oferta["precio_anterior"] = formatear_precio_mxn(original_price)

                pictures = data.get("pictures") or []
                if isinstance(pictures, list) and pictures:
                    pic_url = pictures[0].get("secure_url") if isinstance(pictures[0], dict) else ""
                    if pic_url:
                        oferta["imagen"] = normalizar_url(pic_url)
                        oferta["imagen_fuente"] = "api"
        except Exception as e:
            print(f"Aviso enriqueciendo oferta {mlm_id} desde API ML: {type(e).__name__}")

    if not api_ok or oferta.get("imagen_fuente") != "api":
        datos_html = _extraer_datos_html_ml((oferta.get("url") or "").split("?")[0])
        if datos_html.get("imagen"):
            oferta["imagen"] = datos_html["imagen"]
            oferta["imagen_fuente"] = "og"
        if not api_ok:
            for campo in ("titulo", "precio", "precio_anterior"):
                if datos_html.get(campo):
                    oferta[campo] = datos_html[campo]
            p_act = _a_pesos(oferta.get("precio"))
            p_ant = _a_pesos(oferta.get("precio_anterior"))
            if p_ant > p_act > 0:
                pct = round((1 - (p_act / p_ant)) * 100)
                if 1 <= pct <= 95:
                    oferta["descuento"] = f"{pct}% OFF"

    return oferta


def blindar_datos_oferta(oferta: dict) -> dict:
    precio_rss = _a_pesos(oferta.get("precio"))
    descuento_rss = oferta.get("descuento") or ""

    oferta["titulo"] = _ajustar_cantidad_contradictoria(
        oferta.get("titulo") or "",
        oferta.get("url") or "",
    )
    oferta = enriquecer_oferta_con_ml(oferta)
    oferta["titulo"] = _ajustar_cantidad_contradictoria(
        oferta.get("titulo") or "",
        oferta.get("url") or "",
    )

    precio_limpio = _normalizar_precio_visible(oferta.get("precio") or "")
    if precio_limpio:
        oferta["precio"] = precio_limpio

    precio_actual = _a_pesos(oferta.get("precio"))
    if precio_rss and precio_actual and precio_actual > precio_rss * 1.10:
        oferta["descartar"] = f"el precio actual (${precio_actual:,}) supera al de la oferta (${precio_rss:,})"
        return oferta
    if (
        precio_rss and precio_actual and abs(precio_actual - precio_rss) > precio_rss * 0.10
        and not oferta.get("precio_anterior") and descuento_rss and oferta.get("descuento") == descuento_rss
    ):
        oferta["descuento"] = ""

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
            data = resp.json() if resp.ok else {}
            if isinstance(data, dict):
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
                        oferta["imagen_fuente"] = "api"
                        return oferta
        except Exception as e:
            print(f"Aviso validando imagen ML para {mlm_id}: {type(e).__name__}")

    oferta["imagen"] = ""
    oferta["imagen_fuente"] = ""
    return oferta


def _contar_coincidencias(texto, palabras):
    total = 0
    for palabra in palabras:
        if re.search(r"(?<!\w)" + re.escape(palabra) + r"(?!\w)", texto):
            total += 1
    return total


def detectar_nicho_oferta(titulo: str, url: str = "") -> str:
    texto = f"{titulo or ''} {url or ''}".lower().replace("-", " ")
    cuidado = _contar_coincidencias(texto, PALABRAS_NICHO_CUIDADO)
    if PATRON_PROTECCION_SOLAR.search(texto):
        cuidado += 1
    tech = _contar_coincidencias(texto, PALABRAS_NICHO_TECH)
    if PATRON_DATO_TECNICO.search(texto):
        tech += 1

    if cuidado > tech:
        return "cuidado_personal"
    if tech > cuidado:
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
            permalink = desempaquetar_url(item.get("permalink", ""))
            if es_url_producto_exacto(permalink):
                return permalink
    except Exception:
        return ""
    return ""


def _rescatar_url_producto_desde_html(cuerpo_html, etiqueta_origen):
    for interna in extraer_urls_candidatas(cuerpo_html):
        if es_url_producto_exacto(interna):
            return interna, 1, etiqueta_origen
        if "meli.la/" in interna.lower():
            final_meli, cuerpo_meli = seguir_redireccion(interna)
            if es_url_producto_exacto(final_meli):
                return final_meli, 1, f"{etiqueta_origen}-meli"
            for sub in extraer_urls_candidatas(cuerpo_meli):
                if es_url_producto_exacto(sub):
                    return sub, 1, f"{etiqueta_origen}-meli-html"
    return "", 0, ""


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
            rescatada, nivel, origen = _rescatar_url_producto_desde_html(cuerpo, "meli.la-html")
            if rescatada:
                return rescatada, nivel, origen

    match_thread = re.search(r"-(\d{5,9})(?:[/?#]|$)", link_rss or "")
    if match_thread and "promodescuentos.com" in (link_rss or "").lower():
        thread_id = match_thread.group(1)
        for endpoint, etiqueta in (
            (f"https://www.promodescuentos.com/visit/threadmain/{thread_id}", "visit"),
            (f"https://www.promodescuentos.com/visit/hottopic/{thread_id}", "visit-hot"),
        ):
            final_u, cuerpo = seguir_redireccion(endpoint)
            if es_url_producto_exacto(final_u):
                return final_u, 1, etiqueta
            rescatada, nivel, origen = _rescatar_url_producto_desde_html(cuerpo, f"{etiqueta}-html")
            if rescatada:
                return rescatada, nivel, origen

    if link_rss and "promodescuentos.com" in link_rss.lower():
        _, cuerpo_post = seguir_redireccion(link_rss)
        rescatada, nivel, origen = _rescatar_url_producto_desde_html(cuerpo_post, "post-html")
        if rescatada:
            return rescatada, nivel, origen

    titulo_bajo = (titulo or "").lower()
    if any(s in titulo_bajo for s in SENALES_LISTADO):
        return "", 99, "descartado-listado"

    consulta = limpiar_titulo_para_busqueda(titulo)

    permalink_api = buscar_permalink_ml_api(consulta)
    if permalink_api and es_url_producto_exacto(permalink_api):
        return permalink_api, 1, "api-ml"

    slug = slug_listado(consulta)
    if len(slug) >= 8:
        return f"https://listado.mercadolibre.com.mx/{slug}", 2, "listado"

    return "", 99, "sin-link"


def slug_listado(consulta):
    sin_acentos = unicodedata.normalize("NFKD", consulta or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", sin_acentos.lower()).strip("-")


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


def buscar_ofertas_filtradas(publicados=None):
    publicados = publicados or set()
    ofertas = []
    vistos_dedup = set()
    vistos_guid = set()
    stats = Counter()
    inicio = time.monotonic()
    terminar = False

    for feed_url in RSS_URLS:
        if terminar:
            break
        try:
            resp = requests.get(feed_url, headers=HEADERS_BROWSER, timeout=15)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
        except Exception as e:
            print(f"Aviso RSS {feed_url}: {type(e).__name__}")
            continue

        for idx, item in enumerate(root.findall("./channel/item"), start=1):
            if len(ofertas) >= MAX_CANDIDATAS:
                terminar = True
                break
            if time.monotonic() - inicio > PRESUPUESTO_BUSQUEDA_SEG:
                print("Aviso: se agotó el tiempo de búsqueda; se usan las ofertas resueltas hasta ahora.")
                terminar = True
                break

            stats["rss_total"] += 1
            titulo = (item.findtext("title") or "").strip()
            link_rss = (item.findtext("link") or "").strip()
            guid = (item.findtext("guid") or link_rss or f"item-{idx}").strip()
            descripcion = item.findtext("description") or ""

            if not titulo:
                continue
            if guid in publicados or guid in vistos_guid:
                stats["ya_publicado"] += 1
                continue
            vistos_guid.add(guid)

            if re.search(r"(?i)^\s*(?:cup[oó]n\s+de\b|bonificaci[oó]n\b)", limpiar_titulo_simple(titulo)):
                stats["cupon"] += 1
                continue

            texto_bajo = f"{titulo} {descripcion} {link_rss}".lower()
            if (
                "mercado libre" not in texto_bajo
                and "mercadolibre" not in texto_bajo
                and "meli.la" not in texto_bajo
            ):
                stats["otra_tienda"] += 1
                continue

            stats["ml_detectadas"] += 1
            if any(p in texto_bajo for p in PALABRAS_CERO_COMISION):
                stats["cero_comision"] += 1
                continue

            xml_item = ET.tostring(item, encoding="unicode", method="xml") or ""
            url_cruda, tier, origen = resolver_oferta_con_nivel(link_rss, descripcion, xml_item, titulo)
            if tier > 2 or not url_cruda:
                stats[f"sin_resolucion:{origen}"] += 1
                continue
            if not destino_publicable(url_cruda, tier):
                stats["destino_no_valido"] += 1
                print(f"Descartada por destino no válido ({origen}): {url_cruda}")
                continue

            url_afiliado = blindar_link_afiliado(url_cruda)
            if not url_afiliado:
                stats["afiliado_invalido"] += 1
                continue

            mlm_id = mlm_desde_url(url_afiliado)
            clave_dedup = mlm_id or guid
            if clave_dedup in vistos_dedup or (mlm_id and mlm_id in publicados):
                stats["mlm_duplicado"] += 1
                continue
            vistos_dedup.add(clave_dedup)

            precio, descuento = extraer_precio_y_descuento(titulo, descripcion)
            img_match = re.search(r'src=["\'](https?://[^"\']+)["\']', descripcion)
            imagen = normalizar_url(img_match.group(1)) if img_match else ""

            stats[f"aceptada_tier_{tier}"] += 1
            ofertas.append({
                "guid": guid,
                "mlm_id": mlm_id,
                "tier": tier,
                "origen": origen,
                "titulo": titulo,
                "precio": precio,
                "precio_anterior": "",
                "descuento": descuento,
                "url": url_afiliado,
                "imagen": imagen,
                "imagen_fuente": "rss" if imagen else "",
            })

    resumen_stats = ", ".join(f"{k}={v}" for k, v in sorted(stats.items()))
    print(f"Resumen RSS: {resumen_stats or 'sin elementos'}")
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


def _recortar_texto(texto, max_chars):
    limpio = re.sub(r"\s+", " ", texto or "").strip()
    if len(limpio) <= max_chars:
        return limpio
    corte = limpio[: max_chars + 1].rsplit(" ", 1)[0].strip()
    return corte or limpio[:max_chars]


def _telegram_post(metodo, payload, intentos=2):
    for _ in range(intentos):
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{TOKEN}/{metodo}",
                json=payload,
                timeout=20,
            )
            data = r.json() if r.content else {}
        except (requests.RequestException, ValueError) as e:
            print(f"Aviso Telegram {metodo}: {type(e).__name__}")
            time.sleep(2)
            continue

        if data.get("ok"):
            return True
        if r.status_code == 429:
            espera = int((data.get("parameters") or {}).get("retry_after", 3))
            time.sleep(min(max(espera, 1), 20))
            continue
        print(f"Aviso Telegram {metodo}: HTTP {r.status_code} {data.get('description', '')}")
        return False
    return False


def construir_caption_telegram(oferta):
    titulo = escapar_html(_recortar_texto(limpiar_titulo_simple(oferta.get("titulo") or ""), 180))
    precio = (oferta.get("precio") or "").strip()
    anterior = (oferta.get("precio_anterior") or "").strip()
    descuento = (oferta.get("descuento") or "").strip()
    etiqueta = "OFERTA DIRECTA" if oferta.get("tier") == 1 else "OFERTA DESTACADA"

    if precio:
        lineas = [f"<b>{escapar_html(precio)}</b> · {titulo}"]
    else:
        lineas = [f"<b>{titulo}</b>"]

    p_ahora, p_antes = _a_pesos(precio), _a_pesos(anterior)
    if anterior and p_antes > p_ahora > 0:
        lineas.append("")
        lineas.append(f"Antes: <s>{escapar_html(anterior)}</s> | Ahora: <b>{escapar_html(precio)}</b>")
        if descuento:
            lineas.append(f"Ahorras ${p_antes - p_ahora:,} ({escapar_html(descuento)})")
    elif descuento:
        lineas.append("")
        lineas.append(f"Descuento: <b>{escapar_html(descuento)}</b>")

    lineas.extend([
        "",
        f"<code>{etiqueta}</code> Mercado Libre México • {CANAL}",
        "<i>Enlace de afiliado. Precios y disponibilidad sujetos a cambio.</i>",
    ])
    return "\n".join(lineas)[:1000]


def publicar_en_telegram(oferta):
    if not TOKEN:
        print("Error: TELEGRAM_TOKEN no configurado.")
        return False

    url_afiliado = blindar_link_afiliado(oferta.get("url", ""))
    titulo_crudo = (oferta.get("titulo") or "").strip()
    if not url_afiliado or not titulo_crudo:
        return False
    if not destino_publicable(url_afiliado, oferta.get("tier")):
        print(f"Bloqueada: el enlace no es una página de producto ni un listado válido -> {url_afiliado}")
        return False

    caption = construir_caption_telegram(oferta)
    texto_boton = "Ver producto" if oferta.get("tier") == 1 else "Ver oferta"
    botones = {
        "inline_keyboard": [
            [{"text": texto_boton, "url": url_afiliado}],
            [{"text": "Compartir", "url": construir_link_compartir(titulo_crudo, url_afiliado)}],
        ]
    }

    if oferta.get("imagen") and oferta["imagen"].startswith("https://"):
        if _telegram_post("sendPhoto", {
            "chat_id": CANAL,
            "photo": oferta["imagen"],
            "caption": caption,
            "parse_mode": "HTML",
            "reply_markup": botones,
        }):
            return True

    return _telegram_post("sendMessage", {
        "chat_id": CANAL,
        "text": caption,
        "parse_mode": "HTML",
        "reply_markup": botones,
        "disable_web_page_preview": True,
    })


def elegir_para_reel(publicadas, maximo):
    conteo = contar_reels_por_nicho()
    pool = [o for o in publicadas if o.get("tier") == 1 and o.get("precio")]
    elegidas = []

    while pool and len(elegidas) < maximo:
        def clave(o):
            nicho = o.get("nicho", "general")
            return (
                0 if nicho in NICHOS_EXPERIMENTO else 1,
                conteo.get(nicho, 0),
                0 if o.get("descuento") else 1,
            )
        mejor = min(pool, key=clave)
        elegidas.append(mejor)
        pool.remove(mejor)
        conteo[mejor.get("nicho", "general")] += 1
    return elegidas


def main():
    publicados = cargar_publicados()
    ofertas = buscar_ofertas_filtradas(publicados)

    nuevas = []
    listados = 0
    for oferta in ofertas:
        if len(nuevas) >= MAX_POSTS_POR_EJECUCION:
            break
        if oferta["tier"] == 2 and listados >= MAX_LISTADOS_POR_EJECUCION:
            continue

        guid, mlm_id = oferta["guid"], oferta["mlm_id"]
        if guid in publicados or (mlm_id and mlm_id in publicados):
            continue
        if not destino_publicable(oferta["url"], oferta["tier"]):
            continue
        if oferta["tier"] == 1 and not verificar_destino_vivo(oferta["url"]):
            guardar_publicado(guid)
            publicados.add(guid)
            continue

        oferta = blindar_datos_oferta(oferta)
        if oferta.get("descartar"):
            print(f"Descartada: {oferta['descartar']} -> {oferta['titulo']}")
            guardar_publicado(guid)
            publicados.add(guid)
            continue

        oferta["nicho"] = detectar_nicho_oferta(oferta.get("titulo") or "", oferta.get("url") or "")
        nuevas.append(oferta)
        if oferta["tier"] == 2:
            listados += 1

    publicadas_sesion = []
    for oferta in nuevas:
        if publicar_en_telegram(oferta):
            guardar_publicado(oferta["guid"])
            publicados.add(oferta["guid"])
            if oferta["mlm_id"]:
                guardar_publicado(oferta["mlm_id"])
                publicados.add(oferta["mlm_id"])
            publicadas_sesion.append(oferta)
            print(
                f"Publicado [Tier {oferta['tier']}/{oferta['origen']}/{oferta['nicho']}]: "
                f"{oferta['titulo']} ({oferta.get('precio', '')}) -> {oferta['url']}"
            )
            time.sleep(1)

    ig_enviados = 0
    for oferta in elegir_para_reel(publicadas_sesion, MAX_POSTS_IG_POR_EJECUCION):
        if publicar_reel_en_instagram(oferta):
            ig_enviados += 1

    print(
        f"Ejecución terminada. Telegram: {len(publicadas_sesion)} (Listados: {listados}) | "
        f"Instagram Reels: {ig_enviados}"
    )


if __name__ == "__main__":
    main()
