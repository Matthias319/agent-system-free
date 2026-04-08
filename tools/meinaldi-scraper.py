#!/usr/bin/env python3
"""meinALDI Produkt-Scraper (API-basiert).

Nutzt die Spryker Glue API von mein-aldi.de.
Scrape alle Produkte inkl. Nährwerte in einem Durchlauf → SQLite.

Usage:
    uv run ./tools/meinaldi-scraper.py                    # Alle Lebensmittel
    uv run ./tools/meinaldi-scraper.py --all               # Inkl. Non-Food
    uv run ./tools/meinaldi-scraper.py --stats             # DB-Statistiken
    uv run ./tools/meinaldi-scraper.py --search quark      # Suche
    uv run ./tools/meinaldi-scraper.py --top-protein 20    # Top Eiweiß/€
    uv run ./tools/meinaldi-scraper.py --export /tmp/out.json
"""

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

import httpx

DB_PATH = Path.home() / ".claude" / "data" / "meinaldi.db"
API_BASE = "https://api.mein-aldi.de/v3"
SERVICE_POINT = "ADG045_1"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    "Accept": "application/vnd.api+json",
}
PAGE_SIZE = 50

CATEGORIES = {
    "obst-gemüse": "19000000",
    "fleisch-fisch": "22000000",
    "wurstaufschnitt": "1588161408437114",
    "käse": "21000000",
    "eier-milch": "20000000",
    "feinkost": "23000000",
    "tiefkühlung": "30000000",
    "backwaren": "24000000",
    "nudeln-reis": "26000000",
    "saucen-öle": "28000000",
    "konserven": "27000000",
    "backen": "29000000",
    "süßes-salziges": "31000000",
    "getränke": "32000000",
    "alkohol": "33000000",
    "veggie-vegan": "1588161408437106",
    "kaffee": "1588161430420052",
    "tee": "1588161430420060",
    "drogerie": "35000000",
    "baby": "34000000",
    "haushalt": "36000000",
    "tier": "37000000",
    "grillen": "1588161407775435",
    "bio": "18000000",
    "angebote": "12000000",
    "dauerhaft-günstig": "1588161424786225",
}

