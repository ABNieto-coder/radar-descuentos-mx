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
FPS = 25

VOCES_MX = ["es-MX-DaliaNeural", "es-MX-JorgeNeural"]
BUSQUEDAS_MUSICA = [
    "upbeat corporate background loop",
    "lofi chill beat loop",
    "modern tech background music",
    "happy electronic loop",
]

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


def generar_guion_voz(oferta: dict) -> str:
    """Usa Gemini para redactar un guion corto en español mexicano."""
    titulo = html.unescape((oferta.get("titulo") or "").strip())
    precio = (oferta.get("precio") or "").strip()
    descuento = (oferta.get("descuento") or "").strip()

    respaldo = (
        f"Checa esta oferta en Mercado Libre: {titulo[:70]}. "
        f"{f'A solo {precio}. ' if precio else ''}"
        f"Encuentra el enlace directo en nuestra biografía."
    )

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return respaldo

    prompt = (
        "Escribe un guion muy corto (máximo 22 palabras) para un Reel de ofertas en español de México, "
        "tono dinámico y natural, sin emojis, sin asteriscos y sin comillas. "
        "Menciona el producto, el precio/descuento si existe, y cierra invitando al link en la bio.\n"
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
            texto = res.json()["candidates"][0]["content"]["parts"][0]["text"]
            limpio = re.sub(r"[*_#\"`]", "", texto).strip()
            if 10 < len(limpio) < 260:
                return limpio
    except Exception as e:
        print(f"[REEL] Aviso Gemini (usando guion de respaldo): {e}")

    return respaldo


async def _sintetizar_voz(texto: str, ruta_salida: str, voz: str):
    communicate = edge_tts.Communicate(texto, voz, rate="+6%")
    await communicate.save(ruta_salida)


def generar_audio_voz(guion: str, ruta_voz: str) -> float:
    """Genera el MP3 de voz con Edge-TTS y devuelve su duración en segundos."""
    voz = random.choice(VOCES_MX)
    asyncio.run(_sintetizar_voz(guion, ruta_voz, voz))

    probe = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            ruta_voz,
        ],
        capture_output=True,
        text=True,
    )
    try:
        return float(probe.stdout.strip())
    except Exception:
        return 7.0


def descargar_musica_automatica(ruta_musica: str) -> str:
    """Busca y descarga una pista libre de derechos desde Freesound (o usa assets/*.mp3)."""
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
                        return ruta_musica
        except Exception as e:
            print(f"[REEL] Aviso Freesound: {e}")

    locales = glob.glob("assets/*.mp3")
    return random.choice(locales) if locales else ""


