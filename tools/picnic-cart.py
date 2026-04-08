#!/usr/bin/env python3
"""Picnic Warenkorb-Tool — Einkaufsliste → Picnic-Warenkorb.

Liest eine JSON-Einkaufsliste und überträgt sie via Picnic-API
in den Warenkorb. Danach in der Picnic-App bestätigen.

Usage:
    uv run --with python-picnic-api2 ./tools/picnic-cart.py setup
    uv run --with python-picnic-api2 ./tools/picnic-cart.py fill /tmp/shopping-list.json
    uv run --with python-picnic-api2 ./tools/picnic-cart.py show
    uv run --with python-picnic-api2 ./tools/picnic-cart.py clear

Shopping-list JSON format:
    {"items": [{"name": "Hackfleisch", "quantity": 2}, ...]}
"""

import argparse
import json
import os
import sys
from pathlib import Path

CREDS_FILE = Path.home() / ".config" / "picnic" / "credentials.json"


def get_api():
    """Picnic API-Client initialisieren."""
    try:
        from python_picnic_api2 import PicnicAPI
    except ImportError:
        print("Fehler: python-picnic-api2 nicht installiert.", file=sys.stderr)
        print("  uv run --with python-picnic-api2 picnic-cart.py ...", file=sys.stderr)
        sys.exit(1)

    if not CREDS_FILE.exists():
        print(f"Keine Credentials gefunden: {CREDS_FILE}", file=sys.stderr)
        print("Erst: picnic-cart.py setup", file=sys.stderr)
        sys.exit(1)

    creds = json.loads(CREDS_FILE.read_text())
    return PicnicAPI(
        username=creds["username"],
        password=creds["password"],
        country_code="DE",
    )


def cmd_setup(_args):
    """Picnic-Zugangsdaten speichern."""
    print("Picnic Warenkorb-Tool — Setup")
    print("Gib deine Picnic-Zugangsdaten ein (E-Mail + Passwort).")
    print("Die Daten werden lokal gespeichert.\n")

    username = input("E-Mail: ").strip()
    password = input("Passwort: ").strip()

    if not username or not password:
        print("Abgebrochen — E-Mail und Passwort werden benötigt.")
        sys.exit(1)

    # Test-Login
    try:
        from python_picnic_api2 import PicnicAPI

        api = PicnicAPI(username=username, password=password, country_code="DE")
        user = api.get_user()
        name = user.get("firstname", "Unbekannt")
        print(f"\nLogin erfolgreich! Hallo {name}.")
    except Exception as e:
        print(f"\nLogin fehlgeschlagen: {e}", file=sys.stderr)
        sys.exit(1)

    CREDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CREDS_FILE.write_text(json.dumps({"username": username, "password": password}))
    os.chmod(CREDS_FILE, 0o600)
    print(f"Credentials gespeichert: {CREDS_FILE}")


def cmd_fill(args):
    """Einkaufsliste in Picnic-Warenkorb übertragen."""
    list_file = Path(args.file)
    if not list_file.exists():
        print(f"Datei nicht gefunden: {list_file}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(list_file.read_text())
    items = data.get("items", [])
    if not items:
        print("Leere Einkaufsliste.", file=sys.stderr)
        sys.exit(1)

    api = get_api()
    print(f"Übertrage {len(items)} Artikel in den Picnic-Warenkorb...\n")

    added = 0
    skipped = 0
    for item in items:
        name = item["name"]
        qty = item.get("quantity", 1)

        try:
            results = api.search(name)
        except Exception as e:
            print(f"  ✗ Suche '{name}' fehlgeschlagen: {e}")
            skipped += 1
            continue

        # Bestes Ergebnis nehmen (erstes mit Preis)
        product = None
        for r in results:
            items_list = r.get("items", [])
            if items_list:
                product = items_list[0]
                break

        if not product:
            print(f"  ✗ '{name}' — kein Ergebnis bei Picnic")
            skipped += 1
            continue

        product_id = product.get("id", "")
        product_name = product.get("name", "Unbekannt")
        price_cents = product.get("display_price", 0)
        price = price_cents / 100 if price_cents else 0

        try:
            for _ in range(qty):
                api.add_product(product_id)
            print(f"  ✓ {qty}× {product_name} ({price:.2f}€) → Warenkorb")
            added += 1
        except Exception as e:
            print(f"  ✗ '{name}' → Fehler beim Hinzufügen: {e}")
            skipped += 1

    print(f"\nFertig: {added} Artikel hinzugefügt, {skipped} übersprungen.")
    if added > 0:
        print("Öffne die Picnic-App, prüfe den Warenkorb und wähle ein Lieferfenster.")


def cmd_show(_args):
    """Aktuellen Picnic-Warenkorb anzeigen."""
    api = get_api()
    cart = api.get_cart()

    items = cart.get("items", [])
    if not items:
        print("Warenkorb ist leer.")
        return

    total = 0
    print("Picnic Warenkorb:\n")
    for group in items:
        for item in group.get("items", []):
            name = item.get("name", "?")
            qty = (
                item.get("decorators", [{}])[0].get("quantity", 1)
                if item.get("decorators")
                else 1
            )
            price = item.get("display_price", 0) / 100
            print(f"  {qty}× {name:40s} {price:.2f}€")
            total += price * qty

    print(f"\n  {'Gesamt:':>43s} {total:.2f}€")


def cmd_clear(_args):
    """Picnic-Warenkorb leeren."""
    api = get_api()
    api.clear_cart()
    print("Warenkorb geleert.")


def main():
    parser = argparse.ArgumentParser(description="Picnic Warenkorb-Tool")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("setup", help="Picnic-Zugangsdaten einrichten")

    fill_p = sub.add_parser("fill", help="Einkaufsliste in Warenkorb übertragen")
    fill_p.add_argument("file", help="Pfad zur shopping-list.json")

    sub.add_parser("show", help="Warenkorb anzeigen")
    sub.add_parser("clear", help="Warenkorb leeren")

    args = parser.parse_args()

    commands = {
        "setup": cmd_setup,
        "fill": cmd_fill,
        "show": cmd_show,
        "clear": cmd_clear,
    }

    if args.command not in commands:
        parser.print_help()
        sys.exit(1)

    commands[args.command](args)


if __name__ == "__main__":
    main()
