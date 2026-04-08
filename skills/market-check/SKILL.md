---
name: market-check
context: fork
description: "Ermittelt Marktwert gebrauchter Artikel auf Kleinanzeigen"
triggers:
  - "was ist das wert"
  - "Gebrauchtpreis"
  - "Marktwert"
  - "verkaufen"
  - "was bekomme ich dafür"
  - "Kleinanzeigen"
  - "Secondhand"
not_for:
  - "Neupreise/Specs"
  - "allgemeiner Preisvergleich"
delegates_to:
  - "web-search"
---

# Kleinanzeigen Marktwert-Check

Du ermittelst den realistischen Marktpreis für ein Produkt auf kleinanzeigen.de.
Der Suchbegriff kommt aus $ARGUMENTS.

## Voraussetzung: Produktauswahl

Wenn der User **KEIN spezifisches Produkt** nennt, sondern eine Kategorie/Anforderung
(z.B. "bestes Soundsystem für 500-1000€"), dann ZUERST `/web-search` nutzen,
um die Top-Kandidaten zu identifizieren. Danach für jeden Kandidaten `/market-check` ausführen.

**Direkte Produktnennung** (z.B. "KEF LS50 Wireless II"): Direkt `/market-check` starten.

**HTML-Generierung**: Läuft über `market-scraper.py --html` (eigenes integriertes Template). Für andere Report-Typen: Report-Renderer (`./rules-lib/output.md`).

## Klickbare Links (PFLICHT)

**JEDER Report MUSS klickbare Links zu den Kleinanzeigen-Inseraten enthalten.**

- **`--html` Flag**: Links sind im Template bereits eingebaut. Nichts zu tun.
- **Manueller/Custom-Report**: URLs aus dem Scraper-Output (`listing["url"]`) extrahieren, `https://www.kleinanzeigen.de` davor, als `<a>` mit `target="_blank"` einbauen.
- **URL-Format**: Scraper liefert relative Pfade (`/s-anzeige/...`). Immer `https://www.kleinanzeigen.de` + relativer Pfad.
- **Mobile-tauglich**: Links müssen als Touch-Target groß genug sein (min. 44px Höhe).

## Effizienz-Regel

**Kein Kommentar zwischen Tool-Calls.** Keine Zwischenanalysen, keine Erklärungen.
Nur die Tools aufrufen, Ergebnis formatiert ausgeben, fertig.

## 2-Call-Architektur

Dieser Skill nutzt **exakt 2 Bash-Calls**. Der Scraper übernimmt
Geizhals-Lookup (`--auto-geizhals`) und Exclude-Keywords (`--auto-exclude`) intern.

## Ablauf

### VOR Call 1: Entscheidung (kein Tool-Call, nur Denken)

**Ist das Produkt noch regulär neu erhältlich?**

- **Ja** (aktuelle Generation): → `--auto-geizhals` nutzen
- **Nein** (abgekündigt): → `--neupreis UVP --neupreis-source "UVP (Launch JAHR)"` statt `--auto-geizhals`
- **Unsicher?** → `--auto-geizhals` nutzen, Scraper gibt graceful None zurück wenn nichts gefunden

**Kategorie-Auswahl:**
- **Smart-Selection (Default)**: Scraper wählt automatisch die relevanteste Kategorie per Token-Overlap + Brand-Matching
- `--category N` ist nur noch Fallback wenn Smart-Selection Score <= 1

### Call 1: Tracking + Scraper + Kandidaten anzeigen

