---
name: autoresearch
description: "Führt iterative Optimierungsloops (mutate → measure → accept/reject) für systematische Qualitätsverbesserung"
triggers:
  - "optimiere"
  - "verbessere iterativ"
  - "Qualitäts-Loop"
  - "Refactor-Loop"
  - "systematisch verbessern"
  - "A/B-Test"
not_for:
  - "einmalige Fixes"
  - "einfaches Refactoring"
---

# Autoresearch — Iterativer Optimierungsloop

Kernidee: **Mutiere → Miss den tatsächlichen Output → Behalte nur wenn besser.**

```
Tool: ./tools/autoresearch.py
Daten: ./data/autoresearch/<projekt>/
```

## Wann nutzen

| Signal | Passt | Passt NICHT |
|--------|-------|-------------|
| "Optimiere den Skill X" | Ja | — |
| "Refactore das Dashboard" | Ja (code-Typ) | — |
| "Mach das CSS besser" | Ja (config-Typ) | — |
| "Schreib eine neue Funktion" | — | Greenfield, kein Ist-Stand zum Messen |
| "Fix diesen Bug" | — | Einmaliger Fix, kein Loop nötig |

## Zentrale Lektion: Output testen, nicht Struktur

> Strukturelle Checks (Pattern, Syntax) erreichen 100% nach der ersten Iteration und treiben danach keine Verbesserung mehr. **Die echte Metrik ist: Produziert die Änderung besseren Output?**

Für Skills heißt das: Nicht prüfen ob SKILL.md das Wort "Pipe-Pattern" enthält, sondern ob der Skill tatsächlich bessere Suchergebnisse liefert.

## Check-Typen

| Typ | Was es prüft | Wann einsetzen |
|-----|-------------|----------------|
| **`trial`** | Führt die echte Pipeline aus, misst Output-Qualität | **Pflicht für Skills.** Die Kernmetrik. |
| `command` | Shell-Befehl, Exit-Code | Build, Syntax, Server-Start |
| `pattern` | Regex in Datei, Treffer-Zahl | Harte Pflicht-Elemente (sparsam!) |
| `agent` | Binäre Frage, vom Agent beantwortet | Synthese-Qualität, Design-Compliance |

### Trial-Checks (NEU — Herzstück für Skill-Optimierung)

Ein Trial-Check führt `fast-search.py | research-crawler.py` mit definierten Queries aus und misst:

| Metrik | Gewicht | Was es bedeutet |
|--------|---------|-----------------|
| `urls_ok` | 25% | Wie viele verwertbare URLs gefunden? |
| `avg_quality` | 35% | Durchschnittliche Inhaltsqualität (0-10) |
| `boilerplate_pct` | 15% | Anteil nutzloser Ergebnisse |
| `unique_domains` | 25% | Quellenvielfalt |

Daraus wird ein **Trial-Score (0-100)** berechnet. Dieser Score ermöglicht echten Vergleich:
- Iter 1: Trial-Score 72 → Iter 2: Trial-Score 78 → **+6, ACCEPT**
- Iter 2: Trial-Score 78 → Iter 3: Trial-Score 71 → **-7, REJECT**

```json
{
  "id": "t1", "name": "Tech-Recherche", "type": "trial",
  "queries": ["perovskite solar cell efficiency 2026", "Perowskit Solarzelle Wirkungsgrad 2026"],
  "min_urls_ok": 5, "min_avg_quality": 6.5,
  "max_boilerplate_pct": 25, "min_domains": 3,
  "freshness_weight": 2.0,
  "save_output": "/tmp/ar-trial-t1.json"
}
```

### Gute Trials designen

Trials sollten die **Kernszenarien des Skills** abdecken:

| Szenario | Beispiel-Queries | Was es testet |
|----------|-----------------|---------------|
| Breites Thema (DE+EN) | `"KI Agenten 2026"`, `"AI agents framework 2026"` | Findet er Quellen in beiden Sprachen? |
| Nischenthema | `"RTX 6000 Pro HP DL360 compatibility"` | Funktioniert die Suche bei wenig Daten? |
| Vergleich | `"M4 Mac Mini vs Framework Desktop 2026"` | Findet er Quellen für beide Seiten? |
| Lokales/DE-Thema | `"Mietpreisbremse Berlin 2026 Regelung"` | Funktioniert rein-deutsche Suche? |

**3-5 Trials** decken die meisten Skills ab. Mehr → Diminishing Returns + lange Laufzeit.

