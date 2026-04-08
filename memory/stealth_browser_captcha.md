---
name: Stealth Browser — Best Practices & CAPTCHA
description: Best Practices für den Stealth Browser MCP (Screenshots, Formularinteraktion, Datenextraktion, CAPTCHA-Lösung)
type: feedback
---

## Effizienz-Regeln (aus Check24-Session, 2026-03-30)

### Screenshots: IMMER `browser_save_screenshot` verwenden
`browser_take_screenshot` gibt base64-JSON zurück → sprengt Token-Limit (~130-180K chars).
**Stattdessen:** `browser_save_screenshot(path="/tmp/page.jpg")` → speichert direkt → `Read /tmp/page.jpg` zeigt Bild.
Spart 3 Tool-Calls und ~30s pro Screenshot.

### Formularinteraktion: URL-Konstruktion > UI-Klicks
Komplexe Formulare (Kalender-Picker, Autocomplete, React-Komponenten) sind fragil.
**Besser:** Einmal die URL-Struktur einer Site verstehen (z.B. Check24 `areaId=557`), dann direkt per `browser_navigate` die Such-URL bauen.
**Wann UI:** Nur bei einfachen Klicks (Cookies akzeptieren, Tabs wechseln, Dropdown-Auswahl).

### Datenextraktion: `browser_evaluate` mit Auto-IIFE
`browser_evaluate` wrappt jetzt automatisch `return`-Statements in IIFE.
**Pattern für Seitentext:** `browser_evaluate("return document.body.innerText.substring(idx, idx+3000)")`
**Pattern für strukturierte Daten:** JSON.stringify in evaluate, dann im Caller parsen.

### Workflow für unbekannte Websites
1. `browser_navigate(url)` → Seite laden
2. `browser_save_screenshot()` + `Read` → visuellen Überblick
3. `browser_snapshot(max_tokens=1500)` → interaktive Elemente mit refs
4. `browser_evaluate` → URL-Muster, Formular-Struktur, API-Endpoints verstehen
5. URL-basiert navigieren statt Formulare ausfüllen
6. `browser_evaluate` → Daten extrahieren als JSON

## PerimeterX "Press-and-Hold" CAPTCHA

**Erkennung:** URL enthält `captcha-v2`, Seite zeigt "Bist du ein Mensch oder ein Roboter?" + "LÄNGER GEDRÜCKT HALTEN" Button.

**Lösung in 3 Schritten:**

1. **Button finden:** `document.getElementById("px-captcha").getBoundingClientRect()` → Mittelpunkt berechnen
2. **Maus bewegen:** Bezier-Kurve von zufälliger Position zum Button (20-30 Schritte, je 20-40ms)
3. **Press & Hold:** mousePressed → **mindestens 10s halten** mit Micro-Jitter (±2px) → mouseReleased

**Kritisch:** Der Fortschrittsbalken braucht ~7s bis 100%. Bei 5s nur ~90% → Reset. **Immer 10-12s halten.**

## Bot-Detection vermeiden

**Was PX erkennt:**
- `__playwright_mark_target__`, `webdriver-evaluate`, `selenium-evaluate` Events im Document
- Viele CDP Runtime.evaluate Calls in kurzer Zeit
- Persistente UUID per IP (nicht nur Cookies)

**Was funktioniert:**
- `--incognito` + frisches Profil (`rm -rf ~/.stealth-browser-data`) umgeht Cookie-Flags
- `--disable-blink-features=AutomationControlled` + `navigator.webdriver=false` (schon gesetzt)
- Direkte URL-Navigation statt UI-Klicks für Formulare (z.B. Skyscanner Search-URL)
- Minimale CDP-Calls: Nur Page.enable, dann navigieren — kein DOM.enable/Runtime.enable vorher

**Wenn CAPTCHA trotzdem kommt:**
1. Chrome killen: `pkill -9 -f "chromium.*remote-debugging"`
2. Profil löschen: `rm -rf ~/.stealth-browser-data`
3. Neu starten mit `--incognito`
4. Erst Homepage besuchen, 2-4s warten, dann Ziel-URL

## MCP Server Erweiterungen (2026-03-30)

Neue Tools in `server.py`:
- `browser_click_xy(x, y)` — Klick auf Pixel-Koordinaten (geht durch Iframes)
- `browser_press_and_hold(x, y, duration)` — Press-and-Hold für CAPTCHAs

Neue Methoden in `browser.py`:
- `mouse_down(x, y)` / `mouse_up(x, y)` — Low-level CDP mouse events
- `--remote-allow-origins=*` in Chrome Args (erlaubt externe CDP WebSocket-Verbindungen)

**Why:** Ref-basierte Klicks können Cross-Origin Iframes nicht erreichen. Pixel-Koordinaten via CDP `Input.dispatchMouseEvent` gehen durch alle Layer.

**How to apply:** Bei CAPTCHAs oder Iframe-Inhalten immer `browser_click_xy` / `browser_press_and_hold` statt `browser_click(ref=...)`.
