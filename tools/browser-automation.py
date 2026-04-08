#!/usr/bin/env python3
"""Browser-Automation Toolkit — Reusable Playwright Patterns.

Kapselt die häufigsten Browser-Automation-Patterns für den HP ProDesk:
- JS-gerenderte Seiten scrapen
- Cookie-Consent wegklicken
- Formulare ausfüllen + absenden
- Multi-Page Pagination
- Screenshots für Debugging

Nutzung:
    from browser_automation import BrowserSession

    with BrowserSession() as session:
        page = session.navigate("https://example.com")
        session.dismiss_cookies(page)
        data = session.extract(page, ".product", {
            "name": ".title",
            "price": ".price",
        })
"""

import json
import sys
import time
from dataclasses import dataclass, field

from playwright.sync_api import Page, sync_playwright


# Bekannte Cookie-Consent-Selektoren
COOKIE_SELECTORS = [
    # Generische Patterns
    'button:has-text("Akzeptieren")',
    'button:has-text("Alle akzeptieren")',
    'button:has-text("Accept")',
    'button:has-text("Accept All")',
    'button:has-text("Accept all")',
    'button:has-text("Agree")',
    'button:has-text("OK")',
    'button:has-text("Verstanden")',
    'button:has-text("Zustimmen")',
    # CMP-spezifisch
    "#onetrust-accept-btn-handler",
    ".cmpboxbtn.cmpboxbtnyes",
    'button[data-cookiefirst-action="accept"]',
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    ".cc-accept",
    ".cookie-consent-accept",
    'button[aria-label="Consent"]',
]


@dataclass
class ScrapeResult:
    """Ergebnis einer Scraping-Operation."""

    url: str
    title: str
    data: list[dict]
    pages_scraped: int = 1
    elapsed_s: float = 0.0
    errors: list[str] = field(default_factory=list)

    def to_json(self, path: str | None = None) -> str:
        out = json.dumps(
            {
                "url": self.url,
                "title": self.title,
                "total_items": len(self.data),
                "pages_scraped": self.pages_scraped,
                "elapsed_s": self.elapsed_s,
                "errors": self.errors,
                "data": self.data,
            },
            indent=2,
            ensure_ascii=False,
        )
        if path:
            with open(path, "w") as f:
                f.write(out)
        return out


class BrowserSession:
    """Managed Playwright Browser-Session."""

    def __init__(
        self, headless: bool = True, locale: str = "de-DE", timeout: int = 30000
    ):
        self.headless = headless
        self.locale = locale
        self.timeout = timeout
        self._pw = None
        self._browser = None
        self._context = None

    def __enter__(self):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            locale=self.locale,
        )
        self._context.set_default_timeout(self.timeout)
        return self

    def __exit__(self, *args):
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def navigate(self, url: str, wait_for: str | None = None) -> Page:
        """Navigiere zu URL und warte optional auf Selector."""
        page = self._context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        if wait_for:
            page.wait_for_selector(wait_for, timeout=self.timeout)
        return page

    def dismiss_cookies(self, page: Page) -> bool:
        """Versuche Cookie-Consent wegzuklicken."""
        for selector in COOKIE_SELECTORS:
            try:
                btn = page.query_selector(selector)
                if btn and btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(500)
                    return True
            except Exception:
                continue
        return False

    def fill_form(
        self, page: Page, fields: dict[str, str], submit: str | None = None
    ) -> None:
        """Formular ausfüllen. fields = {selector: value}"""
        for selector, value in fields.items():
            page.fill(selector, value)
        if submit:
            page.click(submit)
            page.wait_for_load_state("domcontentloaded")

    def extract(
        self, page: Page, item_selector: str, field_map: dict[str, str]
    ) -> list[dict]:
        """Extrahiere strukturierte Daten aus der Seite.

        Args:
            item_selector: CSS-Selektor für jedes Item (z.B. '.product')
            field_map: {feldname: css_selektor} relativ zum Item
                       Spezial-Key '*tags' extrahiert eine Liste statt Text

        Returns:
            Liste von Dicts mit extrahierten Feldern
        """
        js_fields = json.dumps(field_map)
        return page.evaluate(
            f"""() => {{
            const fieldMap = {js_fields};
            return Array.from(document.querySelectorAll('{item_selector}')).map(item => {{
                const result = {{}};
                for (const [key, selector] of Object.entries(fieldMap)) {{
                    if (key.startsWith('*')) {{
                        result[key.slice(1)] = Array.from(item.querySelectorAll(selector))
                            .map(el => el.textContent.trim());
                    }} else {{
                        const el = item.querySelector(selector);
                        result[key] = el ? el.textContent.trim() : null;
                    }}
                }}
                return result;
            }});
        }}"""
        )

    def paginate(
        self,
        page: Page,
        item_selector: str,
        field_map: dict[str, str],
        next_selector: str = "li.next a",
        max_pages: int = 50,
        delay_ms: int = 300,
    ) -> list[dict]:
        """Extrahiere Daten über mehrere Seiten."""
        all_data = []
        for i in range(max_pages):
            try:
                page.wait_for_selector(item_selector, timeout=5000)
            except Exception:
                break

            items = self.extract(page, item_selector, field_map)
            all_data.extend(items)

            next_btn = page.query_selector(next_selector)
            if not next_btn:
                break
            next_btn.click()
            page.wait_for_timeout(delay_ms)

        return all_data

    def screenshot(self, page: Page, path: str = "/tmp/pw-screenshot.png") -> str:
        """Screenshot für Debugging."""
        page.screenshot(path=path, full_page=True)
        return path

    def get_text(self, page: Page) -> str:
        """Sichtbaren Text der Seite extrahieren."""
        return page.evaluate("() => document.body.innerText")

    def wait_and_click(self, page: Page, selector: str, timeout: int = 5000) -> bool:
        """Warte auf Element und klicke es."""
        try:
            page.wait_for_selector(selector, timeout=timeout)
            page.click(selector)
            return True
        except Exception:
            return False


