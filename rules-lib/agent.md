# Agent Rules (on-demand geladen via Rules Router)

## Parallelisierung

PARALLEL wenn keine Abhängigkeiten. SEQUENTIELL wenn Output von A → Input für B.

| Aufgaben-Typ | Max. parallele Agents |
|--------------|----------------------|
| File-Reads / Code-Analyse | 5 |
| Multi-Perspektiven-Review | 4 |
| Datenextraktion | 4 |
| Research/Web-Fetch | 3 (Netzwerk-Bottleneck) |
| Code-Generierung | 3 |

**HARD LIMIT: Max 5 Agents gleichzeitig auf HP ProDesk (32GB RAM).**
Jeder Agent braucht ~600-700MB. 5 Agents + System = ~12GB → safe.
6+ Agents → RAM-Druck steigt, besonders mit Playwright.

Automatisch parallelisieren bei: "analysiere", "prüfe", "vergleiche", Bulk-Operationen.

## Agent-Spawn-Regeln

| Situation | Approach |
|-----------|----------|
| 1-3 Dateien | Direkt im Hauptthread (kein Agent) |
| Multi-File-Recherche (> 3) | `Explore`-Agent |
| Web-Recherche | **Hauptthread mit `/web-search` Skill** (bevorzugt) |
| Code schreiben | `general-purpose`-Agent |
| Nur Plan machen | `Plan`-Agent (kann nicht editieren) |

**Agent-Overhead:** ~2.000 Tokens Basis pro Agent.

## Tool-Routing-Injection (PFLICHT bei jedem Agent-Spawn)

**Agents erben KEINE Rules-Files.** Deshalb MUSS jeder Agent-Prompt die Tool-Routing-Regeln enthalten.

**PFLICHT-Block** — in JEDEN Agent-Prompt injizieren der Code liest/sucht:
```
TOOL-ROUTING (befolge strikt):
- Symbol-Navigation (Definition, Referenzen) → LSP (goToDefinition, findReferences)
- Semantische Code-Suche ("wo wird X gehandhabt?") → Probe MCP (mcp__probe__search_code)
- Code-Extraktion mit Kontext → Probe MCP (mcp__probe__extract_code)
- Strukturelle Pattern (alle Funktionen, Klassen) → ast-grep
- Text/Config/Strings → Grep
- Dateien finden → Glob
- Dateien lesen → Read (NIE cat/head/tail als Bash)
- NIE Grep für Code-Suche wenn Probe MCP oder LSP die Frage beantworten kann.
```

**Kurzform** für Agents die nur minimal Code lesen:
```
Tool-Routing: LSP > Probe MCP > ast-grep > Grep > Glob. NIE Bash-grep/cat/find.
```

## HTML-Report-Pflicht (ALLE Agents mit Recherche-Output)

**Agents erben KEINE Memory-Dateien und KEINE Rules-Files.** Deshalb MUSS der Hauptthread:
1. **VOR dem Spawn** das Pattern + Template bestimmen (REPORT_ROUTE)
2. Den REPORT-PFLICHT-Block MIT REPORT_ROUTE in den Agent-Prompt injizieren

### REPORT_ROUTE bestimmen (Hauptthread, VOR Agent-Spawn)

| Content-Signal | REPORT_ROUTE template_type |
|----------------|---------------------------|
| Produkte, Preise, Kaufberatung, Deals | `deep-research-v2` |
| Analyse, Multi-Source, Faktencheck | `deep-research-v2` |
| Orte, Adressen, Routen | `lokal-guide` |
| Reines Text-Briefing ohne Produkte | `research` |

