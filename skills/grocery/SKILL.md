---
name: grocery
description: "Wochenmenüs, Einkaufslisten und automatisiertes Warenkorb-Füllen"
triggers:
  - "Einkaufsliste"
  - "Wocheneinkauf"
  - "was soll ich einkaufen"
  - "Meal-Prep"
  - "Ernährungsplan"
  - "Warenkorb füllen"
  - "REWE bestellen"
not_for:
  - "Restaurant-Empfehlungen"
  - "Rezeptsuche"
---

# Grocery — Einkaufsplanung + Warenkorb-Automation

Erstellt Einkaufspläne mit echten Preisen und Nährwerten, füllt den REWE-Warenkorb automatisch.

## Architektur

```
ALDI-DB (Nährwerte/Preisvergleich)  →  Skill-Logik  →  rewe-cart.py  →  REWE Warenkorb
                                        (Planen)       (Browser-Automation)
```

**Tools:**
- `./tools/meinaldi-scraper.py` — Produkt-DB mit Nährwerten (Preisvergleich)
- `./tools/rewe-cart.py` — REWE Warenkorb: add, remove, list, status
- `./data/meinaldi.db` — SQLite mit ALDI-Produkten + Nährwerten

## Phase 0: Profil laden

**Memory:** `./projects/-home-maetzger/memory/user_fitness_ernaehrung.md`

Falls nicht vorhanden, frage: Ziel, Stats (Alter/Größe/Gewicht), Ausschlüsse, Budget, Haushaltsgröße.

**Matthias' Profil (Stand 2026-03-30, vollständiges Audit):**
- 30J, 180cm, 72kg, Muskelaufbau (Bulk), 2-3x Kraft/Woche, Bürojob
- Kalorien: ~2.700-2.900 kcal/Tag, Protein: 115-145g/Tag
- Kein Fisch/Meeresfrüchte, kein Buchweizen, Eier selten
- Haferflocken **ZART** (nicht kernig!) + Quark als Fixpunkt
- Supplements: Whey + Kreatin (nicht auf Einkaufsliste)
- Meal Prep: ja (kocht einmal, isst 2-3 Tage, max 5-10 Min/Mahlzeit)
- Abwechslung wenig wichtig — kann 5 Tage das Gleiche essen
- 1-2x/Woche auswärts → Einkauf für 5-6 Tage planen
- Budget: 60-80€/Woche für 7 Tage

**Bereits vorhanden (NICHT bestellen):**
- Milch (von Eltern, selbes Haus)
- Sojasauce
- Salz, Pfeffer
- Whey-Proteinpulver, Kreatin

## Phase 1: Produktrecherche via ALDI-DB

ALDI-DB für Nährwerte und Preisvergleich nutzen (NICHT zum Bestellen — bestellt wird bei REWE):

```bash
uv run ./tools/meinaldi-scraper.py --stats   # DB-Status
uv run ./tools/meinaldi-scraper.py --top-protein 20
```

Oder direkt per SQLite:
```sql
SELECT name, price, weight, protein, energy_kcal
FROM products p JOIN nutrition n ON p.sku = n.sku
WHERE protein > 10 AND name NOT LIKE '%Fisch%'
ORDER BY protein / price DESC LIMIT 20
```

## Phase 2: Wochenplan erstellen

**Kalorienziel:** ~2.800 kcal/Tag (72kg × ~39 für Bulk + sitzend + 2-3x Training)
**Proteinziel:** ~130g/Tag (1,8g/kg)

**Bevorzugte Proteinquellen (Preis/Protein):**

| Produkt | Protein/100g | Rolle |
|---------|-------------|-------|
| Magerquark/Speisequark | 12g | Billigste Quelle, Fixpunkt |
| Haferflocken zart | 14g | KH + Protein, Fixpunkt |
| Hähnchenbrust | 23g | Hauptfleisch |
| Skyr | 9-11g | Abend-Snack |
| Emmentaler/Käse | 25-28g | Kalorienreich + Protein |
| Erdnussbutter | 25g | Kalorien-Booster |
| Linsen (trocken) | 28g | Pflanzlich, für Dal |
| Hackfleisch | 18-20g | Bolognese |

**NICHT empfehlen:** "Protein-Pudding", "Protein-Wraps" etc. (Marketing-Aufpreis).

**Snacks einplanen:** Immer zero-prep Snacks mit aufnehmen:
Mini Mozzarella, Babybel, Studentenfutter, Hummus + Karotten, Reiswaffeln + Erdnussbutter, Erdnüsse

## Phase 3: Einkaufsliste generieren

### KRITISCH: Preisoptimierung

**Immer ja!-Marke oder REWE Beste Wahl bevorzugen.** Kein Bio, keine Premium-Marken, es sei denn keine Alternative existiert.

Priorität: `ja!` > `REWE Beste Wahl` > `Eigenmarke` > `Markenprodukt`

### KRITISCH: REWE-Suchbegriffe richtig wählen

**Bekannte Fehlzuordnungen vermeiden:**

| Suchbegriff | Ergebnis | Problem |
|-------------|----------|---------|
| `ja! Passata` | Schupfnudeln | "Passata" existiert nicht als ja!-Produkt |
| `ja! Linsen` | Linseneintopf (Dose) | Eintopf statt trockene Linsen |
| `ja! Curry` | Fertiggericht | Curry-Gericht statt Gewürz |
| `Karotten Snack` | Baby-Dinkelbällchen | "Snack" im Name triggert Falsches |

