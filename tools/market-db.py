#!/home/maetzger/.claude/tools/.venv/bin/python
"""Kleinanzeigen Marktpreis-Datenbank — speichert und analysiert Preisverläufe."""

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path.home() / ".claude/data/market.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT,
    kleinanzeigen_filter TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(name)
);

CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    searched_at TEXT DEFAULT (datetime('now')),
    total_raw INTEGER,
    total_clean INTEGER,
    total_scam INTEGER DEFAULT 0,
    total_final INTEGER,
    total_in_median INTEGER,
    median_price REAL,
    q1_price REAL,
    q3_price REAL,
    min_price REAL,
    max_price REAL,
    source_url TEXT,
    duration_seconds INTEGER,
    new_bestprice REAL,
    new_bestprice_source TEXT
);
CREATE INDEX IF NOT EXISTS idx_searches_product ON searches(product_id);
CREATE INDEX IF NOT EXISTS idx_searches_date ON searches(searched_at);

CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY,
    search_id INTEGER NOT NULL REFERENCES searches(id),
    title TEXT,
    price REAL,
    price_text TEXT,
    date_posted TEXT,
    age_category TEXT,
    url TEXT,
    location TEXT,
    shipping INTEGER DEFAULT 0,
    seller_type TEXT,
    seller_since TEXT,
    is_scam INTEGER DEFAULT 0,
    filtered_reason TEXT,
    included_in_median INTEGER DEFAULT 1,
    seller_badges TEXT,
    is_recommended INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_listings_search ON listings(search_id);