### PFLICHT-Block — in jeden Agent-Prompt mit Recherche-Output:
```
REPORT_ROUTE: template_type=TEMPLATE_TYP

REPORT-PFLICHT: Nach jeder Recherche mit >3 Quellen automatisch HTML-Report generieren:
1. Ergebnisse als JSON nach /tmp/research-data.json
2. ~/.claude/tools/report-renderer.py render TEMPLATE_TYP /tmp/research-data.json -o ~/shared/reports/TOPIC-$(date +%Y-%m-%d).html
3. Report-Link dem User mitteilen

TEMPLATE_TYP ist oben festgelegt — NICHT selbst neu routen.

TEXT-REGELN (PFLICHT):
- IMMER echte UTF-8 Umlaute: ä, ö, ü, ß — NIEMALS ae, oe, ue, ss
- Keine Emojis. Keine HTML-Entities (&auml; etc.)

STRUKTUR-REGELN (PFLICHT):
- Jedes logische Thema = eigene Section in sections[]. NICHT alles in eine Section packen.
- Vergleiche/Tabellen IMMER als table: {headers: [...], rows: [[...]]} — NICHT als Markdown-Pipes in sections.body.
- Bei Vergleich: table: {headers, rows, variant: "comparison", highlight_col: N}

Für deep-research-v2 diese JSON-Keys PFLICHT nutzen:
- pullquotes: [{text, cite}] — min. 1 pro Report (bricht Fließtext visuell)
- keyfacts: [{number, label, text}] — min. 2 (große Kupfer-Zahlen)
- source_bars: [{title, quality}] — animierte Quellen-Balken
- kernaussage: "..." — destilliertes Fazit
- Bei Preisen: price_cards: [{name, price, trend, url}]
- Bei Empfehlungen: cta: [{label, url, icon, variant}]
- sources mit trust_level/type, [Qx]-Zitate im Body
Kein manuelles HTML — der Renderer generiert alles automatisch.
Schema anzeigen: ~/.claude/tools/report-renderer.py schema TEMPLATE_TYP
```

## Pi-Search als Pflicht-Erstschritt (ALLE Agents)

**Jeder Agent MUSS als allererstes Pi-Search queryen**, bevor er Glob/Grep/Web nutzt:
```bash
pisearch "AUFGABE_ALS_QUERY"
```
- **<10ms**, 33k+ indexierte Nachrichten + Dateien — quasi kostenlos
- Verhindert blinde Exploration von Dingen die schon in vergangenen Sessions gelöst wurden
- Treffer als Kontext nutzen → gezieltere Suche statt brute-force Grep/Glob

**Beim Spawnen von Agents** diese Instruktion in den Prompt injizieren:
```
Bevor du mit der Aufgabe startest: Führe als erstes aus:
pisearch "RELEVANTE_QUERY"
Nutze Treffer als Kontext für deine weitere Arbeit.
```

## Web-Recherche: Hauptthread > Agent (PFLICHT)

**IMMER `/web-search` Skill im Hauptthread** statt einen Research-Agent zu spawnen.

Warum: Agents kennen die Rules nicht (kein Zugriff auf die Rule-Files).
Ein general-purpose Agent spammt 15+ native WebSearch-Calls statt das
Search → Crawl Pattern zu nutzen (3-5 WebSearch → research-crawler.py).

| Methode | WebSearch-Calls | Token-Kosten | Qualität |
|---------|----------------|--------------|----------|
| Agent (unkontrolliert) | 10-20 | ~40.000 | Mittel (Snippets) |
| `/web-search` Skill | 3-5 | ~8.000 | Hoch (Volltext) |

**Einzige Ausnahme für Research-Agent:** Wenn die Recherche im Hintergrund laufen
soll UND gleichzeitig andere Arbeit erledigt wird. Dann PFLICHT im Prompt:

```
Nutze max 3-5 WebSearch-Calls für URL-Discovery.
Extrahiere Content mit: ~/.claude/tools/research-crawler.py --max-chars 6000 URL1 URL2 ...
NICHT für jede Detail-Frage einen eigenen WebSearch-Call machen.
```

## Research-Agents: Pflicht-Settings (wenn doch Agent)

```
run_in_background: true    # PFLICHT - blockiert sonst Hauptthread
max_turns: 20              # PFLICHT - verhindert Endlosschleifen
```

