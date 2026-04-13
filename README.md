# 🚗 OLX Multi-Link Views Tracker

Urmărește automat vizualizările pentru oricâte anunțuri OLX vrei și primești raport zilnic pe Telegram. Poți adăuga/șterge linkuri direct din Telegram.

---

## ⚙️ Setup (5 minute)

### 1. Creează un repo GitHub
- [github.com](https://github.com) → **New repository** → numește-l `olx-tracker` (poate fi privat)
- Încarcă toate fișierele păstrând structura de foldere

### 2. Adaugă secretele
**Settings → Secrets and variables → Actions → New repository secret**

| Nume | Valoare |
|------|---------|
| `TELEGRAM_BOT_TOKEN` | Token-ul de la @BotFather |
| `TELEGRAM_CHAT_ID` | ID-ul tău de la @userinfobot |

### 3. Activează Actions
**Actions tab** → Enable workflows

### 4. Testează
**Actions → OLX Views Tracker → Run workflow → job: scrape**

---

## 📱 Comenzi Telegram

| Comandă | Descriere |
|---------|-----------|
| `/add https://olx.ro/...` | Adaugă un anunț de urmărit |
| `/list` | Afișează toate anunțurile |
| `/remove 2` | Șterge anunțul nr. 2 |
| `/help` | Afișează comenzile |

---

## 📬 Exemplu notificare zilnică

```
🚗 OLX Tracker — 13 Apr 2026

──────────────────────────────
1. Renault Kadjar Facelift Intens Panoramic
🔗 https://www.olx.ro/d/oferta/...
👁 1,482 vizualizări
📈 Față de ieri: +37
📊 Medie zilnică: +28/zi

──────────────────────────────
2. Dacia Duster 4x4 Diesel
🔗 https://www.olx.ro/d/oferta/...
👁 856 vizualizări
📈 Față de ieri: +12
📊 Medie zilnică: +15/zi

──────────────────────────────
📋 Total urmărite: 2 anunțuri
```

---

## 🕘 Program
- **09:00 România** — raport zilnic automat
- **La fiecare 5 minute** — bot ascultă comenzile tale Telegram

---

## 📁 Structură
```
olx-tracker/
├── .github/workflows/tracker.yml   ← Actions schedule
├── data/
│   ├── listings.json               ← Anunțurile tale (auto-updated)
│   ├── views_history.json          ← Istoricul vizualizărilor
│   └── telegram_offset.json        ← Stare bot Telegram
├── scraper.py                      ← Scraper + notificare
├── bot.py                          ← Comenzi Telegram
└── README.md
```
