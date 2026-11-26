import asyncio
import json
import os
import subprocess
from io import BytesIO

import edge_tts
import requests
from google import genai
from PIL import Image, ImageDraw, ImageFont

VOICE = "es-MX-DaliaNeural"  # O "es-MX-JorgeNeural"
WIDTH, HEIGHT = 1080, 1920


def generar_guion(oferta: dict) -> dict:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prompt = f"""
    Eres creador de contenido viral de ofertas en México.
    Genera un JSON estricto (sin markdown) para un video corto de 12-15 segundos sobre esta oferta:
    - Producto: {oferta['titulo']}
    - Precio actual: ${oferta['precio_actual']} MXN
    - Precio anterior: ${oferta['precio_anterior']} MXN
    - Descuento: {oferta['descuento']}%

    Formato JSON requerido:
    {{
      "gancho": "Texto corto en mayúsculas de máximo 5 palabras para portada",
      "locucion": "Guion natural de 25 a 32 palabras en español de México invitando a revisar el link en la bio o canal de Telegram",
      "caption": "Descripción corta con precio, descuento y 5 hashtags relevantes en México"
    }}
    """
    resp = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    texto = resp.text.strip().removeprefix("```json").removesuffix("```").strip()
    return json.loads(texto)


def crear_imagen_base(oferta: dict, gancho: str, ruta_salida: str = "frame.png"):
    # Fondo oscuro estilo radar tech
    canvas = Image.new("RGB", (WIDTH, HEIGHT), (15, 18, 28))
    draw = ImageDraw.Draw(canvas)

    # Tarjeta blanca central para el producto
    card_margin = 90
    card_top, card_bottom = 360, 1280
    draw.rounded_rectangle(
        [card_margin, card_top, WIDTH - card_margin, card_bottom],
        radius=45,
        fill=(255, 255, 255),
    )

    # Descargar y centrar imagen del producto
    img_bytes = requests.get(oferta["imagen_url"], timeout=15).content
    prod = Image.open(BytesIO(img_bytes)).convert("RGBA")
    prod.thumbnail((760, 760), Image.Resampling.LANCZOS)
    px = (WIDTH - prod.width) // 2
    py = card_top + (card_bottom - card_top - prod.height) // 2
    canvas.paste(prod, (px, py), prod)

    try:
        font_big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 68)
        font_med = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 52)
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 40)
    except OSError:
        font_big = font_med = font_sm = ImageFont.load_default()

    # Etiqueta superior (Gancho)
    draw.rounded_rectangle([90, 170, WIDTH - 90, 310], radius=30, fill=(255, 59, 48))
    draw.text((WIDTH // 2, 240), gancho[:28], fill=(255, 255, 255), font=font_med, anchor="mm")

    # Badge de descuento
    badge = f"-{oferta['descuento']}% OFF"
    draw.rounded_rectangle([WIDTH - 390, 390, WIDTH - 120, 480], radius=22, fill=(16, 185, 129))
    draw.text((WIDTH - 255, 435), badge, fill=(255, 255, 255), font=font_sm, anchor="mm")

    # Precios abajo de la tarjeta
    draw.text(
        (WIDTH // 2, 1370),
        f"Antes: ${oferta['precio_anterior']} MXN",
        fill=(160, 170, 190),
        font=font_sm,
        anchor="mm",
    )
    draw.text(
        (WIDTH // 2, 1460),
        f"AHORA: ${oferta['precio_actual']} MXN",
        fill=(250, 204, 21),
        font=font_big,
        anchor="mm",
    )
    draw.text(
        (WIDTH // 2, 1760),
        "Link directo en el perfil / @RadarDescuentosMX247",
        fill=(220, 225, 235),
        font=font_sm,
        anchor="mm",
    )

    canvas.save(ruta_salida)


async def _generar_voz_y_srt(texto: str, audio_out: str, srt_out: str):
    communicate = edge_tts.Communicate(texto, VOICE, rate="+8%")
    submaker = edge_tts.SubMaker()
    with open(audio_out, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                submaker.feed(chunk)
    with open(srt_out, "w", encoding="utf-8") as f:
        f.write(submaker.get_srt())


def crear_video_oferta(oferta: dict, salida_mp4: str = "oferta.mp4") -> dict:
    guion = generar_guion(oferta)
    crear_imagen_base(oferta, guion["gancho"], "frame.png")
    asyncio.run(_generar_voz_y_srt(guion["locucion"], "voz.mp3", "subs.srt"))

    # Renderizar con zoom suave (Ken Burns) + subtítulos quemados
    filtro_video = (
        "scale=1080:1920,"
        "zoompan=z='min(zoom+0.0008,1.08)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920,"
        "subtitles=subs.srt:force_style='FontName=DejaVu Sans,FontSize=16,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=3,Outline=2,Alignment=2,MarginV=180'"
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", "frame.png",
        "-i", "voz.mp3",
        "-vf", filtro_video,
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        salida_mp4,
    ]
    subprocess.run(cmd, check=True)
    return {"video_path": salida_mp4, "caption": guion["caption"]}


def subir_mp4_publico(ruta_mp4: str) -> str:
    """Sube el MP4 a hosting temporal para obtener URL pública exigida por Meta/TikTok API."""
    with open(ruta_mp4, "rb") as f:
        resp = requests.post(
            "https://catbox.moe/user/api.php",
            data={"reqtype": "fileupload"},
            files={"fileToUpload": f},
            timeout=60,
        )
    resp.raise_for_status()
    return resp.text.strip()
  
