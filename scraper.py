import os
import json
import time
import re
import requests
from datetime import datetime
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN   = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID     = os.environ["TELEGRAM_CHAT_ID"]
CONFIG_FILE = "data/listings.json"
DATA_FILE   = "data/views_history.json"
# ─────────────────────────────────────────────────────────────────────────────


def get_driver():
    options = uc.ChromeOptions()
    options.add_argument("--window-size=1280,900")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--lang=ro-RO")
    driver = uc.Chrome(options=options, headless=False, version_main=146)
    return driver


def dismiss_popups(driver):
    """Try to close cookie banners and any other popups."""

    # Lista de selectori comuni pentru butoane de accept cookies pe OLX
    cookie_selectors = [
        (By.XPATH, "//button[contains(translate(text(),'ACCEPTA','accepta'),'accepta')]"),
        (By.XPATH, "//button[contains(translate(text(),'ACCEPT','accept'),'accept')]"),
        (By.XPATH, "//button[contains(@id,'accept')]"),
        (By.XPATH, "//button[contains(@class,'accept')]"),
        (By.XPATH, "//button[contains(@data-testid,'accept')]"),
        (By.CSS_SELECTOR, "[id*='cookie'] button"),
        (By.CSS_SELECTOR, "[class*='cookie'] button"),
        (By.CSS_SELECTOR, "[id*='consent'] button"),
        (By.CSS_SELECTOR, "button#onetrust-accept-btn-handler"),
    ]

    for by, selector in cookie_selectors:
        try:
            btn = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((by, selector)))
            btn.click()
            print(f"  [popup] clicked: {selector}")
            time.sleep(1)
            return True
        except Exception:
            continue

    print("  [popup] no popup found or already dismissed")
    return False


def scrape_listing(driver, url):
    """Returns (title, views) from an OLX listing."""
    try:
        driver.get(url)

        # Wait for page to start loading
        time.sleep(3)

        # Dismiss cookie popups
        dismiss_popups(driver)

        # Wait for vizualizari to appear after popup dismissed
        try:
            WebDriverWait(driver, 15).until(
                lambda d: re.search(r'[Vv]izualiz', d.page_source)
            )
        except Exception:
            pass

        # Extra wait for full JS render
        time.sleep(4)

        # Scroll down to make sure lazy-loaded elements appear
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 2);")
        time.sleep(2)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)

        source = driver.page_source

        # ── Save full HTML for debugging ───────────────────────────────────
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(source)
        print("  [debug] HTML salvat in debug_page.html")

        # ── Debug: dump relevant snippet ──────────────────────────────────
        idx = source.lower().find("vizualiz")
        if idx != -1:
            print(f"  [debug] found 'vizualiz': ...{source[max(0,idx-30):idx+80]}...")
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

        # Method 1: DOM elements
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

        # Method 2: regex on page source
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
                        print(f"  [regex] found views={views}")
                        break
                    except ValueError:
                        continue

        # Method 3: JSON blobs
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
    today_str = datetime.now().strftime("%Y-%m-%d")
    listings  = load_json(CONFIG_FILE, [])
    history   = load_json(DATA_FILE, {})

    if not listings:
        send_telegram("⚠️ *OLX Tracker*\n\nNu ai niciun anunț de urmărit.\nTrimite `/add <url>` pentru a adăuga unul.")
        return

    driver  = get_driver()
    results = []

    try:
        for listing in listings:
            url = listing["url"]
            print(f"\nScraping: {url}")
            title, views = scrape_listing(driver, url)

            url_history = history.get(url, [])
            if not title and url_history:
                title = url_history[-1].get("title")

            existing = next((e for e in url_history if e["date"] == today_str), None)
            if existing:
                existing.update({"views": views, "title": title})
            else:
                url_history.append({"date": today_str, "views": views, "title": title})
            history[url] = url_history

            delta, avg = None, None
            valid = [e for e in url_history if e.get("views") is not None]
            if len(valid) >= 2 and views is not None:
                delta = views - valid[-2]["views"]
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
