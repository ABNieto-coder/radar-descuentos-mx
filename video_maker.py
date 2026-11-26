import asyncio
import html
import json
import os
import re
import subprocess
import tempfile
from io import BytesIO

import edge_tts
import requests
from google import genai
from PIL import Image, ImageDraw, ImageFont

VOICE = "es-MX-JorgeNeural"
WIDTH, HEIGHT = 1080, 1920
FPS = 30
CANAL_TELEGRAM = "@RadarDescuentosMX247"


def _limpiar_prohibidas(texto: str) -> str:
    limpio = html.unescape(texto or "")
    limpio = re.sub(r"\bcuradur[íi]a\b", "selección", limpio, flags=re.IGNORECASE)
    limpio = re.sub(r"\bcorre\b", "entra", limpio, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", limpio).strip()


def _limpiar_voz(texto: str) -> str:
    limpio = _limpiar_prohibidas(texto)
    limpio = limpio.replace("$", " pesos ")
    limpio = limpio.replace("%", " por ciento ")
    limpio = re.sub(r"[^\w\sáéíóúüñÁÉÍÓÚÜÑ.,!?-]", " ", limpio)
    return re.sub(r"\s+", " ", limpio).strip()


def _respaldo_guion(oferta: dict) -> dict:
    titulo = _limpiar_prohibidas(str(oferta.get("titulo") or "Producto en Mercado Libre"))
    precio_actual = str(oferta.get("precio_actual") or "").strip()
    descuento = str(oferta.get("descuento") or "").strip()

    gancho = "PRECIO ACCESIBLE ML"
    if descuento:
        gancho = f"AHORRA {descuento}% EN ML"[:28]

    locucion = _limpiar_voz(
        f"Buen precio en Mercado Libre para {titulo[:45]}"
        + (f" a {precio_actual} pesos." if precio_actual else ".")
        + " Revisa el enlace en la bio y guárdalo."
    )

    lineas_cap = [f"Precio accesible en Mercado Libre — {titulo}"]
    if precio_actual:
        lineas_cap.append(f"Precio: ${precio_actual} MXN" + (f" ({descuento}% desc.)" if descuento else ""))
    lineas_cap.extend([
        f"Enlace en la bio y más opciones en Telegram ({CANAL_TELEGRAM}).",
        "Guarda este video para consultarlo después.",
        "#MercadoLibre #OfertasMexico #DescuentosMX #ComprasInteligentes #RadarDeDescuentosMX",
    ])
    return {
        "gancho": gancho,
        "locucion": locucion,
        "caption": _limpiar_prohibidas("\n".join(lineas_cap)),
    }


def generar_guion(oferta: dict) -> dict:
    respaldo = _respaldo_guion(oferta)
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return respaldo

    client = genai.Client(api_key=api_key)
    prompt = f"""
    Genera un JSON estricto (sin markdown) para un video vertical de 12 a 15 segundos sobre una oferta de precio accesible en Mercado Libre México.
    Tono sobrio, seguro, claro y confiable (sin gritos, sin exageraciones y sin usar la palabra curaduría ni la palabra corre).
    Datos:
    - Producto: {_limpiar_prohibidas(str(oferta.get('titulo') or ''))}
    - Precio actual: ${oferta.get('precio_actual', '')} MXN
    - Precio anterior: ${oferta.get('precio_anterior', '')} MXN
    - Descuento: {oferta.get('descuento', '')}%

    Formato JSON requerido:
    {{
      "gancho": "Texto corto en mayúsculas de máximo 5 palabras para portada",
      "locucion": "Guion natural de 16 a 22 palabras en español de México mencionando Mercado Libre, el precio accesible y el enlace en la bio o Telegram",
      "caption": "Descripción corta con precio, descuento, mención a Mercado Libre y 5 hashtags relevantes en México"
    }}
    """
    try:
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        texto = (resp.text or "").strip().removeprefix("```json").removesuffix("```").strip()
        data = json.loads(texto)
        gancho = _limpiar_prohibidas(str(data.get("gancho") or respaldo["gancho"])).upper()[:28]
        locucion = _limpiar_voz(str(data.get("locucion") or respaldo["locucion"]))
        caption = _limpiar_prohibidas(str(data.get("caption") or respaldo["caption"]))
        if len(locucion) < 15:
            locucion = respaldo["locucion"]
        return {"gancho": gancho, "locucion": locucion, "caption": caption}
    except Exception as e:
        print(f"[VIDEOMAKER] Aviso generando guion con Gemini (usando respaldo): {e}")
        return respaldo


def crear_imagen_base(oferta: dict, gancho: str, ruta_salida: str) -> bool:
    canvas = Image.new("RGB", (WIDTH, HEIGHT), (12, 16, 26))
    draw = ImageDraw.Draw(canvas)

    card_margin = 88
    card_top, card_bottom = 350, 1260
    draw.rounded_rectangle(
        [card_margin, card_top, WIDTH - card_margin, card_bottom],
        radius=44,
        fill=(255, 255, 255),
    )

    img_url = (oferta.get("imagen_url") or "").strip()
    if img_url:
        try:
            resp = requests.get(img_url, timeout=15)
            resp.raise_for_status()
            prod = Image.open(BytesIO(resp.content)).convert("RGBA")
            prod.thumbnail((780, 780), Image.Resampling.LANCZOS)
            px = (WIDTH - prod.width) // 2
            py = card_top + (card_bottom - card_top - prod.height) // 2
            canvas.paste(prod, (px, py), prod)
        except Exception as e:
            print(f"[VIDEOMAKER] Aviso descargando imagen de producto: {e}")

    try:
        font_big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 66)
        font_med = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 38)
    except OSError:
        font_big = font_med = font_sm = ImageFont.load_default()

    draw.rounded_rectangle([88, 165, WIDTH - 88, 300], radius=30, fill=(20, 32, 52), outline=(16, 185, 129), width=3)
    draw.text((WIDTH // 2, 232), _limpiar_prohibidas(gancho)[:28], fill=(255, 255, 255), font=font_med, anchor="mm")

    descuento = str(oferta.get("descuento") or "").strip()
    if descuento:
        badge = f"-{descuento}% ML"
        draw.rounded_rectangle([WIDTH - 390, 380, WIDTH - 120, 468], radius=22, fill=(16, 185, 129))
        draw.text((WIDTH - 255, 424), badge, fill=(255, 255, 255), font=font_sm, anchor="mm")

    precio_anterior = str(oferta.get("precio_anterior") or "").strip()
    precio_actual = str(oferta.get("precio_actual") or "").strip()

    if precio_anterior:
        draw.text(
            (WIDTH // 2, 1345),
            f"Antes: ${precio_anterior} MXN",
            fill=(148, 163, 184),
            font=font_sm,
            anchor="mm",
        )
    if precio_actual:
        draw.text(
            (WIDTH // 2, 1435),
            f"AHORA: ${precio_actual} MXN",
            fill=(250, 204, 21),
            font=font_big,
            anchor="mm",
        )

    draw.text(
        (WIDTH // 2, 1740),
        f"Enlace en bio  •  Telegram {CANAL_TELEGRAM}",
        fill=(226, 232, 240),
        font=font_sm,
        anchor="mm",
    )

    canvas.save(ruta_salida, format="PNG")
    return os.path.exists(ruta_salida) and os.path.getsize(ruta_salida) > 0


async def _generar_voz_y_srt(texto: str, audio_out: str, srt_out: str):
    communicate = edge_tts.Communicate(texto, VOICE, rate="+3%")
    submaker = edge_tts.SubMaker()
    with open(audio_out, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                submaker.feed(chunk)
    with open(srt_out, "w", encoding="utf-8") as f:
        f.write(submaker.get_srt() or "")


def _duracion_audio_seg(ruta_audio: str) -> float:
    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                ruta_audio,
            ],
            text=True,
            timeout=10,
        ).strip()
        val = float(out)
        if val > 0:
            return val
    except Exception as e:
        print(f"[VIDEOMAKER] Aviso obteniendo duración con ffprobe: {e}")
    return 10.0


def crear_video_oferta(oferta: dict, salida_mp4: str = "oferta.mp4") -> dict:
    guion = generar_guion(oferta)

    with tempfile.TemporaryDirectory() as tmpdir:
        ruta_img = os.path.join(tmpdir, "frame.png")
        ruta_voz = os.path.join(tmpdir, "voz.mp3")
        ruta_srt = os.path.join(tmpdir, "subs.srt")

        if not crear_imagen_base(oferta, guion["gancho"], ruta_img):
            raise RuntimeError("No se pudo crear la imagen base del video.")

        asyncio.run(_generar_voz_y_srt(guion["locucion"], ruta_voz, ruta_srt))
        if not os.path.exists(ruta_voz) or os.path.getsize(ruta_voz) == 0:
            raise RuntimeError("Edge-TTS no generó audio válido.")

        duracion_total = max(8.0, min(16.5, round(_duracion_audio_seg(ruta_voz) + 1.5, 2)))
        total_frames = max(1, int(duracion_total * FPS))
        denom = max(1, total_frames - 1)

        filtros = [
            f"scale=2160:3840:flags=lanczos",
            f"zoompan=z='1.0+0.035*(1-cos(PI*on/{denom}))/2':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={total_frames}:s={WIDTH}x{HEIGHT}:fps={FPS}",
        ]
        if os.path.exists(ruta_srt) and os.path.getsize(ruta_srt) > 0:
            ruta_srt_escapada = ruta_srt.replace("\\", "/").replace(":", "\\:")
            filtros.append(
                f"subtitles='{ruta_srt_escapada}':force_style='FontName=DejaVu Sans,FontSize=16,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=3,Outline=2,Alignment=2,MarginV=190'"
            )

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", ruta_img,
            "-i", ruta_voz,
            "-filter_complex", f"[0:v]{','.join(filtros)},format=yuv420p[vout]",
            "-map", "[vout]", "-map", "1:a",
            "-t", str(duracion_total),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            salida_mp4,
        ]
        subprocess.run(cmd, check=True)

    return {"video_path": salida_mp4, "caption": guion["caption"]}


def subir_mp4_publico(ruta_mp4: str) -> str:
    """Sube el MP4 a hosting temporal para obtener URL pública."""
    with open(ruta_mp4, "rb") as f:
        resp = requests.post(
            "https://catbox.moe/user/api.php",
            data={"reqtype": "fileupload"},
            files={"fileToUpload": f},
            timeout=60,
        )
    resp.raise_for_status()
    return resp.text.strip()
