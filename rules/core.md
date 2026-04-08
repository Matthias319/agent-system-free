# Core Rules (immer geladen)

## Model

Opus 4.6 für alles. Kein Sonnet, kein Haiku.

## Tool-Vorrang

- Read statt cat/head/tail | Edit statt sed/awk | Write statt echo/heredoc
- Grep statt bash grep/rg | Glob statt bash find | Bash nur für git/systemctl/python3/uv/pipes
- **tee-to-file**: Langer Output → `cmd 2>&1 | tee /tmp/out.log | tail -20`
- **rtk**: `rtk <befehl>` für Token-Kompression (-80%). Nicht bei Debugging.
- **LSP vor Grep** für Code-Navigation (50ms vs 30s). Grep nur für Text-/Pattern-Suche.
- **Code-Suche Routing**: Symbol-Navigation → LSP | Struktur/Pattern → ast-grep | Text/Config/Strings → Grep | Gezielt semantisch in bekanntem Scope → Probe MCP (`search_code`) | Breite Codebase-Exploration → Explore Agent

## Anti-Pattern-Guards

### Dedizierte Tools statt Bash
- Für Dateiinhalte: Read Tool statt cat/head/tail
- Für Textsuche: Grep Tool statt bash grep/rg
- Für Dateisuche: Glob Tool statt bash find
- Für Dateiänderungen: Edit Tool statt sed/awk
- Kein Agent spawnen bei <3 Dateien (Overhead: ~2.000 Tokens)
- Explore-Agent immer mit `model: "sonnet"` (Default Haiku ist zu schwach)
- Bei Explore-Prompts: LSP-Hinweis injizieren ("Use LSP tools when possible: goToDefinition, findReferences, documentSymbol. Use ast-grep for structural patterns. Grep only for text search.")
- `head_limit` bei Grep setzen wenn >20 Treffer möglich
- Grep nicht für semantische Code-Suche → Probe MCP `mcp__probe__search_code` mit Path-Scope
- Probe ergänzt den Explore Agent, ersetzt ihn nicht bei breiter Exploration
- Bei Agent-Spawns die Code suchen: Tool-Routing-Block in den Prompt injizieren (siehe `~/.claude/rules-lib/agent.md`)
- Tools direkt aufrufen (Shebang), nicht `python3 ~/.claude/tools/X.py`

### Workflow-Guards
- Datei zuerst lesen, dann bearbeiten — Read vor Edit/Write
- Keine Edits auf Dateien die in dieser Session noch nicht gelesen wurden
- Bei großen Dateien (JSONL, Logs >25K Tokens): Read mit `offset` + `limit`
- Nur 1 Playwright-Instanz gleichzeitig — keine parallele Browser-Nutzung
- Temporäre Dateien (/tmp/*.json, Helper-Scripts) nach Aufgabenabschluss aufräumen

### Entscheidungs-Effizienz (Opus 4.6 spezifisch)
- Bei klarer Aufgabenstellung: Ansatz wählen und durchziehen. Nicht zwischen Alternativen hin und her überlegen.
- Kurskorrektur nur bei konkretem Widerspruch, nicht bei theoretischen Bedenken.
- Nach 2 gescheiterten Korrekturversuchen am gleichen Problem: `/clear` vorschlagen statt im verschmutzten Context weiterzumachen. Fehlgeschlagene Versuche akkumulieren Rauschen im Context und erschweren die Lösung.

## Agent Self-Healing: Issue Queue

Wenn du wiederholt fehlerhafte Toolcalls siehst (Broken Pipes, fehlende URLs, Parser-Fehler etc.):
- 1 großer Fehler oder 2-3 kleine am gleichen Tool → Issue schreiben
- Datei: `~/.claude/data/agent-issues.md`
- Format: Siehe Vorlage in der Datei (Kurztitel, Problem, Reproduktion, Fix-Vorschlag, Priorität)
- Wann selbst fixen: Fix <10 Zeilen, keine anderen Tools betroffen
- Wann auslagern: Fix riskant, mehrere Dateien, Session nicht blockiert
- Der Nachtschicht-Agent (6:00 Cron) arbeitet die Queue täglich ab.

## Anti-Halluzinations-Guards

- Bei Research/Analyse: Fakten nur mit Quellenzuordnung. Keine "confident wrong"-Antworten.
- Unsicherheit explizit kommunizieren: "Die Quellen beantworten das nicht" statt plausibel klingende Antwort ohne Beleg.
- Trainingswissen nicht als Fakten ausgeben wenn Quellen vorhanden — Quellen haben Vorrang.
- Widersprüche zwischen Quellen nicht still auflösen — beide Positionen benennen.
- Eigene Inferenz bei Synthese als solche markieren ("[Eigene Inferenz]" oder "[Eigene Einschätzung]").
- Overcompliance treibt Halluzinationen — kürzere, präzisere Antworten mit Quellenbezug statt elaborierter ohne.
- Synthese-Verifikation bei Research: Mindestens 3 Quellen-URLs zitieren. Wenn <3 Quellen → warnen.
- Bei Dokument-Analyse (PDFs, Verträge, Code): Relevante Textstellen erst wörtlich extrahieren, dann analysieren. Auf Zitate stützen, nicht auf Paraphrasen.
- Bei Code-Fragen: Datei zuerst lesen, dann antworten. Nicht über Code spekulieren der nicht in dieser Session gelesen wurde.

## Reversibility Guard

Vor destruktiven Aktionen (rm -rf, git push --force, git reset --hard, DROP TABLE, branch -D, systemctl disable) nachfragen. Lokale, reversible Aktionen (File-Edits, Tests) sind ok ohne Nachfrage. Bei Hindernissen keine destruktiven Shortcuts — Ursache finden statt Symptom wegräumen.

## Rules Router — bei Bedarf nachladen (1 Read-Call)

Vor der Arbeit: Prüfe ob die Anfrage Keywords aus der linken Spalte enthält.
Wenn ja: `Read` die entsprechende Datei. Im Zweifel: laden (billiger als Fehler).
Einmal geladene Rules bleiben im Context — nicht erneut laden.

| Keywords | Lade | Skills |
|----------|------|--------|
| web, url, scrape, fetch, search, crawl, preis, github, trending | `~/.claude/rules-lib/web.md` | /web-search, /market-check |
| LSP, definition, references, grep, read, ast-grep, navigate, explore, codebase, code-suche | `~/.claude/rules-lib/code-nav.md` | — |
| report, html, dashboard, renderer, design, shell | `~/.claude/rules-lib/output.md` | /html-reports |
| agent, parallel, team, subagent, spawn, background | `~/.claude/rules-lib/agent.md` | — |
| prompt, LLM-prompt, system-prompt, halluzination, evidence, schema, meeting-prompt, action-items | `~/.claude/rules-lib/prompting.md` | /autoresearch |
| groq, whisper, transkription, speech-to-text, tts, lpu, audio | `~/.claude/rules-lib/groq.md` | — |
