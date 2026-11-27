def normalizar_url(url_raw):
    if not url_raw:
        return ""
    limpia = unquote(html.unescape(url_raw.strip()))
    limpia = limpia.rstrip(").,;!?\"'\\]>").split("#")[0].strip()
    if limpia.startswith("http://"):
        limpia = "https://" + limpia[7:]
    if not limpia.startswith("https://"):
        return ""
    # Evita que corchetes sueltos o malformados disparen ValueError: Invalid IPv6 URL
    sin_esquema = limpia[8:]
    host_candidato = sin_esquema.split("/", 1)[0].split("?", 1)[0]
    if "[" in host_candidato or "]" in host_candidato:
        return ""
    try:
        urlparse(limpia)
    except ValueError:
        return ""
    return limpia


def es_url_producto_exacto(url):
    try:
        limpia = normalizar_url(url)
        if not limpia:
            return False
        partes = urlparse(limpia)
        host = (partes.netloc or "").lower()
        ruta = (partes.path or "").lower()

        if not (host == "mercadolibre.com.mx" or host.endswith(".mercadolibre.com.mx")):
            return False
        if any(seg in ruta for seg in ("/ofertas", "/listado", "/tienda/", "/c/", "/gz/")):
            return False

        return bool(
            extraer_mlm_id(ruta)
            or "/p/" in ruta
            or "-_jm" in ruta
            or host.startswith("articulo.mercadolibre.com.mx")
        )
    except ValueError:
        return False


def blindar_link_afiliado(url_destino):
    try:
        limpia = normalizar_url(url_destino)
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
            partes.path or "/",
            "",
            urlencode(params_limpios, doseq=True),
            ""
        ))
    except ValueError:
        return ""
