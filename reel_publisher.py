import os
import re
import time
import unicodedata
import requests

GRAPH_API_VERSION = "v27.0"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


def limpiar_texto(texto: str | None) -> str:
    if not texto:
        return ""
    normalizado = unicodedata.normalize("NFKC", texto)
    sin_controles = "".join(
        ch for ch in normalizado if unicodedata.category(ch)[0] != "C"
    )
    return re.sub(r"\s+", " ", sin_controles).strip()


def formatear_precio_mxn(precio: str | float | int) -> str:
    limpio = limpiar_texto(str(precio)).replace("$", "").replace("MXN", "")
    limpio = limpio.replace(",", "").strip()
    try:
        valor = float(limpio)
        if valor.is_integer():
            return f"${int(valor):,}"
        return f"${valor:,.2f}"
    except ValueError:
        return limpiar_texto(str(precio))


def listar_modelos_gemini(api_key: str) -> list[str]:
    try:
        resp = requests.get(
            f"{GEMINI_API_BASE}/models",
            params={"key": api_key},
            timeout=15,
        )
        if resp.status_code in (403, 429):
            print(f"[REEL] Aviso Gemini al listar modelos HTTP {resp.status_code}")
            return []
        resp.raise_for_status()
        modelos: list[str] = []
        for item in resp.json().get("models", []):
            metodos = item.get("supportedGenerationMethods", [])
            if "generateContent" in metodos:
                nombre = limpiar_texto(item.get("name", "")).removeprefix("models/")
                if nombre and nombre not in modelos:
                    modelos.append(nombre)
        return modelos
    except requests.RequestException as exc:
        print(f"[REEL] Aviso al consultar modelos de Gemini: {exc}")
        return []


def generar_guion_reel(titulo: str, precio: str, url: str) -> str:
    titulo_limpio = limpiar_texto(titulo)
    precio_fmt = formatear_precio_mxn(precio)
    url_limpia = limpiar_texto(url)
    fallback = (
        f"{titulo_limpio} baja a {precio_fmt}. "
        f"Disponible en Mercado Libre Mexico. "
        f"Revisa el enlace en el perfil."
    )[:300]

    api_key = limpiar_texto(os.getenv("GEMINI_API_KEY"))
    if not api_key:
        print("[REEL] Aviso: falta GEMINI_API_KEY, se usa guion base.")
        return fallback

    modelo_env = limpiar_texto(os.getenv("GEMINI_MODEL"))
    candidatos: list[str] = []
    if modelo_env:
        candidatos.append(modelo_env)
    for m in listar_modelos_gemini(api_key):
        if m not in candidatos:
            candidatos.append(m)

    if not candidatos:
        print("[REEL] Aviso Gemini HTTP 404: sin modelos disponibles para la clave.")
        return fallback

    prompt = (
        "Escribe un guion breve en espanol neutro (maximo 220 caracteres) para un Reel "
        "vertical sobre esta oferta. Sin emojis ni hashtags.\n"
        f"Producto: {titulo_limpio}\n"
        f"Precio: {precio_fmt}\n"
        f"Enlace: {url_limpia}"
    )

    for modelo in candidatos:
        try:
            resp = requests.post(
                f"{GEMINI_API_BASE}/models/{modelo}:generateContent",
                params={"key": api_key},
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=30,
            )
            if resp.status_code == 404:
                print(f"[REEL] Aviso Gemini HTTP 404 con modelo '{modelo}'")
                continue
            if resp.status_code in (403, 429):
                print(f"[REEL] Aviso Gemini HTTP {resp.status_code} con modelo '{modelo}'")
                continue
            resp.raise_for_status()
            data = resp.json()
            partes = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [])
            )
            texto = limpiar_texto("".join(p.get("text", "") for p in partes))
            if texto:
                return texto[:300]
        except requests.RequestException as exc:
            print(f"[REEL] Aviso llamada Gemini ({modelo}): {exc}")

    return fallback


def publicar_reel_instagram(
    video_url: str,
    caption: str,
    ig_user_id: str | None = None,
    access_token: str | None = None,
) -> dict:
    user_id = limpiar_texto(ig_user_id or os.getenv("IG_USER_ID"))
    token = limpiar_texto(access_token or os.getenv("IG_ACCESS_TOKEN"))
    video_clean = limpiar_texto(video_url)
    caption_clean = limpiar_texto(caption)[:2200]

    if not user_id or not token:
        return {"ok": False, "error": "Falta IG_USER_ID o IG_ACCESS_TOKEN"}
    if not video_clean.startswith(("http://", "https://")):
        return {"ok": False, "error": "URL de video invalida para Graph API"}

    base_url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{user_id}"

    try:
        create_resp = requests.post(
            f"{base_url}/media",
            data={
                "media_type": "REELS",
                "video_url": video_clean,
                "caption": caption_clean,
                "access_token": token,
            },
            timeout=45,
        )
        create_data = create_resp.json() if create_resp.text else {}
        if create_resp.status_code >= 400 or "error" in create_data:
            err = create_data.get("error", {})
            code = err.get("code", create_resp.status_code)
            msg = err.get("message", create_resp.text)
            print(f"[REEL] Error iniciando contenedor: code={code} msg={msg}")
            return {"ok": False, "code": code, "error": msg}

        creation_id = limpiar_texto(str(create_data.get("id", "")))
        if not creation_id:
            return {"ok": False, "error": "No se recibio creation_id"}

        for _ in range(6):
            time.sleep(5)
            status_resp = requests.get(
                f"https://graph.facebook.com/{GRAPH_API_VERSION}/{creation_id}",
                params={"fields": "status_code", "access_token": token},
                timeout=20,
            )
            status_data = status_resp.json() if status_resp.text else {}
            status_code = status_data.get("status_code")
            if status_code == "FINISHED":
                break
            if status_code == "ERROR":
                return {"ok": False, "error": f"Fallo en procesamiento del contenedor: {status_data}"}

        publish_resp = requests.post(
            f"{base_url}/media_publish",
            data={"creation_id": creation_id, "access_token": token},
            timeout=45,
        )
        publish_data = publish_resp.json() if publish_resp.text else {}
        if publish_resp.status_code >= 400 or "error" in publish_data:
            err = publish_data.get("error", {})
            code = err.get("code", publish_resp.status_code)
            msg = err.get("message", publish_resp.text)
            print(f"[REEL] Error publicando contenedor: code={code} msg={msg}")
            return {"ok": False, "code": code, "error": msg}

        media_id = publish_data.get("id")
        print(f"[REEL] Reel publicado con exito. ID: {media_id}")
        return {"ok": True, "id": media_id}
    except requests.RequestException as exc:
        print(f"[REEL] Error de red en Graph API: {exc}")
        return {"ok": False, "error": str(exc)}


if __name__ == "__main__":
    guion = generar_guion_reel(
        titulo="LAPTOP SNAPDRAGON OLED",
        precio="$12,999",
        url="https://www.mercadolibre.com.mx/",
    )
    print("Guion:", guion)
    resultado = publicar_reel_instagram(
        video_url=limpiar_texto(os.getenv("TEST_REEL_VIDEO_URL", "")),
        caption=guion,
    )
    print("Resultado IG:", resultado)
