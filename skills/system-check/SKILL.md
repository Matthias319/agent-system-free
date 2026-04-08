---
name: system-check
description: "Server-Gesundheitscheck mit HTML-Report (CPU, RAM, Disk, Services)"
triggers:
  - "System-Status"
  - "wie geht es dem Server"
  - "Health-Check"
  - "Performance-Problem"
  - "warum ist es langsam"
  - "Temperatur"
  - "Speicher"
  - "CPU"
  - "Disk"
not_for:
  - "Application-Level Debugging"
  - "Netzwerk-Konfiguration"
---

# System Check -- Server Gesundheitsreport

Führe einen umfassenden Gesundheitscheck durch und erstelle einen HTML-Report.

**HTML-Reports**: Bevorzugt Report-Renderer nutzen (`./rules-lib/output.md`, Template: `dashboard`).

## Tracking + Self-Heal (PFLICHT)

```bash
RUN_ID=$(./tools/skill-tracker.py start system-check)
./tools/skill-tracker.py heal system-check
```

Am Ende Metriken loggen:

```bash
./tools/skill-tracker.py metrics-batch $RUN_ID '{
  "cpu_temp": XX.X, "ram_usage_pct": XX.X, "disk_usage_pct": XX.X,
  "services_ok": XX, "services_fail": XX, "overall_status": X
}'
./tools/skill-tracker.py complete $RUN_ID
```

(`overall_status`: 0=gesund, 1=warnung, 2=kritisch)

## Schritt 1: Daten sammeln

```bash
./tools/system-check.py 2>&1 1>/tmp/system-check.json | cat && echo "---JSON---" && cat /tmp/system-check.json
```

## Schritt 2: HTML-Report generieren

Lese die JSON-Daten aus der Bash-Ausgabe (nach `---JSON---`). Generiere einen standalone HTML-Report unter `~/shared/reports/system-check.html`.

### Warn-Schwellen

| Metrik | OK | Warnung | Kritisch |
|--------|-----|---------|----------|
| CPU Temp | < 70 C | 70-80 C | > 80 C |
| RAM Nutzung | < 85% | 85-95% | > 95% |
| Disk Nutzung | < 80% | 80-90% | > 90% |
| Throttling | 0x0 | -- | Jedes Flag gesetzt |
| Service Status | active | -- | nicht active |

### Gesamtstatus berechnen

- **Alle OK** → Gesamtstatus "Gesund"
- **Mind. 1 Warnung** → "Aufmerksamkeit"
- **Mind. 1 Kritisch** → "Kritisch"

### HTML-Template Design ("Warm Dark Editorial")

For HTML styling, read `/home/maetzger/.claude/skills/html-reports/references/foundation.md` for CSS tokens and base styles. Use the Dashboard Pattern from `/home/maetzger/.claude/skills/html-reports/references/patterns.md`.

**Layout-Struktur:**

1. **Header**: Großer Titel "System Check", Timestamp, Gesamtstatus als farbiger Badge
2. **Metric-Kacheln** (Grid 3 Spalten): CPU Temp, RAM Nutzung, Disk Nutzung -- jeweils mit:
   - Großer Zahlenwert (font-display, 2rem)
   - Label darunter (text-muted, uppercase)
   - Farbiger Rand unten (3px) je nach Status (grün/gelb/rot)
   - Subtiler Glow bei hover
3. **CPU-Sektion**: Takt, Governor, Load Average als Inline-Stats
4. **Overclocking-Sektion**: Config-Werte, Throttling-Status, Flags als Callout-Box wenn gesetzt
5. **RAM-Sektion**: Bar-Visualisierung (RAM + Swap), Zahlen daneben
6. **Disk-Sektion**: Usage-Bar, Top-10 Verzeichnisse als horizontale Bar-Chart
7. **Services**: Liste mit Status-Dots (grün = active, rot = down), Service-Name, Laufzeit
8. **Netzwerk**: IP-Adressen, UFW-Status, offene Ports als kompakte Tabelle
9. **Python**: Version, uv, installierte Tools
10. **Updates**: Anzahl verfügbar, Paketliste in ausklappbarem `<details>`
11. **Footer**: Hostname, Sammeldauer, Report-Zeitpunkt

**Component-Styles** (Callout-Boxen, Progress-Bars, Service-Status-Dots, responsive Breakpoints): Use the component styles from the `html-reports` skill foundation. Apply status colors (green/yellow/red) from the shared design tokens.

Schreibe den kompletten HTML-Report als EINE Datei mit inline CSS und JS nach `~/shared/reports/system-check.html`.

## Schritt 3: Terminal-Zusammenfassung

```
System Check -- [DATUM]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Gesamtstatus: [STATUS]

CPU:  [TEMP] | [TAKT] MHz | Load [LOAD]
RAM:  [USED]/[TOTAL] MB ([PCT]%)
Disk: [USED]/[TOTAL] GB ([PCT]%)
OC:   [TAKT] MHz | Throttling: [STATUS]

Services: [N]/[N] aktiv
Updates:  [N] verfügbar

Report: ~/shared/reports/system-check.html
```

## Token-Budget

- 1 Bash-Call: Script ausführen + JSON lesen
- 1 Write-Call: HTML-Report schreiben
- Ziel: unter 5.000 Tokens pro Ausführung
- KEIN separater Read-Call nötig (JSON kommt direkt aus Bash)
