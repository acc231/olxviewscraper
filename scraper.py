import os
import json
import time
import re
import requests
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

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
    """Returns (title, views) from an OLX listing."""
    try:
        driver.get(url)

        # Wait up to 15 seconds for the views element to appear in DOM
        try:
            WebDriverWait(driver, 15).until(
                lambda d: re.search(r'[Vv]izualiz', d.page_source)
            )
        except Exception:
            pass

        # Extra wait for JS to finish rendering
        time.sleep(5)

        source = driver.page_source

        # ── Debug: dump relevant snippet ──────────────────────────────────
        idx = source.lower().find("vizualiz")
        if idx != -1:
            print(f"  [debug] found 'vizualiz' at index {idx}: ...{source[max(0,idx-30):idx+80]}...")
        else:
            print("  [debug] 'vizualiz' NOT found in page source")

        # ── Title ──────────────────────────────────────────────────────────
        title = None
        title_patterns = [
            r'<h1[^>]*>\s*([^<]{10,}?)\s*</h1>',
            r'"name"\s*:\s*"([^"]{10,})"',
            r'<title>([^|<]{10,})',
        ]
        for pat in title_patterns:
            m = re.search(pat, source, re.IGNORECASE)
            if m:
                title = m.group(1).strip()
                title = re.sub(r'\s*[•·|]\s*(OLX|Autovit).*$', '', title, flags=re.IGNORECASE).strip()
                if len(title) > 8:
                    break

        # ── Views — try DOM elements first ────────────────────────────────
        views = None

        # Method 1: look for elements containing "vizualiz" text
        try:
            elements = driver.find_elements(By.XPATH, "//*[contains(translate(text(),'VIZUALIZARI','vizualizari'),'vizualiz')]")
            for el in elements:
                text = el.text.strip()
                print(f"  [dom] element text: {repr(text)}")
                nums = re.findall(r'\d+', text.replace(" ", "").replace("\xa0", ""))
                if nums:
                    candidate = int(nums[0])
                    if candidate > 0:
                        views = candidate
                        print(f"  [dom] found views={views}")
                        break
        except Exception as e:
            print(f"  [dom] error: {e}")

        # Method 2: regex on full page source
        if views is None:
            view_patterns = [
                r'(\d[\d\s\xa0]{0,5})\s*[Vv]izualiz',
                r'[Vv]izualiz[a-zări]*[^\d]{0,10}(\d[\d\s\xa0]*)',
                r'"views"\s*:\s*(\d+)',
                r'"viewCount"\s*:\s*(\d+)',
                r'viewCount["\s:]+(\d+)',
            ]
            for pat in view_patterns:
                m = re.search(pat, source, re.IGNORECASE)
                if m:
                    raw = re.sub(r'[\s\xa0]', '', m.group(1))
                    try:
                        views = int(raw)
                        print(f"  [regex] pattern '{pat}' found views={views}")
                        break
                    except ValueError:
                        continue

        # Method 3: look in embedded JSON blobs
        if views is None:
            json_blobs = re.findall(r'\{[^{}]{0,2000}"views"[^{}]{0,500}\}', source)
            for blob in json_blobs:
                m = re.search(r'"views"\s*:\s*(\d+)', blob)
                if m:
                    views = int(m.group(1))
                    print(f"  [json-blob] found views={views}")
                    break

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
