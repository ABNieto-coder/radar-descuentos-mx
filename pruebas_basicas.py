"""Pruebas rápidas sin internet. Si alguna falla, el flujo de GitHub Actions se detiene
antes de publicar nada. Para ejecutarlas a mano: python pruebas_basicas.py"""
import sys

import bot
import reel_publisher as rp

fallos = []


def revisar(condicion, descripcion):
    if not condicion:
        fallos.append(descripcion)
        print(f"FALLA: {descripcion}")


casos_producto = [
    ("https://www.mercadolibre.com.mx/glossary/P/1", False),
    ("https://www.mercadolibre.com.mx/glossary/P/1?matt_word=charlysource&matt_tool=29165755", False),
    ("https://www.mercadolibre.com.mx/ofertas", False),
    ("https://www.mercadolibre.com.mx/categorias", False),
    ("https://www.mercadolibre.com.mx/social/alguien/lists/123", False),
    ("https://listado.mercadolibre.com.mx/tenis-adidas", False),
    ("https://example.com/MLM-1234567890-tenis", False),
    ("http://[::1/MLM-1234567890", False),
    ("https://articulo.mercadolibre.com.mx/MLM-1234567890-tenis-adidas-lightblaze-_JM", True),
    ("https://www.mercadolibre.com.mx/tenis-adidas-lightblaze/p/MLM12345678", True),
    ("https://www.mercadolibre.com.mx/tenis-adidas/up/MLMU123456789", False),
]
for url, esperado in casos_producto:
    revisar(bot.es_url_producto_exacto(url) is esperado, f"es_url_producto_exacto({url}) debía ser {esperado}")

revisar(bot.destino_publicable("https://listado.mercadolibre.com.mx/tenis-adidas", 2), "un listado válido debe poder publicarse en nivel 2")
revisar(not bot.destino_publicable("https://www.mercadolibre.com.mx/glossary/P/1", 2), "el glosario no debe publicarse como listado")
revisar(not bot.destino_publicable("https://www.mercadolibre.com.mx/glossary/P/1", 1), "el glosario no debe publicarse como producto")

afiliado = bot.blindar_link_afiliado("https://articulo.mercadolibre.com.mx/MLM-1234567890-x-_JM?utm_source=a&ref=b")
revisar("matt_word=charlysource" in afiliado and "matt_tool=29165755" in afiliado, "el enlace debe llevar los parámetros de afiliado")
revisar("utm_source" not in afiliado and "ref=" not in afiliado, "el enlace no debe conservar parámetros de rastreo ajenos")
revisar(bot.mlm_desde_url(afiliado) == "MLM1234567890", "mlm_desde_url debe extraer el id de la ruta")

casos_nicho = [
    ("Monitor Gamer 27 pulgadas 240 fps 1ms", "tecnologia"),
    ("Monitor 144 Hz curvo", "tecnologia"),
    ("Protector Solar Facial Isdin FPS 50+", "cuidado_personal"),
    ("Bloqueador solar SPF50 Anthelios", "cuidado_personal"),
    ("Audífonos Bluetooth TWS Xiaomi", "tecnologia"),
    ("Paquete de 6 calcetines deportivos", "general"),
]
for titulo, esperado in casos_nicho:
    obtenido = bot.detectar_nicho_oferta(titulo)
    revisar(obtenido == esperado, f"nicho de '{titulo}': esperado {esperado}, obtenido {obtenido}")

revisar(rp.limpiar_texto_para_voz("Cuesta $1,299.50") == "Cuesta 1299 pesos con 50", "precio con decimales para la voz")
revisar(rp.limpiar_texto_para_voz("Cuesta $2,000") == "Cuesta 2000 pesos", "precio entero para la voz")
revisar(rp._normalizar_descuento("25% OFF") == "25%", "descuento '25% OFF'")
revisar(rp._normalizar_descuento("25 % de descuento") == "25%", "descuento '25 % de descuento'")
revisar(rp._normalizar_descuento("120%") == "", "descuento fuera de rango")

oferta = {
    "titulo": "Audífonos Inalámbricos Bluetooth Xiaomi Redmi Buds 6 Play",
    "precio": "$399", "precio_anterior": "$599", "descuento": "33% OFF", "nicho": "tecnologia",
}
d = rp._datos_oferta(oferta)
permitidos = rp._numeros_permitidos(d)
revisar(d["ahorro"] == 200 and d["pct"] == "33%", "ahorro y porcentaje calculados")
for cand in rp._candidatos_plantilla(d):
    revisar(rp._numeros_ok(cand["hablado"], permitidos), f"gancho con número inventado: {cand['hablado']}")
revisar(not rp._numeros_ok("Solo $249 por estos audífonos.", permitidos), "un precio inventado debe rechazarse")
revisar(rp.puntuar_gancho("Hola amigos, mira esto $399.", d)[0] == 0, "un saludo debe puntuar 0")
revisar(rp.puntuar_gancho("Precio increíble en audífonos $399.", d)[0] == 0, "una palabra exagerada debe puntuar 0")

palabra_a = "cura" + "duría"
palabra_b = "co" + "rre"
sucio = f"Esta {palabra_a} es única, {palabra_b} por ella"
limpio = rp._quitar_palabra_prohibida(sucio).lower()
revisar(palabra_a not in limpio and f" {palabra_b} " not in f" {limpio} ", "las palabras prohibidas deben sustituirse")
guion = rp.construir_guion(d, rp._candidatos_plantilla(d)[0])
revisar("cura" + "dur" not in guion["voz"].lower(), "el guion no debe contener palabras prohibidas")

caption = rp.armar_caption_reel(oferta, d)
revisar(caption.count("#") <= 5, "el caption no debe pasar de 5 hashtags")
revisar(len(caption) <= 2200, "el caption no debe pasar de 2200 caracteres")
revisar(len(caption.split("\n")[0]) <= 125, "la primera línea del caption debe caber en 125 caracteres")
revisar("\u2014" not in caption, "el caption no debe llevar guiones largos")
revisar("https://t.me/RadarDescuentosMX247" in caption, "el caption debe incluir el vínculo directo de Telegram")
revisar("@RadarDescuentosMX247" not in caption, "el caption no debe usar arroba para Telegram en Instagram")

if fallos:
    print(f"\n{len(fallos)} prueba(s) fallaron.")
    sys.exit(1)
print("Todas las pruebas pasaron.")
