#!/usr/bin/env python3
"""Demo 3: Multi-Step Pagination — JS-gerenderte Seiten durchblättern.

Navigiert automatisch durch alle Seiten einer JS-gerenderten Website,
sammelt Daten und aggregiert Statistiken. httpx kann das nicht,
weil die Inhalte erst per JavaScript in den DOM injiziert werden.

Testziel: quotes.toscrape.com/js/ (10 Seiten, 100 Quotes)
"""

import json
import sys
import time
from collections import Counter

from playwright.sync_api import sync_playwright


def scrape_all_pages(base_url: str = "https://quotes.toscrape.com/js/") -> dict:
    """Alle Seiten durchlaufen und Daten sammeln."""
    start = time.time()
    all_quotes = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(base_url, wait_until="domcontentloaded")

        page_num = 0
        while True:
            page_num += 1

            # Warte auf JS-Rendering
            page.wait_for_selector(".quote", timeout=5000)

            # Extrahiere Quotes dieser Seite
            quotes = page.evaluate("""() => {
                return Array.from(document.querySelectorAll('.quote')).map(q => ({
                    text: q.querySelector('.text')?.textContent?.trim(),
                    author: q.querySelector('.author')?.textContent?.trim(),
                    tags: Array.from(q.querySelectorAll('.tag')).map(t => t.textContent)
                }));
            }""")

            all_quotes.extend(quotes)
            print(f"  Seite {page_num}: {len(quotes)} Quotes gesammelt")

            # Nächste Seite?
            next_btn = page.query_selector("li.next a")
            if not next_btn:
                break
            next_btn.click()
            page.wait_for_timeout(300)

        elapsed = time.time() - start
        browser.close()

    # Statistiken
    authors = Counter(q["author"] for q in all_quotes)
    all_tags = Counter(t for q in all_quotes for t in q["tags"])

    return {
        "total_pages": page_num,
        "total_quotes": len(all_quotes),
        "unique_authors": len(authors),
        "top_authors": authors.most_common(5),
        "top_tags": all_tags.most_common(10),
        "elapsed_s": round(elapsed, 2),
        "quotes": all_quotes,
    }


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://quotes.toscrape.com/js/"

    print(f"Ziel: {url}\n")
    print("=" * 60)
    print("Multi-Page Pagination (JS-gerendert)\n")

    result = scrape_all_pages(url)

    print(f"\n{'=' * 60}")
    print("Ergebnis:")
    print(f"  Seiten:  {result['total_pages']}")
    print(f"  Quotes:  {result['total_quotes']}")
    print(f"  Autoren: {result['unique_authors']}")
    print(f"  Zeit:    {result['elapsed_s']}s")
    print("\nTop 5 Autoren:")
    for author, count in result["top_authors"]:
        print(f"  {count:2d}x {author}")
    print("\nTop 10 Tags:")
    for tag, count in result["top_tags"]:
        print(f"  {count:2d}x {tag}")

    # Optional: JSON-Export
    if "--json" in sys.argv:
        outfile = "/tmp/quotes-all.json"
        with open(outfile, "w") as f:
            json.dump(result["quotes"], f, indent=2, ensure_ascii=False)
        print(f"\nJSON exportiert: {outfile}")


if __name__ == "__main__":
    main()
