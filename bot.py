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
    limpio = re.sub(r"\s*\[\vert{}\]\s*Mercado\s*Libre.*$", "", limpio, flags=re.IGNORECASE)
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
                    
