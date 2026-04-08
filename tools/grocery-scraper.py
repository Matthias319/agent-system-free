#!/usr/bin/env python3
"""Aldi Süd Produkt-Scraper für den /grocery Skill.

Scraped den Aldi-Produktkatalog und gibt strukturierte Produktdaten zurück.
Erweiterbar auf andere Supermärkte (REWE, Lidl sobald APIs/Seiten verfügbar).

Usage:
    uv run ./tools/grocery-scraper.py --categories fitness
    uv run ./tools/grocery-scraper.py --categories all
    uv run ./tools/grocery-scraper.py --categories "obst,gemüse,fleisch"
    uv run ./tools/grocery-scraper.py --search "haferflocken"
"""

import argparse
import json
import re
import sys
import time

import httpx
from selectolax.parser import HTMLParser

BASE = "https://www.aldi-sued.de"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

# Alle verfügbaren Kategorien mit Aldi-URL-Pfaden
ALL_CATEGORIES = {
    "obst": "/produkte/obst/k/1588161425467060",
    "gemüse": "/produkte/gemuese/k/1588161425467066",
    "hähnchen": "/produkte/fleisch-fisch/haehnchen-gefluegel/k/1588161425467054",
    "rind-schwein": "/produkte/fleisch-fisch/rind-schwein-lamm/k/1588161425467053",
    "wurst": "/produkte/wurst-aufschnitt/k/1588161425467075",
    "käse": "/produkte/kaese/k/1588161425467083",
    "milch-eier": "/produkte/milchprodukte-eier/k/1588161425467093",
    "joghurt": "/produkte/milchprodukte-eier/joghurt/k/1588161425467094",
    "nudeln-reis": "/produkte/nudeln-reis-huelsenfruechte/k/1588161425467115",
    "nüsse": "/produkte/nussplatten-trockenobst-nuesse/k/1588161425467171",
    "vegan": "/produkte/vegetarisch-vegan/k/1588161425467039",
    "brot": "/produkte/backwaren-aufstriche-cerealien/k/1588161425467101",
    "aufstriche": "/produkte/backwaren-aufstriche-cerealien/aufstriche/k/1588161425467108",
    "müsli": "/produkte/backwaren-aufstriche-cerealien/muesli-cerealien/k/1588161425467113",
    "tk-gemüse": "/produkte/tiefkuehlung/tk-gemuese/k/1588161425467150",
    "tk-fleisch": "/produkte/tiefkuehlung/tk-fleisch/k/1588161425467142",
    "tk-fertig": "/produkte/tiefkuehlung/tk-pfannen-fertiggerichte/k/1588161425467147",
    "konserven": "/produkte/konserven-fertiggerichte/k/1588161425467133",
    "saucen-öle": "/produkte/saucen-oele-gewuerze/k/1588161425467121",
    "getränke": "/produkte/getraenke/k/1588161425467180",
    "wasser-saft": "/produkte/getraenke/wasser-saft-schorle/k/1588161425467182",
}

# Vordefinierte Kategorie-Sets
CATEGORY_SETS = {
    "fitness": [
        "obst",
        "gemüse",
        "hähnchen",
        "rind-schwein",
        "milch-eier",
        "joghurt",
        "nudeln-reis",
        "nüsse",
        "brot",
        "tk-gemüse",
        "konserven",
        "wasser-saft",
        "vegan",
    ],
    "basics": [
        "obst",
        "gemüse",
        "milch-eier",
        "brot",
        "nudeln-reis",
        "getränke",
        "konserven",
    ],
    "all": list(ALL_CATEGORIES.keys()),
}


def extract_product(a_tag: object) -> dict | None:
    """Extrahiere Produktinfo aus einem Produkt-Link."""
    href = a_tag.attributes.get("href", "")
    if "/produkt/" not in href:
        return None

    full_text = a_tag.text(strip=True, separator=" ")

    # Produktname aus URL (zuverlässiger als HTML-Parsing)
    url_part = href.split("/produkt/")[-1]
    # Entferne die Artikelnummer am Ende (000000000...)
    name_raw = re.sub(r"-0{6,}\d+$", "", url_part)
    name = name_raw.replace("-", " ").strip().title()

    # Preis: Suche nach dem günstigsten/aktuellen Preis
    # Reduzierter Preis hat Vorrang
    prices = re.findall(r"(\d+,\d{2})\s*€", full_text)
    price_str = prices[0] if prices else ""
    price = float(price_str.replace(",", ".")) if price_str else 0.0

    # Gewicht/Menge
    weight_match = re.search(
        r"(\d+(?:,\d+)?)\s*(kg|g|l|ml)\b", full_text, re.IGNORECASE
    )
    weight = weight_match.group(0) if weight_match else ""
    weight_g = 0.0
    if weight_match:
        val = float(weight_match.group(1).replace(",", "."))
        unit = weight_match.group(2).lower()
        if unit == "kg":
            weight_g = val * 1000
        elif unit == "g":
            weight_g = val
        elif unit == "l":
            weight_g = val * 1000  # ml equivalent
        elif unit == "ml":
            weight_g = val

    # Kilopreis
    kgprice_match = re.search(r"\((\d+,\d{2})\s*€/1\s*(kg|l)\)", full_text)
    kgprice = float(kgprice_match.group(1).replace(",", ".")) if kgprice_match else 0.0
    kgprice_unit = kgprice_match.group(2) if kgprice_match else ""

    # Berechne Kilopreis falls nicht vorhanden
    if not kgprice and price > 0 and weight_g > 0:
        kgprice = price / (weight_g / 1000)

    # Tags aus dem Text extrahieren
    tags = []
    text_lower = full_text.lower()
    if "bio" in text_lower:
        tags.append("bio")
    if "vegan" in text_lower:
        tags.append("vegan")
    if "protein" in text_lower:
        tags.append("protein")
    if "kühlung" in text_lower:
        tags.append("kühlware")
    if "laktosefrei" in text_lower:
        tags.append("laktosefrei")

    return {
        "name": name,
        "price": price,
        "weight": weight,
        "weight_g": weight_g,
        "kgprice": round(kgprice, 2),
        "kgprice_unit": kgprice_unit or "kg",
        "tags": tags,
        "url": href,
        "full_url": f"{BASE}{href}",
    }


