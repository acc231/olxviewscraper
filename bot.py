"""
bot.py — OLX Tracker Telegram Bot

Commands:
  /add <url> [nume]   — Adaugă anunț (scrape imediat ca punct de start)
  /list               — Lista anunțurilor cu delta vizualizări
  /remove <nr>        — Șterge anunț
  /rename <nr> <nume> — Redenumește anunț
  /stats <nr>         — Istoric complet
  /help               — Comenzi disponibile
"""

import os
import json
import time
import re
import requests

BOT_TOKEN    = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID      = os.environ["TELEGRAM_CHAT_ID"]  # primary chat
CONFIG_FILE  = "data/listings.json"
HISTORY_FILE = "data/views_history.json"
OFFSET_FILE  = "data/telegram_offset.json"
CHATS_FILE   = "data/allowed_chats.json"


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_allowed_chats():
    """Load allowed chat IDs. Always includes primary CHAT_ID."""
    chats = load_json(CHATS_FILE, [])
    primary = str(CHAT_ID)
    if primary not in [str(c) for c in chats]:
        chats.append(primary)
        save_json(CHATS_FILE, chats)
    return [str(c) for c in chats]


def send_to(chat_id, text, parse_mode="Markdown"):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }, timeout=15)
    except Exception as e:
        print(f"Failed to send to {chat_id}: {e}")


def send(text, chat_id=None, parse_mode="Markdown"):
    """Send to specific chat or all allowed chats."""
    if chat_id:
        send_to(chat_id, text, parse_mode)
    else:
        for cid in get_allowed_chats():
            send_to(cid, text, parse_mode)


def get_updates(offset=None):
    params = {"timeout": 20, "allowed_updates": ["message"]}
    if offset:
        params["offset"] = offset
    resp = requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
        params=params, timeout=30
    )
    return resp.json().get("result", [])


def is_valid_olx_url(url):
    return bool(re.match(r'https?://(www\.)?olx\.ro/', url))


def extract_price_number(price_str):
    if not price_str or price_str == "—":
        return None
    nums = re.sub(r'[^\d]', '', str(price_str))
    try:
        return int(nums) if nums else None
    except ValueError:
        return None




# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_add(args, reply_chat):
    listings = load_json(CONFIG_FILE, [])
    if not args:
        send("❌ Exemplu:\n`/add https://www.olx.ro/... Kadjar Albastru`", chat_id=reply_chat)
        return

    parts = args.strip().split(None, 1)
    url   = parts[0]
    name  = parts[1].strip() if len(parts) > 1 else None

    if not is_valid_olx_url(url):
        send("❌ URL invalid. Trebuie să fie un link de pe *olx.ro*.", chat_id=reply_chat)
        return

    if any(l["url"] == url for l in listings):
        send("⚠️ Acest anunț este deja urmărit!", chat_id=reply_chat)
        return

    from datetime import datetime
    today_str = datetime.now().strftime("%Y-%m-%d")

    entry = {
        "url": url,
        "added_date": today_str,
    }
    if name:
        entry["custom_name"] = name

    listings.append(entry)
    save_json(CONFIG_FILE, listings)

    display = name or url
    send(
        f"✅ *{display}* adăugat!\n"
        f"🔗 {url}\n\n"
        f"📊 Prima citire vine mâine la *09:00* — atunci începe Ziua 1.\n"
        f"Poți adăuga mai multe linkuri cu `/add` înainte de atunci.",
        chat_id=reply_chat
    )


def cmd_list(reply_chat):
    listings = load_json(CONFIG_FILE, [])
    history  = load_json(HISTORY_FILE, {})

    if not listings:
        send("📋 Nu urmărești niciun anunț.\nFolosește `/add <url>` pentru a adăuga unul.", chat_id=reply_chat)
        return

    lines = ["📋 *Anunțuri urmărite:*", ""]

    for i, l in enumerate(listings, 1):
        url         = l["url"]
        name        = l.get("custom_name") or l.get("title") or "*(titlu necunoscut)*"
        url_history = history.get(url, [])
        days        = len(url_history)

        latest    = url_history[-1] if url_history else None
        views     = latest.get("views") if latest else None
        price     = latest.get("price", "—") if latest else "—"
        views_str = f"{views:,}" if views is not None else "—"

        valid = [e for e in url_history if e.get("views") is not None]
        delta_str = ""
        if len(valid) >= 2:
            delta = valid[-1]["views"] - valid[-2]["views"]
            sign  = "+" if delta >= 0 else ""
            arrow = "📈" if delta > 0 else ("📉" if delta < 0 else "➡️")
            delta_str = f" {arrow}{sign}{delta}"

        lines.append(f"*{i}.* {name}")
        lines.append(f"    👁 {views_str}{delta_str}  |  💰 {price}  |  📆 Ziua {days}")
        lines.append(f"    🔗 {url}")
        lines.append("")

    lines.append(f"Total: *{len(listings)}* anunțuri")
    lines.append("Detalii cu `/stats <nr>` • Șterge cu `/remove <nr>`")
    send("\n".join(lines), chat_id=reply_chat)