CREATE INDEX IF NOT EXISTS idx_listings_price ON listings(price);
"""


def get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db():
    db = get_db()
    db.executescript(SCHEMA)
    db.close()


def upsert_product(db, name, category=None, filter_url=None):
    db.execute(
        "INSERT INTO products (name, category, kleinanzeigen_filter) "
        "VALUES (?, ?, ?) ON CONFLICT(name) DO UPDATE SET "
        "category=COALESCE(excluded.category, products.category), "
        "kleinanzeigen_filter=COALESCE(excluded.kleinanzeigen_filter, products.kleinanzeigen_filter)",
        (name, category, filter_url),
    )
    db.commit()
    row = db.execute("SELECT id FROM products WHERE name=?", (name,)).fetchone()
    return row["id"]


def save_search(db, product_id, stats):
    cur = db.execute(
        "INSERT INTO searches (product_id, total_raw, total_clean, total_scam, "
        "total_final, total_in_median, median_price, q1_price, q3_price, "
        "min_price, max_price, source_url, duration_seconds, "
        "new_bestprice, new_bestprice_source, report_filename) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            product_id,
            stats.get("total_raw"),
            stats.get("total_clean"),
            stats.get("total_scam", 0),
            stats.get("total_final"),
            stats.get("total_in_median"),
            stats.get("median"),
            stats.get("q1"),
            stats.get("q3"),
            stats.get("min"),
            stats.get("max"),
            stats.get("source_url"),
            stats.get("duration_seconds"),
            stats.get("new_bestprice"),
            stats.get("new_bestprice_source"),
            stats.get("report_filename"),
        ),
    )
    db.commit()
    return cur.lastrowid


def save_listings(db, search_id, listings):
    for item in listings:
        db.execute(
            "INSERT INTO listings (search_id, title, price, price_text, date_posted, "
            "age_category, url, location, shipping, seller_type, seller_since, "
            "is_scam, filtered_reason, included_in_median, seller_badges, is_recommended) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                search_id,
                item.get("title"),
                item.get("price"),
                item.get("priceText") or item.get("price_text"),
                item.get("date") or item.get("date_posted"),
                item.get("age_category"),
                item.get("url"),
                item.get("location"),
                1 if item.get("shipping") else 0,
                item.get("seller_type"),
                item.get("seller_since"),
                item.get("is_scam", 0),
                item.get("filtered_reason"),
                item.get("included_in_median", 1),
                item.get("seller_badges"),
                item.get("is_recommended", 0),
            ),
        )
    db.commit()


def get_history(db, product_name, days=90):
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    rows = db.execute(
        "SELECT s.searched_at, s.median_price, s.q1_price, s.q3_price, "
        "s.total_final, s.total_in_median, s.duration_seconds, "
        "s.new_bestprice, s.new_bestprice_source "
        "FROM searches s JOIN products p ON s.product_id=p.id "
        "WHERE p.name=? AND s.searched_at>=? ORDER BY s.searched_at DESC",
        (product_name, cutoff),
    ).fetchall()
    return [dict(r) for r in rows]


def get_recommendation(db, product_name):
    """Get the recommended listing from the most recent search."""
    row = db.execute(
        "SELECT l.title, l.price, l.price_text, l.url, l.seller_badges, "
        "l.seller_since, l.seller_type, s.searched_at "
        "FROM listings l JOIN searches s ON l.search_id=s.id "
        "JOIN products p ON s.product_id=p.id "
        "WHERE p.name=? AND l.is_recommended=1 "
        "ORDER BY s.searched_at DESC LIMIT 1",
        (product_name,),
    ).fetchone()
    return dict(row) if row else None


def get_best_deals(db, product_name, max_age_days=7):
    cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat()
    rows = db.execute(
        "SELECT l.title, l.price, l.url, l.age_category, s.searched_at "
        "FROM listings l JOIN searches s ON l.search_id=s.id "
        "JOIN products p ON s.product_id=p.id "
        "WHERE p.name=? AND s.searched_at>=? AND l.included_in_median=1 "
        "AND l.is_scam=0 AND l.filtered_reason IS NULL "
        "ORDER BY l.price ASC LIMIT 10",
        (product_name, cutoff),
    ).fetchall()
    return [dict(r) for r in rows]


def compare_products(db):
    rows = db.execute(
        "SELECT p.name, p.category, "
        "  (SELECT s2.median_price FROM searches s2 WHERE s2.product_id=p.id "
        "   ORDER BY s2.searched_at DESC LIMIT 1) AS last_median, "
        "  (SELECT s2.total_in_median FROM searches s2 WHERE s2.product_id=p.id "
        "   ORDER BY s2.searched_at DESC LIMIT 1) AS last_n, "
        "  (SELECT s3.median_price FROM searches s3 WHERE s3.product_id=p.id "
        "   ORDER BY s3.searched_at DESC LIMIT 1 OFFSET 1) AS prev_median, "
        "  (SELECT COUNT(*) FROM searches s4 WHERE s4.product_id=p.id) AS searches_count "
        "FROM products p ORDER BY p.name"
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if d["last_median"] and d["prev_median"]:
            diff = d["last_median"] - d["prev_median"]
            d["trend"] = "steigend" if diff > 0 else "fallend" if diff < 0 else "stabil"
        else:
            d["trend"] = "—"
        result.append(d)
    return result


# --- CLI ---


def cmd_save(args):
    init_db()
    db = get_db()
    stats = json.loads(args.stats)
    listings = json.loads(args.listings) if args.listings else []
    product_id = upsert_product(db, args.product, args.category, args.filter_url)
    search_id = save_search(db, product_id, stats)
    if listings:
        save_listings(db, search_id, listings)
    print(
        f"Gespeichert: {args.product} → search_id={search_id}, "
        f"{len(listings)} Listings, Median={stats.get('median')}€"
    )
    db.close()


def cmd_history(args):
    init_db()
    db = get_db()
    history = get_history(db, args.product, args.days)
    if not history:
        print(f"Keine Daten für '{args.product}'")
        db.close()
        return
    print(f"Preisverlauf: {args.product} (letzte {args.days} Tage)")
    print("─" * 55)
    medians = []
    for h in history:
        dt = h["searched_at"][:10]
        med = h["median_price"]
        n_median = h["total_in_median"]
        n_final = h["total_final"]
        dur = h.get("duration_seconds")
        medians.append(med)
        dur_str = f"  [{dur}s]" if dur else ""
        if n_median and n_final:
            print(
                f"  {dt}  {med:>8.0f}€  ({n_median} von {n_final} Inseraten){dur_str}"
            )
        elif n_final:
            print(f"  {dt}  {med:>8.0f}€  (n={n_final}){dur_str}")
        else:
            print(f"  {dt}  {med:>8.0f}€{dur_str}")
    if len(medians) >= 2:
        diff = medians[0] - medians[-1]
        arrow = "↓" if diff < 0 else "↑" if diff > 0 else "→"
        print(f"\n  Trend: {arrow} {abs(diff):.0f}€ seit erster Messung")
    db.close()


def cmd_deals(args):
    init_db()
    db = get_db()
    deals = get_best_deals(db, args.product, args.days)
    if not deals:
        print(f"Keine Deals für '{args.product}'")
        db.close()
        return
    print(f"Günstigste Angebote: {args.product}")
    print("─" * 50)
    for d in deals:
        url = d["url"] or ""
        if url and not url.startswith("http"):
            url = f"https://www.kleinanzeigen.de{url}"
        print(f"  {d['price']:>8.0f}€  {d['title'][:50]}")
        if url:
            print(f"           {url}")
    db.close()


def cmd_compare(args):
    init_db()
    db = get_db()
    products = compare_products(db)
    if not products:
        print("Keine Produkte in der Datenbank.")
        db.close()
        return
    print("Produkt-Vergleich")
    print("─" * 60)
    for p in products:
        med = f"{p['last_median']:.0f}€" if p["last_median"] else "—"
        n_info = f"n={p['last_n']}" if p.get("last_n") else ""
        print(
            f"  {p['name']:<25} {med:>8}  {p['trend']:<10} "
            f"({p['searches_count']} Suchen, {n_info})"
        )
    db.close()


def main():
    parser = argparse.ArgumentParser(description="Kleinanzeigen Marktpreis-DB")
    sub = parser.add_subparsers(dest="cmd")

    p_save = sub.add_parser("save", help="Suchergebnis speichern")
    p_save.add_argument("--product", required=True)
    p_save.add_argument("--category", default=None)
    p_save.add_argument("--filter-url", default=None)
    p_save.add_argument("--stats", required=True, help="JSON mit Statistiken")
    p_save.add_argument("--listings", default="[]", help="JSON-Array mit Listings")

    p_hist = sub.add_parser("history", help="Preisverlauf anzeigen")
    p_hist.add_argument("--product", required=True)
    p_hist.add_argument("--days", type=int, default=90)

    p_deals = sub.add_parser("deals", help="Günstigste Angebote")
    p_deals.add_argument("--product", required=True)
    p_deals.add_argument("--days", type=int, default=7)

    sub.add_parser("compare", help="Alle Produkte vergleichen")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(1)

    {
        "save": cmd_save,
        "history": cmd_history,
        "deals": cmd_deals,
        "compare": cmd_compare,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
