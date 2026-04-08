# Output Rules (on-demand geladen via Rules Router)

## Edit vs Write

| Situation | Tool |
|-----------|------|
| Wenige Zeilen ändern | `Edit` |
| Variable umbenennen (ganzes File) | `Edit` mit `replace_all: true` |
| Mehr als 50% des Files neu | `Write` (komplett überschreiben) |
| Neues File erstellen | `Write` |
| File existiert, < 30% Änderung | `Edit` (spart Tokens — nur Diff) |

## Report-Renderer — Systemweite HTML-Report-Generierung

Für HTML-Reports: `~/.claude/tools/report-renderer.py`
Agent liefert kompaktes JSON → Renderer baut vollständige HTML im "Warm Dark Editorial" Design.

**IMMER** wenn ein HTML-Report generiert wird.

**Ausnahmen** (haben eigene integrierte Templates):
- `/market-check` → `market-scraper.py --html` (Template im Scraper)
- `/price-track` → `price-track.py html` (eigenes Template)

### Quick Reference

```bash
~/.claude/tools/report-renderer.py render TYPE data.json -o ~/shared/reports/NAME.html
~/.claude/tools/report-renderer.py schema TYPE
~/.claude/tools/report-renderer.py list
```

`TYPE=auto` → Erkennt Template automatisch aus JSON-Struktur.

### Template-Auswahl — Pattern-First Routing (PFLICHT)

**Erst Pattern bestimmen, dann Renderer-Typ ableiten. NIE direkt Template wählen.**

#### Schritt 1: Pattern bestimmen

| Content-Signal | Pattern |
|----------------|---------|
| Produkte, Preise, Specs, Kaufberatung, Deals, "welches X" | **Product Presentation** |
| Analyse, Multi-Source, Community, Faktencheck, Widersprüche | **Deep Research** |
| Orte, Adressen, Routen, Maps, "wo gibt es" | **Lokal-Guide** |
| Produkt + Analyse zusammen (Kaufberatung mit Recherche) | **Hybrid Product + Deep** |

#### Schritt 2: Pattern → Renderer-Typ

| Pattern | Renderer-Typ | Warum |
|---------|-------------|-------|
| **Lokal-Guide** | `lokal-guide` | Eigenes Template mit Action Cards, Maps |
| **Pure Produkt-Gegenüberstellung** (options[] als Hauptstruktur) | `comparison` | Einfaches A-vs-B Layout |
| **Kaufberatung / Deals / Product+Research Hybrid** | `deep-research-v2` | Hat PRICE_CARDS, CTA, TABLE, SOURCE_BARS, Pull Quotes |
| **Deep Research** (Analyse, Faktencheck) | `deep-research-v2` | Pull Quotes, Key-Facts, Verified Badge |
| **Einfaches text-lastiges Briefing** (kein Produkt, kein Lokal) | `research` | Nur Fließtext + Quellen |
| **KPI-Dashboard** | `dashboard` | Stat-Cards dominant |
| **Anleitung / How-To** | `guide` | Nummerierte Schritte |

**⚠ `research` ist der SIMPLSTE Typ — nur für reine Text-Briefings ohne Produkte/Preise/Deals.**

#### Schritt 3: Visuelle Elemente via JSON-Keys

Für `deep-research-v2` diese Keys nutzen (Renderer generiert automatisch):

| Element | JSON-Key | Wann einsetzen |
|---------|----------|----------------|
| Pull Quotes | `pullquotes: [{text, cite}]` | PFLICHT: min. 1 pro Report |
| Key-Fact Callouts | `keyfacts: [{number, label, text}]` | PFLICHT: min. 2 (große Kupfer-Zahlen) |
| Verified Badge | `verified: {links_checked, facts_confirmed}` | Nach Verifikation |
| Confidence Gauge | `confidence_gauge: {value, label}` | Bei Analyse |
| Source Quality Bars | `source_bars: [{title, quality}]` | Bei >3 Quellen |
| Conflict Boxes | `conflicts: [{title, body}]` | Bei Quellen-Widersprüchen |
| Kernaussage | `kernaussage: "..."` | Fazit am Ende |
| Price Cards | `price_cards: [{name, price, trend}]` | Bei Preisvergleich |
| CTA Cards | `cta: [{label, url, icon, variant}]` | Handlungsempfehlungen |
| Comparison Table | `table: {variant: "comparison", highlight_col}` | Feature-Vergleich |

**Vollständige Komponenten-Doku + JSON-Beispiele:**
`Read ~/.claude/skills/web-search/references/presentation-system.md`

