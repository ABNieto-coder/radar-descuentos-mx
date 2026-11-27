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
        "Abre con el dato concreto (precio, ahorro o porcentaje) o con el producto.\n"
        "- Sin saludos, sin 'en este video', sin 'mira esto' y sin exagerar con palabras como "
        "'increíble' o 'imperdible'.\n"
        "- Tono seguro y sobrio, en español natural de México.\n"
        "- pantalla: lista de 1 o 2 líneas en mayúsculas, máximo 6 palabras en total.\n"
        'Responde solo con un arreglo JSON: [{"formula": "...", "hablado": "...", "pantalla": ["...", "..."]}]'
    )

    try:
        res = requests.post(
            GEMINI_URL,
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.9,
                    "maxOutputTokens": 900,
                    "responseMimeType": "application/json",
                    "thinkingConfig": {"thinkingBudget": 0},
                },
            },
            timeout=20,
        )
        if not res.ok:
            print(f"[REEL] Aviso Gemini HTTP {res.status_code}")
            return []
        candidatos = res.json().get("candidates") or []
        partes = (candidatos[0].get("content", {}).get("parts") or []) if candidatos else []
        texto = (partes[0].get("text") or "").strip() if partes else ""
        texto = re.sub(r"^```(?:json)?|```$", "", texto, flags=re.MULTILINE).strip()
        data = json.loads(texto)
        if isinstance(data, dict):
            data = data.get("ganchos") or data.get("candidatos") or [data]
        permitidos = _numeros_permitidos(d)
        salida = []
        for item in data[:5]:
            cand = _normalizar_candidato_gemini(item, d, permitidos)
            if cand:
                salida.append(cand)
        return salida
    except Exception as e:
        print(f"[REEL] Aviso Gemini (se usan solo plantillas): {type(e).__name__}")
        return []


def puntuar_gancho(hablado: str, d: dict):
    """Puntaje local de 0 a 100. Sirve para descartar ganchos flojos, no para predecir cuál se hará viral.
    Devuelve (puntaje, motivo_si_se_descarta)."""
    texto = (hablado or "").strip()
    if not texto:
        return 0, "vacío"
    if PATRON_APERTURA_DEBIL.search(texto):
        return 0, "apertura de relleno o saludo"
    if PATRON_EXAGERADO.search(texto):
        return 0, "palabra exagerada"

    bajo = texto.lower()
    primera = re.split(r"(?<=[.!?])\s+", texto, maxsplit=1)[0]
    palabras = primera.split()
    primeras4 = " ".join(palabras[:4]).lower()
    tiene_numero = bool(re.search(r"\d", primera))
    tiene_producto = any(p in bajo for p in d["palabras_producto"])
    producto_al_inicio = any(p in primeras4 for p in d["palabras_producto"])

    especificidad = (70 if tiene_numero else 0) + (30 if tiene_producto else 0)

    adelanto = 0
    if re.search(r"\d", primeras4) or producto_al_inicio:
        adelanto += 60
    if len(palabras) <= 8:
        adelanto += 40
    elif len(palabras) <= 10:
        adelanto += 20

    direccion = 100 if re.search(r"\b(ahorras|buscas|tu|tus|te|ti|llévate|llevate)\b", bajo) else 0
    ganancia = 100 if re.search(r"\b(ahorras|antes|descuento|menos|ahora|baja)\b", bajo) else 0

    puntaje = 0.30 * especificidad + 0.25 * adelanto + 0.15 * direccion + 0.20 * ganancia + 0.10 * 100
    return round(puntaje, 1), ""


def elegir_gancho(d: dict) -> dict:
    """Junta ganchos de plantilla y de Gemini, los puntúa, deduplica y sortea entre los mejores.
    El sorteo deja registro de qué fórmula se usó para comparar resultados después."""
    crudos = _candidatos_plantilla(d) + _candidatos_gemini(d)
    vistos = set()
    candidatos = []
    for c in crudos:
        clave = re.sub(r"\s+", " ", (c.get("hablado") or "").lower().strip())
        if clave and clave not in vistos:
            vistos.add(clave)
            c["puntaje"], c["motivo"] = puntuar_gancho(c["hablado"], d)
            candidatos.append(c)

    resumen = " | ".join(f"{c['puntaje']:.0f} {c['formula']}" for c in candidatos)
    print(f"[REEL] Ganchos puntuados: {resumen}")

    aceptables = [c for c in candidatos if c["puntaje"] >= UMBRAL_GANCHO]
    if not aceptables:
        mejor = max(candidatos, key=lambda c: c["puntaje"])
        print(f"[REEL] Ningún gancho llegó a {UMBRAL_GANCHO}; se usa el mejor disponible: {mejor['formula']}")
        return mejor

    tope = max(c["puntaje"] for c in aceptables)
    finalistas = [c for c in aceptables if c["puntaje"] >= tope - MARGEN_FINALISTAS]
    return random.choice(finalistas)


