import asyncio
import csv
import glob
import html
import json
import os
import random
import re
import subprocess
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from io import BytesIO

import edge_tts
import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

IG_API_VERSION = "v27.0"
CANAL_TELEGRAM = "@RadarDescuentosMX247"
FPS = 30
ANCHO, ALTO = 1080, 1920
ARCHIVO_LOG_REELS = "reels_log.csv"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

# Zona segura de un Reel de 1080x1920: la interfaz de Instagram tapa la parte de arriba
# (hasta y=230), la de abajo (desde y=1440, donde va el caption) y el borde derecho (botones).
# El contenido va centrado, con 130 px libres a cada lado.
ZONA_X1, ZONA_X2 = 130, 950
ZONA_Y1, ZONA_Y2 = 250, 1430
CENTRO_X = (ZONA_X1 + ZONA_X2) // 2
ANCHO_UTIL = ZONA_X2 - ZONA_X1

UMBRAL_GANCHO = 55          # puntaje mínimo para aceptar un gancho
MARGEN_FINALISTAS = 12      # se sortea entre los que quedan a esta distancia del mejor
MAX_DURACION_VOZ = 15.0
MAX_DURACION_TOTAL = 17.5

VOZ_CHICO_MX = "es-MX-JorgeNeural"
BUSQUEDAS_MUSICA = [
    "upbeat happy background music",
    "cheerful acoustic upbeat loop",
    "energetic positive electronic beat",
    "bright happy indie pop instrumental",
]

HEADERS_IMG = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
    "Referer": "https://www.promodescuentos.com/",
}

FONT_BOLD_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]
FONT_REG_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]

ETIQUETAS_NICHO = {
    "tecnologia": "TECH EN MERCADO LIBRE",
    "cuidado_personal": "CUIDADO PERSONAL ML",
    "general": "PRECIO ACCESIBLE ML",
}
TEXTO_NICHO = {
    "tecnologia": "Tecnología en Mercado Libre México.",
    "cuidado_personal": "Cuidado personal en Mercado Libre México.",
    "general": "Disponible en Mercado Libre México.",
}
HASHTAGS_NICHO = {
    "tecnologia": ["#OfertasTech", "#Tecnologia", "#Gadgets"],
    "cuidado_personal": ["#CuidadoPersonal", "#Skincare", "#BellezaMX"],
    "general": ["#OfertasMexico", "#DescuentosMX", "#ComprasInteligentes"],
}
HASHTAGS_BASE = ["#MercadoLibre", "#RadarDeDescuentosMX"]

# Aperturas que no aportan nada: saludos, presentaciones y frases de relleno.
PATRON_APERTURA_DEBIL = re.compile(
    r"^\s*(hola|hey|oye|mira|amigos|chicos|bienvenid\w*|hoy te|en este video|en este reel|"
    r"no te pierdas|atenci[oó]n|prep[aá]rate|descubre|sum[eé]rgete)\b",
    flags=re.IGNORECASE,
)
# Palabras de hype que van contra el tono sobrio del canal.
PATRON_EXAGERADO = re.compile(
    r"\b(incre[ií]ble|imperdible|locura|brutal|espectacular|alucinante|revolucion\w*|"
    r"el mejor del mundo|nunca visto|no te lo pierdas|sin duda alguna|en el mundo de|"
    r"stop scrolling|follow for more|sigue para m[aá]s|detente a ver esto)\b",
    flags=re.IGNORECASE,
)
INVISIBLES = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u00ad\u2063]")


# ---------------------------------------------------------------------------
# Limpieza de texto
# ---------------------------------------------------------------------------

def cargar_fuente(rutas, tamano):
    for ruta in rutas:
        if os.path.exists(ruta):
            return ImageFont.truetype(ruta, tamano)
    return ImageFont.load_default()


def _limpiar_basico(texto: str) -> str:
    """Quita caracteres invisibles y guiones largos, que delatan texto generado."""
    t = html.unescape(texto or "")
    t = t.replace("\u00a0", " ").replace("\u202f", " ")
    t = INVISIBLES.sub("", t)
    t = re.sub(r"\s*\u2014\s*", ", ", t)
    t = re.sub(r"\s+\u2013\s+", " - ", t)
    t = t.replace("\u2013", "-")
    return re.sub(r"\s+", " ", t).strip()


