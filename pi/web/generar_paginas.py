#!/usr/bin/env python3
"""Genera las páginas públicas de inmuebles de soypetra.com desde pi/web/conjuntos.json.

Uso (desde la raíz del repo):
    python3 pi/web/generar_paginas.py

Qué genera:
    /conjuntos/                         índice de edificios conectados
    /conjuntos/<conjunto>-<ciudad>/     página de cada edificio
    /conjuntos/<conjunto>-<ciudad>/<inmueble>/   página de cada inmueble
    /barrios/<barrio>-<ciudad>/         página por barrio
    /ciudades/<ciudad>/                 página por ciudad
    /inmobiliaria/...                   redirecciones de las URL viejas (PR 6)
    index.html                          bloque «buscador + edificios» y <head> de la landing
    sitemap.xml, robots.txt
    img/conjuntos/<slug>/*.webp         fotos optimizadas (y og.jpg para WhatsApp)
    pi/web/FALTANTES.md                 lo que falta en los datos (precio, m², fotos...)

Nunca inventa datos: si falta precio, m² o habitaciones, la página dice «Consultar»
y el faltante queda en FALTANTES.md.
"""
import datetime
import hashlib
import html
import json
import os
import re
import shutil
import sys
import unicodedata
import urllib.parse
import urllib.request

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATOS = os.path.join(RAIZ, "pi", "web", "conjuntos.json")
CACHE = os.path.join(RAIZ, "pi", "web", ".cache")
HOY = datetime.date.today().isoformat()

try:
    from PIL import Image, ImageOps
except ImportError:  # sin Pillow no se pueden crear las WebP
    Image = None

# ----------------------------------------------------------------- utilidades

def slug(txt):
    txt = unicodedata.normalize("NFKD", str(txt)).encode("ascii", "ignore").decode()
    txt = re.sub(r"[^a-zA-Z0-9]+", "-", txt).strip("-").lower()
    return txt


def cap(txt):
    return txt[:1].upper() + txt[1:]


def e(txt):
    return html.escape(str(txt), quote=True)


def escribir(ruta_rel, contenido):
    ruta = os.path.join(RAIZ, ruta_rel)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(contenido)


def pesos(valor):
    return "$" + f"{int(valor):,}".replace(",", ".")


def jsonld(obj):
    return '<script type="application/ld+json">' + json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/") + "</script>"


TIPOS = {
    "apartamento": ("Apartamento", "Apartamentos", "Apartment"),
    "apartaestudio": ("Apartaestudio", "Apartaestudios", "Apartment"),
    "penthouse": ("Penthouse", "Penthouses", "Apartment"),
    "casa": ("Casa", "Casas", "House"),
    "local": ("Local", "Locales", "Accommodation"),
}
FUENTES = {
    "qr": "en el QR del conjunto", "tiktok": "en TikTok", "ig": "en Instagram",
    "fb": "en Facebook", "yt": "en YouTube", "grupo": "en un grupo de Facebook",
    "marketplace": "en Marketplace", "fincaraiz": "en Fincaraíz", "google": "en Google",
}
ORIGEN_DEFECTO = "en soypetra.com"

# --------------------------------------------------------------------- datos

with open(DATOS, encoding="utf-8") as f:
    D = json.load(f)
S = D["sitio"]
DOM = S["dominio"].rstrip("/")
FALTA = []  # (conjunto, inmueble/campo, qué falta)


def url_abs(ruta):
    return DOM + ruta


def ops_texto(ops):
    ops = [o for o in ("venta", "arriendo") if o in ops]
    return " y ".join(ops) if ops else "venta y arriendo"


conjuntos = []
for c in D["conjuntos"]:
    nombre = c["nombre"]
    if not c.get("publicar"):
        faltan = [k for k in ("barrio", "direccion") if not c.get(k)]
        FALTA.append((nombre, "conjunto sin publicar", "falta " + ", ".join(faltan) if faltan else "marcado publicar=false"))
        continue
    c["corto"] = c.get("nombre_corto") or nombre
    c["slug"] = slug(f"{nombre} {c['ciudad']}")
    c["url"] = f"/conjuntos/{c['slug']}/"
    c["ciudad_slug"] = slug(c["ciudad"])
    c["barrio_slug"] = slug(f"{c['barrio']} {c['ciudad']}") if c.get("barrio") else ""
    c["tipo_plural"] = "Casas" if c.get("tipo_conjunto") == "casas" else "Apartamentos"
    ops = sorted({i["operacion"] for i in c["inmuebles"]})
    c["ops"] = ops_texto(ops)
    if not c.get("barrio"):
        FALTA.append((nombre, "conjunto", "falta barrio"))
    if not c.get("localidad"):
        FALTA.append((nombre, "conjunto", "falta localidad"))
    if not c.get("mapa"):
        FALTA.append((nombre, "conjunto", "falta enlace de Google Maps"))
    if not c.get("fotos"):
        FALTA.append((nombre, "conjunto", "faltan fotos del conjunto (fachada, zonas comunes)"))
    if not c.get("videos"):
        FALTA.append((nombre, "conjunto", "faltan videos (YouTube)"))
    if not c.get("zonas_comunes"):
        FALTA.append((nombre, "conjunto", "faltan zonas comunes"))
    palabras = len(" ".join(c.get("texto", [])).split())
    if palabras < 250:
        FALTA.append((nombre, "conjunto", f"falta texto propio (~300 palabras; hoy {palabras})"))
    if not c["inmuebles"]:
        FALTA.append((nombre, "conjunto", "no hay inventario cargado"))
    if c.get("verificar"):
        FALTA.append((nombre, "conjunto", "verificar: " + c["verificar"]))

    for i in c["inmuebles"]:
        t1, tn, schema_t = TIPOS.get(i["tipo"], (i["tipo"].capitalize(), i["tipo"].capitalize() + "s", "Accommodation"))
        i["tipo_txt"], i["schema_tipo"] = t1, schema_t
        partes = []
        if i.get("bloque"):
            partes.append(f"bloque {i['bloque']}")
        if i.get("piso") is not None:
            partes.append(f"piso {i['piso']}")
        i["ubic"] = ", ".join(partes)
        base = f"{t1.lower()}-en-{i['operacion']}"
        extra = []
        if i.get("habitaciones"):
            extra.append(f"{i['habitaciones']}-habitaciones")
        if i.get("m2"):
            extra.append(f"{i['m2']}-m2")
        if i.get("bloque"):
            extra.append(f"bloque-{i['bloque']}")
        if i.get("piso") is not None:
            extra.append(f"piso-{i['piso']}")
        i["slug"] = slug("-".join([base] + extra))
        for campo, txt in (("precio", "precio"), ("m2", "m²"), ("habitaciones", "habitaciones"), ("banos", "baños")):
            if not i.get(campo):
                FALTA.append((nombre, i["ref"], f"falta {txt}"))
        if i.get("verificar"):
            FALTA.append((nombre, i["ref"], "verificar: " + i["verificar"]))
    # slugs únicos dentro del conjunto
    vistos = {}
    for i in c["inmuebles"]:
        if i["slug"] in vistos:
            i["slug"] += "-" + slug(i["ref"])
        vistos[i["slug"]] = 1
        i["url"] = f"{c['url']}{i['slug']}/"
    conjuntos.append(c)