```bash
RUN_ID=$(./tools/skill-tracker.py start market-check --context '{"product": "NAME"}') && \
echo "$RUN_ID" > /tmp/market-run-id && \
./tools/skill-tracker.py heal market-check && \
./tools/market-scraper.py 'SUCHBEGRIFF' \
  --product-name "NAME" --auto-geizhals --auto-exclude \
  --category N \
  --save \
  --html ~/shared/reports/market-SLUG.html \
  2>/tmp/market-stderr.log > /tmp/market-result.json && \
cat /tmp/market-stderr.log && \
python3 -c "
import json
with open('/tmp/market-result.json') as f: d = json.load(f)
a = d.get('agent_analysis', {})
s = d.get('stats', {})
print(f'Roh: {d[\"total_raw\"]}, Clean: {d[\"total_clean\"]}, Scam: {d[\"total_scam\"]}, Final: {d[\"total_final\"]}')
print(f'Median: {s.get(\"median\")}€, Spanne: {s.get(\"min\")}-{s.get(\"max\")}€')
print(f'Markt: {a.get(\"market\", \"?\")}')
print()
for i, p in enumerate(d.get('smart_picks', [])[:5], 1):
    print(f'--- Kandidat {i}: {int(p[\"price\"])}€ — {p[\"title\"]}')
    print(f'  Score: {p.get(\"score\",0)} | Badges: {p.get(\"seller_badges\",\"-\")} | Alter: {p.get(\"age_days\",\"?\")}d')
    specs = p.get('specs')
    if specs:
        spec_parts = [f'{k}={v}' for k,v in specs.items()]
        print(f'  Specs: {\" · \".join(spec_parts)}')
    risks = p.get('risk_flags', [])
    if risks:
        print(f'  ⚠ Risiken: {\", \".join(risks)}')
    tgtbt = p.get('tgtbt_flags', [])
    if tgtbt:
        print(f'  ⚠ TGTBT: {\", \".join(tgtbt)}')
    desc = (p.get('description') or '')[:200]
    if desc:
        print(f'  Beschreibung: {desc}')
    print(f'  Algo-Grund: {a.get(f\"pick{i}_reason\", \"?\")}')
    print(f'  Algo-Vorschlag: {a.get(f\"pick{i}_suggest\", \"?\")}')
    print()
nb = d.get('nearby_pick')
if nb:
    print(f'--- Nearby: {int(nb[\"price\"])}€ — {nb[\"title\"]}')
    desc = (nb.get('description') or '')[:200]
    if desc:
        print(f'  Beschreibung: {desc}')
    print(f'  Algo: {a.get(\"nearby_reason\", \"?\")} | Vorschlag: {a.get(\"nearby_suggest\", \"?\")}')
tw = a.get('tgtbt_warning', '')
if tw:
    print(f'\n{tw}')
hw = a.get('hacked_account_warning', '')
if hw:
    print(f'\n{hw}')
print(f'\nFazit (Algo): {a.get(\"fazit\", \"?\")}')
"
```

**Für abgekündigte Produkte** (statt `--auto-geizhals`):
```bash
  --neupreis UVP --neupreis-source "UVP (Launch JAHR)" \
```

**heal-Output beachten:** Bekannte Fehler-Domains/Patterns vermeiden. Reflexionen (bestätigt/offen) aktiv berücksichtigen.

### Zwischen Call 1 und 2: Schnell-Validierung (kein Tool-Call, KURZ denken)

**Schnell-Scan aller Picks + Empfehlung + Nearby.** Pro Eintrag 1 Sekunde:
- Zubehör/Ersatzteil statt Gerät? → `AGENT_HIDE_N = style="display:none"`
- Defekt/Bastlerware/MDM-Lock? → ausblenden
- TGTBT-Flag? → Nicht ausblenden, aber Agent-Note mit Warnung
- Risk-Flags (Wasserschaden, ohne Garantie etc.)? → Note erwähnen
- Hacked-Account-Warnung vorhanden? → In der Note erwähnen
- Ok? → 5-Wort Agent-Note + weiter

### Call 2: Injection + History + Metriken + Cleanup

```bash
python3 -c "
from pathlib import Path
html = Path('REPORT_PATH').read_text()
notes = {
    '<!--AGENT_NOTE_1-->': '<div class=\"smart-pick__agent-note\">NOTE_1</div>',
    '<!--AGENT_NOTE_2-->': '<div class=\"smart-pick__agent-note\">NOTE_2</div>',
    '<!--AGENT_NOTE_3-->': '<div class=\"smart-pick__agent-note\">NOTE_3</div>',
    '<!--AGENT_NOTE_NEARBY-->': '<div class=\"smart-pick__agent-note\">NOTE_NEARBY</div>',
}
hide = {
    '<!--AGENT_HIDE_1-->': '',
    '<!--AGENT_HIDE_2-->': '',
    '<!--AGENT_HIDE_3-->': '',
    '<!--AGENT_HIDE_4-->': '',
    '<!--AGENT_HIDE_5-->': '',
    '<!--AGENT_HIDE_NEARBY-->': '',
    '<!--AGENT_HIDE_RECO-->': '',
    '<!--AGENT_HIDE_NEARBY_HERO-->': '',
}
for k, v in {**notes, **hide}.items():
    html = html.replace(k, v)
Path('REPORT_PATH').write_text(html)
print('Agent-Notes + Visibility injiziert')
" && \
./tools/market-db.py history --product "NAME" && \
RUN_ID=$(cat /tmp/market-run-id) && \
./tools/skill-tracker.py metrics-batch "$RUN_ID" '{"listings_found":XX,"listings_valid":XX,"scam_rate":0.12,"geizhals_success":true,"geizhals_price":XX,"price_median":XX,"price_range_min":XX,"price_range_max":XX,"smart_picks_count":X}' && \
./tools/skill-tracker.py complete "$RUN_ID" && \
./tools/skill-tracker.py auto-learn 2>&1 | tail -3 && \
rm -f /tmp/market-result.json /tmp/market-stderr.log /tmp/market-run-id
```