**Regeln für Suchbegriffe:**
1. Generisch suchen, nicht mit Marke prefixen wenn unsicher: `Passata 700g` statt `ja! Passata`
2. Bei Gewürzen: Immer `REWE Beste Wahl` + Gewürzname (ja! hat kaum Gewürze)
3. Bei Trockenware: Spezifisch sein: `Rote Linsen 500g` statt `Linsen`
4. Das Tool prüft jetzt per Keyword-Matching ob das Ergebnis passt — Fehlzuordnungen werden als `not_found` gemeldet statt blind hinzugefügt

### REWE Mengenlimit

REWE begrenzt auf ~2-3 Stück pro Artikel. Strategie:
- **500g Packungen statt 250g** wenn verfügbar (z.B. `ja! Speisequark 500g` statt 4x 250g)
- Verschiedene Marken mixen wenn nötig (z.B. 2x ja! + 2x Schwälbchen)

### Output als JSON für `rewe-cart.py`:

```json
[
  "ja! Zarte Haferflocken 500g",
  "ja! Speisequark Magerstufe 500g",
  "ja! Skyr Natur",
  "ja! Basmati Reis 1kg",
  "ja! Dinkel Spaghetti 500g",
  "ja! Erdnussbutter Creamy",
  "ja! Natives Olivenöl",
  "ja! Junge Erbsen tiefgefroren",
  "ja! Käseaufschnitt 250g",
  "Hähnchen Brustfilet frisch",
  "Hackfleisch gemischt 500g",
  "Gutfried Putenbrust",
  "REWE Bio Rote Linsen 500g",
  "Harry Vollkorn Urtyp",
  "Fuego Vollkorn Wrap",
  "REWE Bio Passata 700g",
  "Speisezwiebeln",
  "Bananen",
  "Karotten 1kg",
  "Erdnüsse geröstet 200g",
  "ja! Mini Mozzarella",
  "Mini Babybel",
  "ja! Studentenfutter",
  "ja! Hummus natur",
  "REWE Bio Reiswaffeln"
]
```

## Phase 4: REWE Warenkorb füllen

**Interaktiver Flow — braucht User-Input für 2FA!**

```bash
# 1. Browser starten (persistent, Xvfb + CDP Port 9222)
uv run ./tools/rewe-cart.py start

# 2. Login starten (Credentials aus ./.env)
uv run ./tools/rewe-cart.py login
# Output: "2FA_NEEDED" → User nach Code fragen!

# 3. User gibt 2FA-Code (aus E-Mail)
uv run ./tools/rewe-cart.py code 371717
# Output: "LOGGED_IN"

# 4. Einkaufsliste in Warenkorb
echo '[...]' > /tmp/shopping.json
uv run ./tools/rewe-cart.py add-list /tmp/shopping.json

# 5. Warenkorb prüfen
uv run ./tools/rewe-cart.py list

# 6. Unerwünschte Produkte entfernen
uv run ./tools/rewe-cart.py remove "Kölln Bio"
# Oder mehrere:
echo '["Kölln Bio", "Barilla"]' > /tmp/remove.json
uv run ./tools/rewe-cart.py remove-list /tmp/remove.json

# 7. Status prüfen
uv run ./tools/rewe-cart.py status

# 8. Browser NICHT beenden (Session bleibt eingeloggt)
```

**Wichtig für 2FA:** Nach `login` SOFORT den User fragen: "REWE hat einen Code an deine E-Mail geschickt. Wie lautet er?" Dann `code XXXXXX` ausführen. Code ist 10 Min gültig.

### Nach dem Befüllen: Verifizieren!

1. `rewe-cart.py list` ausführen
2. Prüfen ob alle Produkte korrekt sind (Name-Check)
3. Fehlzuordnungen mit `remove` entfernen
4. Fehlende Produkte mit alternativen Suchbegriffen nachtragen
5. Dem User eine kurze Zusammenfassung im Chat geben (kein HTML-Report nötig)

## Phase 5: Preisvergleich (optional)

ALDI-DB für Vergleich nutzen:
```sql
SELECT name, price FROM products
WHERE name LIKE '%Haferflocken%zart%'
   OR name LIKE '%Speisequark%250%'
   OR name LIKE '%Basmati%'
```

Tabelle: Produkt | ALDI-Preis | REWE-Preis | Differenz

## Technische Details

### Browser-Automation (undetected-chromedriver)
- System-Chromium (`/usr/bin/chromium`) statt Playwright — umgeht Bot-Detection
- Xvfb `:99` als virtueller Bildschirm
- CDP Port 9222 für persistente Steuerung via `pychrome`
- **Browser NICHT stoppen** nach Bestellung — Session bleibt eingeloggt
- REWE Cookie-Banner: Usercentrics Shadow DOM → `#usercentrics-root.shadowRoot`
- REWE Cart-Items: `div[class*="OverviewLineItem__lineItemContainer"]`
- REWE Delete: Erst "Menge reduzieren" bis Qty=1, dann erscheint "Produkt löschen"

### Produktsuche (Keyword-Matching)
- `add`/`add-list` prüfen jetzt ob der gefundene Produktname die Suchbegriffe enthält
- Keywords werden extrahiert (Marken-Prefixe und Mengenangaben ignoriert)
- Mindestens 50% der Keywords müssen im Produktnamen vorkommen
- Bei keinem Match: `not_found` statt blindes Hinzufügen

### Credentials
```bash
source ./.env
# REWE_EMAIL, REWE_PASS
```
