# Code Navigation Rules (on-demand geladen via Rules Router)

## PFLICHT-Entscheidungsbaum: Welches Tool für welche Suche?

Bevor du Grep/Glob benutzt, gehe diesen Baum durch. **Jedes Mal.** Kein Überspringen.

```
Frage: "Was suche ich?"
│
├─ "Wo ist X definiert?" ──────────────── LSP goToDefinition (50ms)
├─ "Wer ruft X auf?" ─────────────────── LSP findReferences (50ms)
├─ "Was ist der Typ von X?" ──────────── LSP hover (50ms)
├─ "Welche Symbole hat diese Datei?" ─── LSP documentSymbol (50ms)
├─ "Finde Symbol X im Workspace" ─────── LSP workspaceSymbol (50ms)
│
├─ "Wo wird Auth in src/ gehandhabt?" ─── Probe MCP search_code (gezielter Scope!)
├─ "Finde Code der Y tut" (semantisch) ── Probe MCP search_code (mit explizitem Path)
├─ "Zeige die Funktion X im Kontext" ──── Probe MCP extract_code
├─ "Erkläre die Architektur von X" ─────── Explore Agent (navigiert + versteht Struktur)
│
├─ "Finde alle Funktionen die Y tun" ─── ast-grep (48ms)
├─ "Finde Code-Pattern/Struktur" ──────── ast-grep (48ms)
├─ "Welche Klassen haben Methode Z?" ─── ast-grep (48ms)
├─ "Finde alle try/except Blöcke" ────── ast-grep (48ms)
│
├─ "Finde Text-String in Dateien" ────── Grep (100ms)
├─ "Finde Config/Markdown-Einträge" ──── Grep (100ms)
├─ "Welche Dateien enthalten Text X?" ── Grep files_with_matches (100ms)
│
├─ "Finde Dateien mit Namens-Pattern" ── Glob (20ms)
└─ "Existiert Datei X?" ──────────────── Glob (20ms)
```

**Routing-Kurzregel:** Symbol → LSP | Semantik/gezielter Scope → Probe MCP | Breite Exploration → Explore Agent | Struktur/Pattern → ast-grep | Text/Config → Grep | Dateien → Glob

**Wenn du bei Grep landest, frage dich:** "Suche ich Code-Struktur oder Text?"
Wenn Code → zurück zu Probe MCP/ast-grep/LSP. Grep ist NUR für Text-/Pattern-Suche.

## LSP: Semantische Navigation (IMMER zuerst prüfen)

| Aufgabe | Operation | Speed |
|---------|-----------|-------|
| Wo ist Funktion X definiert? | `goToDefinition` | 50ms |
| Wer ruft Funktion X auf? | `findReferences` | 50ms |
| Welchen Typ hat Variable Y? | `hover` | 50ms |
| Alle Symbole in Datei | `documentSymbol` | 50ms |
| Symbol im Workspace finden | `workspaceSymbol` | 50ms |
| Implementierungen eines Interface | `goToImplementation` | 50ms |
| Wer ruft diese Funktion auf? | `incomingCalls` | 50ms |
| Was ruft diese Funktion auf? | `outgoingCalls` | 50ms |

**LSP ist 10-100x schneller und präziser als Grep** — versteht Code-Struktur, nicht nur Text.
Installiert: pyright 1.1.408 (Python), typescript-lsp (TS/JS).

### Wann NICHT LSP
- Datei hat keinen LSP-Server (Markdown, YAML, Shell-Skripte)
- Reine Text-Suche (Strings, Kommentare, Config-Werte)
- Suche über viele Dateien nach einem Pattern → ast-grep

## ast-grep: Strukturelle Code-Suche (NEU — BENUTZEN!)

Binary: `/usr/local/bin/ast-grep` (v0.41.0, via Symlink)

```bash
# IMMER über Bash-Tool aufrufen:
ast-grep run --pattern 'PATTERN' --lang LANG /pfad/
```

### Pattern-Syntax (die wichtigsten)

| Pattern | Findet | Beispiel |
|---------|--------|----------|
| `$VAR` | Ein beliebiger Ausdruck | `def $FUNC()` |
| `$$$` | Null oder mehr Argumente | `db.execute($$$)` |
| `$$$ $VAR` | Rest + letztes Argument | `print($$$ $LAST)` |

### Häufige Patterns

```bash
# Funktions-Definitionen
ast-grep run --pattern 'def $FUNC($$$)' --lang python /pfad/

# Async-Funktionen
ast-grep run --pattern 'async def $FUNC($$$)' --lang python /pfad/

# Klassen-Definitionen
ast-grep run --pattern 'class $NAME($$$)' --lang python /pfad/

# Alle Aufrufe einer Funktion
ast-grep run --pattern 'db.execute($$$)' --lang python /pfad/

# Import-Statements
ast-grep run --pattern 'from $MOD import $NAME' --lang python /pfad/

# Dekoratoren
ast-grep run --pattern '@app.get($$$)' --lang python /pfad/

# Variablen-Zuweisungen mit Typ
ast-grep run --pattern '$VAR: $TYPE = $VAL' --lang python /pfad/
```

### Sprachen
`--lang python`, `--lang javascript`, `--lang typescript`, `--lang html`, `--lang css`, `--lang json`

### Performance
- 48ms für ~9000 Matches über ~/.claude/tools/ (12 Dateien)
- Skaliert linear, bleibt unter 200ms für typische Projekte
- Kein Index nötig (im Gegensatz zu ctags)

