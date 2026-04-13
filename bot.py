"""
bot.py — Handles Telegram commands to manage tracked listings.
Runs as a separate GitHub Actions job triggered by webhook (polling mode).

Commands:
  /add <url>      — Add a new OLX listing to track
  /list           — Show all currently tracked listings
  /remove <index> — Remove listing by number (from /list)
  /help           — Show available commands
"""

import os
import json
import time
import re
import requests

BOT_TOKEN   = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID     = os.environ["TELEGRAM_CHAT_ID"]
CONFIG_FILE = "data/listings.json"
OFFSET_FILE = "data/telegram_offset.json"


def send(text, parse_mode="Markdown"):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": parse_mode, "disable_web_page_preview": True}, timeout=15)


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_updates(offset=None):
    params = {"timeout": 20, "allowed_updates": ["message"]}
    if offset:
        params["offset"] = offset
    resp = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates", params=params, timeout=30)
    return resp.json().get("result", [])


def is_valid_olx_url(url):
    return re.match(r'https?://(www\.)?olx\.ro/', url) is not None


def cmd_add(args):
    listings = load_json(CONFIG_FILE, [])
    if not args:
        send("❌ Trimite un URL după comandă.\nExemplu: `/add https://www.olx.ro/d/oferta/...`")
        return

    url = args.strip().split()[0]
    if not is_valid_olx_url(url):
        send("❌ URL invalid. Trebuie să fie un link de pe *olx.ro*.")
        return

    # Check duplicate
    if any(l["url"] == url for l in listings):
        send("⚠️ Acest anunț este deja urmărit!")
        return

    listings.append({"url": url})
    save_json(CONFIG_FILE, listings)
    send(f"✅ Anunț adăugat!\n🔗 {url}\n\nVa fi urmărit începând de mâine la 09:00.")


def cmd_list():
    listings = load_json(CONFIG_FILE, [])
    if not listings:
        send("📋 Nu urmărești niciun anunț.\nFolosește `/add <url>` pentru a adăuga unul.")
        return

    lines = ["📋 *Anunțuri urmărite:*", ""]
    for i, l in enumerate(listings, 1):
        url   = l["url"]
        title = l.get("title", "*(titlu necunoscut)*")
        lines.append(f"*{i}.* {title}")
        lines.append(f"    🔗 {url}")
        lines.append("")

    lines.append(f"Total: *{len(listings)}* anunțuri")
    lines.append("Șterge cu `/remove <număr>`")
    send("\n".join(lines))


def cmd_remove(args):
    listings = load_json(CONFIG_FILE, [])
    if not listings:
        send("📋 Nu ai niciun anunț de șters.")
        return

    if not args:
        send("❌ Specifică numărul anunțului.\nExemplu: `/remove 2`\nVezi lista cu `/list`")
        return

    try:
        idx = int(args.strip()) - 1
        if idx < 0 or idx >= len(listings):
            raise ValueError
    except ValueError:
        send(f"❌ Număr invalid. Alege între 1 și {len(listings)}.")
        return

    removed = listings.pop(idx)
    save_json(CONFIG_FILE, listings)
    url = removed["url"]
    title = removed.get("title", url)
    send(f"🗑 Anunț șters:\n*{title}*\n🔗 {url}")


def cmd_help():
    send(
        "🤖 *OLX Tracker — Comenzi*\n\n"
        "`/add <url>` — Adaugă un anunț OLX\n"
        "`/list` — Afișează anunțurile urmărite\n"
        "`/remove <nr>` — Șterge un anunț\n"
        "`/help` — Afișează această listă\n\n"
        "Raportul zilnic se trimite automat la *09:00* 🇷🇴"
    )


def process_update(update):
    msg = update.get("message", {})
    text = msg.get("text", "").strip()
    chat_id = str(msg.get("chat", {}).get("id", ""))

    # Only respond to the authorized chat
    if chat_id != str(CHAT_ID):
        print(f"Ignored message from unauthorized chat {chat_id}")
        return

    if not text.startswith("/"):
        return

    parts   = text.split(None, 1)
    command = parts[0].lower().split("@")[0]  # handle /cmd@botname format
    args    = parts[1] if len(parts) > 1 else ""

    print(f"Command: {command} | Args: {args}")

    if command == "/add":
        cmd_add(args)
    elif command == "/list":
        cmd_list()
    elif command == "/remove":
        cmd_remove(args)
    elif command == "/help" or command == "/start":
        cmd_help()
    else:
        send(f"❓ Comandă necunoscută: `{command}`\nScrie `/help` pentru lista de comenzi.")


def main():
    """Poll for new Telegram messages for up to 55 seconds (safe for GitHub Actions 6min limit)."""
    offset_data = load_json(OFFSET_FILE, {"offset": None})
    offset      = offset_data.get("offset")
    deadline    = time.time() + 55  # poll for 55 seconds max
    processed   = 0

    print(f"Starting bot polling (offset={offset})...")

    while time.time() < deadline:
        updates = get_updates(offset)
        for update in updates:
            process_update(update)
            offset = update["update_id"] + 1
            processed += 1

        if updates:
            save_json(OFFSET_FILE, {"offset": offset})

        if not updates:
            time.sleep(3)

    print(f"Bot polling finished. Processed {processed} updates.")


if __name__ == "__main__":
    main()
