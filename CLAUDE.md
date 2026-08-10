# CLAUDE.md

## Qué hace

Revisa las carpetas IMAP configuradas (buzón de disroot) en busca de correos
de notificación de wantlist de Discogs ("un ítem de tu wantlist está a la
venta"), extrae los datos de cada oferta (artista, título, condición,
vendedor, precio, enlace) y los envía por Telegram. Al enviar con éxito,
marca el correo original como leído (`\Seen`) — esa es la única forma de
deduplicación: un correo ya marcado como leído no se vuelve a procesar.

Pensado para ejecutarse periódicamente vía Ofelia (p.ej. cada pocas horas):
como solo actúa sobre correos `UNSEEN`, cada ejecución detecta tanto ofertas
nuevas como el caso "llevaba una semana sin ejecutarse".

## Estructura del HTML de Discogs

El correo de Discogs usa un layout de tablas anidadas (`hse-column`,
`hse-column-container`) donde la imagen del producto y sus metadatos
**no** están en el mismo bloque:

- `<img alt="{título}" src="https://i.discogs.com/...">` vive dentro de un
  `div.hse-column` que solo contiene la imagen envuelta en un enlace de
  tracking (`ct.discogs.com`).
- Los metadatos reales (artista, `Media:`, `Sleeve:`, `Ships from:`,
  `Seller:`, `Seller Rating:`, precio, enlace real del listado) están en el
  **siguiente `div.hse-column` hermano** (`find_next_sibling`), como texto
  plano separado por `<p>`/`<a>`, no en atributos.

`parse_wantlist_email()` en `discogs_wantlist_notifier.py` ancla la
búsqueda en cada `<img>` de producto y navega al hermano siguiente para
extraer el texto — un regex directo sobre el HTML aplanado falla porque el
bloque de imagen y el bloque de texto quedan intercalados con basura de
otras columnas (estilos, ids de tracking en base64, etc.).

## Variables de entorno

Ver `.env.example`. `IMAP_FOLDERS` va separado por `|` (no por espacio,
los nombres de carpeta pueden contener espacios). El token/chat de
Telegram pueden reutilizar el bot admin ya configurado en `bot_conciertos`
(`ADMIN_BOT_TOKEN`/`ADMIN_CHAT_ID` en su `.env`) — son variables
independientes aquí para poder apuntar a otro bot si se prefiere.

## Ejecución manual / pruebas

```bash
python discogs_wantlist_notifier.py --dry-run
```

`--dry-run` no envía a Telegram ni marca nada como leído; imprime los
ítems detectados por stdout.
