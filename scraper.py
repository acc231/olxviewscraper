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
    driver = uc.Chrome(options=options, headless=False)
    return driver


def dismiss_popups(driver):
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


def scrape_price(source):
    """Extract price from page source."""
    price_patterns = [
        r'"price"\s*:\s*"([^"]+)"',
        r'"price"\s*:\s*(\d+)',
        r'(\d[\d\s]*)\s*€',
        r'(\d[\d\s]*)\s*euro',
        r'(\d[\d\s]*)\s*lei',
    ]
    for pat in price_patterns:
        m = re.search(pat, source, re.IGNORECASE)
        if m:
            raw = m.group(1).strip()
            # Check if it looks like a price (not too small, not too big)
            nums = re.sub(r'[\s\xa0]', '', raw)
            try:
                val = int(nums)
                if 100 <= val <= 9999999:
                    # Try to get currency
                    currency = "€" if "€" in source[max(0, m.start()-5):m.end()+10] else ""
                    return f"{val:,} {currency}".strip()
            except ValueError:
                return raw
    return "—"


def scrape_listing(driver, url):
    """Returns (title, views, price) from an OLX listing."""
    try:
        driver.get(url)
        time.sleep(3)
        dismiss_popups(driver)

        try:
            WebDriverWait(driver, 15).until(
                lambda d: re.search(r'[Vv]izualiz', d.page_source)
            )
        except Exception:
            pass

        time.sleep(4)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 2);")
        time.sleep(2)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)

        source = driver.page_source

        # ── Title ──────────────────────────────────────────────────────────
        title = None
        for pat in [r'<h1[^>]*>\s*([^<]{10,}?)\s*</h1>', r'"name"\s*:\s*"([^"]{10,})"', r'<title>([^|<]{10,})']:
            m = re.search(pat, source, re.IGNORECASE)
            if m:
                title = re.sub(r'\s*[•·|]\s*(OLX|Autovit).*$', '', m.group(1).strip(), flags=re.IGNORECASE).strip()
                if len(title) > 8:
                    break

        # ── Price ──────────────────────────────────────────────────────────
        price = scrape_price(source)

        # ── Views ──────────────────────────────────────────────────────────
        views = None

        # Method 1: DOM
        try:
            elements = driver.find_elements(By.XPATH, "//*[contains(translate(text(),'VIZUALIZARI','vizualizari'),'vizualiz')]")
            for el in elements:
                text = el.text.strip()
                nums = re.findall(r'\d+', text.replace(" ", "").replace("\xa0", ""))
                if nums:
                    candidate = int(nums[0])
                    if candidate > 0:
                        views = candidate
                        print(f"  [dom] found views={views}")
                        break
        except Exception as e:
            print(f"  [dom] error: {e}")

        # Method 2: regex
        if views is None:
            for pat in [
                r'(\d[\d\s\xa0]{0,5})\s*[Vv]izualiz',
                r'[Vv]izualiz[a-zări]*[^\d]{0,10}(\d[\d\s\xa0]*)',
                r'"views"\s*:\s*(\d+)',
                r'"viewCount"\s*:\s*(\d+)',
            ]:
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
            for blob in re.findall(r'\{[^{}]{0,2000}"views"[^{}]{0,500}\}', source):
                m = re.search(r'"views"\s*:\s*(\d+)', blob)
                if m:
                    views = int(m.group(1))
                    print(f"  [json-blob] found views={views}")
                    break

        print(f"  → title={title}, views={views}, price={price}")
        return title, views, price

    except Exception as e:
        print(f"Error scraping {url}: {e}")
        return None, None, "—"


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
    """Send to all allowed chats."""
    chats_file = "data/allowed_chats.json"
    if os.path.exists(chats_file):
        with open(chats_file, "r", encoding="utf-8") as f:
            chats = json.load(f)
    else:
        chats = [CHAT_ID]
    # Always include primary CHAT_ID
    if str(CHAT_ID) not in [str(c) for c in chats]:
        chats.append(CHAT_ID)
    for chat_id in chats:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True}
            resp = requests.post(url, json=payload, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            print(f"Failed to send to {chat_id}: {e}")


def build_messages(results, today_str):
    """Returns a list of messages — header + one message per listing."""
    today_fmt = datetime.strptime(today_str, "%Y-%m-%d").strftime("%d %b %Y")
    messages = []

    # Header
    messages.append(f"🚗 *OLX Tracker — {today_fmt}*\n📋 {len(results)} anunțuri urmărite")

    # One message per listing
    for i, r in enumerate(results, 1):
        name  = r.get("custom_name") or r.get("title") or r.get("url")
        url   = r["url"]
        views = r.get("views")
        delta = r.get("delta")
        avg   = r.get("avg")
        price = r.get("price", "—")
        day   = r.get("day", 1)

        lines = []
        lines.append(f"*{i}. {name}*")
        lines.append(f"🔗 {url}")

        price_delta = r.get("price_delta")
        if price_delta is not None and price_delta != 0:
            sign  = "+" if price_delta >= 0 else ""
            emoji = "💸" if price_delta < 0 else "📈"
            lines.append(f"📆 Ziua *{day}*  |  💰 *{price}* ({sign}{price_delta:,}) {emoji}")
        else:
            lines.append(f"📆 Ziua *{day}*  |  💰 *{price}*")

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

        messages.append("\n".join(lines))

    return messages


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
            url         = listing["url"]
            custom_name = listing.get("custom_name")
            added_date  = listing.get("added_date", today_str)

            print(f"\nScraping: {url}")
            title, views, price = scrape_listing(driver, url)

            url_history = history.get(url, [])

            # Use stored title if scrape didn't get one
            if not title and url_history:
                title = next((e.get("title") for e in reversed(url_history) if e.get("title")), None)

            # Upsert today's entry
            existing = next((e for e in url_history if e["date"] == today_str), None)
            if existing:
                existing.update({"views": views, "title": title, "price": price})
            else:
                url_history.append({"date": today_str, "views": views, "title": title, "price": price})
            history[url] = url_history

            # Day number
            day = len(url_history)

            # Delta and average
            delta, avg = None, None
            valid = [e for e in url_history if e.get("views") is not None]
            if len(valid) >= 2 and views is not None:
                delta = views - valid[-2]["views"]
                total = valid[-1]["views"] - valid[0]["views"]
                avg   = round(total / (len(valid) - 1)) if len(valid) > 1 else None

            # Price delta vs yesterday
            price_delta = None
            valid_prices = [e for e in url_history if e.get("price") and e.get("price") != "—"]
            if len(valid_prices) >= 2:
                import re as _re
                def _extract_num(s):
                    nums = _re.sub(r"[^\d]", "", str(s))
                    try: return int(nums) if nums else None
                    except: return None
                prev_p = _extract_num(valid_prices[-2]["price"])
                curr_p = _extract_num(valid_prices[-1]["price"])
                if prev_p and curr_p:
                    price_delta = curr_p - prev_p

            results.append({
                "url": url,
                "title": title,
                "custom_name": custom_name,
                "views": views,
                "price": price,
                "price_delta": price_delta,
                "delta": delta,
                "avg": avg,
                "day": day,
            })

    finally:
        driver.quit()

    save_json(DATA_FILE, history)

    messages = build_messages(results, today_str)
    for message in messages:
        print("\n" + message)
        send_telegram(message)
        time.sleep(1)  # avoid Telegram rate limit


if __name__ == "__main__":
    main()