FOOD_CATEGORIES = [
    "obst-gemüse",
    "fleisch-fisch",
    "wurstaufschnitt",
    "käse",
    "eier-milch",
    "feinkost",
    "tiefkühlung",
    "backwaren",
    "nudeln-reis",
    "saucen-öle",
    "konserven",
    "backen",
    "süßes-salziges",
    "getränke",
    "veggie-vegan",
    "kaffee",
    "tee",
    "grillen",
    "bio",
]


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DROP TABLE IF EXISTS products")
    conn.execute("DROP TABLE IF EXISTS nutrition")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
            sku TEXT PRIMARY KEY,
            name TEXT,
            brand TEXT,
            price_cents INTEGER,
            price REAL,
            weight TEXT,
            kgprice REAL,
            kgprice_display TEXT,
            category TEXT,
            url_slug TEXT,
            image_url TEXT,
            label TEXT,
            diet_type TEXT,
            country_origin TEXT,
            ingredients TEXT,
            allergens TEXT,
            last_seen TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS nutrition (
            sku TEXT PRIMARY KEY,
            energy_kj REAL,
            energy_kcal REAL,
            fat REAL,
            fat_saturated REAL,
            carbs REAL,
            carbs_sugar REAL,
            fiber REAL,
            protein REAL,
            salt REAL,
            per TEXT DEFAULT '100g',
            FOREIGN KEY (sku) REFERENCES products(sku)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cat ON products(category)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_name ON products(name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_brand ON products(brand)")
    conn.commit()
    return conn


def extract_nutrition(nutritional_values: list) -> dict:
    mapping = {
        "ENER-": "energy_kj",
        "ENER-KCAL": "energy_kcal",
        "FAT": "fat",
        "FASAT": "fat_saturated",
        "CHOAVL": "carbs",
        "SUGAR-": "carbs_sugar",
        "FIBTG": "fiber",
        "PRO-": "protein",
        "SALTEQ": "salt",
    }
    result = {}
    for nv in nutritional_values:
        code = nv.get("nutritionTypeCode", "")
        if code in mapping:
            try:
                result[mapping[code]] = float(nv["value"])
            except (ValueError, TypeError):
                pass
    return result


def fetch_category(client: httpx.Client, cat_key: str) -> list[dict]:
    products = []
    offset = 0

    while True:
        url = (
            f"{API_BASE}/product-search"
            f"?serviceType=delivery"
            f"&servicePoint={SERVICE_POINT}"
            f"&categoryKey={cat_key}"
            f"&limit={PAGE_SIZE}"
            f"&offset={offset}"
            f"&sort=relevance"
        )

        r = client.get(url)
        if r.status_code != 200:
            break

        data = r.json()
        items = data.get("data", [])
        if not items:
            break

        products.extend(items)

        total = data.get("meta", {}).get("pagination", {}).get("totalCount", 0)
        offset += PAGE_SIZE
        if offset >= total:
            break

        time.sleep(0.2)

    return products


def store_products(conn: sqlite3.Connection, raw_products: list, category: str):
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    count = 0

    for p in raw_products:
        sku = p.get("sku", "")
        price_info = p.get("price", {})
        price_cents = price_info.get("amountRelevant", 0)
        price = price_cents / 100.0

        # KG-Preis
        kgprice = (price_info.get("comparison", 0) or 0) / 100.0
        kgprice_display = price_info.get("comparisonDisplay", "")

        # Bild-URL (erstes Asset)
        assets = p.get("assets", [])
        image_url = ""
        if assets:
            image_url = (
                assets[0].get("url", "").replace("{width}", "250").replace("{slug}", "")
            )

        # Label
        labels = p.get("labels", [])
        label = labels[0] if labels else ""

        # MultiInformations (Nährwerte, Zutaten, etc.)
        mi_list = p.get("multiInformations", [])
        diet_type = ""
        country_origin = ""
        ingredients = ""
        allergens = ""
        nutritional_values = []

        if mi_list:
            mi = mi_list[0]
            diet_type = mi.get("dietTypes") or ""
            country_origin = mi.get("countryOrigin") or ""
            attrs = mi.get("attributes") or {}
            ingredients = (attrs.get("composition") or "")[:500]
            allergens = (attrs.get("allergensContained") or "")[:200]
            nutritional_values = mi.get("nutritionalValues") or []

        conn.execute(
            """INSERT OR REPLACE INTO products
               (sku, name, brand, price_cents, price, weight, kgprice, kgprice_display,
                category, url_slug, image_url, label, diet_type, country_origin,
                ingredients, allergens, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sku,
                p.get("name", ""),
                p.get("brandName", ""),
                price_cents,
                price,
                p.get("sellingSize", ""),
                kgprice,
                kgprice_display,
                category,
                p.get("urlSlugText", ""),
                image_url,
                label,
                diet_type,
                country_origin,
                ingredients,
                allergens,
                timestamp,
            ),
        )

        # Nährwerte
        if nutritional_values:
            nutr = extract_nutrition(nutritional_values)
            if nutr:
                conn.execute(
                    """INSERT OR REPLACE INTO nutrition
                       (sku, energy_kj, energy_kcal, fat, fat_saturated,
                        carbs, carbs_sugar, fiber, protein, salt)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        sku,
                        nutr.get("energy_kj"),
                        nutr.get("energy_kcal"),
                        nutr.get("fat"),
                        nutr.get("fat_saturated"),
                        nutr.get("carbs"),
                        nutr.get("carbs_sugar"),
                        nutr.get("fiber"),
                        nutr.get("protein"),
                        nutr.get("salt"),
                    ),
                )
        count += 1

    conn.commit()
    return count


def scrape_all(conn: sqlite3.Connection, categories: list[str]):
    client = httpx.Client(headers=HEADERS, follow_redirects=True, timeout=20)
    total = 0

    for cat_name in categories:
        if cat_name not in CATEGORIES:
            print(f"  Unbekannt: {cat_name}", file=sys.stderr)
            continue

        raw = fetch_category(client, CATEGORIES[cat_name])
        stored = store_products(conn, raw, cat_name)
        total += stored
        print(f"  {cat_name}: {stored} Produkte", file=sys.stderr)

    client.close()
    return total


def print_stats(conn: sqlite3.Connection):
    total = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    nutr = conn.execute(
        "SELECT COUNT(*) FROM nutrition WHERE protein IS NOT NULL"
    ).fetchone()[0]
    last = conn.execute("SELECT MAX(last_seen) FROM products").fetchone()[0]
    cats = conn.execute(
        "SELECT category, COUNT(*) FROM products GROUP BY category ORDER BY COUNT(*) DESC"
    ).fetchall()

    print(f"meinALDI Produktdatenbank: {DB_PATH}")
    print(f"Gesamt: {total} Produkte | {nutr} mit Nährwerten | Stand: {last}")
    print()
    for cat, count in cats:
        print(f"  {cat:25} {count:4}")


def search_products(conn: sqlite3.Connection, query: str, limit: int = 20):
    rows = conn.execute(
        """SELECT p.name, p.brand, p.price, p.weight, p.kgprice, p.category,
                  n.protein, n.energy_kcal, n.carbs, n.fat
           FROM products p
           LEFT JOIN nutrition n ON p.sku = n.sku
           WHERE p.name LIKE ? OR p.brand LIKE ? OR p.ingredients LIKE ?
           ORDER BY p.price
           LIMIT ?""",
        (f"%{query}%", f"%{query}%", f"%{query}%", limit),
    ).fetchall()

    for name, brand, price, weight, kgprice, cat, protein, kcal, carbs, fat in rows:
        nutr_str = ""
        if protein is not None:
            nutr_str = f" | {protein:.0f}g Protein, {kcal:.0f} kcal"
        print(f"  {price:5.2f}€ | {brand:20} | {name:40} | {weight:8}{nutr_str}")


def top_protein(conn: sqlite3.Connection, limit: int = 20):
    """Top Produkte nach Eiweiß pro Euro."""
    rows = conn.execute(
        """SELECT p.name, p.brand, p.price, p.weight, p.kgprice, p.category,
                  n.protein, n.energy_kcal, n.carbs, n.fat,
                  CASE WHEN p.price > 0 THEN n.protein / p.price ELSE 0 END as protein_per_euro
           FROM products p
           JOIN nutrition n ON p.sku = n.sku
           WHERE n.protein IS NOT NULL AND n.protein > 0 AND p.price > 0
           ORDER BY protein_per_euro DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()

    print(
        f"{'Protein/€':>10} | {'Preis':>6} | {'Protein':>8} | {'kcal':>5} | {'Produkt'}"
    )
    print("-" * 90)
    for (
        name,
        brand,
        price,
        weight,
        kgprice,
        cat,
        protein,
        kcal,
        carbs,
        fat,
        ppe,
    ) in rows:
        print(
            f"  {ppe:7.1f}g/€ | {price:5.2f}€ | {protein:6.1f}g | {kcal:5.0f} | {brand} {name} ({weight})"
        )


def export_db(conn: sqlite3.Connection, path: str):
    rows = conn.execute(
        """SELECT p.sku, p.name, p.brand, p.price, p.weight, p.kgprice,
                  p.kgprice_display, p.category, p.url_slug, p.label,
                  p.diet_type, p.ingredients, p.allergens,
                  n.energy_kj, n.energy_kcal, n.fat, n.fat_saturated,
                  n.carbs, n.carbs_sugar, n.fiber, n.protein, n.salt
           FROM products p
           LEFT JOIN nutrition n ON p.sku = n.sku"""
    ).fetchall()

    products = []
    for row in rows:
        products.append(
            {
                "sku": row[0],
                "name": row[1],
                "brand": row[2],
                "price": row[3],
                "weight": row[4],
                "kgprice": row[5],
                "kgprice_display": row[6],
                "category": row[7],
                "url_slug": row[8],
                "label": row[9],
                "diet_type": row[10],
                "ingredients": row[11],
                "allergens": row[12],
                "nutrition": {
                    "energy_kj": row[13],
                    "energy_kcal": row[14],
                    "fat": row[15],
                    "fat_saturated": row[16],
                    "carbs": row[17],
                    "carbs_sugar": row[18],
                    "fiber": row[19],
                    "protein": row[20],
                    "salt": row[21],
                },
            }
        )

    with open(path, "w") as f:
        json.dump(
            {
                "store": "meinaldi",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "total": len(products),
                "products": products,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"{len(products)} Produkte → {path}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="meinALDI Scraper (API)")
    parser.add_argument("--categories", help="Komma-getrennte Kategorien")
    parser.add_argument(
        "--all", action="store_true", help="Alle Kategorien inkl. Non-Food"
    )
    parser.add_argument("--stats", action="store_true", help="DB-Statistiken")
    parser.add_argument("--search", help="Produkte suchen")
    parser.add_argument(
        "--top-protein", type=int, metavar="N", help="Top N Eiweiß/€-Produkte"
    )
    parser.add_argument("--export", help="Als JSON exportieren")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    conn = (
        init_db()
        if not (args.stats or args.search or args.top_protein or args.export)
        else sqlite3.connect(DB_PATH)
    )

    if args.stats:
        print_stats(conn)
    elif args.search:
        search_products(conn, args.search)
    elif args.top_protein:
        top_protein(conn, args.top_protein)
    elif args.export:
        export_db(conn, args.export)
    else:
        if args.categories:
            cats = [c.strip() for c in args.categories.split(",")]
        elif args.all:
            cats = list(CATEGORIES.keys())
        else:
            cats = FOOD_CATEGORIES

        if not args.quiet:
            print(f"Scrape {len(cats)} Kategorien via API...", file=sys.stderr)
        total = scrape_all(conn, cats)
        if not args.quiet:
            print(f"\n{total} Produkte → {DB_PATH}", file=sys.stderr)

    conn.close()


if __name__ == "__main__":
    main()