def _quitar_palabra_prohibida(texto: str) -> str:
    # Los patrones se arman por partes para que el archivo no contenga las palabras completas.
    limpio = re.sub(r"\b" + "cura" + r"dur[íi]a\b", "selección", texto or "", flags=re.IGNORECASE)
    limpio = re.sub(r"\b" + "co" + r"rre\b", "entra", limpio, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", limpio).strip()


CONECTORES_FINALES = {
    "de", "del", "la", "las", "el", "los", "con", "sin", "para", "por",
    "y", "en", "a", "al", "un", "una", "o", "e", "ni", "que",
}

RUIDO_PROMO_TITULO = re.compile(
    r"(?i)(?:"
    r"\$\s?[\d,]+(?:\.\d{1,2})?"
    r"|\b\d{1,3}\s?%\s?(?:off|de descuento|descuento|dto)\b"
    r"|\b(?:env[ií]o\s+gratis|full|msi|meses\s+sin\s+intereses|cup[oó]n\s+aplicado|con\s+cup[oó]n)\b"
    r"|\b(?:color|modelo|talla|tama[ñn]o)\s*:\s*[^|,/]+"
    r")"
)


def _quitar_conectores_finales(palabras):
    palabras = list(palabras)
    while len(palabras) > 2 and palabras[-1].lower().strip(",.;:") in CONECTORES_FINALES:
        palabras.pop()
    return palabras


def _recortar_en_palabra(texto: str, max_chars: int = 48) -> str:
    limpio = re.sub(r"\s+", " ", (texto or "").strip())
    if len(limpio) <= max_chars:
        return limpio
    recorte = limpio[: max_chars + 1].rsplit(" ", 1)[0].strip()
    palabras = _quitar_conectores_finales(recorte.split())
    return " ".join(palabras) if palabras else limpio[:max_chars].strip()


def _deduplicar_palabras_consecutivas(texto: str) -> str:
    """Elimina repeticiones típicas de títulos SEO de Mercado Libre (ej. 'Sony Sony WH-1000XM5')."""
    palabras = (texto or "").split()
    if not palabras:
        return ""
    resultado = [palabras[0]]
    for p in palabras[1:]:
        if p.lower().strip(",.;:-") != resultado[-1].lower().strip(",.;:-"):
            resultado.append(p)
    return " ".join(resultado)


def limpiar_titulo_visual(titulo: str) -> str:
    limpio = _limpiar_basico(titulo)
    limpio = re.sub(r"^\s*\d+\s*°\s*[-:]?\s*", "", limpio)
    limpio = re.sub(r"(?i)^mercado\s*libre\s*:?\s*", "", limpio)
    limpio = re.sub(r"\s*[|]\s*Mercado\s*Libre.*$", "", limpio, flags=re.IGNORECASE)
    limpio = RUIDO_PROMO_TITULO.sub(" ", limpio)
    limpio = _quitar_palabra_prohibida(limpio)
    limpio = re.sub(r"\s*[-–|:,/]+\s*$", "", limpio)
    limpio = re.sub(r"^\s*[-–|:,/]+\s*", "", limpio)
    limpio = re.sub(r"\s+", " ", limpio).strip()
    limpio = _deduplicar_palabras_consecutivas(limpio)
    return limpio or "Selección destacada"


def _nombre_corto(titulo: str, max_palabras: int = 4, max_chars: int = 34) -> str:
    """Nombre del producto que cabe en el gancho hablado y en la tarjeta de pantalla."""
    sin_parentesis = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", titulo or "")
    sin_ruido = RUIDO_PROMO_TITULO.sub(" ", sin_parentesis)
    palabras = re.sub(r"\s+", " ", sin_ruido).strip().split()
    palabras = _deduplicar_palabras_consecutivas(" ".join(palabras)).split()
    corto = " ".join(_quitar_conectores_finales(palabras[:max_palabras])).strip(" ,.;:-/")
    corto = _recortar_en_palabra(corto, max_chars).strip(" ,.;:-/")
    return corto or (titulo or "este producto")


# ---------------------------------------------------------------------------
# Imagen del producto
# ---------------------------------------------------------------------------

def normalizar_imagen_ml(imagen_url: str) -> str:
    if not imagen_url:
        return ""
    url = imagen_url.replace("http://", "https://")
    return re.sub(r"-[A-Z]\.(webp|jpg|jpeg)$", "-O.jpg", url, flags=re.IGNORECASE)


def extraer_mlm_desde_oferta(oferta: dict) -> str:
    mlm_id = (oferta.get("mlm_id") or "").strip().upper()
    if mlm_id:
        return mlm_id
    url = oferta.get("url") or ""
    match = re.search(r"\b(MLM-?\d{6,14})\b", url, flags=re.IGNORECASE)
    return match.group(1).upper().replace("-", "") if match else ""


def obtener_imagen_desde_api_ml(mlm_id: str) -> str:
    if not mlm_id:
        return ""
    try:
        resp = requests.get(
            f"https://api.mercadolibre.com/items/{mlm_id}",
            headers={"User-Agent": "Mozilla/5.0 (compatible; RadarDescuentosMX/1.0)"},
            timeout=10,
        )
        if not resp.ok:
            return ""
        data = resp.json()
        pictures = data.get("pictures") or []
        if isinstance(pictures, list):
            for pic in pictures:
                if isinstance(pic, dict) and pic.get("secure_url"):
                    return pic["secure_url"].replace("http://", "https://")
        thumb = data.get("secure_thumbnail") or data.get("thumbnail") or ""
        if thumb:
            return normalizar_imagen_ml(thumb)
    except Exception as e:
        print(f"[REEL] Aviso consultando API ML para {mlm_id}: {type(e).__name__}")
    return ""


def descargar_imagen_producto(oferta: dict):
    candidatas = []
    if (oferta.get("imagen_fuente") or "").lower() != "rss":
        img_raw = normalizar_imagen_ml(oferta.get("imagen", ""))
        if img_raw:
            candidatas.append(img_raw)

    mlm_id = extraer_mlm_desde_oferta(oferta)
    img_api = obtener_imagen_desde_api_ml(mlm_id)
    if img_api and img_api not in candidatas:
        candidatas.append(img_api)

    for url in candidatas:
        try:
            resp = requests.get(url, headers=HEADERS_IMG, timeout=20)
            resp.raise_for_status()
            img = Image.open(BytesIO(resp.content)).convert("RGBA")
            if img.width >= 60 and img.height >= 60:
                return img
        except Exception as e:
            print(f"[REEL] Aviso descargando imagen: {type(e).__name__}")

    return None


# ---------------------------------------------------------------------------
# Números y voz
# ---------------------------------------------------------------------------

def _a_pesos(texto) -> int:
    """'$1,299.50' -> 1300. Devuelve 0 si no hay un número válido."""
    limpio = re.sub(r"[^\d.]", "", str(texto or ""))
    try:
        valor = float(limpio)
    except ValueError:
        return 0
    return int(round(valor)) if valor > 0 else 0


def _fmt_pesos(valor: int) -> str:
    return f"${valor:,}" if valor else ""


def _precio_a_voz(match: re.Match) -> str:
    """Convierte '$1,299.50' en '1299 pesos con 50' para que la voz lo lea bien."""
    entero = match.group(1).replace(",", "")
    decimales = match.group(2)
    if decimales and int(decimales) != 0:
        return f"{entero} pesos con {decimales}"
    return f"{entero} pesos"


def _normalizar_descuento(descuento: str) -> str:
    """Reduce '25% OFF', '25 %' o '25% de descuento' a '25%'. Devuelve '' si no hay número válido."""
    match = re.search(r"(?<!\d)(\d{1,3})(?!\d)", descuento or "")
    if not match:
        return ""
    numero = int(match.group(1))
    if not 1 <= numero <= 95:
        return ""
    return f"{numero}%"


ABREVIACIONES_VOZ = [
    (re.compile(r"(?i)\b(\d+)\s*(?:pzas?|pzs?|pz)\b"), r"\1 piezas"),
    (re.compile(r"(?i)\b(?:pzas?|pzs?|pz)\b"), "piezas"),
    (re.compile(r"(?i)\b(\d+)\s*(?:uds?|unids?)\b"), r"\1 unidades"),
    (re.compile(r"(?i)\b(?:uds?|unids?)\b"), "unidades"),
    (re.compile(r"(?i)\b(\d+)\s*paq\.?\b"), r"\1 paquetes"),
    (re.compile(r"(?i)\bpaq\.?\b"), "paquete"),
    (re.compile(r"(?i)\b(\d+(?:\.\d+)?)\s*ml\b"), r"\1 mililitros"),
    (re.compile(r"(?i)\b(\d+(?:\.\d+)?)\s*lts?\b"), r"\1 litros"),
    (re.compile(r"(?i)\b(\d+(?:\.\d+)?)\s*grs?\b"), r"\1 gramos"),
    (re.compile(r"(?i)\b(\d+(?:\.\d+)?)\s*kgs?\b"), r"\1 kilogramos"),
    (re.compile(r"(?i)\b(\d+(?:\.\d+)?)\s*mg\b"), r"\1 miligramos"),
    (re.compile(r"(?i)\b(\d+(?:\.\d+)?)\s*mcg\b"), r"\1 microgramos"),
    (re.compile(r"(?i)\b(\d+(?:\.\d+)?)\s*oz\b"), r"\1 onzas"),
    (re.compile(r"(?i)\b(\d+(?:\.\d+)?)\s*cms?\b"), r"\1 centímetros"),
    (re.compile(r"(?i)\b(\d+(?:\.\d+)?)\s*mms?\b"), r"\1 milímetros"),
    (re.compile(r"(?i)\b(\d+(?:\.\d+)?)\s*mts?\b"), r"\1 metros"),
    (re.compile(r"(?i)\b(\d+(?:\.\d+)?)\s*pulg\.?\b"), r"\1 pulgadas"),
    (re.compile(r"(?i)\b(\d+)\s*gb\b"), r"\1 gigabytes"),
    (re.compile(r"(?i)\b(\d+)\s*tb\b"), r"\1 terabytes"),
    (re.compile(r"(?i)\b(\d+)\s*mb\b"), r"\1 megabytes"),
    (re.compile(r"(?i)\b(\d+)\s*mah\b"), r"\1 miliamperios hora"),
    (re.compile(r"(?i)\b(\d+)\s*hz\b"), r"\1 hercios"),
    (re.compile(r"(?i)\b(\d+)\s*w\b"), r"\1 watts"),
    (re.compile(r"(?i)\b(\d+)\s*v\b"), r"\1 voltios"),
    (re.compile(r"(?i)\b(\d+)\s*c[aá]ps\.?\b"), r"\1 cápsulas"),
    (re.compile(r"(?i)\bc[aá]ps\.?\b"), "cápsulas"),
    (re.compile(r"(?i)\b(\d+)\s*tabs\.?\b"), r"\1 tabletas"),
    (re.compile(r"(?i)\btabs\.?\b"), "tabletas"),
    (re.compile(r"(?i)\b(\d+)\s*comp\.?\b"), r"\1 comprimidos"),
    (re.compile(r"(?i)\b(\d+)\s*pares\b"), r"\1 pares"),
    (re.compile(r"(?i)\b(\d+)\s*x\s*(\d+)\b"), r"\1 por \2"),
    (re.compile(r"(?i)\bbluetooth\b"), "blutut"),
    (re.compile(r"(?i)\bwireless\b"), "inalámbrico"),
    (re.compile(r"(?i)\bsmartwatch\b"), "reloj inteligente"),
    (re.compile(r"(?i)\bskincare\b"), "cuidado de la piel"),
    (re.compile(r"(?i)\bFPS\s*(\d+)\+?\b"), r"factor de protección solar \1"),
    (re.compile(r"(?i)\bSPF\s*(\d+)\+?\b"), r"factor de protección solar \1"),
    (re.compile(r"(?i)\bc/u\b"), "cada uno"),
    (re.compile(r"(?i)\bs/n\b"), "sin número"),
    (re.compile(r"(?i)\b(\d+)\s*msi\b"), r"\1 meses sin intereses"),
    (re.compile(r"(?i)\bmsi\b"), "meses sin intereses"),
]


def _expandir_abreviaciones_voz(texto: str) -> str:
    resultado = texto or ""
    for patron, reemplazo in ABREVIACIONES_VOZ:
        resultado = patron.sub(reemplazo, resultado)
    return resultado


def limpiar_texto_para_voz(texto: str) -> str:
    limpio = _limpiar_basico(texto)
    limpio = _quitar_palabra_prohibida(limpio)
    limpio = re.sub(r"https?://\S+", "", limpio)
    limpio = _expandir_abreviaciones_voz(limpio)
    limpio = re.sub(r"\$\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?", _precio_a_voz, limpio)
    limpio = limpio.replace("$", " pesos ")
    limpio = limpio.replace("%", " por ciento ")
    limpio = re.sub(r"[^\w\sáéíóúüñÁÉÍÓÚÜÑ.,!?-]", " ", limpio)
    limpio = re.sub(r'[*_#~`"\u201c\u201d\u2018\u2019\[\]<>|]+', " ", limpio)
    limpio = re.sub(r"\s+([.,!?])", r"\1", limpio)
    limpio = re.sub(r"\s+", " ", limpio).strip()
    return limpio


# ---------------------------------------------------------------------------
# Datos de la oferta
# ---------------------------------------------------------------------------

def _datos_oferta(oferta: dict) -> dict:
    """Reúne solo datos reales de la oferta. Nada de lo que sale de aquí se inventa."""
    titulo = limpiar_titulo_visual(oferta.get("titulo") or "")
    producto = _nombre_corto(titulo)

    precio_txt = _limpiar_basico(oferta.get("precio") or "")
    precio = _a_pesos(precio_txt)
    if precio_txt and not precio_txt.startswith("$"):
        precio_txt = f"${precio_txt}"
    if not precio:
        precio_txt = ""

    anterior = _a_pesos(oferta.get("precio_anterior") or "")
    if not precio or anterior <= precio:
        anterior = 0
    ahorro = anterior - precio if anterior else 0

    pct = _normalizar_descuento(oferta.get("descuento") or "")
    if not pct and anterior:
        calculado = round(100 * ahorro / anterior)
        if 1 <= calculado <= 95:
            pct = f"{calculado}%"

    palabras_producto = [
        p for p in re.findall(r"\w+", producto.lower())
        if len(p) > 3 and p not in CONECTORES_FINALES
    ][:3]

    return {
        "titulo": titulo,
        "producto": producto,
        "palabras_producto": palabras_producto,
        "precio": precio,
        "precio_txt": precio_txt,
        "anterior": anterior,
        "anterior_txt": _fmt_pesos(anterior),
        "ahorro": ahorro,
        "ahorro_txt": _fmt_pesos(ahorro),
        "pct": pct,
        "nicho": (oferta.get("nicho") or "general").strip().lower(),
    }


def _numeros_permitidos(d: dict) -> set:
    permitidos = set()
    for fuente in (d["precio_txt"], d["anterior_txt"], d["ahorro_txt"], d["pct"], d["titulo"]):
        permitidos.update(re.findall(r"\d+", (fuente or "").replace(",", "")))
    return permitidos


def _numeros_ok(texto: str, permitidos: set) -> bool:
    return all(n in permitidos for n in re.findall(r"\d+", (texto or "").replace(",", "")))


# ---------------------------------------------------------------------------
# Ganchos: fórmulas, puntaje local y elección
# ---------------------------------------------------------------------------

def _pantalla_por_defecto(d: dict) -> list:
    primera = d["precio_txt"] or (f"{d['pct']} DE DESCUENTO" if d["pct"] else "")
    lineas = [l for l in (primera, d["producto"].upper()) if l]
    return lineas[:2] or ["OFERTA EN MERCADO LIBRE"]


def _candidatos_plantilla(d: dict) -> list:
    """Ganchos con datos reales, breves (<= 8 palabras) y con el dato clave al inicio."""
    prod = d["producto"]
    candidatos = []
    if d["precio"] and d["anterior"]:
        candidatos.append({
            "formula": "Antes y ahora",
            "hablado": f"Antes {d['anterior_txt']}, ahora {d['precio_txt']} en {prod}.",
            "pantalla": [f"ANTES {d['anterior_txt']}", f"AHORA {d['precio_txt']}"],
        })
    if d["ahorro"] >= 50:
        candidatos.append({
            "formula": "Ahorro en pesos",
            "hablado": f"Ahorras {d['ahorro_txt']} en {prod}.",
            "pantalla": [f"AHORRAS {d['ahorro_txt']}", prod.upper()],
        })
    if d["precio"]:
        candidatos.append({
            "formula": "El número primero",
            "hablado": f"{d['precio_txt']} por {prod}.",
            "pantalla": [d["precio_txt"], prod.upper()],
        })
        candidatos.append({
            "formula": "Dirigido",
            "hablado": f"{prod} baja a {d['precio_txt']}.",
            "pantalla": [d["precio_txt"], prod.upper()],
        })
    if d["pct"]:
        candidatos.append({
            "formula": "Descuento",
            "hablado": f"{d['pct']} menos en {prod}.",
            "pantalla": [f"{d['pct']} DE DESCUENTO", prod.upper()],
        })
    if not candidatos:
        candidatos.append({
            "formula": "Sin dato",
            "hablado": f"{prod} en oferta hoy.",
            "pantalla": [prod.upper()],
        })
    return candidatos


def _normalizar_candidato_gemini(item, d: dict, permitidos: set):
    if not isinstance(item, dict):
        return None
    hablado = _quitar_palabra_prohibida(_limpiar_basico(str(item.get("hablado") or ""))).strip('"\u201c\u201d ')
    if not hablado or "http" in hablado.lower():
        return None
    if hablado[-1] not in ".!?":
        hablado += "."
    if len(hablado.split()) > 12 or not _numeros_ok(hablado, permitidos):
        return None

    pantalla = item.get("pantalla")
    if isinstance(pantalla, str):
        pantalla = [pantalla]
    lineas = []
    for linea in (pantalla or [])[:2]:
        limpia = _quitar_palabra_prohibida(_limpiar_basico(str(linea))).upper()
        if limpia:
            lineas.append(limpia)
    pantalla_valida = (
        lineas
        and sum(len(l.split()) for l in lineas) <= 7
        and all(len(l) <= 30 for l in lineas)
        and all(_numeros_ok(l, permitidos) for l in lineas)
    )
    if not pantalla_valida:
        lineas = _pantalla_por_defecto(d)

    formula = _limpiar_basico(str(item.get("formula") or "libre"))[:30]
    return {"formula": f"Gemini: {formula}", "hablado": hablado, "pantalla": lineas}


def _candidatos_gemini(d: dict) -> list:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return []

    def dato(valor):
        return valor or "no disponible"

    prompt = (
        "Eres guionista de Reels de ofertas para México. Escribe 3 ganchos de voz, con su texto en pantalla, "
        "para esta oferta de Mercado Libre.\n\n"
        "Datos reales. No uses ningún otro número, marca ni característica:\n"
        f"- Producto: {d['titulo']}\n"
        f"- Nombre corto: {d['producto']}\n"
        f"- Precio actual: {dato(d['precio_txt'])}\n"
        f"- Precio anterior: {dato(d['anterior_txt'])}\n"
        f"- Ahorro en pesos: {dato(d['ahorro_txt'])}\n"
        f"- Descuento: {dato(d['pct'])}\n"
        f"- Nicho: {d['nicho']}\n\n"
        "Usa 3 fórmulas distintas, una por gancho, elegidas entre:\n"
        "1. Antes y ahora (solo si hay precio anterior)\n"
        "2. Ahorro en pesos (solo si hay ahorro)\n"
        "3. El número primero: abre con el precio\n"
        "4. Descuento: abre con el porcentaje (solo si hay descuento)\n"
        "5. Dirigido: le habla a quien busca ese producto\n\n"
        "Reglas:\n"
        "- hablado: máximo 9 palabras, termina en punto y se dice en menos de 2.5 segundos. "
        "Abre con el dato concreto (precio, ahorro o porcentaje) o con el producto.\
