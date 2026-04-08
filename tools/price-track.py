#!/home/maetzger/.claude/tools/.venv/bin/python
"""Preisentwicklung und Kauf-Alerts für getrackte Produkte.

Baut auf market.db auf und bietet:
- Übersicht aller Produkte mit Trend
- Detaillierte Preisentwicklung pro Produkt
- Kauf-Alerts bei Preisschwellen
- HTML-Report mit SVG-Chart
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB_PATH = Path.home() / ".claude/data/market.db"
SHARED_REPORTS = Path.home() / "shared/reports"

# Sicherstellen dass die price_alerts-Tabelle existiert
ALERT_SCHEMA = """
CREATE TABLE IF NOT EXISTS price_alerts (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    threshold REAL NOT NULL,
    status TEXT DEFAULT 'aktiv',
    created_at TEXT DEFAULT (datetime('now')),
    triggered_at TEXT,
    UNIQUE(product_id, threshold)
);
"""


def get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(ALERT_SCHEMA)
    return db


# --- Subcommands ---


def cmd_overview(args):
    """Übersicht aller getrackten Produkte."""
    db = get_db()
    rows = db.execute(
        """
        SELECT
            p.id, p.name, p.category,
            COUNT(s.id) AS checks,
            -- Letzter Median
            (SELECT s2.median_price FROM searches s2
             WHERE s2.product_id=p.id ORDER BY s2.searched_at DESC LIMIT 1) AS last_median,
            (SELECT s2.searched_at FROM searches s2
             WHERE s2.product_id=p.id ORDER BY s2.searched_at DESC LIMIT 1) AS last_check,
            (SELECT s2.total_in_median FROM searches s2
             WHERE s2.product_id=p.id ORDER BY s2.searched_at DESC LIMIT 1) AS last_n,
            -- Vorletzter Median (für Trend)
            (SELECT s3.median_price FROM searches s3
             WHERE s3.product_id=p.id ORDER BY s3.searched_at DESC LIMIT 1 OFFSET 1) AS prev_median,
            -- All-Time Min/Max
            MIN(s.median_price) AS all_time_low,
            MAX(s.median_price) AS all_time_high,
            -- Neupreis (letzter bekannter)
            (SELECT s4.new_bestprice FROM searches s4
             WHERE s4.product_id=p.id AND s4.new_bestprice IS NOT NULL
             ORDER BY s4.searched_at DESC LIMIT 1) AS neupreis
        FROM products p
        LEFT JOIN searches s ON s.product_id=p.id
        GROUP BY p.id
        ORDER BY p.name
        """
    ).fetchall()

    products = []
    for r in rows:
        d = dict(r)
        # Trend berechnen
        if d["last_median"] and d["prev_median"]:
            diff = d["last_median"] - d["prev_median"]
            pct = (diff / d["prev_median"]) * 100 if d["prev_median"] else 0
            if abs(pct) < 2:
                d["trend"] = "stabil"
                d["trend_pct"] = 0
            elif diff > 0:
                d["trend"] = "steigend"
                d["trend_pct"] = round(pct, 1)
            else:
                d["trend"] = "fallend"
                d["trend_pct"] = round(pct, 1)
        else:
            d["trend"] = "keine Daten"
            d["trend_pct"] = 0

        # Aktive Alerts für dieses Produkt
        alerts = db.execute(
            "SELECT threshold, status FROM price_alerts WHERE product_id=? AND status='aktiv'",
            (d["id"],),
        ).fetchall()
        d["alerts"] = [
            {"threshold": a["threshold"], "status": a["status"]} for a in alerts
        ]

        products.append(d)

    db.close()
    print(json.dumps({"products": products, "total": len(products)}, default=str))


def cmd_detail(args):
    """Detaillierte Preisentwicklung für ein Produkt."""
    db = get_db()

    # Produkt suchen (fuzzy)
    product = db.execute(
        "SELECT id, name, category FROM products WHERE name LIKE ?",
        (f"%{args.product}%",),
    ).fetchone()

    if not product:
        print(json.dumps({"error": f"Produkt '{args.product}' nicht gefunden"}))
        db.close()
        return

    # Alle Datenpunkte
    datapoints = db.execute(
        """
        SELECT searched_at, median_price, q1_price, q3_price,
               min_price, max_price, total_final, total_in_median,
               new_bestprice, new_bestprice_source
        FROM searches WHERE product_id=?
        ORDER BY searched_at ASC
        """,
        (product["id"],),
    ).fetchall()

    points = [dict(d) for d in datapoints]
    medians = [p["median_price"] for p in points if p["median_price"] is not None]

    # Alerts
    alerts = db.execute(
        "SELECT id, threshold, status, created_at, triggered_at FROM price_alerts WHERE product_id=?",
        (product["id"],),
    ).fetchall()

    result = {
        "product": product["name"],
        "category": product["category"],
        "checks": len(points),
        "datapoints": points,
        "stats": {},
        "alerts": [dict(a) for a in alerts],
    }

    if medians:
        result["stats"] = {
            "current_median": medians[-1],
            "all_time_low": min(medians),
            "all_time_high": max(medians),
            "avg_median": round(sum(medians) / len(medians), 1),
        }
        if len(medians) >= 2:
            diff = medians[-1] - medians[-2]
            pct = (diff / medians[-2]) * 100 if medians[-2] else 0
            if abs(pct) < 2:
                result["stats"]["trend"] = "stabil"
            elif diff > 0:
                result["stats"]["trend"] = "steigend"
            else:
                result["stats"]["trend"] = "fallend"
            result["stats"]["trend_pct"] = round(pct, 1)
        else:
            result["stats"]["trend"] = "erste Messung"
            result["stats"]["trend_pct"] = 0

    db.close()
    print(json.dumps(result, default=str))


def cmd_alert(args):
    """Alert setzen: benachrichtigt wenn Median unter Schwelle fällt."""
    db = get_db()

    product = db.execute(
        "SELECT id, name FROM products WHERE name LIKE ?",
        (f"%{args.product}%",),
    ).fetchone()

    if not product:
        print(json.dumps({"error": f"Produkt '{args.product}' nicht gefunden"}))
        db.close()
        return

    try:
        db.execute(
            "INSERT INTO price_alerts (product_id, threshold) VALUES (?, ?)",
            (product["id"], args.price),
        )
        db.commit()
        print(
            json.dumps(
                {
                    "status": "ok",
                    "message": f"Alert gesetzt: {product['name']} < {args.price}EUR",
                    "product": product["name"],
                    "threshold": args.price,
                }
            )
        )
    except sqlite3.IntegrityError:
        # Alert existiert bereits, aktualisieren
        db.execute(
            "UPDATE price_alerts SET status='aktiv', triggered_at=NULL WHERE product_id=? AND threshold=?",
            (product["id"], args.price),
        )
        db.commit()
        print(
            json.dumps(
                {
                    "status": "ok",
                    "message": f"Alert reaktiviert: {product['name']} < {args.price}EUR",
                    "product": product["name"],
                    "threshold": args.price,
                }
            )
        )

    db.close()


def cmd_check_alerts(args):
    """Alle aktiven Alerts prüfen."""
    db = get_db()

    alerts = db.execute(
        """
        SELECT a.id, a.threshold, a.created_at, p.name,
               (SELECT s.median_price FROM searches s
                WHERE s.product_id=p.id ORDER BY s.searched_at DESC LIMIT 1) AS current_median
        FROM price_alerts a
        JOIN products p ON a.product_id=p.id
        WHERE a.status='aktiv'
        """
    ).fetchall()

    results = []
    for a in alerts:
        d = dict(a)
        if d["current_median"] is not None and d["current_median"] <= d["threshold"]:
            d["triggered"] = True
            db.execute(
                "UPDATE price_alerts SET status='ausgeloest', triggered_at=datetime('now') WHERE id=?",
                (d["id"],),
            )
        else:
            d["triggered"] = False
        results.append(d)

    db.commit()
    db.close()
    print(
        json.dumps(
            {
                "alerts": results,
                "triggered_count": sum(1 for r in results if r["triggered"]),
            }
        )
    )


def cmd_html(args):
    """HTML-Report mit SVG-Chart generieren."""
    db = get_db()

    product = db.execute(
        "SELECT id, name, category FROM products WHERE name LIKE ?",
        (f"%{args.product}%",),
    ).fetchone()

    if not product:
        print(json.dumps({"error": f"Produkt '{args.product}' nicht gefunden"}))
        db.close()
        return

    datapoints = db.execute(
        """
        SELECT searched_at, median_price, q1_price, q3_price,
               total_in_median, new_bestprice
        FROM searches WHERE product_id=?
        ORDER BY searched_at ASC
        """,
        (product["id"],),
    ).fetchall()

    points = [dict(d) for d in datapoints]
    medians = [p["median_price"] for p in points if p["median_price"] is not None]

    if not medians:
        print(json.dumps({"error": "Keine Datenpunkte vorhanden"}))
        db.close()
        return

    # Alerts
    alerts = db.execute(
        "SELECT threshold, status, created_at, triggered_at FROM price_alerts WHERE product_id=?",
        (product["id"],),
    ).fetchall()

    # Stats
    current = medians[-1]
    atl = min(medians)
    ath = max(medians)
    checks = len(points)

    if len(medians) >= 2:
        diff = medians[-1] - medians[-2]
        pct = (diff / medians[-2]) * 100 if medians[-2] else 0
        if abs(pct) < 2:
            trend = "stabil"
            trend_icon = "~"
        elif diff > 0:
            trend = "steigend"
            trend_icon = "+"
        else:
            trend = "fallend"
            trend_icon = "-"
        trend_pct = round(pct, 1)
    else:
        trend = "erste Messung"
        trend_icon = "~"
        trend_pct = 0

    # SVG-Chart generieren
    svg = _build_svg_chart(points, alerts)

    # Alert-HTML
    alert_html = ""
    for a in alerts:
        a = dict(a)
        status_class = "alert-active" if a["status"] == "aktiv" else "alert-triggered"
        status_label = "Aktiv" if a["status"] == "aktiv" else "Ausgeloest"
        alert_html += (
            f'<div class="alert-item {status_class}">'
            f'<span class="alert-threshold">&lt; {a["threshold"]:.0f}EUR</span>'
            f'<span class="alert-status">{status_label}</span>'
            f'<span class="alert-date">seit {a["created_at"][:10]}</span>'
            f"</div>"
        )

    if not alert_html:
        alert_html = (
            '<div class="alert-item" style="opacity:0.5">Keine Alerts gesetzt</div>'
        )

    # Datenpunkte-Tabelle
    table_rows = ""
    for p in reversed(points):
        date = p["searched_at"][:10] if p["searched_at"] else "?"
        med = f"{p['median_price']:.0f}" if p["median_price"] else "-"
        q1 = f"{p['q1_price']:.0f}" if p["q1_price"] else "-"
        q3 = f"{p['q3_price']:.0f}" if p["q3_price"] else "-"
        n = p["total_in_median"] if p["total_in_median"] else "-"
        table_rows += (
            f"<tr><td>{date}</td><td>{med}EUR</td>"
            f"<td>{q1} - {q3}EUR</td><td>{n}</td></tr>"
        )

    # Trend-Farbe
    trend_color = (
        "#6db87a"
        if trend == "fallend"
        else "#d4675a"
        if trend == "steigend"
        else "#c9a84a"
    )

    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Preisentwicklung: {product["name"]}</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,600;1,6..72,400&family=Outfit:wght@300;400;500;600&display=swap');
:root {{
    --bg: #111110;
    --bg-raised: #1a1918;
    --bg-card: #1f1e1c;
    --text: #e8e4de;
    --text-secondary: #b5afa5;
    --text-muted: #706b62;
    --accent: #cf865a;
    --accent-dim: rgba(207,134,90,0.15);
    --accent-glow: rgba(207,134,90,0.08);
    --green: #6db87a;
    --yellow: #c9a84a;
    --red: #d4675a;
    --border: #2a2826;
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
    font-family: 'Outfit', sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 2rem;
    max-width: 900px;
    margin: 0 auto;
}}
h1 {{
    font-family: 'Newsreader', serif;
    font-size: 1.8rem;
    font-weight: 600;
    margin-bottom: 0.3rem;
}}
.subtitle {{
    color: var(--text-muted);
    font-size: 0.85rem;
    margin-bottom: 2rem;
}}
.stats-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 1rem;
    margin-bottom: 2rem;
}}
.stat-card {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1.2rem;
    text-align: center;
}}
.stat-card .label {{
    color: var(--text-muted);
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 0.3rem;
}}
.stat-card .value {{
    font-family: 'Newsreader', serif;
    font-size: 1.6rem;
    font-weight: 600;
}}
.stat-card .value.accent {{ color: var(--accent); }}
.stat-card .value.green {{ color: var(--green); }}
.stat-card .value.red {{ color: var(--red); }}
.stat-card .value.yellow {{ color: var(--yellow); }}
.chart-container {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1.5rem;
    margin-bottom: 2rem;
    overflow-x: auto;
}}
.chart-container h2 {{
    font-family: 'Newsreader', serif;
    font-size: 1.2rem;
    margin-bottom: 1rem;
    color: var(--text-secondary);
}}
.section {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1.5rem;
    margin-bottom: 1.5rem;
}}
.section h2 {{
    font-family: 'Newsreader', serif;
    font-size: 1.2rem;
    margin-bottom: 1rem;
    color: var(--text-secondary);
}}
table {{
    width: 100%;
    border-collapse: collapse;
}}
th, td {{
    padding: 0.6rem 0.8rem;
    text-align: left;
    border-bottom: 1px solid var(--border);
    font-size: 0.9rem;
}}
th {{
    color: var(--text-muted);
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 500;
}}
td {{ color: var(--text-secondary); }}
td:nth-child(2) {{ color: var(--accent); font-weight: 500; }}
.alert-item {{
    display: flex;
    align-items: center;
    gap: 1rem;
    padding: 0.8rem 1rem;
    border-radius: 8px;
    margin-bottom: 0.5rem;
    font-size: 0.9rem;
}}
.alert-active {{
    background: rgba(109,184,122,0.1);
    border: 1px solid rgba(109,184,122,0.3);
}}
.alert-triggered {{
    background: rgba(207,134,90,0.1);
    border: 1px solid rgba(207,134,90,0.3);
}}
.alert-threshold {{
    font-weight: 600;
    color: var(--text);
    min-width: 100px;
}}
.alert-status {{
    font-size: 0.8rem;
    padding: 0.2rem 0.6rem;
    border-radius: 4px;
    background: var(--bg-raised);
    color: var(--text-secondary);
}}
.alert-date {{
    color: var(--text-muted);
    font-size: 0.8rem;
    margin-left: auto;
}}
.footer {{
    text-align: center;
    color: var(--text-muted);
    font-size: 0.75rem;
    margin-top: 2rem;
    padding-top: 1rem;
    border-top: 1px solid var(--border);
}}
</style>
</head>
<body>
<h1>Preisentwicklung: {product["name"]}</h1>
<p class="subtitle">Stand: {now} | {checks} Checks | Kategorie: {product["category"] or "Allgemein"}</p>

<div class="stats-grid">
    <div class="stat-card">
        <div class="label">Aktueller Median</div>
        <div class="value accent">{current:.0f}EUR</div>
    </div>
    <div class="stat-card">
        <div class="label">All-Time Low</div>
        <div class="value green">{atl:.0f}EUR</div>
    </div>
    <div class="stat-card">
        <div class="label">All-Time High</div>
        <div class="value red">{ath:.0f}EUR</div>
    </div>
    <div class="stat-card">
        <div class="label">Trend</div>
        <div class="value" style="color:{trend_color}">{trend_icon}{abs(trend_pct)}%</div>
    </div>
    <div class="stat-card">
        <div class="label">Checks</div>
        <div class="value">{checks}</div>
    </div>
</div>

<div class="chart-container">
    <h2>Preisverlauf</h2>
    {svg}
</div>

<div class="section">
    <h2>Alerts</h2>
    {alert_html}
</div>

<div class="section">
    <h2>Datenpunkte</h2>
    <table>
        <thead><tr><th>Datum</th><th>Median</th><th>IQR</th><th>Stichprobe</th></tr></thead>
        <tbody>{table_rows}</tbody>
    </table>
</div>

<div class="footer">
    Generiert von price-track.py | Warm Dark Editorial
</div>
</body>
</html>"""

    # Speichern
    SHARED_REPORTS.mkdir(parents=True, exist_ok=True)
    slug = product["name"].lower().replace(" ", "-").replace("/", "-")
    output_path = (
        Path(args.output)
        if args.output
        else SHARED_REPORTS / f"price-track-{slug}.html"
    )
    output_path.write_text(html, encoding="utf-8")
    print(
        json.dumps(
            {"status": "ok", "path": str(output_path), "product": product["name"]}
        )
    )

    db.close()