def completitud(i):
    return -sum(1 for k in ("precio", "m2", "habitaciones", "banos") if i.get(k))


for c in conjuntos:
    c["inmuebles"].sort(key=completitud)
todos_inm = sorted(((c, i) for c in conjuntos for i in c["inmuebles"]), key=lambda x: completitud(x[1]))

# ------------------------------------------------------------------- fotos

def descargar(origen):
    os.makedirs(CACHE, exist_ok=True)
    nombre = hashlib.sha1(origen.encode()).hexdigest()[:16] + os.path.splitext(urllib.parse.urlparse(origen).path)[1]
    ruta = os.path.join(CACHE, nombre)
    if not os.path.exists(ruta):
        if origen.startswith("http"):
            print("  descargando", origen)
            with urllib.request.urlopen(origen, timeout=60) as r, open(ruta, "wb") as f:
                shutil.copyfileobj(r, f)
        else:
            shutil.copy(os.path.join(RAIZ, origen), ruta)
    return ruta


def procesar_fotos(c):
    """Crea <n>-600.webp, <n>-1200.webp y og.jpg (1200x630). Devuelve la lista de fotos listas."""
    salida = []
    if Image is None:
        print("AVISO: falta Pillow (pip install pillow); no se generan fotos.")
        return salida
    carpeta = f"img/conjuntos/{c['slug']}"
    os.makedirs(os.path.join(RAIZ, carpeta), exist_ok=True)
    for n, foto in enumerate(c.get("fotos", []), 1):
        try:
            src = descargar(foto["origen"])
        except Exception as ex:  # sin red: se reutilizan las WebP ya generadas
            print("  no se pudo descargar", foto["origen"], ex)
            src = None
        rutas = {w: f"{carpeta}/{n}-{w}.webp" for w in (600, 1200)}
        if src:
            im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
            for w, rel in rutas.items():
                copia = im.copy()
                copia.thumbnail((w, w * 2))
                copia.save(os.path.join(RAIZ, rel), "WEBP", quality=78, method=6)
            if n == 1:
                og = ImageOps.fit(im, (1200, 630), Image.LANCZOS)
                og.save(os.path.join(RAIZ, carpeta, "og.jpg"), "JPEG", quality=80, optimize=True, progressive=True)
        if os.path.exists(os.path.join(RAIZ, rutas[1200])):
            with Image.open(os.path.join(RAIZ, rutas[1200])) as im2:
                ancho, alto = im2.size
            salida.append({"src": "/" + rutas[1200], "src_s": "/" + rutas[600], "alt": foto["alt"], "w": ancho, "h": alto})
    c["og"] = f"/{carpeta}/og.jpg" if salida and os.path.exists(os.path.join(RAIZ, carpeta, "og.jpg")) else "/" + S["og_imagen_defecto"]
    return salida


def webp_landing():
    """Crea versiones .webp de las fotos de la landing (img/*.jpg)."""
    if Image is None:
        return
    for nombre in os.listdir(os.path.join(RAIZ, "img")):
        if not nombre.lower().endswith(".jpg") or nombre.startswith("og"):
            continue
        src = os.path.join(RAIZ, "img", nombre)
        dst = os.path.splitext(src)[0] + ".webp"
        if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src):
            im = Image.open(src)
            im = im.convert("RGBA") if im.mode in ("RGBA", "LA", "P") else im.convert("RGB")
            im.save(dst, "WEBP", quality=80, method=6)

# ------------------------------------------------------------------ plantilla

CSS = """
:root{--bg:#F8F8FB;--ink:#111318;--muted:#555B69;--card:#fff;--line:#E9EAF0;--acc:#3F7FE6;--wa:#25D366;--grad:linear-gradient(90deg,#7B5CF0 0%,#3F7FE6 50%,#0A9CC0 100%);--shadow:0 10px 30px rgba(17,19,24,.07),0 1px 4px rgba(17,19,24,.04)}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;font-size:17px;line-height:1.6}
img{max-width:100%;height:auto;display:block}
a{color:inherit}
.wrap{max-width:1040px;margin:0 auto;padding:0 16px}
header{background:rgba(248,248,251,.95);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
nav{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 0;flex-wrap:wrap}
.brand img{height:22px;width:auto}
.links{display:flex;gap:6px 18px;flex-wrap:wrap;font-size:15px}
.links a{text-decoration:none;color:var(--muted)}
.miga{font-size:14px;color:var(--muted);margin:18px 0 0;padding:0;list-style:none;display:flex;flex-wrap:wrap;gap:4px}
.miga li+li:before{content:"›";margin-right:4px}
.miga a{text-decoration:none}
h1{font-size:clamp(28px,5.2vw,42px);line-height:1.12;letter-spacing:-.025em;margin:14px 0 10px}
h2{font-size:clamp(22px,3.4vw,28px);letter-spacing:-.02em;margin:0 0 14px;line-height:1.2}
.lead{color:var(--muted);font-size:18px;margin:0 0 18px}
section{padding:30px 0;border-top:1px solid var(--line)}
.hero{padding:0 0 24px}
.btns{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:48px;padding:12px 20px;border-radius:999px;font-weight:700;text-decoration:none;background:var(--card);border:1px solid var(--line)}
.btn.wa{background:var(--wa);border-color:var(--wa);color:#052E16}
.btn svg{width:20px;height:20px;fill:currentColor}
.datos{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:16px 0}
.dato{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 14px}
.dato small{display:block;color:var(--muted);font-size:13px}
.dato b{font-size:19px}
.consultar{color:#B4541F}
.galeria{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
.galeria figure{margin:0;background:var(--card);border-radius:16px;overflow:hidden;box-shadow:var(--shadow)}
.galeria img{width:100%;aspect-ratio:4/3;object-fit:cover}
.galeria figcaption{font-size:14px;color:var(--muted);padding:8px 12px}
.mapa{width:100%;aspect-ratio:16/10;border:0;border-radius:16px;background:#e9eaf0}
.video{position:relative;display:block;width:100%;aspect-ratio:16/9;border:0;border-radius:16px;overflow:hidden;background:#000;cursor:pointer;padding:0}
.video img{width:100%;height:100%;object-fit:cover;opacity:.85}
.video span{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:18px}
.texto p{margin:0 0 14px}
.inv{display:grid;gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:16px;box-shadow:var(--shadow)}
.card h3{margin:0 0 4px;font-size:19px;line-height:1.3}
.card h3 a{text-decoration:none}
.card .meta{color:var(--muted);font-size:15px;margin:0 0 8px}
.card .fila{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:15px;margin:0 0 6px}
.card .btns{margin:10px 0 0}
.card .btn{min-height:42px;padding:9px 16px;font-size:15px}
.chips{display:flex;flex-wrap:wrap;gap:6px;padding:0;margin:8px 0;list-style:none}
.chips li{background:#EEF2FB;border-radius:999px;padding:3px 10px;font-size:14px}
.lista{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
.nota{color:var(--muted);font-size:14px}
footer{padding:28px 0 40px;color:var(--muted);font-size:14px;border-top:1px solid var(--line)}
footer a{margin-right:14px}
"""