def scrape_category(
    client: httpx.Client, cat_name: str, cat_path: str, max_pages: int = 3
) -> list[dict]:
    """Scrape eine Kategorie (mit Pagination)."""
    products = []
    seen_urls = set()

    for page in range(1, max_pages + 1):
        url = f"{BASE}{cat_path}"
        if page > 1:
            url += f"?page={page}"

        try:
            r = client.get(url)
            if r.status_code != 200:
                break

            tree = HTMLParser(r.text)
            page_products = 0

            for a in tree.css('a[href*="/produkt/"]'):
                p = extract_product(a)
                if p and p["url"] not in seen_urls:
                    seen_urls.add(p["url"])
                    p["category"] = cat_name
                    products.append(p)
                    page_products += 1

            if page_products == 0:
                break

        except Exception as e:
            print(f"  Fehler bei {cat_name} Seite {page}: {e}", file=sys.stderr)
            break

        time.sleep(0.2)

    return products


def search_products(client: httpx.Client, query: str) -> list[dict]:
    """Suche nach Produkten über die Aldi-Suchfunktion."""
    url = f"{BASE}/produkte?query={query}"
    try:
        r = client.get(url)
        tree = HTMLParser(r.text)
        products = []
        seen = set()
        for a in tree.css('a[href*="/produkt/"]'):
            p = extract_product(a)
            if p and p["url"] not in seen:
                seen.add(p["url"])
                p["category"] = f"Suche: {query}"
                products.append(p)
        return products
    except Exception as e:
        print(f"Suchfehler: {e}", file=sys.stderr)
        return []


def main():
    parser = argparse.ArgumentParser(description="Aldi Süd Produkt-Scraper")
    parser.add_argument(
        "--categories",
        default="fitness",
        help="Kategorie-Set (fitness/basics/all) oder komma-getrennte Liste",
    )
    parser.add_argument("--search", help="Produktsuche")
    parser.add_argument(
        "--max-pages", type=int, default=2, help="Max Seiten pro Kategorie"
    )
    parser.add_argument(
        "--output", default="/tmp/aldi_products.json", help="Output-Datei"
    )
    parser.add_argument("--quiet", action="store_true", help="Weniger Output")
    args = parser.parse_args()

    client = httpx.Client(headers=HEADERS, follow_redirects=True, timeout=15)

    if args.search:
        products = search_products(client, args.search)
        if not args.quiet:
            print(f"Suche '{args.search}': {len(products)} Treffer", file=sys.stderr)
    else:
        # Kategorien auflösen
        if args.categories in CATEGORY_SETS:
            cat_names = CATEGORY_SETS[args.categories]
        else:
            cat_names = [c.strip() for c in args.categories.split(",")]

        products = []
        for cat_name in cat_names:
            if cat_name not in ALL_CATEGORIES:
                print(
                    f"  Unbekannte Kategorie: {cat_name} (verfügbar: {', '.join(ALL_CATEGORIES.keys())})",
                    file=sys.stderr,
                )
                continue

            cat_prods = scrape_category(
                client, cat_name, ALL_CATEGORIES[cat_name], args.max_pages
            )
            products.extend(cat_prods)
            if not args.quiet:
                print(f"  {cat_name}: {len(cat_prods)} Produkte", file=sys.stderr)

    client.close()

    # Deduplizieren
    seen = set()
    unique = []
    for p in products:
        if p["url"] not in seen:
            seen.add(p["url"])
            unique.append(p)

    # Output
    result = {
        "store": "aldi-sued",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total_products": len(unique),
        "products": unique,
    }

    with open(args.output, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    if not args.quiet:
        print(
            f"\n{len(unique)} Produkte → {args.output}",
            file=sys.stderr,
        )

    # Auch auf stdout für Pipe-Nutzung
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
