#!/usr/bin/env python3
"""REWE Warenkorb-Automation via undetected-chromedriver + CDP.

Startet einen persistenten Chrome-Browser, loggt sich bei REWE ein,
und füllt den Warenkorb mit Produkten.

Architektur: Chrome läuft persistent im Hintergrund (Xvfb + CDP Port 9222).
Steuerung über pychrome (Chrome DevTools Protocol).

Usage:
    # Browser starten (einmalig pro Session)
    uv run ./tools/rewe-cart.py start

    # Login (erfordert 2FA-Code von User)
    uv run ./tools/rewe-cart.py login

    # 2FA-Code eingeben
    uv run ./tools/rewe-cart.py code 371717

    # Produkt suchen und in Warenkorb (mit Keyword-Matching!)
    uv run ./tools/rewe-cart.py add "Haferflocken zart"

    # Mehrere Produkte aus JSON-Datei
    uv run ./tools/rewe-cart.py add-list /tmp/shopping.json

    # Warenkorb-Inhalt als JSON auflisten
    uv run ./tools/rewe-cart.py list

    # Produkt aus Warenkorb entfernen (nach Name-Substring)
    uv run ./tools/rewe-cart.py remove "Kölln Bio"

    # Mehrere Produkte entfernen
    uv run ./tools/rewe-cart.py remove-list /tmp/remove.json

    # Warenkorb-Status prüfen
    uv run ./tools/rewe-cart.py status

    # Screenshot machen
    uv run ./tools/rewe-cart.py screenshot /tmp/rewe.png

    # Browser beenden
    uv run ./tools/rewe-cart.py stop
"""

import argparse
import base64
import json
import subprocess
import sys
import time
from pathlib import Path

CDP_PORT = 9222
DISPLAY = ":99"
ENV_FILE = Path.home() / ".claude" / ".env"