### Wann ast-grep statt Grep
- **Code-Strukturen**: Funktionssignaturen, Klassen, Dekoratoren, Imports
- **Refactoring-Vorbereitung**: "Wo wird dieses Pattern verwendet?"
- **Codebase-Exploration**: "Welche async Funktionen gibt es?"

### Wann NICHT ast-grep
- Reine Text-Suche (Config-Werte, Kommentare, Markdown)
- Regex-Patterns (ast-grep versteht keine Regex)
- Datei-Suche (dafür Glob)

## Grep: Text- und Pattern-Suche (Fallback)

| Ziel | output_mode | Parameter |
|------|------------|-----------|
| "Welche Dateien enthalten X?" | `files_with_matches` (default) | `head_limit: 10` |
| "Zeige mir die Zeilen mit X" | `content` | `-C: 3`, `head_limit: 50` |
| "Wie oft kommt X vor?" | `count` | - |

**IMMER `head_limit` setzen** wenn >20 Treffer möglich.
**`type` statt `glob`** für Standardtypen: `type: "py"` statt `glob: "*.py"`.

### Grep NUR für
- Text-Strings in beliebigen Dateien (Config, Markdown, Logs, Shell)
- Regex-Patterns die ast-grep nicht kann
- Schnelle "gibt es das irgendwo?"-Prüfung

### Grep NICHT für
- "Wo ist Funktion X definiert?" → **LSP**
- "Finde alle Klassen mit Methode Y" → **ast-grep**
- "Wer ruft X auf?" → **LSP findReferences**

## Read: Große Dateien gezielt lesen

| Dateigröße | Strategie |
|-----------|-----------|
| < 200 Zeilen | Komplett lesen (default) |
| 200-500 Zeilen | Komplett lesen, nur beim ersten Mal |
| 500-2000 Zeilen | `offset` + `limit` gezielt, nie komplett |
| > 2000 Zeilen | Wird automatisch bei 2000 abgeschnitten! Immer `offset`+`limit` |

## Glob: Datei-Suche

Schnellstes Tool für "existiert Datei X?" oder "finde alle *.py in /pfad/".
**Glob > Bash find.** fdfind (`fdfind -e py`) nur in Bash-Pipelines.

## Probe MCP — Gezielte semantische Code-Suche

MCP Server `probe` läuft persistent (registriert via `claude mcp add --scope user`). 3 Tools:

| Tool | Zweck | Beispiel |
|------|-------|---------|
| `mcp__probe__search_code` | Semantische Suche in bekanntem Scope | `path: "/home/maetzger/Projects/X/src", query: "authentication handler"` |
| `mcp__probe__extract_code` | Code-Block mit AST-Kontext extrahieren | `path: "/home/maetzger/Projects/X", files: ["/path/file.py:42"]` |
| `mcp__probe__grep` | Text-Suche in Non-Code-Dateien | Für Logs, Config, Markdown |

### Wann Probe

- Gezieltes Konzept in **bekanntem Verzeichnis** suchen (`path` auf `src/`, `routes/`, `core/` einschränken)
- Exaktes Symbol mit `exact: true` finden (schneller als Grep für Code)
- Code-Block mit AST-Kontext extrahieren (`extract_code` nach `search_code`)

### Wann NICHT Probe

- **Breite Codebase-Exploration** → Explore Agent (navigiert, versteht Struktur, 2× sparsamer)
- **Repos mit verschachtelten Fremd-Repos** ohne Scope-Einschränkung → Probe matcht alles per BM25, Noise dominiert
- **Exakte Text-Patterns** (Config-Werte, Strings) → Grep (schneller, präziser)

### A/B-Test-Ergebnis (2026-03-20, MCB mit research-findings/)

| Metrik | Explore Agent | Probe (via Subagent) |
|--------|--------------|---------------------|
| Ø Tokens | **41K** | 80K |
| Ø Dauer | **76s** | 235s |
| Präzision | Nur relevante Dateien | Noise aus Fremd-Repos |
| Fazit | **Haupttool** für Exploration | **Ergänzung** für gezielte Suche |

### Probe + Explore kombinieren (Best Practice)

1. **Explore Agent** für Architektur-Überblick ("Wie ist das Projekt aufgebaut?")
2. **Probe `search_code`** mit engem `path`-Scope für gezielte Suche in bekannten Bereichen
3. **Probe `extract_code`** um gefundene Stellen mit vollem AST-Kontext zu lesen

## Anti-Patterns (VERBOTEN)

| Falsch | Richtig | Warum |
|--------|---------|-------|
| `Grep "def my_func"` | `LSP goToDefinition` auf my_func | LSP ist exakt, Grep findet auch Kommentare |
| `Grep "error handling"` (Code) | `Probe search_code "error handling"` | Probe versteht Semantik, Grep nur Text |
| `Grep "class MyClass"` | `ast-grep 'class MyClass($$$)'` | ast-grep versteht Vererbung |
| `Grep "import requests"` | `ast-grep 'import $MOD'` | ast-grep findet nur echte Imports |
| Agent(Explore) für 1-2 Dateien | Direktes Read/LSP | Agent-Overhead ~2000 Tokens |
| `Bash "grep -rn"` | Grep-Tool | Grep-Tool hat bessere UX |
| `Bash "find . -name"` | Glob-Tool | Glob ist schneller |
