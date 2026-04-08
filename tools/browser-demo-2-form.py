#!/usr/bin/env python3
"""Demo 2: Formular-Automation — Login + Session-basiertes Scraping.

Zeigt wie Playwright Formulare ausfüllt, abschickt und authentifizierte
Inhalte extrahiert. httpx bräuchte Session-Management + CSRF-Tokens.

Testziel: quotes.toscrape.com (akzeptiert beliebige Credentials)
"""

import json
import sys
import time

from playwright.sync_api import sync_playwright


def login_and_scrape(url: str = "https://quotes.toscrape.com") -> dict:
    """Login via Formular, dann authentifizierten Content extrahieren."""
    start = time.time()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="de-DE")
        page = context.new_page()

        # Schritt 1: Login-Seite laden
        page.goto(f"{url}/login", wait_until="domcontentloaded")
        login_title = page.title()

        # Schritt 2: Formular ausfüllen
        page.fill("#username", "testuser")
        page.fill("#password", "testpass123")

        # Schritt 3: Absenden
        page.click('input[type="submit"]')
        page.wait_for_load_state("domcontentloaded")
        elapsed_login = time.time() - start

        # Schritt 4: Prüfe ob Login erfolgreich
        is_logged_in = page.query_selector('a[href="/logout"]') is not None

        # Schritt 5: Extrahiere Goodreads-Links (nur nach Login sichtbar)
        quotes_data = page.evaluate("""() => {
            const quotes = [];
            document.querySelectorAll('.quote').forEach(q => {
                const goodreads = q.querySelector('a[href*="goodreads"]');
                quotes.push({
                    text: q.querySelector('.text')?.textContent?.trim(),
                    author: q.querySelector('.author')?.textContent?.trim(),
                    goodreads_url: goodreads?.href || null
                });
            });
            return quotes;
        }""")

        # Schritt 6: Logout
        logout_link = page.query_selector('a[href="/logout"]')
        if logout_link:
            logout_link.click()
            page.wait_for_load_state("domcontentloaded")
        is_logged_out = page.query_selector('a[href="/login"]') is not None

        elapsed_total = time.time() - start
        browser.close()

        return {
            "login_page": login_title,
            "login_success": is_logged_in,
            "login_time_s": round(elapsed_login, 2),
            "quotes_extracted": len(quotes_data),
            "has_goodreads_links": any(q["goodreads_url"] for q in quotes_data),
            "logout_success": is_logged_out,
            "total_time_s": round(elapsed_total, 2),
            "sample": quotes_data[:3],
        }


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://quotes.toscrape.com"

    print(f"Ziel: {url}\n")
    print("=" * 60)
    print("Formular-Automation: Login → Scrape → Logout\n")

    result = login_and_scrape(url)

    print(f"  Login-Seite: {result['login_page']}")
    print(f"  Login erfolgreich: {result['login_success']}")
    print(f"  Login-Zeit: {result['login_time_s']}s")
    print(f"  Quotes extrahiert: {result['quotes_extracted']}")
    print(f"  Goodreads-Links: {result['has_goodreads_links']}")
    print(f"  Logout erfolgreich: {result['logout_success']}")
    print(f"  Gesamtzeit: {result['total_time_s']}s")
    print("\n  Beispiel-Daten:")
    print(json.dumps(result["sample"], indent=4, ensure_ascii=False))


if __name__ == "__main__":
    main()
