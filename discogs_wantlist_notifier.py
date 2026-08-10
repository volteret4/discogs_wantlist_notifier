#!/usr/bin/env python3
"""Revisa el correo de disroot en busca de correos de oferta del wantlist de
Discogs y envía cada ítem nuevo por Telegram, marcando el correo como leído."""

import argparse
import logging
import os
import sys
from email import message_from_bytes
from email.header import decode_header
from imaplib import IMAP4_SSL

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

IMAP_SERVER = os.environ["IMAP_SERVER"]
IMAP_PORT = int(os.environ.get("IMAP_PORT") or 993)
IMAP_EMAIL = os.environ["IMAP_EMAIL"]
IMAP_PASSWORD = os.environ["IMAP_PASSWORD"]
IMAP_FOLDERS = [f for f in os.environ.get("IMAP_FOLDERS", "").split("|") if f]

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("ADMIN_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID") or os.environ.get("ADMIN_CHAT_ID", "")

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger(__name__)


def decode_subject(raw):
    parts = decode_header(raw or "")
    out = ""
    for text, enc in parts:
        out += text.decode(enc or "utf-8", errors="replace") if isinstance(text, bytes) else text
    return out


def select_folder(m, folder):
    typ, _ = m.select(folder)
    if typ != "OK":
        typ, _ = m.select('"' + folder + '"')
    return typ


def get_html_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
        return None
    if msg.get_content_type() == "text/html":
        return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", errors="replace")
    return None


def parse_wantlist_email(html):
    """Extrae los ítems en oferta de un correo de notificación de wantlist de Discogs."""
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for img in soup.find_all("img", src=lambda s: s and "i.discogs.com" in s):
        title = img.get("alt", "").strip()
        img_col = img.find_parent("div", class_="hse-column")
        if img_col is None:
            continue
        info_col = img_col.find_next_sibling("div", class_="hse-column")
        if info_col is None:
            continue
        links = info_col.find_all("a")
        listing_url = links[0]["href"] if links else None
        fields = [f.strip() for f in info_col.get_text("|", strip=True).split("|") if f.strip()]

        item = {
            "title": title, "url": listing_url, "artist": None, "media": None,
            "sleeve": None, "ships_from": None, "seller": None, "rating": None, "price": None,
        }
        seller_next = False
        for f in fields:
            if f == title or f in ("Add to cart", "View all new Wantlist items"):
                continue
            if f.startswith("Media:"):
                item["media"] = f.split(":", 1)[1].strip()
            elif f.startswith("Sleeve:"):
                item["sleeve"] = f.split(":", 1)[1].strip()
            elif f.startswith("Ships from:"):
                item["ships_from"] = f.split(":", 1)[1].strip()
            elif f == "Seller:":
                seller_next = True
            elif seller_next:
                item["seller"] = f
                seller_next = False
            elif f.startswith("Seller Rating:"):
                item["rating"] = f.split(":", 1)[1].strip()
            elif f.startswith(("€", "$")) or "EUR" in f or "USD" in f:
                item["price"] = f
            elif item["artist"] is None:
                item["artist"] = f
        if item["url"]:
            items.append(item)
    return items


def format_item_message(item):
    lines = [f"🛒 Nueva oferta en tu wantlist de Discogs"]
    header = item["title"] if not item["artist"] else f"{item['artist']} - {item['title']}"
    lines.append(f"💿 {header}")
    cond = " | ".join(p for p in (
        f"Media: {item['media']}" if item["media"] else None,
        f"Sleeve: {item['sleeve']}" if item["sleeve"] else None,
    ) if p)
    if cond:
        lines.append(cond)
    if item["ships_from"]:
        lines.append(f"📍 Envía desde: {item['ships_from']}")
    if item["seller"]:
        seller_line = f"👤 Vendedor: {item['seller']}"
        if item["rating"]:
            seller_line += f" ({item['rating']})"
        lines.append(seller_line)
    if item["price"]:
        lines.append(f"💰 {item['price']}")
    lines.append(item["url"])
    return "\n".join(lines)


def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID no configurados")
        return False
    resp = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "disable_web_page_preview": False},
        timeout=15,
    )
    if resp.status_code != 200:
        log.error("Telegram HTTP %s: %s", resp.status_code, resp.text)
        return False
    return True


def process_folder(m, folder, dry_run):
    typ = select_folder(m, folder)
    if typ != "OK":
        log.warning("No se pudo seleccionar la carpeta %s", folder)
        return 0

    typ, data = m.search(None, "UNSEEN")
    if typ != "OK" or not data[0]:
        log.info("%s: sin correos nuevos", folder)
        return 0

    ids = data[0].split()
    log.info("%s: %d correo(s) nuevo(s)", folder, len(ids))
    sent = 0
    for msg_id in ids:
        typ, msgdata = m.fetch(msg_id, "(RFC822)")
        if typ != "OK" or not msgdata or not msgdata[0]:
            log.warning("No se pudo leer el mensaje %s en %s", msg_id, folder)
            continue
        msg = message_from_bytes(msgdata[0][1])
        subject = decode_subject(msg.get("Subject", ""))
        html = get_html_body(msg)
        if not html:
            log.warning("Mensaje sin cuerpo HTML: %s", subject)
            continue

        items = parse_wantlist_email(html)
        if not items:
            log.warning("No se detectaron ítems en: %s", subject)
            continue

        ok = True
        for item in items:
            text = format_item_message(item)
            if dry_run:
                print(text)
                print("---")
            else:
                ok = send_telegram(text) and ok

        if ok:
            sent += len(items)
            if not dry_run:
                m.store(msg_id, "+FLAGS", "\\Seen")
        else:
            log.error("Fallo enviando ítems del mensaje %s (%s); se deja como no leído", msg_id, subject)

    return sent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="No envía a Telegram ni marca como leído; imprime por stdout")
    args = parser.parse_args()

    if not IMAP_FOLDERS:
        log.error("IMAP_FOLDERS no configurado")
        sys.exit(1)

    m = IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    m.login(IMAP_EMAIL, IMAP_PASSWORD)

    total = 0
    try:
        for folder in IMAP_FOLDERS:
            total += process_folder(m, folder, args.dry_run)
    finally:
        m.logout()

    log.info("Total ítems procesados: %d", total)


if __name__ == "__main__":
    main()