def ensure_browser():
    """Prüfe ob Chrome + Xvfb laufen."""
    import httpx

    try:
        r = httpx.get(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def start_browser():
    """Starte Xvfb + Chrome mit Remote-Debugging."""
    if ensure_browser():
        print("Browser läuft bereits", file=sys.stderr)
        return

    subprocess.Popen(
        ["Xvfb", DISPLAY, "-screen", "0", "1920x1080x24"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1)

    import os

    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY
    subprocess.Popen(
        [
            "/usr/bin/chromium",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            f"--remote-debugging-port={CDP_PORT}",
            "--window-size=1920,1080",
            "--lang=de-DE",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    time.sleep(3)

    if ensure_browser():
        print("Browser gestartet (CDP Port 9222)", file=sys.stderr)
    else:
        print("FEHLER: Browser konnte nicht gestartet werden", file=sys.stderr)
        sys.exit(1)


def get_tab():
    """Verbinde zum ersten Tab via pychrome."""
    import pychrome

    browser = pychrome.Browser(url=f"http://127.0.0.1:{CDP_PORT}")
    tab = browser.list_tab()[0]
    tab.start()
    return tab


def js(tab, expression):
    """JavaScript ausführen und Ergebnis zurückgeben."""
    r = tab.Runtime.evaluate(expression=expression)
    return r.get("result", {}).get("value", "")


def take_screenshot(tab, path):
    """Screenshot als PNG speichern."""
    r = tab.Page.captureScreenshot(format="png")
    with open(path, "wb") as f:
        f.write(base64.b64decode(r["data"]))


def navigate(tab, url):
    """Navigiere und warte."""
    tab.Page.navigate(url=url)
    time.sleep(5)


def dismiss_cookies(tab):
    """Cookie-Banner schließen (Usercentrics Shadow DOM)."""
    js(
        tab,
        """(function() {
            var uc = document.getElementById('usercentrics-root');
            if (uc && uc.shadowRoot) {
                var btns = uc.shadowRoot.querySelectorAll('button');
                for (var j = 0; j < btns.length; j++) {
                    if (btns[j].textContent.trim().toLowerCase().includes('nur notwendige'))
                        { btns[j].click(); return 'dismissed'; }
                }
            }
            return 'no-banner';
        })()""",
    )
    time.sleep(1)


def load_credentials():
    """Lade REWE Credentials aus .env."""
    if not ENV_FILE.exists():
        return None, None
    content = ENV_FILE.read_text()
    email = password = ""
    for line in content.splitlines():
        if line.startswith("REWE_EMAIL="):
            email = line.split("=", 1)[1].strip()
        elif line.startswith("REWE_PASS="):
            password = line.split("=", 1)[1].strip()
    return email, password


def cmd_start(_args):
    start_browser()


def cmd_login(_args):
    """Login starten — navigiert zur Login-Seite und gibt Credentials ein."""
    email, password = load_credentials()
    if not email or not password:
        print("FEHLER: REWE_EMAIL/REWE_PASS nicht in ./.env", file=sys.stderr)
        sys.exit(1)

    tab = get_tab()
    navigate(tab, "https://shop.rewe.de/mydata/login")
    time.sleep(5)
    dismiss_cookies(tab)

    js(
        tab,
        f"""(function() {{
            var inputs = document.querySelectorAll('input');
            for (var i = 0; i < inputs.length; i++) {{
                var t = inputs[i].type || '';
                var n = (inputs[i].name || '').toLowerCase();
                if (t === 'email' || n.includes('email')) {{
                    inputs[i].focus();
                    inputs[i].value = '{email}';
                    inputs[i].dispatchEvent(new Event('input', {{bubbles: true}}));
                    inputs[i].dispatchEvent(new Event('change', {{bubbles: true}}));
                }} else if (t === 'password' || n.includes('pass')) {{
                    inputs[i].focus();
                    inputs[i].value = '{password}';
                    inputs[i].dispatchEvent(new Event('input', {{bubbles: true}}));
                    inputs[i].dispatchEvent(new Event('change', {{bubbles: true}}));
                }}
            }}
            return 'ok';
        }})()""",
    )
    time.sleep(1)

    js(
        tab,
        """(function() {
            var btns = document.querySelectorAll('button');
            for (var i = 0; i < btns.length; i++) {
                try { var t = btns[i].textContent.trim().toLowerCase();
                    if (t === 'anmelden' && btns[i].offsetParent !== null) { btns[i].click(); return 'ok'; }
                } catch(e) {}
            }
            return 'no-btn';
        })()""",
    )
    time.sleep(10)

    take_screenshot(tab, "/tmp/rewe-login-status.png")
    body = js(tab, "document.body.innerText.substring(0, 300)")

    if "code" in body.lower() or "bestätig" in body.lower():
        print("2FA_NEEDED")
    elif "Hallo" in body or "loggedIn" in js(tab, "window.location.href"):
        print("LOGGED_IN")
    else:
        print("UNKNOWN")
        print(f"Body: {body[:100]}", file=sys.stderr)

    tab.stop()


def cmd_code(args):
    """2FA-Code eingeben und bestätigen."""
    code = args.code
    tab = get_tab()

    js(
        tab,
        f"""(function() {{
            var inputs = document.querySelectorAll('input');
            for (var i = 0; i < inputs.length; i++) {{
                if (inputs[i].offsetParent !== null && inputs[i].type !== 'hidden') {{
                    inputs[i].focus();
                    inputs[i].value = '{code}';
                    inputs[i].dispatchEvent(new Event('input', {{bubbles: true}}));
                    inputs[i].dispatchEvent(new Event('change', {{bubbles: true}}));
                    return 'set';
                }}
            }}
            return 'no-input';
        }})()""",
    )
    time.sleep(1)

    js(
        tab,
        """(function() {
            var btns = document.querySelectorAll('button');
            for (var i = 0; i < btns.length; i++) {
                try { var t = btns[i].textContent.trim().toLowerCase();
                    if (btns[i].offsetParent !== null &&
                        (t.includes('bestätigen') || t.includes('weiter') || t.includes('code')))
                        { btns[i].click(); return 'ok'; }
                } catch(e) {}
            }
            return 'no-btn';
        })()""",
    )
    time.sleep(12)

    url = js(tab, "window.location.href")
    if "loggedIn" in url or "shop" in url.split("?")[0]:
        print("LOGGED_IN")
    else:
        print("UNKNOWN")
        take_screenshot(tab, "/tmp/rewe-after-code.png")
        print(f"URL: {url}", file=sys.stderr)

    tab.stop()


def _search_keywords(search_term):
    """Extrahiere relevante Keywords aus Suchbegriff für Matching."""
    # Ignoriere Marken-Prefixe und Mengenangaben beim Matching
    skip = {"ja!", "rewe", "bio", "beste", "wahl", "ca.", "ca", "g", "kg", "ml", "l"}
    words = search_term.lower().replace("!", "").split()
    return [w for w in words if w not in skip and len(w) > 1]


def _product_matches(product_name, search_keywords):
    """Prüfe ob ein Produktname mindestens die Hälfte der Keywords enthält."""
    if not search_keywords:
        return True
    name_lower = product_name.lower()
    matches = sum(1 for kw in search_keywords if kw in name_lower)
    return matches >= max(1, len(search_keywords) // 2)


def _find_best_product_link(tab, search_term):
    """Suche Produkt und gib den besten Match zurück (Link + Name)."""
    keywords = _search_keywords(search_term)

    # Alle Produktlinks mit Namen sammeln
    products_json = js(
        tab,
        """(function() {
            var links = document.querySelectorAll("a[href*='/shop/p/']");
            var results = [];
            var seen = {};
            for (var i = 0; i < links.length; i++) {
                if (links[i].offsetParent !== null) {
                    var href = links[i].href;
                    if (seen[href]) continue;
                    seen[href] = true;
                    var name = links[i].textContent.trim().replace(/\\s+/g, ' ').substring(0, 120);
                    results.push(JSON.stringify({href: href, name: name}));
                    if (results.length >= 10) break;
                }
            }
            return '[' + results.join(',') + ']';
        })()""",
    )

    try:
        products = json.loads(products_json) if products_json else []
    except json.JSONDecodeError:
        products = []

    if not products:
        return None, None

    # Besten Match finden: erstes Produkt dessen Name die Keywords enthält
    for p in products:
        if _product_matches(p.get("name", ""), keywords):
            return p["href"], p["name"]

    # Kein Match — NICHT blind das erste nehmen
    return None, None


def cmd_add(args):
    """Ein Produkt suchen und in den Warenkorb legen."""
    search_term = args.product
    tab = get_tab()

    navigate(
        tab,
        f"https://shop.rewe.de/productList?search={search_term.replace(' ', '+')}",
    )
    time.sleep(3)

    link, preview_name = _find_best_product_link(tab, search_term)

    if not link:
        print(json.dumps({"status": "not_found", "search": search_term}))
        tab.stop()
        return

    navigate(tab, link)
    result = js(
        tab,
        """(function() {
            var btns = document.querySelectorAll('button');
            for (var i = 0; i < btns.length; i++) {
                var aria = (btns[i].getAttribute('aria-label') || '');
                if (aria.includes('Produkt hinzufügen') && btns[i].offsetParent !== null)
                    { btns[i].click(); return 'added'; }
            }
            return 'no-btn';
        })()""",
    )
    time.sleep(1)

    name = js(tab, "document.querySelector('h1')?.textContent?.trim() || ''")
    print(
        json.dumps(
            {
                "status": "added" if result == "added" else "failed",
                "search": search_term,
                "product": name,
            },
            ensure_ascii=False,
        )
    )
    tab.stop()


def cmd_add_list(args):
    """Mehrere Produkte aus JSON-Datei in den Warenkorb legen."""
    with open(args.file) as f:
        items = json.load(f)

    tab = get_tab()
    added = 0
    results = []

    for item in items:
        search_term = item if isinstance(item, str) else item.get("search", "")
        if not search_term:
            continue

        print(f"  → {search_term}...", end=" ", file=sys.stderr, flush=True)

        navigate(
            tab,
            f"https://shop.rewe.de/productList?search={search_term.replace(' ', '+')}",
        )
        time.sleep(2)

        link, preview_name = _find_best_product_link(tab, search_term)

        if not link:
            print("NICHT GEFUNDEN", file=sys.stderr, flush=True)
            results.append({"search": search_term, "status": "not_found"})
            continue

        navigate(tab, link)
        result = js(
            tab,
            """(function() {
                var btns = document.querySelectorAll('button');
                for (var i = 0; i < btns.length; i++) {
                    var aria = (btns[i].getAttribute('aria-label') || '');
                    if (aria.includes('Produkt hinzufügen') && btns[i].offsetParent !== null)
                        { btns[i].click(); return 'added'; }
                }
                return 'no-btn';
            })()""",
        )

        name = js(tab, "document.querySelector('h1')?.textContent?.trim() || ''")
        ok = result == "added"
        if ok:
            added += 1
        print(f"{'OK' if ok else 'FEHLER'} → {name[:40]}", file=sys.stderr, flush=True)
        results.append(
            {
                "search": search_term,
                "product": name,
                "status": "added" if ok else "failed",
            }
        )
        time.sleep(1)

    print(
        json.dumps(
            {"added": added, "total": len(items), "results": results},
            ensure_ascii=False,
        )
    )
    tab.stop()


def _navigate_to_cart(tab):
    """Navigiere zum Warenkorb (Checkout-Basket)."""
    # Erst zur Shop-Seite, dann Cart-Button klicken (direkter URL geht nicht immer)
    navigate(tab, "https://www.rewe.de/shop/")
    time.sleep(3)
    js(
        tab,
        """(function() {
            var btns = document.querySelectorAll('button');
            for (var i = 0; i < btns.length; i++) {
                var t = btns[i].textContent.trim();
                if (t.includes('€') && t.includes(',')) { btns[i].click(); return 'ok'; }
            }
            return 'no-cart-btn';
        })()""",
    )
    time.sleep(5)


def cmd_list(_args):
    """Warenkorb-Inhalt als JSON auflisten."""
    tab = get_tab()
    _navigate_to_cart(tab)

    items_json = js(
        tab,
        """(function() {
            var containers = document.querySelectorAll('div[class*="OverviewLineItem__lineItemContainer"]');
            var items = [];
            containers.forEach(function(c) {
                var nameEl = c.querySelector('div[class*="OverviewLineItem__lineItem___"]');
                if (!nameEl) return;
                var name = nameEl.textContent.trim();
                var prices = c.querySelectorAll('section[class*="priceContainer"]');
                var einzelpreis = '', gesamtpreis = '';
                if (prices.length >= 2) {
                    einzelpreis = prices[0].textContent.replace('Einzelpreis', '').trim();
                    gesamtpreis = prices[1].textContent.replace('Gesamt', '').trim();
                }
                items.push(JSON.stringify({name: name, einzelpreis: einzelpreis, gesamtpreis: gesamtpreis}));
            });
            return '[' + items.join(',') + ']';
        })()""",
    )

    try:
        items = json.loads(items_json) if items_json else []
    except json.JSONDecodeError:
        items = []

    # Gesamtsumme
    body = js(tab, "document.body.innerText")
    import re

    total_m = re.search(r"Gesamtsumme\s*([\d,]+\s*€)", body or "")
    total = total_m.group(1) if total_m else "?"

    print(
        json.dumps(
            {"items": items, "count": len(items), "total": total},
            ensure_ascii=False,
        )
    )
    tab.stop()


def cmd_remove(args):
    """Produkt aus dem Warenkorb entfernen (nach Name-Substring)."""
    search = args.product
    tab = get_tab()
    _navigate_to_cart(tab)

    removed = False
    for _attempt in range(5):
        result = js(
            tab,
            f"""(function() {{
                var containers = document.querySelectorAll('div[class*="OverviewLineItem__lineItemContainer"]');
                for (var i = 0; i < containers.length; i++) {{
                    if (containers[i].textContent.includes('{search}')) {{
                        var btns = containers[i].querySelectorAll('button');
                        for (var j = 0; j < btns.length; j++) {{
                            var label = btns[j].getAttribute('aria-label') || '';
                            if (label.includes('reduzieren') || label.includes('löschen')) {{
                                btns[j].click();
                                return label;
                            }}
                        }}
                        return 'NO_BTN';
                    }}
                }}
                return 'GONE';
            }})()""",
        )

        if result == "GONE":
            removed = True
            break
        if result == "NO_BTN":
            break
        time.sleep(2)

    print(
        json.dumps(
            {"status": "removed" if removed else "failed", "search": search},
            ensure_ascii=False,
        )
    )
    tab.stop()


def cmd_remove_list(args):
    """Mehrere Produkte aus JSON-Datei aus dem Warenkorb entfernen."""
    with open(args.file) as f:
        items = json.load(f)

    tab = get_tab()
    _navigate_to_cart(tab)
    removed_count = 0
    results = []

    for search in items:
        print(f"  ✕ {search}...", end=" ", file=sys.stderr, flush=True)
        gone = False
        for _attempt in range(5):
            result = js(
                tab,
                f"""(function() {{
                    var containers = document.querySelectorAll('div[class*="OverviewLineItem__lineItemContainer"]');
                    for (var i = 0; i < containers.length; i++) {{
                        if (containers[i].textContent.includes('{search}')) {{
                            var btns = containers[i].querySelectorAll('button');
                            for (var j = 0; j < btns.length; j++) {{
                                var label = btns[j].getAttribute('aria-label') || '';
                                if (label.includes('reduzieren') || label.includes('löschen')) {{
                                    btns[j].click();
                                    return label;
                                }}
                            }}
                            return 'NO_BTN';
                        }}
                    }}
                    return 'GONE';
                }})()""",
            )
            if result == "GONE":
                gone = True
                break
            if result == "NO_BTN":
                break
            time.sleep(2)

        if gone:
            removed_count += 1
            print("ENTFERNT", file=sys.stderr, flush=True)
        else:
            print("FEHLER", file=sys.stderr, flush=True)
        results.append({"search": search, "status": "removed" if gone else "failed"})

    print(
        json.dumps(
            {"removed": removed_count, "total": len(items), "results": results},
            ensure_ascii=False,
        )
    )
    tab.stop()


def cmd_status(_args):
    """Warenkorb-Status abfragen."""
    import re

    tab = get_tab()
    navigate(tab, "https://shop.rewe.de/")
    time.sleep(2)

    body = js(tab, "document.body.innerText")
    url = js(tab, "window.location.href")
    euro = re.search(r"(\d+,\d{2})\s*€", body or "")
    logged_in = "Abmelden" in (body or "") or "Matthias" in (body or "")

    print(
        json.dumps(
            {
                "logged_in": logged_in,
                "cart_total": euro.group(0) if euro else "0,00 €",
                "url": url,
            },
            ensure_ascii=False,
        )
    )
    tab.stop()


def cmd_screenshot(args):
    """Screenshot der aktuellen Seite."""
    tab = get_tab()
    take_screenshot(tab, args.path)
    tab.stop()
    print(f"Screenshot → {args.path}", file=sys.stderr)


def cmd_stop(_args):
    """Browser und Xvfb beenden."""
    subprocess.run(["pkill", "-f", "remote-debugging-port=9222"], capture_output=True)
    subprocess.run(["pkill", "-f", "Xvfb :99"], capture_output=True)
    print("Browser gestoppt", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="REWE Warenkorb-Automation")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("start", help="Browser starten")
    sub.add_parser("login", help="Bei REWE einloggen")

    p_code = sub.add_parser("code", help="2FA-Code eingeben")
    p_code.add_argument("code", help="6-stelliger Code")

    p_add = sub.add_parser("add", help="Produkt hinzufügen")
    p_add.add_argument("product", help="Suchbegriff")

    p_list = sub.add_parser("add-list", help="Produkte aus JSON hinzufügen")
    p_list.add_argument("file", help="JSON-Datei")

    p_rm = sub.add_parser("remove", help="Produkt entfernen (Name-Substring)")
    p_rm.add_argument("product", help="Produktname (Substring)")

    p_rmlist = sub.add_parser("remove-list", help="Produkte aus JSON entfernen")
    p_rmlist.add_argument("file", help="JSON-Datei")

    sub.add_parser("list", help="Warenkorb-Inhalt auflisten")
    sub.add_parser("status", help="Warenkorb-Status")

    p_ss = sub.add_parser("screenshot", help="Screenshot")
    p_ss.add_argument("path", help="Dateipfad")

    sub.add_parser("stop", help="Browser beenden")

    args = parser.parse_args()
    cmds = {
        "start": cmd_start,
        "login": cmd_login,
        "code": cmd_code,
        "add": cmd_add,
        "add-list": cmd_add_list,
        "remove": cmd_remove,
        "remove-list": cmd_remove_list,
        "list": cmd_list,
        "status": cmd_status,
        "screenshot": cmd_screenshot,
        "stop": cmd_stop,
    }

    if args.command in cmds:
        cmds[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
