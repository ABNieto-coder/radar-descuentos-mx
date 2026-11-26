import asyncio
import glob
import html
import os
import random
import re
import subprocess
import tempfile
import textwrap
import time
from io import BytesIO

import edge_tts
import requests
from PIL import Image, ImageDraw, ImageFont

IG_API_VERSION = "v27.0"
CANAL_TELEGRAM = "@RadarDescuentosMX247"
FPS = 30

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


def cargar_fuente(rutas, tamano):
    for ruta in rutas:
        if os.path.exists(ruta):
            return ImageFont.truetype(ruta, tamano)
    return ImageFont.load_default()


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
        print(f"[REEL] Aviso consultando API ML para {mlm_id}: {e}")
    return ""


def descargar_imagen_producto(oferta: dict) -> Image.Image | None:
    candidatas = []
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
            if img.width >= 80 and img.height >= 80:
                return img
        except Exception as e:
            print(f"[REEL] Aviso descargando imagen ({url}): {e}")

    return None


def limpiar_texto_para_voz(texto: str) -> str:
    limpio = html.unescape(texto or "")
    limpio = re.sub(r"https?://\S+", "", limpio)
    limpio = limpio.replace("$", " pesos ")
    limpio = limpio.replace("%", " por ciento ")
    limpio = re.sub(r"[*_#~`\"“”‘’\[\]<>|]+", " ", limpio)
    limpio = re.sub(r"\s+", " ", limpio).strip()
    return limpio


def generar_guion_voz(oferta: dict) -> str:
    titulo = html.unescape((oferta.get("titulo") or "").strip())
    precio = (oferta.get("precio") or "").strip()
    descuento = (oferta.get("descuento") or "").strip()

    gancho = f"¡Ojo a esta oferta en {titulo[:55]}!"
    if descuento:
        gancho = f"¡{descuento} en {titulo[:50]}!"
    respaldo = limpiar_texto_para_voz(
        f"{gancho} {f'Queda en {precio}. ' if precio else ''}Corre al link de la bio y guárdalo."
    )

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return respaldo

    prompt = (
        "Escribe un guion corto de 18 a 24 palabras en español de México para un Reel de ofertas. "
        "Arranca en el segundo 0 con un gancho fuerte y directo (sin saludos ni rodeos). "
        "Menciona el producto, el precio o descuento si está disponible, e invita a ir al enlace de la bio y guardar el Reel. "
        "Devuelve solo el texto a locutar, sin emojis, sin asteriscos y sin comillas.\n"
        f"Producto: {titulo}\n"
        f"Precio: {precio or 'no especificado'}\n"
        f"Descuento: {descuento or 'no especificado'}"
    )

    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        res = requests.post(
            url,
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=15,
        )
        if res.ok:
            candidatos = res.json().get("candidates") or []
            if candidatos:
                partes = candidatos[0].get("content", {}).get("parts") or []
                if partes and partes[0].get("text"):
                    limpio = limpiar_texto_para_voz(partes[0]["text"])
                    if 15 <= len(limpio) <= 280:
                        return limpio
    except Exception as e:
        print(f"[REEL] Aviso Gemini (usando respaldo): {e}")

    return respaldo


async def _sintetizar_voz(texto: str, ruta_salida: str, voz: str):
    communicate = edge_tts.Communicate(texto, voz, rate="+8%")
    await communicate.save(ruta_salida)


def generar_audio_voz(guion: str, ruta_voz: str) -> float:
    asyncio.run(_sintetizar_voz(guion, ruta_voz, VOZ_CHICO_MX))

    if not os.path.exists(ruta_voz) or os.path.getsize(ruta_voz) == 0:
        raise RuntimeError("Edge-TTS no generó archivo de audio válido.")

    chars_utiles = max(len(guion or ""), 45)
    duracion_estimada = round(chars_utiles / 13.5, 2)
    return max(6.5, min(13.5, duracion_estimada))


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
                    "token": api_key,
                },
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
                        print(f"[REEL] Música alegre descargada desde Freesound ({query}).")
                        return ruta_musica
        except Exception as e:
            print(f"[REEL] Aviso Freesound: {e}")

    locales = glob.glob("assets/*.mp3")
    if locales:
        elegida = random.choice(locales)
        print(f"[REEL] Usando pista local: {elegida}")
        return elegida

    print("[REEL] Aviso: sin pista de música disponible, se publicará con voz y audio base.")
    return ""