def crear_imagen_reel(oferta: dict, ruta_salida: str) -> bool:
    """Genera un lienzo 1080x1920 con tarjeta del producto, precio y CTA."""
    ancho, alto = 1080, 1920
    img_url = normalizar_imagen_ml(oferta.get("imagen", ""))
    if not img_url:
        return False

    try:
        resp = requests.get(img_url, timeout=20)
        resp.raise_for_status()
        prod_img = Image.open(BytesIO(resp.content)).convert("RGBA")
    except Exception as e:
        print(f"[REEL] No se pudo descargar la imagen del producto: {e}")
        return False

    canvas = Image.new("RGB", (ancho, alto), (15, 23, 42))
    draw = ImageDraw.Draw(canvas)

    draw.rounded_rectangle([140, 130, 940, 235], radius=45, fill=(239, 68, 68))
    f_badge = cargar_fuente(FONT_BOLD_PATHS, 46)
    draw.text((ancho // 2, 182), "OFERTA DETECTADA", fill=(255, 255, 255), font=f_badge, anchor="mm")

    card_x1, card_y1, card_x2, card_y2 = 90, 290, 990, 1110
    draw.rounded_rectangle([card_x1, card_y1, card_x2, card_y2], radius=40, fill=(255, 255, 255))

    max_w = (card_x2 - card_x1) - 80
    max_h = (card_y2 - card_y1) - 80
    prod_img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)

    px = card_x1 + ((card_x2 - card_x1) - prod_img.width) // 2
    py = card_y1 + ((card_y2 - card_y1) - prod_img.height) // 2
    canvas.paste(prod_img, (px, py), prod_img)

    descuento = (oferta.get("descuento") or "").strip().upper()
    if descuento:
        draw.rounded_rectangle([720, 260, 1010, 350], radius=30, fill=(250, 204, 21))
        f_dto = cargar_fuente(FONT_BOLD_PATHS, 42)
        draw.text((865, 305), descuento[:12], fill=(15, 23, 42), font=f_dto, anchor="mm")

    titulo = html.unescape((oferta.get("titulo") or "").strip())
    lineas_titulo = textwrap.wrap(titulo, width=28)[:3]
    f_titulo = cargar_fuente(FONT_BOLD_PATHS, 50)
    y_cursor = 1175
    for linea in lineas_titulo:
        draw.text((ancho // 2, y_cursor), linea, fill=(248, 250, 252), font=f_titulo, anchor="mm")
        y_cursor += 64

    precio = (oferta.get("precio") or "").strip()
    if precio:
        draw.rounded_rectangle([190, 1405, 890, 1545], radius=35, fill=(34, 197, 94))
        f_precio = cargar_fuente(FONT_BOLD_PATHS, 76)
        draw.text((ancho // 2, 1475), precio, fill=(15, 23, 42), font=f_precio, anchor="mm")

    f_cta = cargar_fuente(FONT_BOLD_PATHS, 40)
    f_sub = cargar_fuente(FONT_REG_PATHS, 34)
    draw.text((ancho // 2, 1630), "LINK DIRECTO EN NUESTRA BIO", fill=(250, 204, 21), font=f_cta, anchor="mm")
    draw.text((ancho // 2, 1690), f"Telegram: {CANAL_TELEGRAM}", fill=(148, 163, 184), font=f_sub, anchor="mm")

    canvas.save(ruta_salida, format="PNG")
    return True


def renderizar_video_mp4(ruta_imagen: str, ruta_voz: str, ruta_musica: str, duracion: float, ruta_video: str) -> bool:
    """Combina imagen 9:16 con zoom suave + voz en primer plano + música de fondo al 14%."""
    duracion = max(6.0, min(15.0, round(duracion + 1.2, 2)))
    total_frames = int(duracion * FPS)
    fade_out_v = max(0.5, round(duracion - 0.5, 2))
    fade_out_a = max(0.5, round(duracion - 1.0, 2))

    filtro_video = (
        f"[0:v]zoompan=z='min(zoom+0.0005,1.06)'"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={total_frames}:s=1080x1920:fps={FPS},"
        f"fade=t=in:st=0:d=0.35,"
        f"fade=t=out:st={fade_out_v}:d=0.5,"
        f"format=yuv420p[vout]"
    )

    if ruta_musica and os.path.exists(ruta_musica):
        filtro_audio = (
            f"[1:a]adelay=300|300,volume=1.0[voz];"
            f"[2:a]volume=0.14,afade=t=in:st=0:d=0.4,afade=t=out:st={fade_out_a}:d=1.0[mus];"
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
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
            "-movflags", "+faststart",
            ruta_video,
        ]
    else:
        filtro_audio = "[1:a]adelay=300|300,apad,volume=1.0[aout]"
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", ruta_imagen,
            "-i", ruta_voz,
            "-filter_complex", f"{filtro_video};{filtro_audio}",
            "-map", "[vout]", "-map", "[aout]",
            "-t", str(duracion),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
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
    lineas = ["🚨 ¡OFERTA DETECTADA! 🚨", "", f"📦 {titulo}", ""]

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
        f"🔗 Link directo de compra en el enlace de nuestra bio (Telegram {CANAL_TELEGRAM}).",
        "⚠️ Los precios y disponibilidad pueden cambiar en cualquier momento.",
        "",
        "#OfertasMexico #DescuentosMX #MercadoLibre #Promociones #RadarDeDescuentosMX",
    ])
    return "\n".join(lineas)


def publicar_reel_en_instagram(oferta: dict) -> bool:
    """Genera el Reel 9:16 con voz y música automática y lo sube a Meta Graph API."""
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
        file_size = os.path.getsize(ruta_mp4)

        try:
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
                        "offset": "0",
                        "file_size": str(file_size),
                    },
                    data=f_video,
                    timeout=120,
                )
            data_up = res_up.json()
            if not res_up.ok or data_up.get("success") is False:
                print(f"[REEL] Error subiendo video: {data_up}")
                return False

            for _ in range(20):
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

        except Exception as e:
            print(f"[REEL] Excepción inesperada: {e}")
            return False
  