def construir_guion(d: dict, gancho: dict) -> dict:
    """Tres tiempos: gancho, apoyo y cierre con una sola invitación que repite el dato del gancho."""
    hablado1 = gancho["hablado"]
    bajo = hablado1.lower()

    producto_en_gancho = any(p in bajo for p in d["palabras_producto"][:2])
    if not producto_en_gancho:
        hablado2 = f"{d['producto']}, disponible en Mercado Libre México."
    elif d["pct"] and d["anterior"] and d["pct"].lower() not in bajo:
        hablado2 = f"Eso es {d['pct']} menos que su precio anterior."
    else:
        hablado2 = TEXTO_NICHO.get(d["nicho"], TEXTO_NICHO["general"])

    if d["precio_txt"] and d["precio_txt"].lower() in bajo:
        hablado3 = f"Confirma los {d['precio_txt']} en el enlace de la bio."
    elif d["pct"] and d["pct"].lower() in bajo:
        hablado3 = f"Confirma el {d['pct']} en el enlace de la bio."
    else:
        hablado3 = "Mira el precio en el enlace de la bio."

    beats = [limpiar_texto_para_voz(b) for b in (hablado1, hablado2, hablado3)]
    return {"beats": beats, "voz": " ".join(beats)}


# ---------------------------------------------------------------------------
# Imágenes de cada escena
# ---------------------------------------------------------------------------

def _crear_fondo_editorial(ancho: int, alto: int) -> Image.Image:
    base = Image.new("RGB", (ancho, alto), (10, 14, 22))
    draw = ImageDraw.Draw(base)

    top_rgb = (10, 14, 22)
    bot_rgb = (17, 24, 39)
    for y in range(alto):
        t = y / max(1, alto - 1)
        r = int(top_rgb[0] + (bot_rgb[0] - top_rgb[0]) * t)
        g = int(top_rgb[1] + (bot_rgb[1] - top_rgb[1]) * t)
        b = int(top_rgb[2] + (bot_rgb[2] - top_rgb[2]) * t)
        draw.line([(0, y), (ancho, y)], fill=(r, g, b))

    glow = Image.new("RGBA", (ancho, alto), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse([-120, 240, 580, 940], fill=(0, 255, 65, 20))
    gdraw.ellipse([500, 950, 1200, 1650], fill=(56, 189, 248, 24))
    glow = glow.filter(ImageFilter.GaussianBlur(150))

    compuesta = Image.alpha_composite(base.convert("RGBA"), glow)
    return compuesta.convert("RGB")


def _encuadrar_producto_grande(img: Image.Image, box_w: int, box_h: int) -> Image.Image:
    rgba = img.convert("RGBA")
    rgb = rgba.convert("RGB")
    w, h = rgb.size
    px = rgb.load()

    esquinas = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]
    fondo_blanco = sum(1 for r, g, b in esquinas if r > 246 and g > 246 and b > 246) == 4
    if fondo_blanco:
        left, top, right, bottom = w, h, 0, 0
        for y in range(0, h, 2):
            for x in range(0, w, 2):
                r, g, b = px[x, y]
                if not (r > 246 and g > 246 and b > 246):
                    left = min(left, x)
                    top = min(top, y)
                    right = max(right, x)
                    bottom = max(bottom, y)
        if (right - left) >= 60 and (bottom - top) >= 60:
            pad_x = max(10, int((right - left) * 0.05))
            pad_y = max(10, int((bottom - top) * 0.05))
            rgba = rgba.crop((
                max(0, left - pad_x),
                max(0, top - pad_y),
                min(w, right + pad_x),
                min(h, bottom + pad_y),
            ))

    target_w = int(box_w * 0.92)
    target_h = int(box_h * 0.92)
    escala = min(target_w / max(1, rgba.width), target_h / max(1, rgba.height))
    nuevo_w = max(1, int(rgba.width * escala))
    nuevo_h = max(1, int(rgba.height * escala))

    redimensionada = rgba.resize((nuevo_w, nuevo_h), Image.Resampling.LANCZOS)
    rgb_sharp = redimensionada.convert("RGB").filter(ImageFilter.UnsharpMask(radius=1.2, percent=110, threshold=3))
    resultado = rgb_sharp.convert("RGBA")
    resultado.putalpha(redimensionada.getchannel("A"))
    return resultado


