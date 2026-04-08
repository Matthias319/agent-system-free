---
name: Supermarkt-Scraping & Cart-Automation Ergebnisse
description: Welche Supermärkte scrapbar sind, Login-Bypass via undetected-chromedriver, REWE Cart-Flow funktioniert
type: project
---

**Stand: 2026-03-30**

## Funktionierende Flows

**REWE (Hauptweg):**
- `undetected-chromedriver` + Xvfb + System-Chromium (v145) umgeht Cloudflare komplett
- Login via Keycloak SSO (account.rewe.de), 2FA per E-Mail-Code
- Persistent Chrome über CDP (Port 9222) — Schritt-für-Schritt steuerbar
- Cart-Flow: Suche → Produktlink extrahieren → Detailseite → `aria-label="Produkt hinzufügen"` klicken
- 17/17 Produkte erfolgreich in Warenkorb gelegt (39,70€)
- Matthias' Account: in .env als REWE_EMAIL/REWE_PASS, Adresse: Im Grund 7, 64342 Seeheim-Jugenheim

**meinALDI (Backup, wenn Liefergebiet verfügbar):**
- Spryker Glue API: `api.mein-aldi.de/v3/product-search?serviceType=delivery&servicePoint=ADG045_1&categoryKey=X&limit=50&offset=0`
- 2.242 Produkte + Nährwerte in einem API-Call, keine Auth nötig
- Login via Shadow DOM (depth 4) + FriendlyCaptcha bypass mit undetected-chromedriver
- Aktuell: Liefert NICHT nach 64342 Seeheim-Jugenheim (Warteliste)

**Picnic (Alternative):**
- `python-picnic-api` auf PyPI: login(), search(), add_product(), get_cart()
- Darmstadt im Liefergebiet, keine Bot-Protection
- Matthias hat noch keinen Account

## Nicht scrapbar
REWE via httpx (Cloudflare mTLS), Kaufland (Cloudflare), Edeka (React-SPA), Penny (JS-only), Lidl (Prospekte-Redirect)

## Technische Erkenntnisse
- Playwright wird von FriendlyCaptcha und Cloudflare erkannt → `undetected-chromedriver` nutzen
- Chrome persistent über CDP (Port 9222) steuern, NICHT als monolithisches Script
- pychrome für CDP-Steuerung (kein ChromeDriver-Version-Problem)
- Xvfb :99 als virtueller Bildschirm
- Cookie-Consent oft in Shadow DOM (#usercentrics-root)
- REWE "In den Warenkorb" nur auf Produktdetailseiten, nicht in Suchergebnissen

**Why:** Matthias will automatisierten Wocheneinkauf (Fitness, proteinreich, Single)
**How to apply:** `/grocery` Skill nutzt diesen Flow. Scraper: `~/.claude/tools/meinaldi-scraper.py`

## Erster erfolgreicher Run (2026-03-30)

**Bestellt bei REWE:** 78,26€ (31 Produkte inkl. 6 Gewürze, 3€ Liefergebühr)
- ja!-Marke überall wo verfügbar → ~30€ gespart vs. Markenprodukte
- Gewürze (Einmalinvestition ~12€): Paprika, Kurkuma, Kreuzkümmel, Curry, Ital. Kräuter, Knoblauch

**Learnings (eingebaut in Skill + Tool):**
1. `rewe-cart.py` hat jetzt `remove`, `remove-list` und `list` Befehle
2. Keyword-Matching verhindert falsche Produktzuordnungen (Schupfnudeln statt Passata etc.)
3. REWE Mengenlimit: Max ~2-3 pro Artikel → 500g Packungen bevorzugen
4. "ja! Passata" existiert nicht → `REWE Bio Passata` oder `Passata 700g` suchen
5. Bei Gewürzen: `REWE Beste Wahl` statt `ja!` (ja! hat kaum Gewürze)
6. Browser NICHT stoppen nach Bestellung → Session bleibt eingeloggt