# --- CLI ---


def _demo_js_scrape():
    """Demo: JS-Rendering vs httpx."""
    url = "https://quotes.toscrape.com/js/"
    print(f"JS-Scraping: {url}\n")

    with BrowserSession() as session:
        page = session.navigate(url, wait_for=".quote")
        data = session.extract(
            page,
            ".quote",
            {
                "text": ".text",
                "author": ".author",
                "*tags": ".tag",
            },
        )

    print(f"Extrahiert: {len(data)} Quotes")
    for q in data[:3]:
        print(f"  {q['author']}: {q['text'][:60]}...")


def _demo_login():
    """Demo: Formular-Automation."""
    url = "https://quotes.toscrape.com"
    print(f"Login-Flow: {url}\n")

    with BrowserSession() as session:
        page = session.navigate(f"{url}/login")
        session.fill_form(
            page,
            {
                "#username": "testuser",
                "#password": "testpass",
            },
            submit='input[type="submit"]',
        )

        logged_in = page.query_selector('a[href="/logout"]') is not None
        print(f"  Login erfolgreich: {logged_in}")

        data = session.extract(
            page,
            ".quote",
            {
                "text": ".text",
                "author": ".author",
            },
        )
        print(f"  Quotes nach Login: {len(data)}")


def _demo_multipage():
    """Demo: Multi-Page Pagination."""
    url = "https://quotes.toscrape.com/js/"
    print(f"Pagination: {url}\n")

    start = time.time()
    with BrowserSession() as session:
        page = session.navigate(url, wait_for=".quote")
        data = session.paginate(
            page,
            ".quote",
            {
                "text": ".text",
                "author": ".author",
                "*tags": ".tag",
            },
        )

    elapsed = time.time() - start
    print(f"\n  Total: {len(data)} Quotes in {elapsed:.1f}s")

    from collections import Counter

    authors = Counter(q["author"] for q in data)
    print("  Top-Autoren:")
    for author, count in authors.most_common(5):
        print(f"    {count:2d}x {author}")


DEMOS = {
    "js": _demo_js_scrape,
    "login": _demo_login,
    "multipage": _demo_multipage,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in DEMOS:
        print("Browser-Automation Toolkit")
        print(f"\nNutzung: {sys.argv[0]} <demo>")
        print(f"Demos:   {', '.join(DEMOS)}")
        print("\nOder als Library:")
        print("  from browser_automation import BrowserSession")
        return

    DEMOS[sys.argv[1]]()


if __name__ == "__main__":
    main()
