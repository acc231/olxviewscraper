import os
import json
import time
import re
import requests
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN   = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID     = os.environ["TELEGRAM_CHAT_ID"]
CONFIG_FILE = "data/listings.json"
DATA_FILE   = "data/views_history.json"
# ─────────────────────────────────────────────────────────────────────────────


def get_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,900")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    return webdriver.Chrome(options=options)


def scrape_listing(driver, url):
    """Returns (title, views) from an OLX listing. Both can be None on failure."""
    try:
        driver.get(url)
        time.sleep(6)
        source = driver.page_source

        # ── Title ──────────────────────────────────────────────────────────
        title = None
        title_patterns = [
            r'<h1[^>]*class="[^"]*css-[^"]*"[^>]*>\s*([^<]+)\s*</h1>',
            r'"name"\s*:\s*"([^"]{10,})"',
            r'<title>([^|<]+)',
        ]
        for pat in title_patterns:
            m = re.search(pat, source, re.IGNORECASE)
            if m:
                title = m.group(1).strip()
                # Clean up OLX suffix like " • OLX.ro"
                title = re.sub(r'\s*[•·|]\s*(OLX|Autovit).*$', '', title, flags=re.IGNORECASE).strip()
                if len(title) > 8:
                    break

        # ── Views ──────────────────────────────────────────────────────────
        views = None
        view_patterns = [
            r'Vizualizari[^\d]*(\d[\d\s\xa0]*)',
            r'vizualizari[^\d]*(\d[\d\s\xa0]*)',
            r'"views"\s*:\s*(\d+)',
            r'(\d[\d\s]*)\s*[Vv]izualiz',
        ]
        for pat in view_patterns:
            m = re.search(pat, source, re.IGNORECASE)
            if m:
                raw = re.sub(r'[\s\xa0]', '', m.group(1))
                try:
                    views = int(raw)
                    break
                except ValueError:
                    continue

        return title, views

    except Exception as e:
        print(f"Error scraping {url}: {e}")
        return None, None


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True}
    resp = requests.post(url, json=payload, timeout=15)
    resp.raise_for_status()


def build_message(results, today_str):
    today_fmt = datetime.strptime(today_str, "%Y-%m-%d").strftime("%d %b %Y")
    lines = [f"🚗 *OLX Tracker — {today_fmt}*", ""]

    for i, r in enumerate(results, 1):
        title  = r.get("title") or r.get("url")
        url    = r["url"]
        views  = r.get("views")
        delta  = r.get("delta")
        avg    = r.get("avg")

        lines.append(f"{'─'*30}")
        lines.append(f"*{i}. {title}*")
        lines.append(f"🔗 {url}")

        if views is None:
            lines.append("⚠️ Nu s-au putut citi vizualizările")
        else:
            lines.append(f"👁 *{views:,}* vizualizări")
            if delta is not None:
                arrow = "📈" if delta > 0 else ("📉" if delta < 0 else "➡️")
                sign  = "+" if delta >= 0 else ""
                lines.append(f"{arrow} Față de ieri: *{sign}{delta}*")
            if avg is not None:
                lines.append(f"📊 Medie zilnică: *+{avg}*/zi")

        lines.append("")

    lines.append(f"{'─'*30}")
    lines.append(f"📋 Total urmărite: *{len(results)}* anunțuri")
    return "\n".join(lines)


def main():
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    listings  = load_json(CONFIG_FILE, [])
    history   = load_json(DATA_FILE, {})  # { url: [{date, views, title}, ...] }

    if not listings:
        send_telegram("⚠️ *OLX Tracker*\n\nNu ai niciun anunț de urmărit.\nTrimite `/add <url>` pentru a adăuga unul.")
        return

    driver  = get_driver()
    results = []

    try:
        for listing in listings:
            url = listing["url"]
            print(f"Scraping: {url}")
            title, views = scrape_listing(driver, url)

            # Use stored title if scrape didn't get one
            url_history = history.get(url, [])
            if not title and url_history:
                title = url_history[-1].get("title")

            # Upsert today's entry
            existing = next((e for e in url_history if e["date"] == today_str), None)
            if existing:
                existing.update({"views": views, "title": title})
            else:
                url_history.append({"date": today_str, "views": views, "title": title})
            history[url] = url_history

            # Compute delta and average
            delta, avg = None, None
            valid = [e for e in url_history if e.get("views") is not None]
            if len(valid) >= 2:
                delta = views - valid[-2]["views"] if views is not None else None
                total = valid[-1]["views"] - valid[0]["views"]
                avg   = round(total / len(valid)) if len(valid) > 1 else None

            results.append({"url": url, "title": title, "views": views, "delta": delta, "avg": avg})
            print(f"  → title={title}, views={views}")

    finally:
        driver.quit()

    save_json(DATA_FILE, history)

    message = build_message(results, today_str)
    print("\n" + message)
    send_telegram(message)


if __name__ == "__main__":
    main()