WA_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2a10 10 0 0 0-8.6 15.1L2 22l5-1.3A10 10 0 1 0 12 2zm5.3 14.1c-.2.6-1.3 1.2-1.8 1.2-.5.1-1 .2-3.3-.7-2.8-1.1-4.6-4-4.7-4.2-.1-.2-1.1-1.5-1.1-2.9s.7-2 1-2.3c.2-.3.5-.3.7-.3h.5c.2 0 .4 0 .6.5l.8 2c.1.2.1.4 0 .5l-.3.5-.4.4c-.1.1-.3.3-.1.6.2.3.8 1.3 1.6 2.1 1.1 1 2.1 1.3 2.4 1.4.3.1.5.1.6-.1l.9-1c.2-.3.4-.2.6-.1l1.9.9c.3.1.5.2.5.3.1.2.1.7-.1 1.2z"/></svg>'


def ga_head():
    gid = S.get("ga4_id")
    if not gid:
        return "<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments)}</script>"
    return (f'<script async src="https://www.googletagmanager.com/gtag/js?id={e(gid)}"></script>'
            f"<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments)}}gtag('js',new Date());gtag('config','{e(gid)}');</script>")


def meta_head(titulo, desc, ruta, og_img, og_tipo="website", robots="index,follow"):
    canon = url_abs(ruta)
    img = url_abs(og_img if og_img.startswith("/") else "/" + og_img)
    v = S.get("google_site_verification")
    return "\n".join(x for x in [
        f"<title>{e(titulo)}</title>",
        f'<meta name="description" content="{e(desc)}">',
        f'<meta name="robots" content="{robots}">',
        f'<link rel="canonical" href="{canon}">',
        f'<meta name="google-site-verification" content="{e(v)}">' if v else "",
        f'<meta property="og:type" content="{og_tipo}">',
        '<meta property="og:locale" content="es_CO">',
        f'<meta property="og:site_name" content="{e(S["marca"])}">',
        f'<meta property="og:title" content="{e(titulo)}">',
        f'<meta property="og:description" content="{e(desc)}">',
        f'<meta property="og:url" content="{canon}">',
        f'<meta property="og:image" content="{img}">',
        '<meta name="twitter:card" content="summary_large_image">',
    ] if x)


# JS común: arma el mensaje de WhatsApp según ?fuente= y registra el clic en GA4.
JS = """<script>
(function(){
var F=%s,D=%s;
var f=(new URLSearchParams(location.search).get('fuente')||'').toLowerCase();
var o=F[f]||D;
document.querySelectorAll('a[data-wa]').forEach(function(a){
  var m=a.getAttribute('data-wa').replace('{origen}',o);
  a.href='https://wa.me/%s?text='+encodeURIComponent(m);
  a.addEventListener('click',function(){
    gtag('event','whatsapp_click',{conjunto:a.dataset.conjunto||'',inmueble:a.dataset.inmueble||'',operacion:a.dataset.op||'',tipo_pagina:document.body.dataset.pagina||'',fuente:f||'web',transport_type:'beacon'});
  });
});
document.querySelectorAll('a[href^="tel:"]').forEach(function(a){
  a.addEventListener('click',function(){gtag('event','telefono_click',{conjunto:a.dataset.conjunto||'',tipo_pagina:document.body.dataset.pagina||''});});
});
document.querySelectorAll('button.video').forEach(function(b){
  b.addEventListener('click',function(){
    var i=document.createElement('iframe');
    i.src='https://www.youtube-nocookie.com/embed/'+b.dataset.id+'?autoplay=1&rel=0';
    i.title=b.getAttribute('aria-label');i.allow='autoplay; encrypted-media; picture-in-picture';i.allowFullscreen=true;i.className='video';
    b.replaceWith(i);
  });
});
})();
</script>""" % (json.dumps(FUENTES, ensure_ascii=False), json.dumps(ORIGEN_DEFECTO), S["whatsapp"])


def wa_href(msg):
    return f"https://wa.me/{S['whatsapp']}?text=" + urllib.parse.quote(msg.replace("{origen}", ORIGEN_DEFECTO))


def boton_wa(msg, texto, conjunto="", inmueble="", op="", clase="btn wa"):
    return (f'<a class="{clase}" href="{wa_href(msg)}" target="_blank" rel="noopener" data-wa="{e(msg)}" '
            f'data-conjunto="{e(conjunto)}" data-inmueble="{e(inmueble)}" data-op="{e(op)}">{WA_SVG}{e(texto)}</a>')


def boton_tel(conjunto=""):
    return f'<a class="btn" href="tel:+{S["whatsapp"]}" data-conjunto="{e(conjunto)}">Llamar al {e(S["telefono_visible"])}</a>'


def migas(items):
    li = []
    for n, (nombre, ruta) in enumerate(items):
        li.append(f'<li><a href="{ruta}">{e(nombre)}</a></li>' if ruta and n < len(items) - 1 else f'<li aria-current="page">{e(nombre)}</li>')
    ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": n + 1, "name": nombre, "item": url_abs(ruta)} for n, (nombre, ruta) in enumerate(items) if ruta]}
    return '<ol class="miga">' + "".join(li) + "</ol>", ld


def pagina(ruta, titulo, desc, cuerpo, ld=(), og_img=None, tipo_pagina="", og_tipo="website"):
    ld_html = "".join(jsonld(x) for x in ld)
    doc = f"""<!doctype html>
<html lang="es-CO">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{meta_head(titulo, desc, ruta, og_img or S['og_imagen_defecto'], og_tipo)}
<meta name="theme-color" content="#F8F8FB">
<link rel="icon" type="image/png" href="/favicon.png">
<style>{CSS}</style>
{ga_head()}
{ld_html}
</head>
<body data-pagina="{tipo_pagina}">
<header><div class="wrap"><nav aria-label="Principal">
<a class="brand" href="/"><img src="/img/logo-dark.png" alt="PETRA Plataforma Inmobiliaria" width="104" height="22"></a>
<div class="links"><a href="/#buscar">Buscar inmueble</a><a href="/conjuntos/">Edificios</a>{''.join(f'<a href="/ciudades/{x}/">{e(n)}</a>' for x, n in sorted({(c['ciudad_slug'], c['ciudad']) for c in conjuntos}))}</div>
</nav></div></header>
<main class="wrap">
{cuerpo}
</main>
<footer><div class="wrap">
<p>{e(S['marca'])} Plataforma Inmobiliaria · Te atiende {e(S['whatsapp_nombre'])} por WhatsApp al {e(S['telefono_visible'])}, {e(S['horario'].rstrip('.'))}.</p>
<p><a href="/">Inicio</a><a href="/conjuntos/">Edificios conectados</a><a href="/#agentes">Agentes PETRA</a></p>
</div></footer>
{JS}
</body>
</html>
"""
    assert doc.count("<h1") == 1, f"{ruta} debe tener un solo H1"
    escribir(ruta.lstrip("/") + "index.html", doc)
    PAGINAS.append((ruta, titulo, desc))


