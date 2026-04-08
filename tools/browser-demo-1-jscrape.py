#!/usr/bin/env python3
"""Demo 1: JS-heavy Scraping — httpx vs Playwright.

Zeigt den Unterschied zwischen reinem HTTP-Request und echtem Browser
an Booking.com: httpx bekommt fast nichts (Bot-Protection + JS-Rendering),
Playwright bekommt die volle Seite mit allen Inhalten.
"""

import json
import re
import sys
import time

import httpx


def scrape_with_httpx(url: str) -> dict:
    """Versuche die Seite mit httpx zu scrapen."""
    start = time.time()
    try:
        resp = httpx.get(
            url,
            follow_redirects=True,
            timeout=15,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0",
                "Accept-Language": "de-DE,de;q=0.9",
            },
        )
        elapsed = time.time() - start
        text = re.sub(r"<[^>]+>", " ", resp.text)
        text = re.sub(r"\s+", " ", text).strip()
        words = [w for w in text.split() if len(w) > 3]
        return {
            "method": "httpx",
            "status": resp.status_code,
            "content_length": len(resp.text),
            "meaningful_words": len(words),
            "elapsed_s": round(elapsed, 2),
            "sample": " ".join(words[:20]),
        }
    except Exception as e:
        return {
            "method": "httpx",
            "error": f"{type(e).__name__}: {e}",
            "elapsed_s": round(time.time() - start, 2),
        }


def scrape_with_playwright(url: str) -> dict:
    """Scrape die Seite mit Playwright headless Chromium."""
    from playwright.sync_api import sync_playwright

    start = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0",
            locale="de-DE",
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        # Warte auf JS-Rendering
        page.wait_for_timeout(3000)

        title = page.title()
        content = page.content()
        # Extrahiere sichtbaren Text
        text = page.evaluate("() => document.body.innerText")
        elapsed = time.time() - start

        words = [w for w in text.split() if len(w) > 3]

        browser.close()

        return {
            "method": "playwright",
            "title": title,
            "content_length": len(content),
            "meaningful_words": len(words),
            "elapsed_s": round(elapsed, 2),
            "sample": " ".join(words[:30]),
        }


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.booking.com"

    print(f"🎯 Ziel: {url}\n")
    print("=" * 60)

    print("\n📡 Test 1: httpx (reiner HTTP-Request)")
    result_httpx = scrape_with_httpx(url)
    print(json.dumps(result_httpx, indent=2, ensure_ascii=False))

    print("\n🌐 Test 2: Playwright (headless Browser)")
    result_pw = scrape_with_playwright(url)
    print(json.dumps(result_pw, indent=2, ensure_ascii=False))

    print("\n" + "=" * 60)
    print("📊 VERGLEICH:")
    h_words = result_httpx.get("meaningful_words", 0)
    p_words = result_pw.get("meaningful_words", 0)
    if h_words > 0:
        factor = round(p_words / h_words, 1)
        print(f"  httpx:      {h_words} Wörter ({result_httpx.get('elapsed_s', '?')}s)")
        print(f"  Playwright: {p_words} Wörter ({result_pw.get('elapsed_s', '?')}s)")
        print(f"  → Playwright liefert {factor}x mehr Content")
    else:
        print("  httpx:      FEHLER oder 0 Wörter")
        print(f"  Playwright: {p_words} Wörter")
        print("  → httpx komplett gescheitert, Playwright erfolgreich")


if __name__ == "__main__":
    main()