### Section-Hierarchie (research Template)

| Feld | Wirkung |
|------|---------|
| `level: "part"` | Teil-Header (h2, accent-Linie, visuelle Trennung) |
| `badge: "Text"` | Farbiges Badge am Titel (auto: grün/gelb/rot/accent) |
| `callout: "warn"\|"tip"` | Farbige Callout-Box um den Body |
| `collapsed: true` | Collapsible `<details>` statt offener Block |
| `confidence: "high"\|"medium"\|"inferred"` | Quellenvertrauens-Indikator am Titel (grün/gelb/grau) |
| `items: [...]` | Bullet-Liste unter dem Body |

Sections nach `level: "part"` → automatisch h3 (Sub-Sections mit Border-Indent). Ohne Part → h2.

**Badge-Farben:** Grün (stark/hoch/robust) | Gelb (gemischt/moderat/schwach) | Rot (negativ/gescheitert) | Accent (default)

### JSON-Minimum (Beispiel: research)

```json
{
  "title": "Titel des Reports",
  "subtitle": "Untertitel oder Datum",
  "highlights": ["Kernaussage 1", "Kernaussage 2"],
  "sections": [
    {"heading": "Teil I", "level": "part", "body": "Einleitung"},
    {"heading": "Unterpunkt", "badge": "Stark", "body": "Details..."}
  ],
  "sources": [{"title": "Quelle", "url": "https://...", "quality": 85}]
}
```

Optionale Felder: `kpis`, `bars`, `table`, `agent_analysis`, `metrics`.

### Compact JSON Aliases (Token-Sparer)

Der Renderer expandiert kurze Keys automatisch via `_expand_aliases()`. Full-Keys haben Vorrang bei Konflikten.

| Alias | Expandiert zu | Alias | Expandiert zu |
|-------|---------------|-------|---------------|
| `t` | `title` | `s` | `subtitle` |
| `hl` | `highlights` | `sx` | `sections` |
| `src` | `sources` | `hd` | `heading` |
| `bd` | `body` | `q` | `quality` |
| `u` | `url` | `n` | `note` |
| `v` | `value` | `l` | `label` |

Beispiel: `{"t": "Report", "sx": [{"hd": "Intro", "bd": "Text"}]}` → spart ~40% JSON-Tokens.

### Architektur: _base.html Shell

Templates bestehen aus 2 Ebenen:
- **`_base.html`**: HTML-Shell mit `{{TITLE}}`, `{{SUBTITLE}}`, `{{CSS}}`, `{{HEAD_EXTRA}}`, `{{BODY_SLOTS}}`
- **`research.html` etc.**: Nur Body-Slot-Reihenfolge (`{{HIGHLIGHTS}}\n{{KPI_CARDS}}\n{{SECTIONS}}...`)
- **Custom CSS**: `<!-- HEAD_EXTRA: body { --max-w: 900px; } -->` im Template-File

### Workflow

**Erstmaliger Report:**
1. JSON strukturieren (Schema: `schema TYPE`) → `/tmp/report-data.json`
2. `render TYPE data.json -o ~/shared/reports/NAME.html`
3. Temp aufräumen

**Iterative Erweiterung (ab 2. Runde) — KEIN Komplett-Rebuild:**
1. HTML-Struktur prüfen: Welche Sections/Parts existieren bereits?
2. Edit-Tool: neuen `<div class="part-group">` vor `</body>` einfügen
3. Highlights (`.highlights`, max 5), KPIs (`.stat-grid`, max 6), Quellen, Fazit aktualisieren

**Token-Ersparnis:** ~400 Tok JSON → ~20KB HTML (94%). Iteratives Patch: ~300-600 statt ~2.500-4.000 (85%).

## Git-Diffs

`diff -u` = 1.498 chars vs `difft --display inline` = 1.154 chars (23% weniger),
aber `difft` default (side-by-side) = 2.861 chars (91% MEHR).

**Für AI-Agents:** Standard `git diff` (unified format) bleibt am token-effizientesten.
**difft** (`/usr/local/bin/difft`) ist installiert für manuelles Review durch Matthias.

## Shell-Utilities

| Tool | Statt | Vorteil |
|------|-------|---------|
| `jq` | `python3 -c "import json..."` | Instant, weniger Tokens |
| `hyperfine` | `time command` | Statistik, Warmup, Vergleiche |
| `batcat` | `cat` | Syntax-Highlighting (nur manuell relevant) |
| `eza --tree` | `find`/`tree` | Kompakteres Output, Git-aware |