PAGINAS = []

# --------------------------------------------------------------- componentes

def titulo_inm(c, i):
    t = f"{i['tipo_txt']} en {i['operacion']} en {c['corto']}"
    t += f", {c['barrio']}" if c.get("barrio") else ""
    t += f", {c['ciudad']}"
    if i.get("habitaciones"):
        t += f" · {i['habitaciones']} hab"
    if i.get("m2"):
        t += f" · {i['m2']} m²"
    return t


# títulos únicos: si dos inmuebles quedan iguales, se agrega bloque/piso o la referencia
_cuenta = {}
for c, i in todos_inm:
    _cuenta[titulo_inm(c, i)] = _cuenta.get(titulo_inm(c, i), 0) + 1
for c, i in todos_inm:
    t = titulo_inm(c, i)
    if _cuenta[t] > 1:
        t += f" · {cap(i['ubic'])}" if i["ubic"] else f" · Ref. {i['ref']}"
    i["titulo"] = t


def precio_txt(i):
    if i.get("precio"):
        return pesos(i["precio"]) + (" / mes" if i["operacion"] == "arriendo" else "")
    return None


def msg_inm(c, i):
    ub = f", {i['ubic']}" if i["ubic"] else ""
    return (f"Hola {S['whatsapp_nombre']}, vi {{origen}} el {i['tipo_txt'].lower()} en {i['operacion']} de "
            f"{c['corto']}{ub} (ref. {i['ref']}). ¿Me das más información?")


def msg_conj(c, op=None):
    pregunta = f"¿Qué tienen en {op}?" if op else "¿Qué tienen disponible?"
    return f"Hola {S['whatsapp_nombre']}, vi {c['corto']} {{origen}}. {pregunta}"


def tarjeta_inm(c, i, con_conjunto=False):
    pr = precio_txt(i)
    fila = []
    fila.append(f"<span>{i['habitaciones']} hab</span>" if i.get("habitaciones") else '<span class="consultar">Hab: consultar</span>')
    if i.get("banos"):
        fila.append(f"<span>{i['banos']} baños</span>")
    fila.append(f"<span>{i['m2']} m²</span>" if i.get("m2") else '<span class="consultar">m²: consultar</span>')
    fila.append(f"<b>{pr}</b>" if pr else '<b class="consultar">Precio: consultar</b>')
    lugar = f"{c['corto']} · {c['barrio']}" if con_conjunto and c.get("barrio") else (c["corto"] if con_conjunto else "")
    meta = " · ".join(x for x in [lugar, cap(i["ubic"]) if i["ubic"] else "", f"Ref. {i['ref']}"] if x)
    chips = "".join(f"<li>{e(x)}</li>" for x in i.get("caracteristicas", []))
    filtros = (f'data-op="{i["operacion"]}" data-tipo="{i["tipo"]}" data-ciudad="{c["ciudad_slug"]}" '
               f'data-hab="{i.get("habitaciones") or ""}" data-q="{e(slug(" ".join([c["nombre"], c.get("barrio", ""), c.get("localidad", ""), c["ciudad"], i["tipo_txt"], i["operacion"]])).replace("-", " "))}"')
    return f"""<article class="card" {filtros}>
<h3><a href="{i['url']}">{e(i['tipo_txt'])} en {e(i['operacion'])}{(' · ' + str(i['habitaciones']) + ' hab') if i.get('habitaciones') else ''}{(' · ' + str(i['m2']) + ' m²') if i.get('m2') else ''}</a></h3>
<p class="meta">{e(meta)}</p>
<div class="fila">{''.join(fila)}</div>
{'<ul class="chips">' + chips + '</ul>' if chips else ''}
<div class="btns">{boton_wa(msg_inm(c, i), 'Preguntar por WhatsApp', c['nombre'], i['ref'], i['operacion'])}<a class="btn" href="tel:+{S['whatsapp']}" data-conjunto="{e(c['nombre'])}">Tel. {e(S['telefono_visible'])}</a><a class="btn" href="{i['url']}">Ver ficha</a></div>
</article>"""


def tarjeta_conj(c):
    n = len(c["inmuebles"])
    inv = f"{n} inmueble{'s' if n != 1 else ''} publicado{'s' if n != 1 else ''}" if n else "Pregunta por la oferta"
    lugar = ", ".join(x for x in [c.get("barrio"), c.get("localidad"), c["ciudad"]] if x)
    img = ""
    if c.get("fotos_ok"):
        f0 = c["fotos_ok"][0]
        img = f'<img src="{f0["src_s"]}" alt="{e(f0["alt"])}" loading="lazy" decoding="async" width="600" height="450" style="width:100%;aspect-ratio:4/3;object-fit:cover;border-radius:12px;margin:0 0 10px">'
    return f"""<article class="card" data-ciudad="{c['ciudad_slug']}">
{img}<h3><a href="{c['url']}">{e(c['nombre'])}</a></h3>
<p class="meta">{e(lugar)}</p>
<p class="fila"><span>{e(c['tipo_plural'])} en {e(c['ops'])}</span><span>{inv}</span></p>
</article>"""


def foto_html(f, eager=False):
    carga = 'fetchpriority="high"' if eager else 'loading="lazy"'
    return (f'<figure><img src="{f["src"]}" srcset="{f["src_s"]} 600w, {f["src"]} {f["w"]}w" sizes="(max-width:600px) 100vw, 500px" '
            f'alt="{e(f["alt"])}" width="{f["w"]}" height="{f["h"]}" {carga} decoding="async"><figcaption>{e(f["alt"])}</figcaption></figure>')


def direccion_ld(c):
    return {"@type": "PostalAddress", "streetAddress": c.get("direccion") or None, "addressLocality": c["ciudad"],
            "addressRegion": c.get("localidad") or None, "addressCountry": "CO"}


def limpiar(o):
    if isinstance(o, dict):
        return {k: limpiar(v) for k, v in o.items() if v not in (None, "", [], {})}
    if isinstance(o, list):
        return [limpiar(x) for x in o]
    return o

# ------------------------------------------------------------------ páginas

webp_landing()
for c in conjuntos:
    c["fotos_ok"] = procesar_fotos(c)

AGENTE_LD = {"@type": "RealEstateAgent", "@id": DOM + "/#petra", "name": "PETRA Plataforma Inmobiliaria", "url": DOM + "/",
             "logo": DOM + "/img/logo.png", "telephone": "+" + S["whatsapp"], "areaServed": sorted({c["ciudad"] for c in conjuntos})}