Ersetze `REPORT_PATH`, `NOTE_1`-`NOTE_NEARBY` mit deinen Bewertungen.
Ersetze Metriken-Werte mit den echten Zahlen aus Call 1.

**Schlechte Picks ausblenden:** Setze den `AGENT_HIDE_N`-Wert auf `style="display:none"`:
```python
'<!--AGENT_HIDE_3-->': 'style="display:none"',  # Ersatzteil/Zubehör
```
Gute Picks: Wert leer lassen (`''`).

### Danach: Formatiertes Output (kein Tool-Call, nur Text)

```
Marktwert-Analyse: [Suchbegriff]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Kategorie-Filter:           [gewählte Kategorie]
Erfasste Inserate (roh):    [n_raw]
Nach Bereinigung:           [n_clean]
Scam-Accounts gefiltert:    [n_scam]
Finale Stichprobe:          [n_final]

Median-Preis:               [median] EUR
Realistische Spanne:        [min] - [max] EUR (IQR-bereinigt)
Neupreis (Bestpreis):       [bestpreis] EUR ([Quelle])
Ersparnis vs. Neu:          [diff] EUR ([pct]%)

Smart Picks:
  #1  [price]€ — [title] (Score [score])
      → Vorschlag: [suggest_price]€
      [⚠ TGTBT/Risk falls vorhanden]
  #2  [price]€ — [title] (Score [score])
      → Vorschlag: [suggest_price]€

Top in der Nähe (falls vorhanden):
  [price]€ — [title] ([distance]km, [location])
  → Vorschlag: [suggest_price]€

Warnungen (falls vorhanden):
  ⚠ TGTBT: [warning text]
  ⚠ Gehackte Accounts: [warning text]

HTML-Report: ~/shared/reports/market-SLUG.html
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Token-Budget: 2 Tool-Calls

| Phase | Calls | Tool |
|-------|-------|------|
| Tracking + Heal + Scraper + Kandidaten | 1 | Bash |
| **Agent-Validierung** | **0** | **Denken (kein Tool)** |
| Injection + History + Metriken + Cleanup | 1 | Bash |
| **Total** | **2** | -- |

**Sonderfälle (extra Call nötig):**
- Abgekündigte Produkte: Kein extra Call, einfach `--neupreis UVP --neupreis-source "UVP (Launch JAHR)"` statt `--auto-geizhals`
- 0 Inserate: Retry mit breiterem Suchbegriff → +1 Call

## Scraper-Optionen Referenz

```
./tools/market-scraper.py SUCHBEGRIFF [OPTIONEN]

Positional:
  SUCHBEGRIFF              Kleinanzeigen-Suchbegriff

Optionen:
  --product-name NAME      Normalisierter Produktname für DB
  --category N             Kategorie-Index (0=größte, 1=zweitgrößte)
  --category-name NAME     Kategorie-Label für DB
  --price-min N            Mindestpreis-Filter (auto: 10€ bei --auto-geizhals)
  --price-max N            Höchstpreis-Filter (auto: kein Limit)
  --exclude KW1 KW2 ...   Keywords zum Ausschließen (Titel-Match)
  --auto-geizhals          Neupreis automatisch via Geizhals ermitteln
  --auto-exclude           Produkttyp-spezifische Exclude-Keywords automatisch
  --max-checks N           Max Seller-Profile prüfen (Default: 6)
  --neupreis N             Neupreis manuell setzen (überschreibt --auto-geizhals)
  --neupreis-source TEXT   Quelle des Neupreises
  --save                   In ./data/market.db speichern
  --html PFAD              HTML-Report generieren
```

## Fehlerbehandlung

- **0 Inserate**: Suchbegriff zu spezifisch → kürzen oder andere Kategorie
- **Kategorie nicht gefunden**: Generische Suche ohne Kategorie-Filter
- **HTTP 429 (Rate Limit)**: Warten und erneut versuchen (selten)
- **Keine Empfehlung**: Kein Verkäufer erfüllt Trust-Kriterien → normal melden

## Tools

- **Scraper**: `./tools/market-scraper.py`
- **DB**: `./tools/market-db.py`
- **Template**: `./tools/market-report-template.html`
