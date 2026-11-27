# Páginas de inmuebles (SEO)

Fuente única: `pi/web/conjuntos.json`. Todo lo demás se genera.

## Agregar o actualizar un conjunto

1. Edita `pi/web/conjuntos.json` (copia un conjunto existente). Campos clave: `nombre`, `ciudad`, `barrio`, `localidad`, `direccion`, `mapa`, `zonas_comunes`, `fotos` (`origen` = URL o ruta + `alt`), `videos` (`youtube` = ID + `titulo`), `texto` (~300 palabras, en párrafos) e `inmuebles`.
2. Pon `"publicar": true`.
3. Corre `python3 pi/web/generar_paginas.py` (necesita Pillow: `pip install pillow`).
4. Revisa `pi/web/FALTANTES.md`, haz commit y merge a `main` (Render publica solo).

Inmueble: `ref`, `tipo` (apartamento, apartaestudio, penthouse, casa, local), `operacion` (venta / arriendo), y si se conocen `precio` (COP), `m2`, `habitaciones`, `banos`, `bloque`, `piso`, `caracteristicas`. Lo que falte se muestra como «Consultar»: nunca se inventa.

## Medición

- `sitio.ga4_id`: ID de Google Analytics 4 (`G-…`). Cada clic a WhatsApp envía el evento `whatsapp_click` con `conjunto`, `inmueble`, `operacion`, `tipo_pagina` y `fuente`. Los clics a teléfono envían `telefono_click`.
- `sitio.google_site_verification`: código de la metaetiqueta de Search Console (o verifica por DNS y déjalo vacío).
- `?fuente=qr|tiktok|ig|fb|yt|grupo|marketplace|fincaraiz|google` cambia el mensaje de WhatsApp («vi … en TikTok»).