# --- edificio
for c in conjuntos:
    ruta = c["url"]
    lugar = ", ".join(x for x in [c.get("barrio"), c["ciudad"]] if x)
    titulo = f"{c['tipo_plural']} en {c['ops']} en {c['nombre']}, {lugar} | PETRA"
    n = len(c["inmuebles"])
    desc = (f"{c['tipo_plural']} en {c['ops']} en el conjunto {c['nombre']}"
            + (f", barrio {c['barrio']}" if c.get("barrio") else "") + (f" ({c['localidad']})" if c.get("localidad") else "")
            + f", {c['ciudad']}. " + (f"{n} inmuebles con habitaciones y m². " if n else "Fotos, ubicación y oferta disponible. ")
            + "Escríbenos por WhatsApp y agenda tu visita.")
    items = [("Inicio", "/"), (c["ciudad"], f"/ciudades/{c['ciudad_slug']}/")]
    if c.get("barrio"):
        items.append((c["barrio"], f"/barrios/{c['barrio_slug']}/"))
    items.append((c["nombre"], ruta))
    mig, mig_ld = migas(items)
    ops_btn = [o for o in ("arriendo", "venta") if o in c["ops"]]
    botones = "".join(boton_wa(msg_conj(c, o), f"Ver {'arriendos' if o == 'arriendo' else 'ventas'} por WhatsApp", c["nombre"], "", o,
                               "btn wa" if k == 0 else "btn") for k, o in enumerate(ops_btn))
    fotos = c["fotos_ok"]
    galeria = ('<div class="galeria">' + "".join(foto_html(f, k == 0) for k, f in enumerate(fotos)) + "</div>") if fotos else \
        '<p class="nota">Aún no tenemos fotos publicadas de este conjunto. Pídelas por WhatsApp.</p>'
    videos = "".join(f'<button class="video" data-id="{e(v["youtube"])}" aria-label="Reproducir video: {e(v["titulo"])}">'
                     f'<img src="https://i.ytimg.com/vi_webp/{e(v["youtube"])}/hqdefault.webp" alt="{e(v["titulo"])}" loading="lazy" width="480" height="360">'
                     f'<span>▶ {e(v["titulo"])}</span></button>' for v in c.get("videos", []))
    q = urllib.parse.quote(", ".join(x for x in [c.get("direccion"), c.get("barrio"), c["ciudad"], "Colombia"] if x))
    mapa = (f'<iframe class="mapa" title="Mapa de {e(c["nombre"])}" src="https://www.google.com/maps?q={q}&amp;output=embed" loading="lazy" referrerpolicy="no-referrer-when-downgrade"></iframe>'
            if c.get("direccion") else "")
    mapa_link = f'<p><a href="{e(c["mapa"])}" target="_blank" rel="noopener">Abrir en Google Maps</a></p>' if c.get("mapa") else ""
    zonas = ('<ul class="chips">' + "".join(f"<li>{e(z)}</li>" for z in c["zonas_comunes"]) + "</ul>") if c.get("zonas_comunes") else \
        '<p class="nota">Estamos confirmando las zonas comunes con la administración. Pregúntanos por WhatsApp.</p>'
    texto = "".join(f"<p>{e(p)}</p>" for p in c.get("texto", [])) or (
        f"<p>{e(c['nombre'])} es un conjunto de {e(c['tipo_conjunto'])} en {e(lugar)}"
        + (f", en la dirección {e(c['direccion'])}" if c.get("direccion") else "")
        + ". La administración trabaja con PETRA: escríbenos por WhatsApp y te contamos qué hay disponible en arriendo y en venta, con fotos y horario de visita.</p>")
    inv = ('<div class="inv">' + "".join(tarjeta_inm(c, i) for i in c["inmuebles"]) + "</div>") if c["inmuebles"] else \
        f'<p>Todavía no hay inmuebles publicados en {e(c["nombre"])}. Escríbenos y te avisamos apenas haya uno en {e(c["ops"])}.</p>'
    otros = [x for x in conjuntos if x is not c and (x.get("barrio_slug") == c.get("barrio_slug") or x["ciudad_slug"] == c["ciudad_slug"])]
    cuerpo = f"""{mig}
<div class="hero">
<h1>{e(c['tipo_plural'])} en {e(c['ops'])} en {e(c['nombre'])}</h1>
<p class="lead">{e(c.get('direccion') or '')}{' · ' if c.get('direccion') else ''}{e(', '.join(x for x in [c.get('barrio'), c.get('localidad'), c['ciudad']] if x))}</p>
<div class="btns">{botones}{boton_tel(c['nombre'])}</div>
<p class="nota">Te responde {e(S['whatsapp_nombre'])}, {e(S['horario'].rstrip('.'))}.</p>
</div>
<section aria-labelledby="inv-t"><h2 id="inv-t">Inventario disponible</h2>{inv}</section>
<section aria-labelledby="fotos-t"><h2 id="fotos-t">Fotos y videos</h2>{galeria}{videos}</section>
<section aria-labelledby="sobre-t" class="texto"><h2 id="sobre-t">Sobre {e(c['nombre'])}: transporte y lo que hay cerca</h2>{texto}</section>
<section aria-labelledby="zonas-t"><h2 id="zonas-t">Zonas comunes</h2>{zonas}</section>
<section aria-labelledby="ubic-t"><h2 id="ubic-t">Ubicación</h2><p>{e(c.get('direccion') or 'Dirección por confirmar')}, {e(lugar)}.</p>{mapa}{mapa_link}</section>
<section aria-labelledby="mas-t"><h2 id="mas-t">Otros conjuntos en {e(c['ciudad'])}</h2>
<p>{f'<a href="/barrios/{c["barrio_slug"]}/">Inmuebles en {e(c["barrio"])}</a> · ' if c.get('barrio') else ''}<a href="/ciudades/{c['ciudad_slug']}/">Inmuebles en {e(c['ciudad'])}</a> · <a href="/#buscar">Buscar en todos los edificios</a></p>
{('<div class="lista">' + ''.join(tarjeta_conj(x) for x in otros[:6]) + '</div>') if otros else ''}
</section>"""
    complejo = limpiar({
        "@context": "https://schema.org", "@type": "ApartmentComplex" if c.get("tipo_conjunto") != "casas" else "Residence",
        "@id": url_abs(ruta) + "#conjunto", "name": c["nombre"], "url": url_abs(ruta), "description": desc,
        "address": direccion_ld(c), "hasMap": c.get("mapa"),
        "containedInPlace": {"@type": "Place", "name": ", ".join(x for x in [c.get("barrio"), c["ciudad"]] if x)},
        "image": [url_abs(f["src"]) for f in fotos],
        "amenityFeature": [{"@type": "LocationFeatureSpecification", "name": z, "value": True} for z in c.get("zonas_comunes", [])],
        "numberOfAvailableAccommodationUnits": n or None,
        "containsPlace": [{"@type": i["schema_tipo"], "name": i["titulo"], "url": url_abs(i["url"])} for i in c["inmuebles"]],
    })
    pagina(ruta, titulo, desc, cuerpo, [complejo, mig_ld], og_img=c["og"], tipo_pagina="edificio")

    # --- inmuebles
    for i in c["inmuebles"]:
        r = i["url"]
        pr = precio_txt(i)
        partes = [f"{i['tipo_txt']} en {i['operacion']} en {c['corto']}" + (f", barrio {c['barrio']}" if c.get("barrio") else "") + f", {c['ciudad']}."]
        if i["ubic"]:
            partes.append(cap(i["ubic"]) + ".")
        dets = ", ".join(x for x in [f"{i['habitaciones']} habitaciones" if i.get("habitaciones") else "",
                                      f"{i['banos']} baños" if i.get("banos") else "", f"{i['m2']} m²" if i.get("m2") else ""] if x)
        if dets:
            partes.append(dets[0].upper() + dets[1:] + ".")
        partes.append(f"Precio: {pr}." if pr else "Precio: consultar.")
        partes.append("Escríbenos por WhatsApp y agenda tu visita.")
        d = " ".join(partes)
        it = items + [(i["tipo_txt"] + (" · " + i["ubic"] if i["ubic"] else ""), r)]
        it[-2] = (c["nombre"], ruta)
        mig, mig_ld = migas(it)

        def dato(etq, val):
            return f'<div class="dato"><small>{etq}</small><b>{val}</b></div>' if val else f'<div class="dato"><small>{etq}</small><b class="consultar">Consultar</b></div>'
        datos = "".join([
            dato("Precio", e(pr) if pr else ""), dato("Habitaciones", i.get("habitaciones")), dato("Baños", i.get("banos")),
            dato("Área", f"{i['m2']} m²" if i.get("m2") else ""),
            dato("Operación", i["operacion"].capitalize()),
            dato("Ubicación en el conjunto", e(cap(i["ubic"])) if i["ubic"] else ""),
        ])
        chips = "".join(f"<li>{e(x)}</li>" for x in i.get("caracteristicas", []))
        hermanos = [x for x in c["inmuebles"] if x is not i]
        cuerpo = f"""{mig}
<div class="hero">
<h1>{e(i['titulo'])}</h1>
<p class="lead">{e(c['nombre'])} · {e(c.get('direccion') or '')}{', ' if c.get('direccion') else ''}{e(lugar)} · Ref. {e(i['ref'])}</p>
<div class="datos">{datos}</div>
{'<ul class="chips">' + chips + '</ul>' if chips else ''}
<div class="btns">{boton_wa(msg_inm(c, i), 'Preguntar por WhatsApp', c['nombre'], i['ref'], i['operacion'])}{boton_tel(c['nombre'])}</div>
<p class="nota">Te mandamos fotos del inmueble y agendamos la visita con una Agente PETRA del conjunto.</p>
</div>
<section aria-labelledby="conj-t"><h2 id="conj-t">El conjunto: {e(c['nombre'])}</h2>
{('<div class="galeria">' + ''.join(foto_html(f) for f in c['fotos_ok'][:2]) + '</div>') if c['fotos_ok'] else ''}
<p>{e((c.get('texto') or [''])[0])}</p>
<p><a href="{ruta}">Ver {e(c['nombre'])}: inventario, fotos, mapa y zonas comunes</a></p>
</section>
{('<section aria-labelledby="otros-t"><h2 id="otros-t">Otros inmuebles en ' + e(c['nombre']) + '</h2><div class="inv">' + ''.join(tarjeta_inm(c, x) for x in hermanos[:6]) + '</div></section>') if hermanos else ''}
<section><p>{f'<a href="/barrios/{c["barrio_slug"]}/">Inmuebles en {e(c["barrio"])}</a> · ' if c.get('barrio') else ''}<a href="/ciudades/{c['ciudad_slug']}/">Inmuebles en {e(c['ciudad'])}</a> · <a href="/">Inicio</a></p></section>"""
        oferta = limpiar({"@type": "Offer", "businessFunction": "http://purl.org/goodrelations/v1#" + ("LeaseOut" if i["operacion"] == "arriendo" else "Sell"),
                          "priceCurrency": "COP", "price": i.get("precio"), "availability": "https://schema.org/InStock",
                          "url": url_abs(r), "offeredBy": {"@id": DOM + "/#petra"}})
        listing = limpiar({
            "@context": "https://schema.org", "@type": "RealEstateListing", "@id": url_abs(r) + "#aviso",
            "name": i["titulo"], "description": d, "url": url_abs(r), "datePosted": i.get("publicado") or HOY,
            "image": [url_abs(f["src"]) for f in c["fotos_ok"]],
            "offers": oferta,
            "mainEntity": {"@type": i["schema_tipo"], "name": i["titulo"], "numberOfRooms": i.get("habitaciones"),
                           "numberOfBedrooms": i.get("habitaciones"), "numberOfBathroomsTotal": i.get("banos"),
                           "floorSize": {"@type": "QuantitativeValue", "value": i["m2"], "unitCode": "MTK"} if i.get("m2") else None,
                           "address": direccion_ld(c), "containedInPlace": {"@id": url_abs(ruta) + "#conjunto"}},
        })
        pagina(r, i["titulo"] + " | PETRA", d, cuerpo, [listing, {"@context": "https://schema.org", **AGENTE_LD}, mig_ld],
               og_img=c["og"], tipo_pagina="inmueble")


