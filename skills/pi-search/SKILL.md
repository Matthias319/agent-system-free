---
name: pi-search
description: "Findet frühere Sessions, Diskussionen und Arbeit aus der lokalen History (<10ms)"
triggers:
  - "haben wir schon mal"
  - "in welcher Session"
  - "wann war das"
  - "frühere Arbeit"
  - "Kontext wiederherstellen"
not_for:
  - "Web-Recherche"
  - "Code-Suche im aktuellen Projekt"
---

# Pi-Search — Intelligente lokale Suche

22.000+ Session-Nachrichten + 335 Dateien. <10ms pro Query. Typo-tolerant.

```bash
# Kurzform (empfohlen — in PATH):
pisearch "query"                          # Multi-Search, limit 5
pisearch "query" --limit 10               # Mehr Ergebnisse
pisearch "query" --index messages          # Nur Sessions
pisearch "query" --index files             # Nur Dateien

# Langform (für erweiterte Optionen):
INDEXER="./tools/meilisearch-indexer.py"
```

## Phase 0: Gate — Meilisearch oder klassische Tools?

**BEVOR du suchst**: Ist Meilisearch das richtige Tool?

| Signal | Tool | Warum |
|--------|------|-------|
| Fuzzy/unscharfe Begriffe, Tippfehler möglich | **Meilisearch** | Typo-tolerant, ranked |
| "Wann/wo/hatten wir...", Erinnerung an vergangene Session | **Meilisearch** | 22K Nachrichten durchsuchbar |
| Breite Suche ohne bekannten Pfad | **Meilisearch** | Pi-weit, 10ms |
| Exakter Regex-Pattern (`def.*init`) | **Grep** | Meilisearch kann kein Regex |
| Dateiname bekannt, Glob-Pattern (`**/*.py`) | **Glob** | Schneller, gezielter |
| Code-Navigation (Definition, References) | **LSP** | Semantisch, nicht Text |
| Web-Recherche, aktuelle Infos | **/web-search** | Meilisearch = nur lokal |

**Wenn Gate = Meilisearch** → weiter zu Phase 1.

## Phase 1: Intent-Klassifikation (PFLICHT)

Bestimme den Intent aus dem User-Prompt:

| Intent | Erkennungsmuster | Tiefe |
|--------|-----------------|-------|
| **Recall** | "wann haben wir", "hatten wir schon mal", "erinner dich", "letztens" | Schnell |
| **Locate** | "wo ist", "welches tool", "finde den code", "welche datei" | Schnell |
| **Explore** | "was wissen wir über", "alles zu", "Überblick" | Mittel |
| **Verify** | "stimmt es dass wir", "haben wir X jemals", "gibt es bei uns" | Schnell |
| **Forensik** | "was genau wurde gesagt", "zeig mir den Kontext", "vollständig" | Tief |
| **Diff** | "hat sich X geändert", "seit wann machen wir Y" | Mittel |

## Phase 2: Query-Konstruktion

### 2a. Index-Routing

| Intent + Kontext | Index | Begründung |
|-----------------|-------|------------|
| Session-Erinnerung, Gesprächsverlauf | `messages` | Chat-Historie |
| Tool/Skill/Config/Code suchen | `files` | Dateisystem |
| Unklar / beides möglich | `--multi` | Parallel beide |
| Report/Thesis/Plan suchen | `files` + `--filter "category=X"` | Gezielt |

### 2b. Strategie-Routing

| Query-Typ | `--strategy` | Begründung |
|-----------|-------------|------------|
| Natürliche Sprache ("wann haben wir über GPU gesprochen") | `frequency` | Seltene Wörter priorisieren |
| Technische Begriffe ("meilisearch configure_index") | `all` | Jedes Wort zählt |
| Einzelnes Keyword ("overclocking") | `frequency` | Default ist gut |
| Exakte Phrase ("self healing feedback loop") | `frequency` + `"\"phrase\""` | Phrase-Match erzwingen |
| Code-Fragmente ("def parse_session") | `all` | Exakt, kein Fuzzy |

### 2c. Tiefen-Routing

| Intent | `--limit` | `--context` | Nachbearbeitung |
|--------|-----------|-------------|-----------------|
| **Recall** (schnelle Antwort) | 3-5 | 200 | Snippet reicht |
| **Locate** (Datei finden) | 3-5 | 100 | Pfad aus Ergebnis, ggf. `Read` |
| **Explore** (Überblick) | 10-15 | 150 | Mehrere Treffer zusammenfassen |
| **Verify** (Ja/Nein) | 3 | 200 | Existenz prüfen, kurze Antwort |
| **Forensik** (voller Kontext) | 3-5 | 500 | **IMMER** Session-Datei per `Read` nachladen |
| **Diff** (zeitlich) | 10 | 200 | Nach Datum sortieren, Veränderung zeigen |

### 2d. Filter-Konstruktion

Automatisch Filter ableiten aus dem User-Prompt:

| Prompt-Signal | Filter |
|---------------|--------|
| "letzte Woche", "gestern", "heute" | `date>YYYY-MM-DD` (berechnen!) |
| "ich habe gefragt/gesagt" | `role=user` |
| "du hast geantwortet" | `role=assistant` |
| "in der Masterarbeit" | `category=thesis` oder `project` Filter |
| "welches Tool/Script" | `category=tool` |
| "im Report" | `category=report` |
| "im Projekt X" | `project=X` |
| Keine zeitlichen/Rollen-Signale | Kein Filter (breite Suche) |

## Phase 3: Ausführung

### 3a. Erst-Suche