def _fuente_ajustada(draw, texto: str, rutas, max_w: int, tam_max: int, tam_min: int = 28):
    """Baja el tamaño de la letra hasta que el texto quepa en el ancho disponible."""
    tam = tam_max
    while tam > tam_min:
        fuente = cargar_fuente(rutas, tam)
        if draw.textlength(texto, font=fuente) <= max_w:
            return fuente
        tam -= 4
    return cargar_fuente(rutas, tam_min)


def _envolver_texto(draw, texto: str, fuente, max_w: int, max_lineas: int) -> list:
    lineas, actual = [], ""
    for palabra in (texto or "").split():
        prueba = f"{actual} {palabra}".strip()
        if actual and draw.textlength(prueba, font=fuente) > max_w:
            lineas.append(actual)
            actual = palabra
        else:
            actual = prueba
    if actual:
        lineas.append(actual)
    if len(lineas) > max_lineas:
        lineas = lineas[:max_lineas]
        lineas[-1] = " ".join(_quitar_conectores_finales(lineas[-1].split()))
    return lineas


def _lienzo():
    canvas = _crear_fondo_editorial(ANCHO, ALTO)
    draw = ImageDraw.Draw(canvas)
    f_marca = cargar_fuente(FONT_BOLD_PATHS, 24)
    draw.text((CENTRO_X, 275), ">_ RADAR DE DESCUENTOS MX", fill=(148, 163, 184), font=f_marca, anchor="mm")
    return canvas


