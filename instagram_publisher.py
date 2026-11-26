import os
import re
import time
import requests

API_VERSION = "v27.0"


def normalizar_imagen_ml(imagen_url: str) -> str:
    """Convierte URLs de Mercado Libre (.webp o miniaturas -I) a JPEG de alta calidad (-O.jpg)."""
    if not imagen_url:
        return ""
    url = imagen_url.replace("http://", "https://")
    url = re.sub(r"-[A-Z]\.(webp|jpg|jpeg)$", "-O.jpg", url, flags=re.IGNORECASE)
    if url.lower().endswith(".webp"):
        url = url[:-5] + ".jpg"
    return url


def armar_caption(titulo: str, precio_actual: float, precio_anterior: float = None, descuento: int = None) -> str:
    """Genera el texto del post dirigiendo el tráfico al canal de Telegram (link en bio)."""
    lineas = ["🚨 ¡OFERTA DETECTADA! 🚨", ""]
    lineas.append(f"📦 {titulo}")
    lineas.append("")

    if precio_anterior and precio_anterior > precio_actual:
        lineas.append(f"❌ Antes: ${precio_anterior:,.2f} MXN")
    if descuento:
        lineas.append(f"🔥 Ahora: ${precio_actual:,.2f} MXN (-{descuento}% OFF)")
    else:
        lineas.append(f"🔥 Precio: ${precio_actual:,.2f} MXN")

    lineas.extend([
        "",
        "🔗 Link directo de compra en el enlace de nuestra bio (Canal de Telegram @RadarDescuentosMX247).",
        "⚠️ Los precios y disponibilidad pueden cambiar en cualquier momento.",
        "",
        "#OfertasMexico #DescuentosMX #MercadoLibre #Promociones #RadarDeDescuentosMX"
    ])
    return "\n".join(lineas)


def publicar_en_instagram(
    titulo: str,
    precio_actual: float,
    imagen_url: str,
    precio_anterior: float = None,
    descuento: int = None,
) -> bool:
    """Publica una oferta en Instagram sin detener el bot si ocurre algún error."""
    ig_user_id = os.getenv("IG_USER_ID")
    access_token = os.getenv("IG_ACCESS_TOKEN")

    if not ig_user_id or not access_token:
        print("[IG] Saltando publicación: faltan IG_USER_ID o IG_ACCESS_TOKEN.")
        return False

    img_jpeg = normalizar_imagen_ml(imagen_url)
    caption = armar_caption(titulo, precio_actual, precio_anterior, descuento)

    try:
        # Paso 1: Crear contenedor
        url_media = f"https://graph.facebook.com/{API_VERSION}/{ig_user_id}/media"
        res_media = requests.post(
            url_media,
            data={
                "image_url": img_jpeg,
                "caption": caption,
                "access_token": access_token,
            },
            timeout=30,
        )
        data_media = res_media.json()

        if "id" not in data_media:
            print(f"[IG] Error creando contenedor: {data_media}")
            return False

        creation_id = data_media["id"]
        time.sleep(5)

        # Paso 2: Publicar contenedor
        url_publish = f"https://graph.facebook.com/{API_VERSION}/{ig_user_id}/media_publish"
        res_publish = requests.post(
            url_publish,
            data={
                "creation_id": creation_id,
                "access_token": access_token,
            },
            timeout=30,
        )
        data_publish = res_publish.json()

        if "id" not in data_publish:
            print(f"[IG] Error publicando post: {data_publish}")
            return False

        print(f"[IG] ¡Publicado con éxito! Post ID: {data_publish['id']}")
        return True

    except Exception as e:
        print(f"[IG] Excepción inesperada: {e}")
        return False
      