### Check-Mix pro Projekttyp

| Projekttyp | trial | command | pattern | agent |
|------------|-------|---------|---------|-------|
| **skill** | **2-4** | 0-1 | 0-1 | 0-1 |
| code | 0 | 2-3 | 1-2 | 1-2 |
| config | 0-1 | 1 | 2-3 | 1 |

## Ablauf

### Phase 0: Projekt initialisieren

```bash
./tools/autoresearch.py template skill > /tmp/ar-config.json
# Config anpassen (Targets, Queries, Schwellenwerte), dann:
./tools/autoresearch.py init /tmp/ar-config.json
```

### Phase 1: Baseline messen

```bash
./tools/autoresearch.py check <projekt>
```

**Trial-Scores notieren.** Das sind die Werte, die du schlagen musst. Die binären Pass/Fail-Checks sind nur Hygiene — der Trial-Score ist die echte Metrik.

### Phase 2: Mutation

**Eine fokussierte Änderung** an den Target-Dateien.

Für Skills: Einen Aspekt des Prompts verbessern, der die Trial-Metriken beeinflusst:
- Avg Quality niedrig → Query-Formulierungen verbessern, Freshness-Weight anpassen
- Wenige URLs → Mehr Queries generieren, alternative Suchstrategien
- Hohe Boilerplate → Blocklist erweitern, Quality-Threshold erhöhen
- Wenig Domain-Vielfalt → Sprach-Routing verbessern, site:-Strategien

### Phase 3: Erneut messen

```bash
./tools/autoresearch.py check <projekt>
```

Vergleiche **Trial-Scores** (nicht nur Pass/Fail). +2 Punkte = echte Verbesserung.

### Phase 4: Accept oder Reject

```bash
# Trial-Score besser → behalten:
./tools/autoresearch.py accept <projekt> --note "Was + warum"

# Trial-Score schlechter → zurücksetzen:
./tools/autoresearch.py reject <projekt>
```

### Phase 5: Nächste Iteration (zurück zu Phase 2)

## Agent-Loop Protokoll

```
1. check <projekt>            → Baseline Trial-Scores
2. [Trial-Output lesen]       → Schwachstellen identifizieren
3. [EINE Mutation]            → Gezielt die schwächste Metrik verbessern
4. check <projekt>            → Neue Trial-Scores
5. Trial-Score besser?
   Ja  → accept + commit
   Nein → reject
6. → Zurück zu 1 (bis Abbruch)
```

### Schwachstellen aus Trial-Output identifizieren

Nach `check` die gespeicherten Trial-Outputs lesen (`save_output` Pfad):

```bash
# Welche Domains kamen? Welche Qualität?
python3 -c "
import json
data = json.load(open('/tmp/ar-trial-t1.json'))
ok = [d for d in data if not d.get('error') and not d.get('boilerplate')]
for d in ok:
    print(f'  Q{d[\"quality\"]:>2} | {d.get(\"domain_tier\",\"?\"):>3} | {d[\"url\"][:60]}')
"
```

Daraus leiten sich die Mutationen ab:
- Viele Q5-Q6 Ergebnisse? → Query-Formulierung optimieren
- Immer dieselben Domains? → Queries diversifizieren
- Viele Errors? → Blocklist erweitern

### Abbruchbedingungen

- **Trial-Score Plateau:** Stagniert über 3 Iterationen (±1 Punkt)
- **Trial-Score > 85:** Sehr gute Qualität, Diminishing Returns
- **Zeitbudget:** Vom User gesetzt
- **Goodhart:** Score steigt aber Output wird schlechter (Trial-Outputs manuell prüfen!)

## Nützliche Befehle

```bash
./tools/autoresearch.py list              # Alle Projekte
./tools/autoresearch.py status <projekt>   # Status
./tools/autoresearch.py history <projekt>  # Score-Verlauf
./tools/autoresearch.py template skill     # Beispiel-Config
```

## Anti-Patterns

- **NICHT** nur strukturelle Checks für Skills — Trial-Checks sind Pflicht
- **NICHT** alles auf einmal ändern — eine Mutation pro Iteration
- **NICHT** Trial-Score als einzige Wahrheit — Trial-Output manuell prüfen
- **NICHT** mehr als 10 Iterationen ohne Trial-Review
- **NICHT** für Greenfield-Projekte (kein Ist-Stand zum Messen)
