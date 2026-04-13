"""
bot.py — Handles Telegram commands to manage tracked listings.

Commands:
  /add <url> [nume]   — Add a new OLX listing with optional custom name
  /list               — Show all currently tracked listings
  /remove <index>     — Remove listing by number
  /rename <nr> <nume> — Rename a listing
  /stats <nr>         — Full history with views delta, price delta, averages
  /help               — Show available commands
"""

import os
import json
import time
import re
import requests

BOT_TOKEN    = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID      = os.environ["TELEGRAM_CHAT_ID"]
CONFIG_FILE  = "data/listings.json"
HISTORY_FILE = "data/views_history.json"
OFFSET_FILE  = "data/telegram_offset.json"


def send(text, parse_mode="Markdown"):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }, timeout=15)


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
    resp = requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
        params=params, timeout=30
    )
    return resp.json().get("result", [])


def is_valid_olx_url(url):
    return re.match(r'https?://(www\.)?olx\.ro/', url) is not None


def extract_price_number(price_str):
    """Extract numeric value from price string like '13,490 €' or '13490'."""
    if not price_str or price_str == "—":
        return None
    nums = re.sub(r'[^\d]', '', str(price_str))
    try:
        return int(nums) if nums else None
    except ValueError:
        return None


def cmd_add(args):
    listings = load_json(CONFIG_FILE, [])
    if not args:
        send("❌ Trimite un URL după comandă.\nExemplu:\n`/add https://www.olx.ro/... Kadjar Albastru`")
        return

    parts = args.strip().split(None, 1)
    url   = parts[0]
    name  = parts[1].strip() if len(parts) > 1 else None

    if not is_valid_olx_url(url):
        send("❌ URL invalid. Trebuie să fie un link de pe *olx.ro*.")
        return

    if any(l["url"] == url for l in listings):
        send("⚠️ Acest anunț este deja urmărit!")
        return

    from datetime import datetime
    entry = {
        "url": url,
        "added_date": datetime.now().strftime("%Y-%m-%d"),
    }
    if name:
        entry["custom_name"] = name

    listings.append(entry)
    save_json(CONFIG_FILE, listings)

    display = f"*{name}*\n🔗 {url}" if name else f"🔗 {url}"
    send(f"✅ Anunț adăugat!\n{display}\n\nPrimul raport vine mâine la 09:00. Ziua 1 începe azi!")


def cmd_list():
    listings = load_json(CONFIG_FILE, [])
    history  = load_json(HISTORY_FILE, {})

    if not listings:
        send("📋 Nu urmărești niciun anunț.\nFolosește `/add <url>` pentru a adăuga unul.")
        return

    lines = ["📋 *Anunțuri urmărite:*", ""]

    for i, l in enumerate(listings, 1):
        url         = l["url"]
        name        = l.get("custom_name") or l.get("title") or "*(titlu necunoscut)*"
        url_history = history.get(url, [])
        days        = len(url_history)

        latest      = url_history[-1] if url_history else None
        views       = f"{latest['views']:,}" if latest and latest.get("views") is not None else "—"
        price       = latest.get("price", "—") if latest else "—"

        # Views delta vs yesterday
        valid = [e for e in url_history if e.get("views") is not None]
        delta_str = ""
        if len(valid) >= 2:
            delta = valid[-1]["views"] - valid[-2]["views"]
            sign  = "+" if delta >= 0 else ""
            arrow = "📈" if delta > 0 else ("📉" if delta < 0 else "➡️")
            delta_str = f" {arrow}{sign}{delta}"

        lines.append(f"*{i}.* {name}")
        lines.append(f"    👁 {views}{delta_str}  |  💰 {price}  |  📆 Ziua {days}")
        lines.append(f"    🔗 {url}")
        lines.append("")

    lines.append(f"Total: *{len(listings)}* anunțuri")
    lines.append("Detalii cu `/stats <număr>` • Șterge cu `/remove <număr>`")
    send("\n".join(lines))


def cmd_remove(args):
    listings = load_json(CONFIG_FILE, [])
    if not listings:
        send("📋 Nu ai niciun anunț de șters.")
        return

    if not args:
        send("❌ Specifică numărul.\nExemplu: `/remove 2`")
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
    name = removed.get("custom_name") or removed.get("title") or removed["url"]
    send(f"🗑 Anunț șters:\n*{name}*")


def cmd_rename(args):
    listings = load_json(CONFIG_FILE, [])
    if not args:
        send("❌ Exemplu: `/rename 1 Kadjar Albastru Cluj`")
        return

    parts = args.strip().split(None, 1)
    if len(parts) < 2:
        send("❌ Exemplu: `/rename 1 Kadjar Albastru Cluj`")
        return

    try:
        idx = int(parts[0]) - 1
        if idx < 0 or idx >= len(listings):
            raise ValueError
    except ValueError:
        send(f"❌ Număr invalid. Alege între 1 și {len(listings)}.")
        return

    new_name = parts[1].strip()
    listings[idx]["custom_name"] = new_name
    save_json(CONFIG_FILE, listings)
    send(f"✏️ Anunțul {idx+1} se numește acum: *{new_name}*")