def pagina_lista(ruta, h1, titulo, desc, conjs, migas_items, intro, tipo_pagina, extra="", zona=""):
    mig, mig_ld = migas(migas_items)
    inm = [(c, i) for c in conjs for i in c["inmuebles"]]
    cuerpo = f"""{mig}
<div class="hero"><h1>{e(h1)}</h1><p class="lead">{e(intro)}</p>
<div class="btns">{boton_wa("Hola " + S['whatsapp_nombre'] + ", vi {origen} los inmuebles" + (" de " + zona if zona else "") + ". ¿Qué tienen disponible?", 'Preguntar por WhatsApp', zona, '', '')}</div></div>
<section aria-labelledby="ed-t"><h2 id="ed-t">Edificios y conjuntos conectados</h2><div class="lista">{''.join(tarjeta_conj(c) for c in conjs)}</div></section>
{('<section aria-labelledby="in-t"><h2 id="in-t">Inmuebles publicados</h2><div class="inv">' + ''.join(tarjeta_inm(c, i, True) for c, i in inm) + '</div></section>') if inm else ''}
{extra}"""
    lista_ld = {"@context": "https://schema.org", "@type": "CollectionPage", "name": titulo, "url": url_abs(ruta), "description": desc,
                "mainEntity": {"@type": "ItemList", "itemListElement": [
                    {"@type": "ListItem", "position": n + 1, "url": url_abs(c["url"]), "name": c["nombre"]} for n, c in enumerate(conjs)]}}
    pagina(ruta, titulo, desc, cuerpo, [lista_ld, mig_ld], tipo_pagina=tipo_pagina)


# --- barrios
barrios = {}
for c in conjuntos:
    if c.get("barrio"):
        barrios.setdefault(c["barrio_slug"], []).append(c)
