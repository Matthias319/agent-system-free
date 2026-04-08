---
name: browser-scrape
context: fork
description: "Scrapt JS-gerenderte Seiten mit Stealth Browser MCP"
triggers:
  - "konkrete URL + scrape/extract"
  - "SPA"
  - "JS-heavy Site"
  - "Cookie-Wall"
  - "Login-Flow"
  - "Formular ausfüllen"
not_for:
  - "allgemeine Recherche"
  - "Reddit/YouTube/TikTok"
  - "statische Seiten"
---

# Kernprinzip

**Stealth Browser MCP** für interaktive Browser-Automation auf JS-gerenderten Seiten.
Umgeht Bot-Detection (Cloudflare, Akamai, etc.) durch System Chromium + Xvfb.
Cookie-Banner werden automatisch akzeptiert (Chrome Extension).

Dieser Skill startet bei einer **konkreten URL/Seite** — nicht bei einer Frage.

Für Recherche/Multi-Source-Analyse → `/web-search`.
Für Meinungen/Community → `/social-research`.

## Tool-Referenz

22 MCP-Tools über `mcp__stealth_browser__*`:

| Kategorie | Tools |
|-----------|-------|
| **Navigation** | `browser_navigate`, `browser_go_back`, `browser_go_forward`, `browser_wait_for_navigation`, `browser_wait_for_url` |
| **Sehen** | `browser_snapshot`, `browser_take_screenshot` (chunked full-page), `browser_look` (Combo: Screenshot + Snapshot) |
| **Interaktion** | `browser_click`, `browser_click_text`, `browser_type`, `browser_fill_form`, `browser_press_key`, `browser_hover`, `browser_scroll`, `browser_select_option` |
| **Lesen** | `browser_get_text`, `browser_evaluate` |
| **Warten** | `browser_wait_for`, `browser_wait_for_navigation`, `browser_wait_for_url` |
| **Meta** | `browser_tabs`, `browser_network_requests`, `browser_close` |

## Abgrenzung zu /web-search

| Signal | Skill | Warum |
|--------|-------|-------|
| Offene Frage, Faktencheck, Vergleich | `/web-search` | Multi-Source Discovery nötig |
| Konkrete URL + "scrape/extract/auslesen" | `/browser-scrape` | Einzelseiten-Extraktion |
| SPA, React/Angular/Vue-App, JS-rendered | `/browser-scrape` | httpx liefert leeren Body |
| Formulare ausfüllen, Login-Flow, Filter | `/browser-scrape` | Interaktion nötig |
| Cookie-Wall blockiert Content | `/browser-scrape` | Auto-Accept Extension |
| Bot-Detection (Cloudflare, Akamai) | `/browser-scrape` | Stealth-Browser umgeht Detection |

# Phase 0: Pre-Check

| Prüfung | Aktion |
|---------|--------|
| Keine konkrete URL, nur eine Frage | → an `/web-search` delegieren |
| URL ist statische Seite (Docs, Blog) | → `httpx` + `trafilatura` reicht |
| Seite braucht Login/2FA ohne Credentials | → User fragen |

# Phase 1: Navigate + Look

```
browser_navigate(url="<ZIEL-URL>")
browser_look(max_tokens=3000)
```

`browser_look` gibt Screenshot + YAML-Snapshot mit Refs zurück — ein Call statt zwei.
Cookie-Banner werden automatisch akzeptiert (Extension).

# Phase 2: Interaction

| Aktion | Tool | Beispiel |
|--------|------|---------|
| Button/Link klicken (per Text) | `browser_click_text` | `browser_click_text(text="Anmelden")` |
| Button/Link klicken (per Ref) | `browser_click` | `browser_click(ref="e5")` |
| Formular-Feld ausfüllen | `browser_type` | `browser_type(ref="e3", text="test@example.com")` |
| Mehrere Felder auf einmal | `browser_fill_form` | `browser_fill_form(fields={"e3": "Name", "e4": "Email"})` |
| Dropdown wählen | `browser_select_option` | `browser_select_option(ref="e7", value="Option A")` |
| Tastendruck | `browser_press_key` | `browser_press_key(key="Enter")` |
| Scrollen | `browser_scroll` | `browser_scroll(direction="down", amount=500)` |
| Element-Wert lesen | `browser_get_text` | `browser_get_text(ref="e3")` — 0.6ms |
| Warten auf Navigation | `browser_wait_for_navigation` | Nach Click der navigiert |
| Warten auf URL-Pattern | `browser_wait_for_url` | `browser_wait_for_url(url_pattern="success")` |
| Warten auf Text | `browser_wait_for` | `browser_wait_for(text="Erfolgreich")` |

**Nach jedem Interaktionsschritt:** `browser_look()` → sehen was sich geändert hat.

# Phase 3: Extraction

## Strukturierte Daten

```
browser_evaluate(expression="JSON.stringify(Array.from(document.querySelectorAll('.item')).map(el => ({name: el.querySelector('.title')?.textContent, price: el.querySelector('.price')?.textContent})))")
```

## Freitext

```
browser_evaluate(expression="document.body.innerText")
```

## Screenshots

```
browser_take_screenshot(full_page=true, format="jpeg")
```

Full-Page: Automatisch in max 4 Viewport-Chunks gesplittet, volle Auflösung.
Vision-Tokens: ~1500 pro Chunk (Anthropic: w×h/750).

# Phase 4: Pagination

1. Daten extrahieren (Phase 3)
2. `browser_click_text(text="Nächste Seite")` oder `browser_scroll(direction="down")`
3. `browser_wait_for(text="neuer Content")` oder `browser_look()`
4. Wiederholen bis Stop-Bedingung (max 10 Seiten)

# Phase 5: Output

```json
{
  "url": "https://...",
  "title": "Seitentitel",
  "data": [{"name": "...", "price": "..."}],
  "pages_scraped": 3
}
```

Browser am Ende: `browser_close()` (optional — Browser bleibt persistent).

# Typischer Workflow

```
navigate(url) → look() → click_text("Anmelden") → look() → type(ref, text) → look() → ...
```

2 Calls pro Schritt: `look` + Aktion.

# Constraints

- **1 Chrome-Instanz** — Sessions teilen sich den Browser
- **Max 10 Seiten** bei Pagination
- **Timeout**: 10s Default (erzwungen, auch bei hängendem Server)
- **Session-Persistenz**: Logins/Cookies bleiben zwischen Aufrufen erhalten (~/.stealth-browser-data/)