def crear_imagen_reel(oferta: dict, ruta_salida: str) -> bool:
    ancho, alto = 1080, 1920
    canvas = Image.new("RGB", (ancho, alto), (15, 23, 42))
    draw = ImageDraw.Draw(canvas)

    descuento = (oferta.get("descuento") or "").strip().upper()
    precio = (oferta.get("precio") or "").strip()
    titulo = html.unescape((oferta.get("titulo") or "").strip())

    texto_badge = f"OFERTA {descuento}" if descuento else "OFERTA DETECTADA"
    draw.rounded_rectangle([120, 120, 960, 225], radius=45, fill=(239, 68, 68))
    f_badge = cargar_fuente(FONT_BOLD_PATHS, 44)
    draw.text((ancho // 2, 172), texto_badge[:24], fill=(255, 255, 255), font=f_badge, anchor="mm")

    card_x1, card_y1, card_x2, card_y2 = 100, 275, 980, 1055
    draw.rounded_rectangle([card_x1, card_y1, card_x2, card_y2], radius=40, fill=(255, 255, 255))

    prod_img = descargar_imagen_producto(oferta)
    if prod_img is not None:
        max_w = (card_x2 - card_x1) - 60
        max_h = (card_y2 - card_y1) - 60
        prod_img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)

        px = card_x1 + ((card_x2 - card_x1) - prod_img.width) // 2
        py = card_y1 + ((card_y2 - card_y1) - prod_img.height) // 2
        canvas.paste(prod_img, (px, py), prod_img)
    else:
        print("[REEL] Fallback visual activado: sin foto real descargable.")
        centro_x = (card_x1 + card_x2) // 2
        f_fb_marca = cargar_fuente(FONT_BOLD_PATHS, 42)
        f_fb_prod = cargar_fuente(FONT_BOLD_PATHS, 44)
        f_fb_precio = cargar_fuente(FONT_BOLD_PATHS, 56)

        draw.text((centro_x, card_y1 + 120), "MERCADO LIBRE MX", fill=(30, 41, 59), font=f_fb_marca, anchor="mm")
        lineas_fb = textwrap.wrap(titulo, width=24)[:3]
        y_fb = card_y1 + 240
        for linea_fb in lineas_fb:
            draw.text((centro_x, y_fb), linea_fb, fill=(15, 23, 42), font=f_fb_prod, anchor="mm")
            y_fb += 56
        if precio:
            draw.text((centro_x, card_y1 + 520), precio, fill=(22, 163, 74), font=f_fb_precio, anchor="mm")
        if descuento:
            draw.text((centro_x, card_y1 + 610), descuento, fill=(220, 38, 38), font=f_fb_marca, anchor="mm")

    lineas_titulo = textwrap.wrap(titulo, width=28)[:3]
    f_titulo = cargar_fuente(FONT_BOLD_PATHS, 48)
    y_cursor = 1125
    for linea in lineas_titulo:
        draw.text((ancho // 2, y_cursor), linea, fill=(248, 250, 252), font=f_titulo, anchor="mm")
        y_cursor += 60

    if precio:
        draw.rounded_rectangle([180, 1340, 900, 1475], radius=35, fill=(34, 197, 94))
        f_precio = cargar_fuente(FONT_BOLD_PATHS, 72)
        draw.text((ancho // 2, 1407), precio, fill=(15, 23, 42), font=f_precio, anchor="mm")

    f_cta = cargar_fuente(FONT_BOLD_PATHS, 38)
    f_sub = cargar_fuente(FONT_REG_PATHS, 32)
    draw.text((ancho // 2, 1555), "LINK DIRECTO EN NUESTRA BIO", fill=(250, 204, 21), font=f_cta, anchor="mm")
    draw.text((ancho // 2, 1610), f"Telegram: {CANAL_TELEGRAM}", fill=(148, 163, 184), font=f_sub, anchor="mm")

    canvas.save(ruta_salida, format="PNG")
    return True


def renderizar_video_mp4(ruta_imagen: str, ruta_voz: str, ruta_musica: str, duracion: float, ruta_video: str) -> bool:
    duracion = max(6.5, min(14.0, round(duracion + 1.0, 2)))
    total_frames = max(1, int(duracion * FPS))
    denom = max(1, total_frames - 1)
    fade_out_v = max(0.5, round(duracion - 0.45, 2))
    fade_out_a = max(0.5, round(duracion - 0.9, 2))

    filtro_video = (
        f"[0:v]scale=2160:3840:flags=lanczos,"
        f"zoompan=z='1.0+0.04*(1-cos(PI*on/{denom}))/2'"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={total_frames}:s=1080x1920:fps={FPS},"
        f"fade=t=in:st=0:d=0.35,"
        f"fade=t=out:st={fade_out_v}:d=0.45,"
        f"format=yuv420p[vout]"
    )

    if ruta_musica and os.path.exists(ruta_musica):
        filtro_audio = (
            f"[1:a]adelay=250|250,volume=1.05[voz];"
            f"[2:a]volume=0.14,afade=t=in:st=0:d=0.4,afade=t=out:st={fade_out_a}:d=0.9[mus];"
            f"[voz][mus]amix=inputs=2:duration=longest:normalize=0[aout]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", ruta_imagen,
            "-i", ruta_voz,
            "-stream_loop", "-1", "-i", ruta_musica,
            "-filter_complex", f"{filtro_video};{filtro_audio}",
            "-map", "[vout]", "-map", "[aout]",
            "-t", str(duracion),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-g", "60",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
            "-movflags", "+faststart",
            ruta_video,
        ]
    else:
        filtro_audio = "[1:a]adelay=250|250,apad,volume=1.05[aout]"
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", ruta_imagen,
            "-i", ruta_voz,
            "-filter_complex", f"{filtro_video};{filtro_audio}",
            "-map", "[vout]", "-map", "[aout]",
            "-t", str(duracion),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-g", "60",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
            "-movflags", "+faststart",
            ruta_video,
        ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[REEL] Error en FFmpeg: {res.stderr[-500:]}")
        return False
    return os.path.exists(ruta_video) and os.path.getsize(ruta_video) > 0


def armar_caption_reel(oferta: dict) -> str:
    titulo = html.unescape((oferta.get("titulo") or "").strip())
    lineas = ["🔥 ¡OFERTA DETECTADA! 🚨", "", f"📦 {titulo}", ""]

    detalle = []
    if oferta.get("precio"):
        detalle.append(f"💰 Precio: {oferta['precio']}")
    if oferta.get("descuento"):
        detalle.append(f"🏷️ Ahorro: {oferta['descuento']}")
    if detalle:
        lineas.append(" | ".join(detalle))
        lineas.append("")

    lineas.extend([
        "🛒 Tienda: Mercado Libre México",
        f"🔗 Enlace directo en nuestra bio y más ofertas en Telegram ({CANAL_TELEGRAM}).",
        "🔖 Guarda este Reel y mándaselo a quien ande buscando algo así.",
        "⚠️ Precios y stock sujetos a cambios.",
        "",
        "#OfertasMexico #DescuentosMX #MercadoLibre #Promociones #RadarDeDescuentosMX",
    ])
    return "\n".join(lineas)


def _subir_y_publicar_reel(ig_user_id: str, access_token: str, ruta_mp4: str, caption: str) -> bool:
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
        print(f"[REEL] Error iniciando contenedor: {data_init}")
        return False

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
        data_up = {"raw": res_up.text[:300]}

    if not res_up.ok or data_up.get("success") is False:
        print(f"[REEL] Error subiendo video (HTTP {res_up.status_code}): {data_up}")
        return False

    for _ in range(24):
        time.sleep(5)
        res_st = requests.get(
            f"https://graph.facebook.com/{IG_API_VERSION}/{creation_id}",
            params={"fields": "status_code,status", "access_token": access_token},
            timeout=20,
        )
        status_data = res_st.json()
        status_code = status_data.get("status_code")

        if status_code == "FINISHED":
            break
        if status_code in ("ERROR", "EXPIRED"):
            print(f"[REEL] Meta rechazó el video: {status_data}")
            return False
    else:
        print("[REEL] Tiempo agotado esperando procesamiento de Meta.")
        return False

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
        print(f"[REEL] Error publicando Reel: {data_pub}")
        return False

    print(f"[REEL] ¡Reel publicado con éxito! ID: {data_pub['id']}")
    return True


def publicar_reel_en_instagram(oferta: dict) -> bool:
    ig_user_id = os.getenv("IG_USER_ID", "")
    access_token = os.getenv("IG_ACCESS_TOKEN", "")
    if not ig_user_id or not access_token:
        return False

    with tempfile.TemporaryDirectory() as tmpdir:
        ruta_img = os.path.join(tmpdir, "frame.png")
        ruta_voz = os.path.join(tmpdir, "voz.mp3")
        ruta_mus = os.path.join(tmpdir, "musica.mp3")
        ruta_mp4 = os.path.join(tmpdir, "reel.mp4")

        if not crear_imagen_reel(oferta, ruta_img):
            return False

        try:
            guion = generar_guion_voz(oferta)
            duracion_voz = generar_audio_voz(guion, ruta_voz)
        except Exception as e:
            print(f"[REEL] Error generando voz: {e}")
            return False

        musica_lista = descargar_musica_automatica(ruta_mus)

        if not renderizar_video_mp4(ruta_img, ruta_voz, musica_lista, duracion_voz, ruta_mp4):
            return False

        caption = armar_caption_reel(oferta)

        for intento in range(2):
            try:
                if _subir_y_publicar_reel(ig_user_id, access_token, ruta_mp4, caption):
                    return True
            except Exception as e:
                print(f"[REEL] Excepción al subir/publicar (intento {intento + 1}): {e}")
            if intento == 0:
                time.sleep(3)

        return False
        