def cmd_stats(args):
    listings = load_json(CONFIG_FILE, [])
    history  = load_json(HISTORY_FILE, {})

    if not listings:
        send("📋 Nu urmărești niciun anunț.")
        return

    if not args:
        send("❌ Exemplu: `/stats 1`")
        return

    try:
        idx = int(args.strip()) - 1
        if idx < 0 or idx >= len(listings):
            raise ValueError
    except ValueError:
        send(f"❌ Număr invalid. Alege între 1 și {len(listings)}.")
        return

    listing     = listings[idx]
    url         = listing["url"]
    name        = listing.get("custom_name") or listing.get("title") or url
    url_history = history.get(url, [])

    if not url_history:
        send(f"📊 *{name}*\n\nNu există date încă. Primul raport vine mâine la 09:00.")
        return

    lines = [f"📊 *{name}*", f"🔗 {url}", f"{'━'*28}", ""]

    valid_views = [e for e in url_history if e.get("views") is not None]
    valid_prices = [e for e in url_history if e.get("price") and e.get("price") != "—"]

    # Build day-by-day table
    for day_num, entry in enumerate(url_history, 1):
        date  = entry.get("date", "")[5:]  # MM-DD
        views = entry.get("views")
        price = entry.get("price", "—")

        # Views delta vs previous valid entry
        prev_valid_views = [e for e in url_history[:url_history.index(entry)] if e.get("views") is not None]
        if prev_valid_views and views is not None:
            delta = views - prev_valid_views[-1]["views"]
            sign  = "+" if delta >= 0 else ""
            arrow = "📈" if delta > 0 else ("📉" if delta < 0 else "➡️")
            views_str = f"{views:,} {arrow}{sign}{delta}"
        else:
            views_str = f"{views:,}" if views is not None else "—"

        # Price delta vs previous valid price
        prev_valid_prices = [e for e in url_history[:url_history.index(entry)] if e.get("price") and e.get("price") != "—"]
        price_str = price
        if prev_valid_prices and price and price != "—":
            prev_price_num = extract_price_number(prev_valid_prices[-1]["price"])
            curr_price_num = extract_price_number(price)
            if prev_price_num and curr_price_num and prev_price_num != curr_price_num:
                diff = curr_price_num - prev_price_num
                sign = "+" if diff >= 0 else ""
                emoji = "💸" if diff < 0 else "💰"
                price_str = f"{price} {emoji}{sign}{diff:,}"

        lines.append(f"*Ziua {day_num}* ({date})")
        lines.append(f"  👁 {views_str}")
        lines.append(f"  💰 {price_str}")

    lines.append("")
    lines.append(f"{'━'*28}")

    # Summary
    if len(valid_views) >= 2:
        total_views = valid_views[-1]["views"] - valid_views[0]["views"]
        avg_views   = round(total_views / len(valid_views))
        sign        = "+" if total_views >= 0 else ""
        lines.append(f"👁 Total vizualizări: *{sign}{total_views}*")
        lines.append(f"📊 Medie zilnică: *{sign}{avg_views}*/zi")

    if len(valid_prices) >= 2:
        first_price = extract_price_number(valid_prices[0]["price"])
        last_price  = extract_price_number(valid_prices[-1]["price"])
        if first_price and last_price:
            price_diff = last_price - first_price
            sign       = "+" if price_diff >= 0 else ""
            emoji      = "💸" if price_diff < 0 else ("📈" if price_diff > 0 else "➡️")
            lines.append(f"💰 Preț inițial: *{valid_prices[0]['price']}* → *{valid_prices[-1]['price']}* ({sign}{price_diff:,}) {emoji}")

    lines.append(f"📆 Urmărit de *{len(url_history)}* zile")

    # Send in chunks if too long
    full_text = "\n".join(lines)
    if len(full_text) > 4000:
        # Send last 20 days only
        short_lines = [f"📊 *{name}* — ultimele 20 zile", f"🔗 {url}", f"{'━'*28}", ""]
        recent = url_history[-20:]
        for day_num, entry in enumerate(recent, len(url_history) - len(recent) + 1):
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
            short_lines.append(f"*Z{day_num}* ({date}): 👁 {views_str}  💰 {price}")
        send("\n".join(short_lines))
    else:
        send(full_text)


def cmd_help():
    send(
        "🤖 *OLX Tracker — Comenzi*\n\n"
        "`/add <url>` — Adaugă anunț\n"
        "`/add <url> Nume` — Adaugă cu nume personalizat\n"
        "`/list` — Toate anunțurile + delta vizualizări\n"
        "`/stats <nr>` — Istoric complet: vizualizări, preț, delta, medie\n"
        "`/rename <nr> Nume nou` — Redenumește un anunț\n"
        "`/remove <nr>` — Șterge un anunț\n"
        "`/help` — Această listă\n\n"
        "Raportul zilnic se trimite automat la *09:00* 🇷🇴"
    )


def process_update(update):
    msg     = update.get("message", {})
    text    = msg.get("text", "").strip()
    chat_id = str(msg.get("chat", {}).get("id", ""))

    if chat_id != str(CHAT_ID):
        print(f"Ignored message from unauthorized chat {chat_id}")
        return

    if not text.startswith("/"):
        return

    parts   = text.split(None, 1)
    command = parts[0].lower().split("@")[0]
    args    = parts[1] if len(parts) > 1 else ""

    print(f"Command: {command} | Args: {args}")

    if command == "/add":
        cmd_add(args)
    elif command == "/list":
        cmd_list()
    elif command == "/remove":
        cmd_remove(args)
    elif command == "/rename":
        cmd_rename(args)
    elif command == "/stats":
        cmd_stats(args)
    elif command in ("/help", "/start"):
        cmd_help()
    else:
        send(f"❓ Comandă necunoscută: `{command}`\nScrie `/help` pentru lista de comenzi.")


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