def _build_svg_chart(points, alerts):
    """SVG-Liniendiagramm für Preisverlauf (inline, kein JS)."""
    medians = [
        (p["searched_at"], p["median_price"])
        for p in points
        if p["median_price"] is not None
    ]

    if len(medians) < 2:
        # Bei nur einem Datenpunkt: einfache Anzeige
        if medians:
            return (
                f'<svg viewBox="0 0 800 200" style="width:100%;height:200px">'
                f'<text x="400" y="100" text-anchor="middle" fill="#b5afa5" '
                f'font-family="Outfit" font-size="14">'
                f"Nur 1 Datenpunkt: {medians[0][1]:.0f}EUR am {medians[0][0][:10]}"
                f"</text></svg>"
            )
        return (
            '<svg viewBox="0 0 800 200" style="width:100%;height:200px">'
            '<text x="400" y="100" text-anchor="middle" fill="#706b62" '
            'font-family="Outfit" font-size="14">Keine Datenpunkte</text></svg>'
        )

    # Chart-Dimensionen
    w, h = 800, 280
    pad_l, pad_r, pad_t, pad_b = 70, 30, 20, 50
    chart_w = w - pad_l - pad_r
    chart_h = h - pad_t - pad_b

    prices = [m[1] for m in medians]
    p_min = min(prices) * 0.95
    p_max = max(prices) * 1.05
    p_range = p_max - p_min if p_max != p_min else 1

    def x_pos(i):
        return pad_l + (i / (len(medians) - 1)) * chart_w

    def y_pos(price):
        return pad_t + chart_h - ((price - p_min) / p_range) * chart_h

    # Pfad
    path_points = []
    area_points = []
    for i, (date, price) in enumerate(medians):
        px, py = x_pos(i), y_pos(price)
        path_points.append(f"{'M' if i == 0 else 'L'}{px:.1f},{py:.1f}")
        area_points.append(f"{'M' if i == 0 else 'L'}{px:.1f},{py:.1f}")

    # Fläche unter der Linie
    area_points.append(f"L{x_pos(len(medians) - 1):.1f},{pad_t + chart_h:.1f}")
    area_points.append(f"L{x_pos(0):.1f},{pad_t + chart_h:.1f}Z")

    svg_parts = [
        f'<svg viewBox="0 0 {w} {h}" style="width:100%;height:{h}px" xmlns="http://www.w3.org/2000/svg">',
        # Gradient für Fläche
        "<defs>"
        '<linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0%" stop-color="#cf865a" stop-opacity="0.25"/>'
        '<stop offset="100%" stop-color="#cf865a" stop-opacity="0.02"/>'
        "</linearGradient>"
        "</defs>",
    ]

    # Y-Achse: 5 Linien
    for i in range(5):
        price_val = p_min + (i / 4) * p_range
        y = y_pos(price_val)
        svg_parts.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{w - pad_r}" y2="{y:.1f}" '
            f'stroke="#2a2826" stroke-width="1"/>'
        )
        svg_parts.append(
            f'<text x="{pad_l - 10}" y="{y:.1f}" text-anchor="end" '
            f'dominant-baseline="middle" fill="#706b62" font-family="Outfit" '
            f'font-size="11">{price_val:.0f}</text>'
        )

    # Alert-Schwellen als gestrichelte Linien
    for a in alerts:
        a = dict(a)
        if p_min <= a["threshold"] <= p_max:
            y = y_pos(a["threshold"])
            color = "#6db87a" if a["status"] == "aktiv" else "#cf865a"
            svg_parts.append(
                f'<line x1="{pad_l}" y1="{y:.1f}" x2="{w - pad_r}" y2="{y:.1f}" '
                f'stroke="{color}" stroke-width="1.5" stroke-dasharray="6,4" opacity="0.7"/>'
            )
            svg_parts.append(
                f'<text x="{w - pad_r + 5}" y="{y:.1f}" dominant-baseline="middle" '
                f'fill="{color}" font-family="Outfit" font-size="10" opacity="0.8">'
                f"Alert {a['threshold']:.0f}</text>"
            )

    # Fläche
    svg_parts.append(f'<path d="{"".join(area_points)}" fill="url(#areaGrad)"/>')

    # Linie
    svg_parts.append(
        f'<path d="{"".join(path_points)}" fill="none" stroke="#cf865a" '
        f'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>'
    )

    # Datenpunkte
    for i, (date, price) in enumerate(medians):
        px, py = x_pos(i), y_pos(price)
        svg_parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="#cf865a"/>')
        svg_parts.append(
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="6" fill="none" '
            f'stroke="#cf865a" stroke-width="1" opacity="0.4"/>'
        )

    # X-Achse: Datum-Labels (max 8)
    step = max(1, len(medians) // 8)
    for i in range(0, len(medians), step):
        date_str = medians[i][0][:10]
        # Tag.Monat Format
        parts = date_str.split("-")
        label = f"{parts[2]}.{parts[1]}." if len(parts) == 3 else date_str
        px = x_pos(i)
        svg_parts.append(
            f'<text x="{px:.1f}" y="{h - 10}" text-anchor="middle" '
            f'fill="#706b62" font-family="Outfit" font-size="11">{label}</text>'
        )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


# --- CLI ---


def main():
    parser = argparse.ArgumentParser(description="Preisentwicklung und Kauf-Alerts")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("overview", help="Übersicht aller Produkte")

    p_detail = sub.add_parser("detail", help="Detail-Daten für ein Produkt")
    p_detail.add_argument("product", help="Produktname (fuzzy match)")

    p_alert = sub.add_parser("alert", help="Kauf-Alert setzen")
    p_alert.add_argument("price", type=float, help="Preisschwelle in EUR")
    p_alert.add_argument("product", nargs="+", help="Produktname")

    sub.add_parser("check-alerts", help="Alle aktiven Alerts prüfen")

    p_html = sub.add_parser("html", help="HTML-Report generieren")
    p_html.add_argument("product", help="Produktname (fuzzy match)")
    p_html.add_argument("--output", "-o", help="Output-Pfad (optional)")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(1)

    if args.cmd == "alert":
        args.product = " ".join(args.product)

    {
        "overview": cmd_overview,
        "detail": cmd_detail,
        "alert": cmd_alert,
        "check-alerts": cmd_check_alerts,
        "html": cmd_html,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