for bs, cs in barrios.items():
    c0 = cs[0]
    tipos = " y ".join(sorted({c["tipo_plural"].lower() for c in cs})).capitalize()
    ops = ops_texto({i["operacion"] for c in cs for i in c["inmuebles"]})
    n = sum(len(c["inmuebles"]) for c in cs)
    pagina_lista(f"/barrios/{bs}/", f"{tipos} en {ops} en {c0['barrio']}, {c0['ciudad']}",
                 f"{tipos} en {ops} en {c0['barrio']}, {c0['ciudad']} | PETRA",
                 f"{tipos} en {ops} en el barrio {c0['barrio']}" + (f" ({c0['localidad']})" if c0.get("localidad") else "") + f", {c0['ciudad']}: "
                 + ", ".join(c["nombre"] for c in cs) + (f". {n} inmuebles publicados" if n else "") + ". Escríbenos por WhatsApp.",
                 cs, [("Inicio", "/"), (c0["ciudad"], f"/ciudades/{c0['ciudad_slug']}/"), (c0["barrio"], f"/barrios/{bs}/")],
                 f"Conjuntos conectados a PETRA en {c0['barrio']}" + (f", localidad de {c0['localidad']}" if c0.get("localidad") else "") + f", {c0['ciudad']}.",
                 "barrio", zona=c0["barrio"])

# --- ciudades
ciudades = {}
for c in conjuntos:
    ciudades.setdefault(c["ciudad_slug"], []).append(c)
for cs_slug, cs in ciudades.items():
    ciudad = cs[0]["ciudad"]
    bl = sorted({(c["barrio_slug"], c["barrio"]) for c in cs if c.get("barrio")}, key=lambda x: x[1])
    extra = ('<section aria-labelledby="ba-t"><h2 id="ba-t">Barrios</h2><ul class="chips">'
             + "".join(f'<li><a href="/barrios/{s}/">{e(b)}</a></li>' for s, b in bl) + "</ul></section>") if bl else ""
    n = sum(len(c["inmuebles"]) for c in cs)
    pagina_lista(f"/ciudades/{cs_slug}/", f"Apartamentos y casas en venta y arriendo en {ciudad}",
                 f"Apartamentos y casas en venta y arriendo en {ciudad} | Conjuntos conectados | PETRA",
                 f"Apartamentos y casas en venta y arriendo en {ciudad}, conjunto por conjunto: " + ", ".join(b for _, b in bl)
                 + (f". {n} inmuebles publicados" if n else "") + ". Escríbenos por WhatsApp y agenda tu visita.",
                 cs, [("Inicio", "/"), (ciudad, f"/ciudades/{cs_slug}/")],
                 f"{len(cs)} conjuntos conectados a PETRA en {ciudad}. Elige el conjunto o el barrio, o pregúntanos por WhatsApp.",
                 "ciudad", extra, zona=ciudad)

# --- índice de edificios
pagina_lista("/conjuntos/", "Edificios y conjuntos conectados a PETRA",
             "Edificios y conjuntos conectados: apartamentos y casas en venta y arriendo | PETRA",
             "Todos los edificios y conjuntos conectados a PETRA con su inventario de apartamentos y casas en venta y arriendo. "
             + ", ".join(c["nombre"] for c in conjuntos) + ".",
             conjuntos, [("Inicio", "/"), ("Edificios", "/conjuntos/")],
             "En cada conjunto hay un QR de PETRA. Aquí ves la misma oferta: elige el edificio y escríbenos por WhatsApp.", "conjuntos")

# --- redirecciones de las URL del PR 6
for viejo, nuevo in D.get("redirecciones", {}).items():
    destino = "/" + nuevo.strip("/") + "/"
    escribir(viejo.strip("/") + "/index.html", f"""<!doctype html>
<html lang="es-CO"><head><meta charset="utf-8"><title>Redirigiendo…</title>
<meta name="robots" content="noindex,follow"><link rel="canonical" href="{url_abs(destino)}">
<meta http-equiv="refresh" content="0;url={destino}">
<script>location.replace('{destino}'+location.search+location.hash)</script>
</head><body><p><a href="{destino}">Ir a la nueva página</a></p></body></html>
""")

# --------------------------------------------------------------- landing

def landing():
    ruta = os.path.join(RAIZ, "index.html")
    doc = open(ruta, encoding="utf-8").read()
    ciudades_txt = ", ".join(sorted({c["ciudad"] for c in conjuntos}))
    titulo = f"Apartamentos y casas en venta y arriendo en {ciudades_txt} | PETRA Plataforma Inmobiliaria"
    desc = ("Busca apartamentos y casas en venta y arriendo en conjuntos conectados de " + ciudades_txt + ": "
            + ", ".join(c["corto"] for c in conjuntos) + ". Inventario real y visitas por WhatsApp con una Agente PETRA.")
    web_ld = {"@context": "https://schema.org", "@type": "WebSite", "name": "PETRA Plataforma Inmobiliaria", "url": DOM + "/", "inLanguage": "es-CO"}
    agente = {"@context": "https://schema.org", **AGENTE_LD, "image": DOM + "/img/chat.jpg",
              "description": "Plataforma inmobiliaria que conecta cada edificio por WhatsApp: arriendo, venta y administración de inmuebles con Agentes PETRA.",
              "address": {"@type": "PostalAddress", "addressLocality": "Bogotá", "addressCountry": "CO"},
              "makesOffer": [{"@type": "Offer", "itemOffered": {"@type": "Service", "name": n}} for n in ("Arriendo de inmuebles", "Venta de inmuebles", "Administración de inmuebles")]}
    head = "\n".join([meta_head(titulo, desc, "/", S["og_imagen_defecto"]), ga_head(), jsonld(web_ld), jsonld(agente),
                      "<style>" + CSS_LANDING + "</style>"])
    doc = reemplazar(doc, "HEAD", head)

    ops = {"venta": "Venta", "arriendo": "Arriendo"}
    tipos = sorted({(i["tipo"], i["tipo_txt"]) for _, i in todos_inm})
    cdes = sorted({(c["ciudad_slug"], c["ciudad"]) for c in conjuntos})
    sel = lambda nombre, etq, opciones: (f'<label>{etq}<select name="{nombre}"><option value="">Todos</option>'
                                         + "".join(f'<option value="{v}">{e(t)}</option>' for v, t in opciones) + "</select></label>")
    bloque = f"""<section id="buscar" class="buscar" aria-labelledby="buscar-t">
<div class="wrap">
<h1 id="buscar-t">Apartamentos y casas en venta y arriendo, <span class="g">edificio por edificio.</span></h1>
<p class="lead">Inventario real de los conjuntos conectados a PETRA en {e(ciudades_txt)}. Busca, mira la ficha y escríbenos por WhatsApp.</p>
<form class="filtros" role="search" onsubmit="return false">
<label class="q">Conjunto, barrio o ciudad<input name="q" type="search" placeholder="Ej.: Torres de Sevilla II, Suba, Tintal" autocomplete="off"></label>
{sel('op', 'Operación', ops.items())}{sel('tipo', 'Tipo', tipos)}{sel('ciudad', 'Ciudad', cdes)}
<label>Habitaciones<select name="hab"><option value="">Todas</option><option value="1">1+</option><option value="2">2+</option><option value="3">3+</option></select></label>
</form>
<p class="conteo" aria-live="polite"></p>
<div class="resultados">{''.join(tarjeta_inm(c, i, True) for c, i in todos_inm)}</div>
<p class="vermas" hidden><button type="button" class="btn">Ver todos los inmuebles</button></p>
<p class="sin" hidden>No encontramos inmuebles con esos filtros. {boton_wa("Hola " + S['whatsapp_nombre'] + ", vi {origen} y estoy buscando un inmueble. ¿Me ayudas?", 'Cuéntanos qué buscas', '', '', '', 'btn wa')}</p>
<h2 class="sub" id="edificios">Edificios conectados</h2>
<div class="edificios">{''.join(tarjeta_conj(c) for c in conjuntos)}</div>
<p class="mas"><a href="/conjuntos/">Ver todos los edificios</a>{''.join(f' · <a href="/ciudades/{s}/">{e(n)}</a>' for s, n in cdes)}{''.join(f' · <a href="/barrios/{s}/">{e(cs[0]["barrio"])}</a>' for s, cs in barrios.items())}</p>
</div>
</section>
<script>
(function(){{
var f=document.querySelector('.filtros'),cards=[].slice.call(document.querySelectorAll('.resultados .card')),out=document.querySelector('.conteo'),sin=document.querySelector('.buscar .sin');
function n(s){{return (s||'').toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').replace(/[^a-z0-9]+/g,' ').trim()}}
var vm=document.querySelector('.buscar .vermas'),todo=false;
vm.querySelector('button').addEventListener('click',function(){{todo=true;go()}});
function go(){{var q=n(f.q.value),op=f.op.value,ti=f.tipo.value,ci=f.ciudad.value,h=+f.hab.value||0,k=0,filtro=q||op||ti||ci||h;
cards.forEach(function(c){{var d=c.dataset,ok=(!op||d.op==op)&&(!ti||d.tipo==ti)&&(!ci||d.ciudad==ci)&&(!h||(+d.hab||0)>=h)&&(!q||q.split(' ').every(function(w){{return d.q.indexOf(w)>-1}}));if(ok)k++;c.hidden=!ok||(!filtro&&!todo&&k>6)}});
out.textContent=k+(k==1?' inmueble':' inmuebles');sin.hidden=k>0;vm.hidden=filtro||todo||k<=6;vm.querySelector('button').textContent='Ver los '+k+' inmuebles';}}
f.addEventListener('input',go);f.addEventListener('change',go);go();
}})();
</script>"""
    doc = reemplazar(doc, "BUSCADOR", bloque)
    doc = reemplazar(doc, "JS", JS)
    # fotos de la landing en WebP
    doc = re.sub(r'(<img[^>]*src=")img/([\w-]+)\.jpg"', r'\1img/\2.webp"', doc)
    assert doc.count("<h1") == 1, "la landing debe tener un solo H1"
    open(ruta, "w", encoding="utf-8").write(doc)
    PAGINAS.insert(0, ("/", titulo, desc))


