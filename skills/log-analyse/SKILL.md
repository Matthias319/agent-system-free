---
name: log-analyse
description: "Strukturierte Server-Log-Analyse mit journalctl (Fehler, Timeline, Patterns, Service-Korrelation)"
triggers:
  - "Logs"
  - "Log-Analyse"
  - "journalctl"
  - "Fehler suchen"
  - "was ist passiert"
  - "warum crashed"
  - "Service abgestürzt"
  - "seit wann läuft"
  - "was ist zuerst kaputtgegangen"
  - "Fehler-Pattern"
not_for:
  - "System-Health-Check (→ /system-check)"
  - "Application-Code-Debugging"
  - "Netzwerk-Konfiguration"
---

# Log-Analyse — Strukturierte Server-Log-Untersuchung

Analysiert systemd journal und Service-Logs mit Pattern-Erkennung, Timeline-Rekonstruktion und Service-Korrelation.

**Helper**: `./tools/log-analyse.py`
**Abgrenzung**: `/system-check` = "Ist der Server gesund?" | `/log-analyse` = "Was ist passiert und warum?"

## Tracking + Self-Heal (PFLICHT)

```bash
RUN_ID=$(./tools/skill-tracker.py start log-analyse --context '{"mode": "MODE", "since": "SINCE"}')
./tools/skill-tracker.py heal log-analyse
```

Am Ende:

```bash
./tools/skill-tracker.py metrics-batch $RUN_ID '{"mode": "MODE", "total_entries": N, "errors_found": N, "services_affected": N}'
./tools/skill-tracker.py complete $RUN_ID
```

## Routing — Modus aus der Frage ableiten

| Frage | Modus | Helper-Befehl |
|-------|-------|---------------|
| "Was ist passiert?" / "Warum crashed X?" | **timeline** | `log-analyse.py timeline` |
| "Welche Fehler gibt es?" / "Fehler der letzten Stunde" | **errors** | `log-analyse.py errors` |
| "Zeig mir die Logs von X" / "Was loggt service Y?" | **recent** | `log-analyse.py recent` |
| "Welche Services laufen?" / "Was ist down?" | **services** | `log-analyse.py services` |
| "Wann wurde neu gestartet?" | **boots** | `log-analyse.py boots` |

## Zeitraum-Mapping

Der User sagt... → `--since` Parameter:

| User-Input | --since |
|------------|---------|
| "letzte Stunde", "gerade eben" | 1h |
| "heute", "seit heute morgen" | 12h |
| "gestern", "letzte Nacht" | 24h |
| "diese Woche" | 7d |
| "seit dem Neustart" | (kein --since, statt dessen --boot) |
| Spezifisch: "seit 14 Uhr" | Direkt an journalctl weiterreichen |

## Schritt 1: Überblick verschaffen

Bei unklarer Frage immer zuerst Errors + Timeline kombinieren:

```bash
uv run ./tools/log-analyse.py errors --since 1h
```

JSON lesen und die wichtigsten Punkte extrahieren:
- Welche Services werfen Fehler?
- Gibt es wiederkehrende Patterns?
- Wie viele Fehler insgesamt?

## Schritt 2: Tiefergehende Analyse

Je nach Ergebnis aus Schritt 1:

### Fall A: Spezifischer Service betroffen
```bash
uv run ./tools/log-analyse.py timeline --since 1h --unit <service.service>
```

### Fall B: Viele Services betroffen — Korrelation suchen
```bash
uv run ./tools/log-analyse.py timeline --since 1h
```
→ Events chronologisch durchgehen: Was kam zuerst? (Start/Stop/Failure-Kaskade)

### Fall C: Keine offensichtlichen Fehler
```bash
uv run ./tools/log-analyse.py recent --since 1h --priority warning
```
→ Auch Warnings einbeziehen, oft Vorboten

## Schritt 3: Ergebnis präsentieren

Formatierung je nach Modus:

### Errors
```
Log-Analyse: Fehler (letzte 1h)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Gesamt: 12 Fehler in 3 Services

nginx.service (7 Fehler):
  → "upstream timed out" (5x)
  → "connect() failed" (2x)

claude-code.service (4 Fehler):
  → "EPIPE: broken pipe" (4x)

cron.service (1 Fehler):
  → "GRANDCHILD FAILED" (1x)

Top-Pattern: "upstream timed out" — 5 Vorkommnisse
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Timeline
```
Log-Analyse: Timeline (letzte 1h)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
14:23:01  [START]   nginx.service gestartet
14:23:05  [ERROR]   nginx.service — upstream timed out
14:23:06  [ERROR]   nginx.service — upstream timed out
14:25:12  [STOP]    claude-code.service gestoppt
14:25:15  [START]   claude-code.service gestartet
14:30:00  [FAILURE] cron.service — GRANDCHILD FAILED

Analyse: nginx hatte Timeout-Probleme ab 14:23,
möglicherweise Ursache für den claude-code Restart um 14:25.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Schritt 4: Ursachen-Hypothese

Nach der Daten-Präsentation IMMER eine kurze Einschätzung geben:
- Was ist die wahrscheinlichste Ursache?
- Welcher Service hat das Problem ausgelöst (Root Cause)?
- Was sollte als nächstes geprüft werden?

Bei Unsicherheit: Als Hypothese markieren, nicht als Fakt.

## Zusätzliche journalctl-Befehle (direkt)

Für Fälle die der Helper nicht abdeckt, direkt journalctl nutzen:

```bash
# Logs eines spezifischen Boot-Vorgangs
journalctl --boot=-1 -p err --no-pager | tail -50

# Kernel-Meldungen (OOM, Segfault, Hardware)
journalctl -k --since=-1h --no-pager | tail -50

# Disk-I/O-Probleme
journalctl --since=-1h --no-pager | grep -i "i/o error\|read-only\|ext4\|btrfs" | tail -20
```

## Token-Budget: 1-3 Calls

| Analyse-Tiefe | Calls | Tools |
|---------------|-------|-------|
| Schneller Fehler-Check | 1 | Bash (errors) |
| Fehler + Timeline | 2 | Bash (errors) + Bash (timeline) |
| Volle Analyse | 3 | Bash (errors) + Bash (timeline --unit X) + Bash (recent) |
| **Max Total** | **3** | — |

## Fehlerbehandlung

- **Leere Ausgabe**: Keine Logs im Zeitraum → größeren Zeitraum vorschlagen
- **Permission denied**: `sudo` vor journalctl nötig (sollte mit NOPASSWD funktionieren)
- **Sehr viele Entries**: `--since` eingrenzen, spezifischen `--unit` filtern