def cmd_remove(args, reply_chat):
    listings = load_json(CONFIG_FILE, [])
    if not listings:
        send("📋 Nu ai niciun anunț de șters.", chat_id=reply_chat)
        return

    if not args:
        send("❌ Exemplu: `/remove 2`", chat_id=reply_chat)
        return

    try:
        idx = int(args.strip()) - 1
        if idx < 0 or idx >= len(listings):
            raise ValueError
    except ValueError:
        send(f"❌ Număr invalid. Alege între 1 și {len(listings)}.", chat_id=reply_chat)
        return

    removed = listings.pop(idx)
    save_json(CONFIG_FILE, listings)
    name = removed.get("custom_name") or removed.get("title") or removed["url"]
    send(f"🗑 Anunț șters:\n*{name}*", chat_id=reply_chat)


def cmd_rename(args, reply_chat):
    listings = load_json(CONFIG_FILE, [])
    if not args:
        send("❌ Exemplu: `/rename 1 Kadjar Albastru Cluj`", chat_id=reply_chat)
        return

    parts = args.strip().split(None, 1)
    if len(parts) < 2:
        send("❌ Exemplu: `/rename 1 Kadjar Albastru Cluj`", chat_id=reply_chat)
        return

    try:
        idx = int(parts[0]) - 1
        if idx < 0 or idx >= len(listings):
            raise ValueError
    except ValueError:
        send(f"❌ Număr invalid. Alege între 1 și {len(listings)}.", chat_id=reply_chat)
        return

    new_name = parts[1].strip()
    listings[idx]["custom_name"] = new_name
    save_json(CONFIG_FILE, listings)
    send(f"✏️ Anunțul {idx+1} se numește acum: *{new_name}*", chat_id=reply_chat)


def cmd_stats(args, reply_chat):
    listings = load_json(CONFIG_FILE, [])
    history  = load_json(HISTORY_FILE, {})

    if not listings:
        send("📋 Nu urmărești niciun anunț.", chat_id=reply_chat)
        return

    if not args:
        send("❌ Exemplu: `/stats 1`", chat_id=reply_chat)
        return

    try:
        idx = int(args.strip()) - 1
        if idx < 0 or idx >= len(listings):
            raise ValueError
    except ValueError:
        send(f"❌ Număr invalid. Alege între 1 și {len(listings)}.", chat_id=reply_chat)
        return

    listing     = listings[idx]
    url         = listing["url"]
    name        = listing.get("custom_name") or listing.get("title") or url
    url_history = history.get(url, [])

    if not url_history:
        send(f"📊 *{name}*\n\nNu există date încă.", chat_id=reply_chat)
        return

    lines = [f"📊 *{name}*", f"🔗 {url}", f"{'━'*28}", ""]

    for day_num, entry in enumerate(url_history, 1):
        date  = entry.get("date", "")[5:]
        views = entry.get("views")
        price = entry.get("price", "—")

        prev_views  = [e for e in url_history[:url_history.index(entry)] if e.get("views") is not None]
        prev_prices = [e for e in url_history[:url_history.index(entry)] if e.get("price") and e.get("price") != "—"]

        if prev_views and views is not None:
            delta = views - prev_views[-1]["views"]
            sign  = "+" if delta >= 0 else ""
            arrow = "📈" if delta > 0 else ("📉" if delta < 0 else "➡️")
            views_str = f"{views:,} {arrow}{sign}{delta}"
        else:
            views_str = f"{views:,}" if views is not None else "—"

        price_str = price
        if prev_prices and price and price != "—":
            prev_p = extract_price_number(prev_prices[-1]["price"])
            curr_p = extract_price_number(price)
            if prev_p and curr_p and prev_p != curr_p:
                diff  = curr_p - prev_p
                sign  = "+" if diff >= 0 else ""
                emoji = "💸" if diff < 0 else "📈"
                price_str = f"{price} {emoji}{sign}{diff:,}"

        lines.append(f"*Ziua {day_num}* ({date})")
        lines.append(f"  👁 {views_str}  |  💰 {price_str}")

    lines.append("")
    lines.append(f"{'━'*28}")

    valid_views  = [e for e in url_history if e.get("views") is not None]
    valid_prices = [e for e in url_history if e.get("price") and e.get("price") != "—"]

    if len(valid_views) >= 2:
        total = valid_views[-1]["views"] - valid_views[0]["views"]
        avg   = round(total / (len(valid_views) - 1)) if len(valid_views) > 1 else 0
        sign  = "+" if total >= 0 else ""
        lines.append(f"👁 Total: *{sign}{total}*  |  📊 Medie: *{sign}{avg}*/zi")

    if len(valid_prices) >= 2:
        p1 = extract_price_number(valid_prices[0]["price"])
        p2 = extract_price_number(valid_prices[-1]["price"])
        if p1 and p2:
            diff  = p2 - p1
            sign  = "+" if diff >= 0 else ""
            emoji = "💸" if diff < 0 else ("📈" if diff > 0 else "➡️")
            lines.append(f"💰 Preț: *{valid_prices[0]['price']}* → *{valid_prices[-1]['price']}* ({sign}{diff:,}) {emoji}")

    lines.append(f"📆 Urmărit de *{len(url_history)}* zile")

    full_text = "\n".join(lines)
    if len(full_text) > 4000:
        short = [f"📊 *{name}* — ultimele 20 zile", f"🔗 {url}", f"{'━'*28}", ""]
        for day_num, entry in enumerate(url_history[-20:], len(url_history) - 19):
            date  = entry.get("date", "")[5:]
            views = entry.get("views")
            price = entry.get("price", "—")
            prev  = [e for e in url_history[:url_history.index(entry)] if e.get("views") is not None]
            if prev and views is not None:
                delta = views - prev[-1]["views"]
                sign  = "+" if delta >= 0 else ""
                views_str = f"{views:,} ({sign}{delta})"
            else:
                views_str = f"{views:,}" if views is not None else "—"
            short.append(f"*Z{day_num}* ({date}): 👁 {views_str}  💰 {price}")
        send("\n".join(short), chat_id=reply_chat)
    else:
        send(full_text, chat_id=reply_chat)


