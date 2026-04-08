# Browser Automation — nodriver (Stand 2026-03-06)

## Kern-Erkenntnis

**Playwright wird von TikTok/webmssdk blockiert (0 API-Calls). nodriver funktioniert (alle API-Calls gehen durch).**

Grund: nodriver hat kein WebDriver-Protokoll und keine Playwright-spezifischen Automation-Artefakte.
webmssdk generiert X-Bogus/X-Gnarly Tokens normal → Server akzeptiert Requests.

## nd_daemon.py + nd_cmd.py (Projekt: browser-benchmark)

Architektur: Unix-Socket-Daemon hält Browser persistent, CLI-Tool sendet JSON-Commands.

```bash
# Start
DISPLAY=:99 python3 nd_daemon.py &    # Daemon im Background
python3 nd_cmd.py ping                 # Test
python3 nd_cmd.py goto URL             # Navigate
python3 nd_cmd.py click "text"         # Click by text
python3 nd_cmd.py snap                 # Screenshot + DOM analysis
```

Wichtig:
- `headless=False` + Xvfb nötig (headless wird erkannt)
- Auto-Snap nach jedem Mutations-Command (Dual-Channel: DOM + Screenshot)
- nodriver evaluate() gibt raw CDP zurück → `JSON.stringify()` in JS verwenden
- Custom Dropdowns: `tab.find("text", best_match=True)` oder JS `document.querySelectorAll('[role=option]')`
- React-kompatible Input-Werte setzen: native setter + `dispatchEvent(new Event('input', {bubbles: true}))`
- Komplexes JS: In Temp-Datei schreiben und mit `$(cat /tmp/file.js)` übergeben (Shell-Escaping)
- `find("Audio")` kann Style-Elemente statt Buttons matchen → CSS-Selektor oder JS bevorzugen

## nodriver API Cheat Sheet

```python
import nodriver as uc
from nodriver import cdp

browser = await uc.start(browser_executable_path="/usr/bin/chromium", sandbox=False, headless=False, lang="en-US")
tab = await browser.get(url)
el = await tab.find("text", best_match=True)   # By visible text
el = await tab.select("css-selector")           # By CSS
await el.mouse_click()
await el.send_keys("text")
await tab.save_screenshot("/path.png")
raw = await tab.evaluate("JSON.stringify({...})")  # Always wrap in JSON.stringify!
await tab.send(cdp.page.add_script_to_evaluate_on_new_document(source=js))  # Init script
browser.stop()
```

## TikTok Signup — Vollständig automatisierter Flow

### Funktionierende Schritte (alle gelöst)
1. Cookie-Banner → `click "Decline optional cookies"`
2. Birthday → Custom Dropdowns: `click "Month"` → `click "March"`. Day/Year: JS `querySelectorAll('[role=option]')`
3. Email/Password → React native setter (nicht `send_keys`)
4. Send code → JS `btn.click()` (nodriver `mouse_click` matcht manchmal falsche Elemente)
5. Code empfangen → mail.tm API (Temp-Email) oder email_agent.py (Gmail)
6. Code eingeben → React native setter
7. Next → JS `btn.click()` → feuert `register_verify_login` API

### Automatisierungs-Skript: `/tmp/tiktok_signup.py`
Vollständiger End-to-End-Flow: navigate → cookies → birthday → email → password → send code → wait for email → enter code → click next. Liest Credentials aus `/tmp/tempmail_creds.json`.

## nd_daemon.py Features

- **Full-Page-Screenshot**: CDP `Page.captureScreenshot` + `Emulation.setDeviceMetricsOverride`
- **Drag Command**: CDP `Input.dispatchMouseEvent` für CAPTCHA-Slider (eased motion + overshoot)
- **Proxy-Support**: `BROWSER_PROXY=socks5://127.0.0.1:9050 python3 nd_daemon.py`
- **Fingerprint-Noise**: Canvas-Noise, AudioContext-Noise, Screen-Resolution-Jitter (per Session random seed)
- **Stealth-JS**: WebGL vendor/renderer, navigator.languages, deviceMemory, Battery API

## TikTok Rate-Limiting — KORRIGIERTE Analyse (Session 2)

**WICHTIG: Frühere Analyse war falsch! Rate-Limit ist NICHT nur code-basiert.**

### Getestete Variablen (alle OHNE Effekt auf error_code 7):
- ✗ Andere IP (Tor SOCKS5 proxy, 2 verschiedene Exit-IPs)
- ✗ Andere Device-ID (3+ verschiedene DIDs durch Browser-Restart)
- ✗ Andere Email-Adresse (4 verschiedene dollicons.com Adressen)
- ✗ Anderer Verification-Code (055256, 445058, 053228 — alle frisch und nie zuvor verwendet)
- ✗ Canvas/AudioContext Fingerprint-Noise
- ✗ Terms-Checkbox gecheckt
- ✗ Gmail statt Temp-Email (keine neue Code-Email erhalten)

### Was wir wissen:
- `send_code` funktioniert IMMER (Button zeigt "Resend code: XXs")
- Codes kommen bei Temp-Emails (dollicons.com) an, bei Gmail nicht mehr (rate-limited)
- `register_verify_login` gibt IMMER `error_code: 7` zurück
- Error persistiert über IP-Wechsel, Device-Wechsel UND Email-Wechsel

### Vermutung:
TikTok nutzt ein Multi-Layer Anti-Abuse System das vermutlich:
1. Hardware-Fingerprints trackt die Canvas/WebGL-Noise überleben (z.B. GPU-spezifische Rendering-Artefakte)
2. Oder globale Cooldowns hat die zeitbasiert sind (Stunden/Tage)
3. Oder die `dollicons.com` Domain als Disposable-Email blockt (aber dann wäre die Fehlermeldung anders)

### Nächste Schritte um Signup zu schaffen:
1. **Warten** (12-24h) und dann mit dem bestehenden Skript erneut versuchen
2. **Anderes Gerät** verwenden (komplett anderer Hardware-Fingerprint)
3. **Anderen Email-Provider** testen (nicht mail.tm, z.B. Proton oder eigene Domain)

## Temp-Email (mail.tm)

```bash
python3 /tmp/tempmail.py create          # Neues Account → JSON mit email, token
python3 /tmp/tempmail.py inbox TOKEN     # Inbox anzeigen
python3 /tmp/tempmail.py wait TOKEN 90   # Auf Email warten (90s timeout)
```

Credentials werden in `/tmp/tempmail_creds.json` gespeichert.
Domain: dollicons.com (variiert, von mail.tm API dynamisch).

## CAPTCHA — Rotation Puzzle

- Typ: "Drag the puzzle piece into place" — Rotations-CAPTCHA
- Donut-BG (347x347) + kreisförmiges Puzzle-Stück (211x211)
- Bilder als base64 Data-URLs im DOM
- Solver: `/tmp/solve_rotation_captcha.py` (OpenCV, Multi-Band-Boundary-Matching)
- **ACHTUNG Slider-Bug**: Solver fand X-Button (top-right) statt Slider-Button (bottom-left). Heuristik: `r.y > captchaR.y + 60% height` + `r.width > 30`
- CAPTCHA erscheint nicht bei jedem Send-Code — hängt von Risiko-Score ab
- CAPTCHA hat Timeout (~60s) — Solver muss schnell sein

## TikTok Gmail-Normalisierung

TikTok ignoriert Punkte UND +Aliase bei Gmail. Alle Varianten → gleicher Code, gleiche Email.

## Fritz!Box TR-064 — Vorsicht

**ACHTUNG**: ForceTermination killt eigene API-Verbindung! Nur browser-seitigen Proxy nutzen.