def _tarjeta_producto(canvas: Image.Image, prod_img, caja: tuple, titulo: str) -> Image.Image:
    x1, y1, x2, y2 = caja
    sombra = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(sombra)
    sdraw.rounded_rectangle([x1 + 6, y1 + 12, x2 + 6, y2 + 12], radius=40, fill=(0, 0, 0, 130))
    sombra = sombra.filter(ImageFilter.GaussianBlur(18))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), sombra).convert("RGB")
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(list(caja), radius=40, fill=(255, 255, 255), outline=(71, 85, 105), width=2)

    box_w, box_h = x2 - x1, y2 - y1
    if prod_img is not None:
        pieza = _encuadrar_producto_grande(prod_img, box_w, box_h)
        canvas.paste(pieza, (x1 + (box_w - pieza.width) // 2, y1 + (box_h - pieza.height) // 2), pieza)
        return canvas

    cx = (x1 + x2) // 2
    f_tag = cargar_fuente(FONT_BOLD_PATHS, 28)
    f_tit = cargar_fuente(FONT_BOLD_PATHS, 44)
    draw.rounded_rectangle([cx - 165, y1 + 50, cx + 165, y1 + 100], radius=25, fill=(241, 245, 249))
    draw.text((cx, y1 + 75), "MERCADO LIBRE MX", fill=(15, 23, 42), font=f_tag, anchor="mm")
    y = y1 + 190
    for linea in _envolver_texto(draw, titulo, f_tit, box_w - 90, 4):
        draw.text((cx, y), linea, fill=(15, 23, 42), font=f_tit, anchor="mm")
        y += 58
    return canvas


def _pildora(draw, caja: tuple, texto: str, fuente, relleno, borde, color_texto=(255, 255, 255)):
    x1, y1, x2, y2 = caja
    draw.rounded_rectangle(list(caja), radius=(y2 - y1) // 2, fill=relleno, outline=borde, width=3)
    draw.text(((x1 + x2) // 2, (y1 + y2) // 2), texto, fill=color_texto, font=fuente, anchor="mm")


def _escena_gancho(d: dict, gancho: dict, prod_img, ruta: str):
    """Fotograma 1: el gancho ya está en pantalla desde el primer instante."""
    canvas = _lienzo()
    draw = ImageDraw.Draw(canvas)
    lineas = (gancho.get("pantalla") or _pantalla_por_defecto(d))[:2]

    f1 = _fuente_ajustada(draw, lineas[0], FONT_BOLD_PATHS, ANCHO_UTIL, 100, 44)
    draw.text((CENTRO_X, 395), lineas[0], fill=(250, 204, 21), font=f1, anchor="mm")
    if len(lineas) > 1:
        f2 = _fuente_ajustada(draw, lineas[1], FONT_BOLD_PATHS, ANCHO_UTIL, 56, 30)
        draw.text((CENTRO_X, 500), lineas[1], fill=(248, 250, 252), font=f2, anchor="mm")

    canvas = _tarjeta_producto(canvas, prod_img, (ZONA_X1, 580, ZONA_X2, 1270), d["titulo"])
    draw = ImageDraw.Draw(canvas)
    etiqueta = ETIQUETAS_NICHO.get(d["nicho"], ETIQUETAS_NICHO["general"])
    f_badge = cargar_fuente(FONT_BOLD_PATHS, 30)
    _pildora(draw, (CENTRO_X - 280, 1330, CENTRO_X + 280, 1400), etiqueta, f_badge, (20, 28, 44), (0, 255, 65))
    canvas.save(ruta, format="PNG")


def _escena_producto(d: dict, prod_img, ruta: str):
    canvas = _lienzo()
    canvas = _tarjeta_producto(canvas, prod_img, (ZONA_X1, 300, ZONA_X2, 880), d["titulo"])
    draw = ImageDraw.Draw(canvas)

    f_tit = cargar_fuente(FONT_BOLD_PATHS, 46)
    y = 955
    for linea in _envolver_texto(draw, _recortar_en_palabra(d["titulo"], 90), f_tit, ANCHO_UTIL, 3):
        draw.text((CENTRO_X, y), linea, fill=(248, 250, 252), font=f_tit, anchor="mm")
        y += 56

    if d["precio_txt"]:
        if d["anterior_txt"]:
            f_ant = cargar_fuente(FONT_REG_PATHS, 38)
            texto_ant = f"Antes {d['anterior_txt']}"
            draw.text((CENTRO_X, 1150), texto_ant, fill=(148, 163, 184), font=f_ant, anchor="mm")
            mitad = draw.textlength(texto_ant, font=f_ant) / 2
            draw.line([(CENTRO_X - mitad, 1150), (CENTRO_X + mitad, 1150)], fill=(148, 163, 184), width=3)
        texto_precio = f"AHORA {d['precio_txt']}" if d["anterior_txt"] else d["precio_txt"]
        f_precio = _fuente_ajustada(draw, texto_precio, FONT_BOLD_PATHS, ANCHO_UTIL - 80, 72, 40)
        _pildora(draw, (ZONA_X1 + 20, 1195, ZONA_X2 - 20, 1325), texto_precio, f_precio, (18, 28, 45), (16, 185, 129))
        f_ahorro = cargar_fuente(FONT_BOLD_PATHS, 36)
        if d["ahorro_txt"] and d["pct"]:
            draw.text((CENTRO_X, 1385), f"Ahorras {d['ahorro_txt']}  ({d['pct']})", fill=(16, 185, 129),
                      font=f_ahorro, anchor="mm")
        elif d["pct"]:
            draw.text((CENTRO_X, 1385), f"{d['pct']} de descuento", fill=(16, 185, 129), font=f_ahorro, anchor="mm")
    canvas.save(ruta, format="PNG")


def _escena_cierre(d: dict, prod_img, ruta: str):
    canvas = _lienzo()
    canvas = _tarjeta_producto(canvas, prod_img, (ZONA_X1, 300, ZONA_X2, 860), d["titulo"])
    draw = ImageDraw.Draw(canvas)

    f_cta = _fuente_ajustada(draw, "ENLACE EN LA BIO", FONT_BOLD_PATHS, ANCHO_UTIL - 80, 70, 40)
    _pildora(draw, (ZONA_X1 + 20, 940, ZONA_X2 - 20, 1070), "ENLACE EN LA BIO", f_cta, (20, 28, 44), (0, 255, 65))

    if d["precio_txt"]:
        f_precio = _fuente_ajustada(draw, d["precio_txt"], FONT_BOLD_PATHS, ANCHO_UTIL, 90, 44)
        draw.text((CENTRO_X, 1175), d["precio_txt"], fill=(250, 204, 21), font=f_precio, anchor="mm")

    f_nota = cargar_fuente(FONT_REG_PATHS, 30)
    draw.text((CENTRO_X, 1265), "Precio y disponibilidad pueden cambiar", fill=(148, 163, 184), font=f_nota, anchor="mm")
    f_tg = _fuente_ajustada(draw, "Más ofertas en Telegram", FONT_BOLD_PATHS, ANCHO_UTIL, 34, 24)
    draw.text((CENTRO_X, 1345), "Más ofertas en Telegram", fill=(226, 232, 240), font=f_tg, anchor="mm")
    canvas.save(ruta, format="PNG")


def crear_escenas(d: dict, gancho: dict, oferta: dict, carpeta: str) -> list:
    prod_img = descargar_imagen_producto(oferta)
    if prod_img is None:
        print("[REEL] Fallback visual activado: sin foto real descargable.")
    rutas = [os.path.join(carpeta, f"escena{i}.png") for i in (1, 2, 3)]
    _escena_gancho(d, gancho, prod_img, rutas[0])
    _escena_producto(d, prod_img, rutas[1])
    _escena_cierre(d, prod_img, rutas[2])
    return rutas


# ---------------------------------------------------------------------------
# Voz, música y video
# ---------------------------------------------------------------------------

async def _sintetizar_voz(texto: str, ruta_salida: str, voz: str):
    communicate = edge_tts.Communicate(texto, voz, rate="+2%")
    await communicate.save(ruta_salida)


def _obtener_duracion_real_audio(ruta_voz: str, texto_respaldo: str) -> float:
    try:
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                ruta_voz,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if probe.returncode == 0 and probe.stdout.strip():
            dur = float(probe.stdout.strip())
            if dur > 0:
                return round(dur, 2)
    except Exception as e:
        print(f"[REEL] Aviso ffprobe en audio (usando estimación): {type(e).__name__}")

    chars_utiles = max(len(texto_respaldo or ""), 50)
    return round(chars_utiles / 11.5, 2)


def generar_audio_voz(guion: str, ruta_voz: str) -> float:
    asyncio.run(_sintetizar_voz(guion, ruta_voz, VOZ_CHICO_MX))

    if not os.path.exists(ruta_voz) or os.path.getsize(ruta_voz) == 0:
        raise RuntimeError("Edge-TTS no generó archivo de audio válido.")

    duracion = _obtener_duracion_real_audio(ruta_voz, guion)
    print(f"[REEL] Duración real detectada de voz: {duracion}s")
    return max(6.0, min(MAX_DURACION_VOZ, duracion))


def descargar_musica_automatica(ruta_musica: str) -> str:
    api_key = os.getenv("FREESOUND_API_KEY", "").strip()
    if api_key:
        try:
            query = random.choice(BUSQUEDAS_MUSICA)
            res = requests.get(
                "https://freesound.org/apiv2/search/text/",
                params={
                    "query": query,
                    "filter": "duration:[8 TO 60]",
                    "fields": "id,name,previews",
                    "page_size": 15,
                },
                headers={"Authorization": f"Token {api_key}"},
                timeout=15,
            )
            if res.ok:
                resultados = res.json().get("results", [])
                candidatos = [
                    r["previews"].get("preview-hq-mp3")
                    for r in resultados
                    if isinstance(r.get("previews"), dict) and r["previews"].get("preview-hq-mp3")
                ]
                if candidatos:
                    url_mp3 = random.choice(candidatos)
                    audio_res = requests.get(url_mp3, timeout=20)
                    if audio_res.ok and len(audio_res.content) > 5000:
                        with open(ruta_musica, "wb") as f:
                            f.write(audio_res.content)
                        print(f"[REEL] Música descargada desde Freesound ({query}).")
                        return ruta_musica
            else:
                print(f"[REEL] Aviso Freesound HTTP {res.status_code}")
        except Exception as e:
            print(f"[REEL] Aviso Freesound: {type(e).__name__}")

    locales = glob.glob("assets/*.mp3")
    if locales:
        elegida = random.choice(locales)
        print(f"[REEL] Usando pista local: {elegida}")
        return elegida

    print("[REEL] Aviso: sin pista de música disponible, se publicará solo con voz.")
    return ""


def calcular_duraciones(beats: list, duracion_voz: float) -> list:
    """Reparte el tiempo de las 3 escenas según cuánto se habla en cada una."""
    palabras = [max(1, len(b.split())) for b in beats]
    total_palabras = sum(palabras)
    total = max(8.0, min(MAX_DURACION_TOTAL, round(duracion_voz + 1.6, 2)))
    inicio_voz = 0.15

    corte1 = inicio_voz + duracion_voz * palabras[0] / total_palabras
    corte2 = inicio_voz + duracion_voz * (palabras[0] + palabras[1]) / total_palabras
    duraciones = [corte1, corte2 - corte1, total - corte2]
    if min(duraciones) < 1.2:
        duraciones = [total * 0.34, total * 0.33, total * 0.33]
    return [round(x, 3) for x in duraciones]


def renderizar_video_mp4(rutas_escenas: list, duraciones: list, ruta_voz: str, ruta_musica: str, ruta_video: str) -> bool:
    """Une las escenas con corte directo. Cada escena lleva su propio zoom suave."""
    n = len(rutas_escenas)
    total = round(sum(duraciones), 3)
    fade_out_a = max(0.5, round(total - 0.85, 2))

    cmd = ["ffmpeg", "-y"]
    for ruta in rutas_escenas:
        cmd += ["-i", ruta]
    cmd += ["-i", ruta_voz]
    usa_musica = bool(ruta_musica and os.path.exists(ruta_musica))
    if usa_musica:
        cmd += ["-stream_loop", "-1", "-i", ruta_musica]

    partes = []
    for i, dur in enumerate(duraciones):
        frames = max(1, int(round(dur * FPS)))
        denom = max(1, frames - 1)
        partes.append(
            f"[{i}:v]scale=2160:3840:flags=lanczos,"
            f"zoompan=z='1.0+0.03*(1-cos(PI*on/{denom}))/2'"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={frames}:s={ANCHO}x{ALTO}:fps={FPS},setsar=1,format=yuv420p[v{i}]"
        )
    partes.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vout]")

    if usa_musica:
        partes.append(
            f"[{n}:a]adelay=150|150,apad,volume=1.05[voz];"
            f"[{n + 1}:a]volume=0.14,afade=t=in:st=0:d=0.4,afade=t=out:st={fade_out_a}:d=0.85[mus];"
            f"[voz][mus]amix=inputs=2:duration=first:normalize=0[aout]"
        )
    else:
        partes.append(f"[{n}:a]adelay=150|150,apad,volume=1.05[aout]")

    cmd += [
        "-filter_complex", ";".join(partes),
        "-map", "[vout]", "-map", "[aout]",
        "-t", str(total),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-g", "60", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        "-movflags", "+faststart",
        ruta_video,
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[REEL] Error en FFmpeg: {res.stderr[-600:]}")
        return False
    return os.path.exists(ruta_video) and os.path.getsize(ruta_video) > 0


# ---------------------------------------------------------------------------
# Caption
# ---------------------------------------------------------------------------

def armar_caption_reel(oferta: dict, d: dict = None) -> str:
    """Lo único que se ve antes de '... más' son unos 125 caracteres: ahí van el precio y el producto.
    Una sola invitación (el enlace de la bio) y máximo 5 hashtags."""
    d = d or _datos_oferta(oferta)
    etiqueta_nicho = {
        "tecnologia": "Tecnología en Mercado Libre",
        "cuidado_personal": "Cuidado personal en Mercado Libre",
    }.get(d["nicho"], "Precio accesible en Mercado Libre")

    if d["precio_txt"]:
        primera = f"{d['precio_txt']} | {_recortar_en_palabra(d['titulo'], 80)}"
    else:
        primera = _recortar_en_palabra(d["titulo"], 110)

    if d["ahorro_txt"] and d["pct"]:
        segunda = f"{etiqueta_nicho} | Ahorras {d['ahorro_txt']} ({d['pct']})"
    elif d["pct"]:
        segunda = f"{etiqueta_nicho} | {d['pct']} de descuento"
    else:
        segunda = etiqueta_nicho

    hashtags = (HASHTAGS_BASE + HASHTAGS_NICHO.get(d["nicho"], HASHTAGS_NICHO["general"]))[:5]
    lineas = [
        primera,
        segunda,
        "",
        "Enlace en la bio.",
        "Más alertas en Telegram.",
        "Enlace de afiliado. Precios y disponibilidad sujetos a cambios.",
        "",
        " ".join(hashtags),
    ]
    caption = "\n".join(_quitar_palabra_prohibida(_limpiar_basico(l)) for l in lineas)
    return caption[:2200]


# ---------------------------------------------------------------------------
# Bitácora de Reels (para comparar nichos y fórmulas después)
# ---------------------------------------------------------------------------

def registrar_reel_log(oferta: dict, d: dict, gancho: dict, media_id: str):
    try:
        escribir_encabezado = not os.path.exists(ARCHIVO_LOG_REELS) or os.path.getsize(ARCHIVO_LOG_REELS) == 0
        with open(ARCHIVO_LOG_REELS, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if escribir_encabezado:
                w.writerow(["fecha_utc", "nicho", "mlm_id", "formula", "puntaje", "gancho", "precio", "descuento", "media_id"])
            w.writerow([
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                d["nicho"],
                extraer_mlm_desde_oferta(oferta),
                gancho.get("formula", ""),
                gancho.get("puntaje", ""),
                gancho.get("hablado", ""),
                d["precio_txt"],
                d["pct"],
                media_id,
            ])
    except Exception as e:
        print(f"[REEL] Aviso escribiendo bitácora: {type(e).__name__}")


def contar_reels_por_nicho(ultimos: int = 200) -> Counter:
    conteo = Counter()
    try:
        if not os.path.exists(ARCHIVO_LOG_REELS):
            return conteo
        with open(ARCHIVO_LOG_REELS, "r", newline="", encoding="utf-8") as f:
            filas = list(csv.DictReader(f))
        for fila in filas[-ultimos:]:
            conteo[(fila.get("nicho") or "general").strip()] += 1
    except Exception as e:
        print(f"[REEL] Aviso leyendo bitácora: {type(e).__name__}")
    return conteo


# ---------------------------------------------------------------------------
# Meta Graph API
# ---------------------------------------------------------------------------

def _subir_y_publicar_reel(ig_user_id: str, access_token: str, ruta_mp4: str, caption: str) -> str:
    """Publica el Reel y devuelve el id del medio, o '' si algo falla."""
    if not os.path.exists(ruta_mp4) or os.path.getsize(ruta_mp4) == 0:
        print("[REEL] Archivo MP4 vacío o inexistente antes de subir.")
        return ""

    file_size = os.path.getsize(ruta_mp4)

    res_init = requests.post(
        f"https://graph.facebook.com/{IG_API_VERSION}/{ig_user_id}/media",
        data={
            "media_type": "REELS",
            "upload_type": "resumable",
            "caption": caption,
            "share_to_feed": "true",
            "access_token": access_token,
        },
        timeout=30,
    )
    data_init = res_init.json()
    if "id" not in data_init:
        err = data_init.get("error", {}) if isinstance(data_init, dict) else {}
        print(f"[REEL] Error iniciando contenedor: code={err.get('code')} msg={err.get('message', '')}")
        return ""

    creation_id = data_init["id"]
    upload_uri = data_init.get(
        "uri",
        f"https://rupload.facebook.com/ig-api-upload/{IG_API_VERSION}/{creation_id}",
    )

    with open(ruta_mp4, "rb") as f_video:
        res_up = requests.post(
            upload_uri,
            headers={
                "Authorization": f"OAuth {access_token}",
                "Content-Type": "video/mp4",
                "offset": "0",
                "file_size": str(file_size),
            },
            data=f_video,
            timeout=120,
        )
    try:
        data_up = res_up.json()
    except Exception:
        data_up = {}

    if not res_up.ok or data_up.get("success") is False:
        print(f"[REEL] Error subiendo video (HTTP {res_up.status_code})")
        return ""

    for _ in range(24):
        time.sleep(5)
        try:
            res_st = requests.get(
                f"https://graph.facebook.com/{IG_API_VERSION}/{creation_id}",
                params={"fields": "status_code,status", "access_token": access_token},
                timeout=20,
            )
            status_data = res_st.json()
        except Exception as e:
            print(f"[REEL] Aviso consultando estado del contenedor: {type(e).__name__}")
            continue

        status_code = status_data.get("status_code")
        if status_code == "FINISHED":
            break
        if status_code in ("ERROR", "EXPIRED"):
            print(f"[REEL] Meta rechazó el video: {status_code}")
            return ""
    else:
        print("[REEL] Tiempo agotado esperando procesamiento de Meta.")
        return ""

    res_pub = requests.post(
        f"https://graph.facebook.com/{IG_API_VERSION}/{ig_user_id}/media_publish",
        data={
            "creation_id": creation_id,
            "access_token": access_token,
        },
        timeout=30,
    )
    data_pub = res_pub.json()
    if "id" not in data_pub:
        err = data_pub.get("error", {}) if isinstance(data_pub, dict) else {}
        print(f"[REEL] Error publicando Reel: code={err.get('code')} msg={err.get('message', '')}")
        return ""

    print(f"[REEL] ¡Reel publicado con éxito! ID: {data_pub['id']}")
    return str(data_pub["id"])


# ---------------------------------------------------------------------------
# Flujo principal
# ---------------------------------------------------------------------------

def preparar_reel(oferta: dict, carpeta: str, ruta_mp4: str = "") -> dict:
    """Arma el Reel completo (guion, escenas, voz, música y video) sin publicarlo.
    Devuelve None si algo falla."""
    d = _datos_oferta(oferta)
    gancho = elegir_gancho(d)
    guion = construir_guion(d, gancho)
    print(f"[REEL] Gancho ({gancho['formula']}, {gancho['puntaje']}): {gancho['hablado']}")
    print(f"[REEL] Guion: {guion['voz']}")

    ruta_voz = os.path.join(carpeta, "voz.mp3")
    ruta_mus = os.path.join(carpeta, "musica.mp3")
    ruta_mp4 = ruta_mp4 or os.path.join(carpeta, "reel.mp4")

    try:
        rutas_escenas = crear_escenas(d, gancho, oferta, carpeta)
    except Exception as e:
        print(f"[REEL] Error creando escenas: {type(e).__name__}")
        return None

    try:
        duracion_voz = generar_audio_voz(guion["voz"], ruta_voz)
    except Exception as e:
        print(f"[REEL] Error generando voz: {type(e).__name__}")
        return None

    musica = descargar_musica_automatica(ruta_mus)
    duraciones = calcular_duraciones(guion["beats"], duracion_voz)
    print(f"[REEL] Escenas (segundos): {duraciones}")

    if not renderizar_video_mp4(rutas_escenas, duraciones, ruta_voz, musica, ruta_mp4):
        return None

    return {
        "ruta_mp4": ruta_mp4,
        "caption": armar_caption_reel(oferta, d),
        "datos": d,
        "gancho": gancho,
    }


def publicar_reel_en_instagram(oferta: dict) -> bool:
    ig_user_id = os.getenv("IG_USER_ID", "")
    access_token = os.getenv("IG_ACCESS_TOKEN", "")
    if not ig_user_id or not access_token:
        return False

    with tempfile.TemporaryDirectory() as tmpdir:
        reel = preparar_reel(oferta, tmpdir)
        if not reel:
            return False

        for intento in range(2):
            try:
                media_id = _subir_y_publicar_reel(ig_user_id, access_token, reel["ruta_mp4"], reel["caption"])
                if media_id:
                    registrar_reel_log(oferta, reel["datos"], reel["gancho"], media_id)
                    return True
            except Exception as e:
                print(f"[REEL] Excepción al subir/publicar (intento {intento + 1}): {type(e).__name__}")
            if intento == 0:
                time.sleep(3)

        return False


if __name__ == "__main__":
    # Vista previa local, sin publicar nada: python reel_publisher.py
    demo = {
        "titulo": "Audífonos Inalámbricos Bluetooth Xiaomi Redmi Buds 6 Play",
        "precio": "$399",
        "precio_anterior": "$599",
        "descuento": "33% OFF",
        "nicho": "tecnologia",
        "imagen": "",
        "mlm_id": "",
    }
    with tempfile.TemporaryDirectory() as tmp:
        resultado = preparar_reel(demo, tmp, "prueba_reel.mp4")
    if resultado:
        print("Listo: se guardó prueba_reel.mp4")
        print(resultado["caption"])
    else:
        print("No se pudo armar el Reel de prueba.")