def cmd_help(reply_chat):
    send(
        "🤖 *OLX Tracker — Comenzi*\n\n"
        "`/add <url>` — Adaugă anunț (scrape imediat)\n"
        "`/add <url> Nume` — Adaugă cu nume personalizat\n"
        "`/list` — Toate anunțurile + delta vizualizări\n"
        "`/stats <nr>` — Istoric complet\n"
        "`/rename <nr> Nume` — Redenumește anunț\n"
        "`/remove <nr>` — Șterge anunț\n"
        "`/help` — Această listă\n\n"
        "Raportul zilnic vine automat la *09:00* 🇷🇴\n"
        "Botul verifică comenzi la fiecare *30 minute*",
        chat_id=reply_chat
    )


# ── Main loop ─────────────────────────────────────────────────────────────────

def process_update(update):
    msg     = update.get("message", {})
    text    = msg.get("text", "").strip()
    chat_id = str(msg.get("chat", {}).get("id", ""))

    if chat_id not in get_allowed_chats():
        print(f"Ignored message from unauthorized chat {chat_id}")
        return

    if not text.startswith("/"):
        return

    parts   = text.split(None, 1)
    command = parts[0].lower().split("@")[0]
    args    = parts[1] if len(parts) > 1 else ""

    print(f"Command: {command} | Args: {args} | Chat: {chat_id}")

    if command == "/add":
        cmd_add(args, chat_id)
    elif command == "/list":
        cmd_list(chat_id)
    elif command == "/remove":
        cmd_remove(args, chat_id)
    elif command == "/rename":
        cmd_rename(args, chat_id)
    elif command == "/stats":
        cmd_stats(args, chat_id)
    elif command in ("/help", "/start"):
        cmd_help(chat_id)
    else:
        send(f"❓ Comandă necunoscută: `{command}`\nScrie `/help`", chat_id=chat_id)


def main():
    offset_data = load_json(OFFSET_FILE, {"offset": None})
    offset      = offset_data.get("offset")
    deadline    = time.time() + 55
    processed   = 0

    print(f"Starting bot polling (offset={offset})...")

    while time.time() < deadline:
        updates = get_updates(offset)
        for update in updates:
            process_update(update)
            offset    = update["update_id"] + 1
            processed += 1

        if updates:
            save_json(OFFSET_FILE, {"offset": offset})

        if not updates:
            time.sleep(3)

    print(f"Bot polling finished. Processed {processed} updates.")


if __name__ == "__main__":
    main()