CSS_LANDING = """
.buscar{padding:56px 0 70px;text-align:left}
.buscar h1{font-size:clamp(2rem,5vw,3.6rem);margin:0;max-width:880px}
.buscar .lead{margin:16px 0 0;max-width:640px}
.filtros{margin:28px 0 8px;display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;background:var(--card);padding:14px;border-radius:22px;box-shadow:var(--shadow)}
.filtros label{display:flex;flex-direction:column;gap:4px;font-size:13px;font-weight:600;color:var(--muted)}
.filtros .q{grid-column:1/-1}
.filtros input,.filtros select{font:inherit;font-size:16px;color:var(--ink);padding:10px 12px;border:1px solid var(--line);border-radius:12px;background:#fff;min-height:46px}
.conteo{color:var(--muted);font-size:14px;margin:8px 4px}
.resultados,.edificios{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:14px}
.buscar .card{background:var(--card);border-radius:20px;padding:16px;box-shadow:var(--shadow)}
.buscar .card[hidden]{display:none}
.buscar .card h3{margin:0 0 4px;font-size:18px;line-height:1.3}
.buscar .card h3 a{text-decoration:none}
.buscar .card .meta{color:var(--muted);font-size:14px;margin:0 0 8px}
.buscar .card .fila{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:15px;margin:0}
.buscar .chips{display:flex;flex-wrap:wrap;gap:6px;padding:0;margin:8px 0 0;list-style:none}
.buscar .chips li{background:#EEF2FB;border-radius:999px;padding:2px 10px;font-size:13px}
.buscar .card .btns{margin-top:12px;justify-content:flex-start;gap:8px}
.buscar .card .btn{min-height:40px;padding:8px 14px;font-size:14px;background:var(--bg);border:1px solid var(--line)}
.buscar .card .btn.wa{background:var(--wa);border-color:var(--wa);color:#052E16}
.buscar .btn svg{width:18px;height:18px;fill:currentColor;stroke:none}
.consultar{color:#B4541F}
.buscar .sub{font-size:clamp(1.6rem,3vw,2.2rem);margin:56px 0 18px;text-align:left;max-width:none}
.buscar .mas{margin-top:18px;font-size:15px}
.buscar .sin .btn{margin-top:10px}
.buscar .vermas{margin:16px 0 0}
.buscar .vermas .btn{background:var(--card);border:1px solid var(--line);font:inherit;font-weight:700;cursor:pointer}
"""


def reemplazar(doc, marca, contenido):
    a, b = f"<!-- PETRA:{marca}:INICIO -->", f"<!-- PETRA:{marca}:FIN -->"
    if a not in doc:
        sys.exit(f"Falta el marcador {a} en index.html")
    return doc[:doc.index(a) + len(a)] + "\n" + contenido + "\n" + doc[doc.index(b):]


landing()

# ------------------------------------------------- sitemap, robots, faltantes

titulos = [t for _, t, _ in PAGINAS]
descs = [d for _, _, d in PAGINAS]
dup_t = {t for t in titulos if titulos.count(t) > 1}
dup_d = {d for d in descs if descs.count(d) > 1}
if dup_t or dup_d:
    sys.exit(f"Títulos o descripciones repetidos: {dup_t | dup_d}")

prioridad = lambda r: "1.0" if r == "/" else "0.9" if r.count("/") == 3 and r.startswith("/conjuntos/") else "0.8"
escribir("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
         + "".join(f"  <url><loc>{url_abs(r)}</loc><lastmod>{HOY}</lastmod><priority>{prioridad(r)}</priority></url>\n" for r, _, _ in PAGINAS)
         + "</urlset>\n")
escribir("robots.txt", f"User-agent: *\nAllow: /\nDisallow: /pi/\n\nSitemap: {DOM}/sitemap.xml\n")

lineas = ["# Datos que faltan", "", f"Generado el {HOY} por `pi/web/generar_paginas.py`. Mientras falten, la web muestra «Consultar».", ""]
actual = None
for conj, cosa, que in FALTA:
    if conj != actual:
        lineas += ["", f"## {conj}"]
        actual = conj
    lineas.append(f"- {cosa}: {que}")
escribir("pi/web/FALTANTES.md", "\n".join(lineas) + "\n")

print(f"Listo: {len(PAGINAS)} páginas, {len(todos_inm)} inmuebles, {len(conjuntos)} conjuntos publicados.")
print(f"Faltantes: {len(FALTA)} (ver pi/web/FALTANTES.md)")