Max 4 Research-Agents gleichzeitig (Netzwerk-Bottleneck).

## Bidirektionale Recherche (optional, bei wichtigen Entscheidungen)

Experimentell belegt (Zettel #65): Die Schreibreihenfolge beeinflusst welche Fakten
ein Modell recherchiert. URL-Überlappung bei identischem Prompt: 0-15%.

**Wann nutzen:** Architekturentscheidungen, Tool-Wahl, faktenintensive Analysen.
**Wann NICHT:** Quick-Checks, einfache Fragen, Zeitdruck.

**Pattern:** Zwei parallele Research-Agents mit identischem Prompt, nur Format variiert:
- Agent A: "Beginne mit dem aktuellen Stand, arbeite dich chronologisch rückwärts"
- Agent B: "Beginne mit der Entstehungsgeschichte, arbeite dich chronologisch vorwärts"
- Ergebnisse im Hauptthread mergen → +40-60% einzigartige Fakten.

Kostet 2× Tokens, lohnt sich nur bei hohem Vollständigkeitsanspruch.

## Agent Teams (experimentell)

Aktiviert via `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`.

**Teams** wenn Agents untereinander diskutieren sollen (Competing Hypotheses, Peer Review).
**Subagents** wenn Agents nur Ergebnisse zurückliefern (Fan-Out/Fan-In).

Team-Größe: 3-5 Teammates optimal. Jeder Teammate = eigene volle Opus-Session.

## Context Window Management

- Bei 70% Context: Proaktiv State zusammenfassen
- Große Files: Mit `limit=` Parameter lesen
- Wenn Build/Tests fehlschlagen: Erst selbst analysieren, dann gezielt Sub-Agent

## Playwright-Concurrency (STRIKT)

**Max 1 Agent/Thread darf gleichzeitig Playwright nutzen.**

Audit zeigt 26× "browser busy"-Fehler durch parallele Playwright-Nutzung.

| Situation | Lösung |
|-----------|--------|
| Hauptthread nutzt Playwright | Kein Subagent darf Playwright aufrufen |
| Subagent braucht Screenshot | Hauptthread macht den Screenshot, Ergebnis im Prompt |
| Mehrere Agents brauchen Browser | Sequentiell, nicht parallel |

## Research-Agent: Prompt-Templates (BEVORZUGT)

Statt den Recherche-Prompt jedes Mal neu zu konstruieren, lade das Template:

```
prompt: "$(cat ~/.claude/tools/agent-prompts/research.md)\n\nAufgabe: DEINE_AUFGABE"
```

Verfügbare Templates in `~/.claude/tools/agent-prompts/`:
- **research.md** — Web-Recherche (Search→Crawl→Analyse)
- **explore.md** — Codebase-Exploration (Glob/Grep/Read)

Falls du den Prompt manuell baust, MUSS er enthalten:

```
Nutze für URL-Discovery: ~/.claude/tools/fast-search.py "query" "query2"
Nutze für Content-Extraktion: ~/.claude/tools/research-crawler.py --max-chars 6000 URL1 URL2
NICHT natives WebSearch verwenden — es ist 60× langsamer als fast-search.py.
WebSearch NUR für site:tiktok.com oder site:reddit.com Queries.
Max 3-5 Queries für URL-Discovery. Kein einzelner WebSearch pro Detail-Frage.
```

Ohne diese Instruktion fällt der Subagent auf natives WebSearch zurück (178× im Audit belegt).

## Anti-Patterns

- Sequentiell wenn parallel möglich
- Zu wenige Agents bei komplexen Fragen
- Research-Agents OHNE `run_in_background` / `max_turns`
- Research-Agent spawnen statt `/web-search` Skill nutzen
- Research-Agent OHNE Search→Crawl-Anweisung im Prompt (→ fällt auf WebSearch zurück!)
- Agent Teams für einfache Fan-Out-Tasks
- Mehr als 15 Agents (Context-Overhead)
- Mehrere Agents gleichzeitig mit Playwright (→ "browser busy"-Fehler)
