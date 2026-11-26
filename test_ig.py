import os
import time
import requests

IG_USER_ID = os.environ["IG_USER_ID"]
ACCESS_TOKEN = os.environ["IG_ACCESS_TOKEN"]
API_VERSION = "v27.0"

# Imagen pública de prueba en formato JPEG (Instagram API requiere URL pública)
IMAGE_URL = "https://picsum.photos/1080/1080.jpg"
CAPTION = "Prueba de publicación automatizada 🚀 #RadarDeDescuentosMX"

def publicar_imagen():
    # Paso 1: Crear el contenedor de medios
    url_media = f"https://graph.facebook.com/{API_VERSION}/{IG_USER_ID}/media"
    payload_media = {
        "image_url": IMAGE_URL,
        "caption": CAPTION,
        "access_token": ACCESS_TOKEN,
    }
    res_media = requests.post(url_media, data=payload_media)
    data_media = res_media.json()
    print("Respuesta paso 1 (contenedor):", data_media)

    if "id" not in data_media:
        raise Exception(f"Error al crear contenedor: {data_media}")

    creation_id = data_media["id"]

    # Espera breve para que Meta procese la imagen
    time.sleep(5)

    # Paso 2: Publicar el contenedor en el feed
    url_publish = f"https://graph.facebook.com/{API_VERSION}/{IG_USER_ID}/media_publish"
    payload_publish = {
        "creation_id": creation_id,
        "access_token": ACCESS_TOKEN,
    }
    res_publish = requests.post(url_publish, data=payload_publish)
    data_publish = res_publish.json()
    print("Respuesta paso 2 (publicación):", data_publish)

    if "id" not in data_publish:
        raise Exception(f"Error al publicar: {data_publish}")

    print(f"¡Publicado con éxito! ID del post: {data_publish['id']}")

if __name__ == "__main__":
    publicar_imagen()
  