```bash
# Beispiel: Recall, natürliche Sprache, letzte Woche
$INDEXER --search "GPU Server Kompatibilität" --index messages \
  --filter "date>2026-03-03" --strategy frequency --limit 5 --context 200
```

### 3b. Ergebnis-Bewertung (PFLICHT)

Nach der Suche evaluieren:

| Signal | Aktion |
|--------|--------|
| Top-Treffer score ≥ 0.9, Snippet beantwortet Frage | → **Direkt antworten** |
| Treffer gefunden aber Kontext zu knapp | → **Phase 4: Deep Dive** |
| 0 Treffer oder alle scores < 0.5 | → **Phase 5: Query-Erweiterung** |
| Treffer in `files` zeigt Pfad, Inhalt unklar | → **Read die Datei** direkt |
| Treffer in `messages` zeigt Session-ID | → **Read die JSONL** für vollen Kontext |

### 3c. Ergebnis dem User präsentieren

| Intent | Antwort-Format |
|--------|---------------|
| **Recall** | "Ja, am [Datum] in Session [X] haben wir [Zusammenfassung]." |
| **Locate** | "Das ist in `[Pfad]`. [1-2 Zeilen was die Datei macht]." |
| **Explore** | Bullet-Liste der relevanten Treffer mit Datum + Kontext |
| **Verify** | "Ja/Nein, [Beleg aus Treffer]." |
| **Forensik** | Längerer Auszug, ggf. mit Read nachgeladen |

## Phase 4: Deep Dive (nur wenn Phase 3b → "Kontext zu knapp")

Wenn die Snippets nicht reichen:

```bash
# 1. Session-Datei identifizieren (aus Treffer "file" Feld)
# 2. Volles JSONL lesen für den relevanten Abschnitt
Read /home/maetzger/.claude/projects/[project]/[session-id].jsonl
```

**ACHTUNG**: JSONL-Dateien können riesig sein (>1MB). Nutze `offset` und `limit` beim Read.
Tipp: Die `turn`-Nummer aus dem Treffer hilft, die richtige Stelle zu finden.

Für Dateien aus dem `files` Index: Einfach `Read [path]` — die sind klein.

## Phase 5: Query-Erweiterung (nur wenn Phase 3b → "0 Treffer")

| Versuch | Aktion |
|---------|--------|
| 1. Synonyme | Deutschen Begriff → Englisch oder umgekehrt |
| 2. Weniger Wörter | Nur die 1-2 wichtigsten Keywords behalten |
| 3. Anderer Index | Wenn nur in `messages` gesucht → auch `files` probieren |
| 4. Strategy wechseln | `all` → `frequency` (lockerer) |
| 5. Filter entfernen | Zeitfilter oder Rollen-Filter weglassen |
| 6. Aufgeben | "Dazu habe ich nichts in den lokalen Daten gefunden." |

**Max 2 Erweiterungs-Runden.** Dann ehrlich kommunizieren.

## Quick-Reference: Komplette CLI

```bash
# ── Suche ──
$INDEXER --multi "QUERY"                              # Beide Indexes
$INDEXER --search "QUERY" --index messages             # Nur Sessions
$INDEXER --search "QUERY" --index files                # Nur Dateien
$INDEXER --search "\"exakte phrase\"" --index messages  # Phrase-Match

# ── Filter ──
--filter "role=user"                    # Nur User-Nachrichten
--filter "role=assistant"               # Nur Claude-Antworten
--filter "date>2026-03-01"              # Ab Datum
--filter "category=tool"                # Nur Tools
--filter "category=report"              # Nur Reports
--filter "project=mission-control-v3"   # Nur ein Projekt
--filter "has_tools=true"               # Nur Nachrichten mit Tool-Aufrufen
# Kombinieren: --filter "role=user,date>2026-03-01"

# ── Tiefe ──
--limit 3 --context 100                 # Schnell, kompakt
--limit 10 --context 200                # Standard
--limit 5 --context 500                 # Tief, viel Kontext

# ── Strategie ──
--strategy frequency                    # Natürliche Sprache (Default)
--strategy all                          # Jedes Wort muss matchen
--strategy last                         # Letzte Wörter optional

# ── Index-Wartung ──
$INDEXER --delta                        # Neue Dateien nachindexieren (~2s)
$INDEXER --stats                        # Statistiken anzeigen
```

## Daten-Landkarte

```
messages Index (~22.000 Docs)
└── Jede User/Assistant-Nachricht aus allen Sessions
    Felder: text, role, date, session_id, project, tools_used, turn

files Index (~335 Docs)
├── tool     (27)  — ./tools/*.py
├── skill    (12)  — ./skills/**/*.md
├── rule      (6)  — ./rules/, rules-lib/
├── config    (2)  — CLAUDE.md Dateien
├── report   (83)  — ~/shared/reports/
├── plan      (6)  — (historisch, Verzeichnis nicht mehr vorhanden)
├── review    (7)  — Masterarbeit-Reviews
├── thesis   (27)  — .tex + .bib (Masterarbeit + Facharbeit)
├── note      (5)  — ~/shared/notizen/
└── project  (80)  — Source-Code aus 8 Projekten
    Felder: text, filename, path, category, language, project, date
```

## Wartung

- **Service**: `systemctl {start|stop|status} meilisearch`
- **Daten**: `/var/lib/meilisearch/data/` (~600MB)
- **API**: `127.0.0.1:7700` (nur lokal, Master-Key in Service-Unit)
- **Delta-Index empfohlen**: Nach jeder Session `$INDEXER --delta` (~2s)
