---
name: social-research
context: fork
description: "Strukturierte Recherche über Reddit, YouTube und TikTok mit dedizierten Plattform-Extraktoren"
triggers:
  - "was sagen Leute"
  - "Meinungen"
  - "Erfahrungen"
  - "Community"
  - "Reddit"
  - "YouTube"
  - "TikTok"
  - "Geheimtipps"
  - "Trends"
  - "Reviews"
not_for:
  - "faktische Web-Recherche mit offiziellen Quellen"
  - "Gebrauchtpreise"
delegates_to:
  - "web-search"
bundle: research
---

# Social Research — YouTube + Reddit + TikTok Intelligence

Unified entry point for platform-based research. Combines YouTube expert knowledge, Reddit community opinions and TikTok urban discoveries with supplementary web context.

## Modes

| Modus | Reihenfolge | Use-Case | Beispiel |
|-------|-------------|----------|----------|
| **Tech/AI** | **YouTube first → Reddit enriched** (→ optional TikTok) | Dev-Meinungen, Tool-Vergleiche, Erfahrungsberichte, Tutorials | "Was denken Devs über Cursor vs Claude Code?" |
| **Urban/Social** | TikTok primär, Reddit sekundär (YouTube selten relevant) | Restaurants, Aktivitäten, Geheimtipps, Reiseziele | "Beste Restaurants in Lissabon?" |

### Warum YouTube-first bei Tech/AI

Cross-Reference-Tests belegen: YouTube-Titel und -Beschreibungen enthalten Fachterminologie (z.B. "tool search", "programmatic calling", "token overhead"), die generische Reddit-Suchen um **3× mehr relevante Treffer** enrichen. Ohne YouTube-Enrichment findet Reddit ~25% Relevanz; mit Enrichment ~70%+.

## Phase 0: Self-Healing + Tracking Init (1 Bash-Call)

```bash
RUN_ID=$(./tools/skill-tracker.py start social-research --context '{"query": "SUCHBEGRIFF", "platform": "youtube+reddit|tiktok+reddit|all"}') && \
./tools/skill-tracker.py heal social-research
```

## FAST PATH: social-research-runner.py (BEVORZUGT für Tech/AI)

Für Tech/AI-Recherchen den Runner verwenden — **1 Tool-Call statt 4-6 sequentielle Phasen**:

```bash
./tools/social-research-runner.py tech "QUERY" [--subreddits sub1+sub2] > /tmp/evidence.json
```

Der Runner führt parallel aus: YouTube search + Enrichment-Extraktion + Reddit research + YouTube-Transkripte.
Output: JSON evidence pack. Danach direkt zu **Phase 4: Synthesis** springen.

**Wann den FAST PATH nutzen:** Tech/AI-Queries ohne TikTok-Bedarf.
**Wann den klassischen Pfad (Phase 1-3) nutzen:** Urban/Social-Queries mit TikTok, oder wenn explizit einzelne Plattformen angefragt werden.

## Phase 1: Query Routing (nur wenn NICHT der Fast Path)

```
User-Query
  ├─ Explizit "Reddit" → Reddit-only (Phase 2a)
  ├─ Explizit "TikTok" → TikTok-only, Deep: 6-7 Queries (Phase 2b)
  ├─ Explizit "YouTube" → YouTube-only (Phase 2c)
  ├─ Tech/AI Keywords → YouTube first → Reddit enriched (Phase 2c → 2a)
  ├─ Urban/Lokal Keywords → TikTok primär, Reddit sekundär (Phase 2b → optional 2a)
  └─ Unklar → YouTube + Reddit + TikTok (Phase 2c → 2a + 2b)
```

### Keyword-Listen

**Tech/AI** (→ YouTube first, Reddit enriched):
`programming`, `code`, `developer`, `framework`, `library`, `API`, `tool`, `IDE`,
`AI`, `LLM`, `model`, `benchmark`, `self-hosted`, `open source`, `vergleich`,
`vs`, `alternative`, `Erfahrung mit`, `was nutzt ihr`, `was denken Devs`,
`MCP`, `agent`, `tutorial`, `how to`, `best practices`, `pitfalls`

**Urban/Social** (→ TikTok primär):
`Restaurant`, `Café`, `Bar`, `Club`, `Geheimtipp`, `hidden gem`, `Stadtteil`,
`Reise`, `Urlaub`, `Aktivität`, `was machen in`, `beste`, `empfehlung`,
`food`, `nightlife`, `sehenswürdig`, `underground`, `trending`, `angesagt`

## Phase 2c: YouTube Research (Tech/AI Mode: FIRST)

Im Tech/AI-Mode läuft YouTube **vor** Reddit. Die extrahierten Konzepte aus YouTube-Titeln und -Beschreibungen enrichen die nachfolgenden Reddit-Queries.

### Step 1: Search

```bash
./tools/youtube-intel.py search "QUERY" --max 10
```

Liefert JSON-Array mit `id`, `title`, `url`, `channel`, `views`, `duration`, `description`.

### Step 2: Enrichment extrahieren

Aus den Top-5-Titeln und -Beschreibungen **Fachbegriffe, Tool-Namen, Konzepte** sammeln, die in der ursprünglichen Query nicht vorkamen. Diese Begriffe werden in Phase 2a als enriched Reddit-Queries verwendet.

Beispiel: Query "MCP best practices" → YouTube findet "tool search", "programmatic calling", "token overhead" → Reddit-Query wird "MCP token overhead tool search optimization".

### Step 3: Transcript Deep-Dive (max 2 Transkripte, deterministisch)

Transkripte nur für Videos die ALLE Kriterien erfüllen:
- Tutorial, Deep-Dive oder Erklärung (nicht News/Reaction/Vlog)
- >50K Views ODER exakt passender Titel
- Titel + Beschreibung beantworten die Frage NICHT bereits

```bash
./tools/youtube-intel.py transcript VIDEO_ID [--lang en,de]
```

**Hardcap: Max 2 Transkripte pro Recherche.** Tooling enforced (MAX_PIPELINE_VIDEOS=3, yt-dlp-Limit).

### Step 4: Comments (OPTIONAL)

```bash
./tools/youtube-intel.py comments VIDEO_ID --max 15
```

Kommentare lohnen sich bei kontroversen Themen oder wenn Community-Feedback zum Video-Inhalt relevant ist. Likes sind yt-dlp-bedingt oft 0 — Text-Content ist trotzdem brauchbar.

## Phase 2a: Reddit Research (Tech/AI Mode: SECOND, mit enriched Queries)

Im Tech/AI-Mode: Reddit-Queries mit Fachbegriffen aus Phase 2c anreichern.

### Research (BEVORZUGT — ein Aufruf statt N+1)

```bash
./tools/reddit-mcp-query.py research "ENRICHED_QUERY" \
  --subreddits SUBS --top-posts 3 --comments 15
```

Der `research`-Befehl kombiniert Search + Post-Deep-Dive in **einem einzigen Tool-Call**:
- Sucht Posts, sortiert nach Score
- Holt automatisch Details + Comments für die Top-N Posts
- Hält eine persistente MCP-Verbindung (kein npx-Restart pro Call)
- Gibt strukturiertes JSON zurück mit allen Posts + Comments

**Subreddit-Auswahl nach Query-Typ:**

| Typ | Subreddits |
|-----|-----------|
| Tool-Vergleich / IDE | `programming+webdev+ExperiencedDevs+vscode+neovim` |
| AI / LLM | `MachineLearning+LocalLLaMA+artificial+ChatGPT` |
| Self-Hosted / Infra | `selfhosted+homelab+linux+sysadmin` |
| Reise / Stadt | `travel+solotravel+digitalnomad+germany+europe` |
| Essen / Lifestyle | `FoodPorn+AskCulinary+STADT_subreddit` |

### Fallback: Einzelne Calls (nur wenn research nicht reicht)

```bash
./tools/reddit-mcp-query.py search "QUERY" --subreddits SUBS --limit 10
./tools/reddit-mcp-query.py post "URL" --comments 20
```

**Sentiment-Extraktion:**
- Konsens vs. Kontroverse identifizieren
- Upvote-gewichtete Meinungen priorisieren
- Wiederkehrende Empfehlungen/Warnungen extrahieren
- Spezifische Erfahrungsberichte zitieren

## Phase 2b: TikTok Research

TikTok-Content ist nur über WebSearch mit `site:tiktok.com` erreichbar (fast-search.py kann TikTok nicht zuverlässig finden).

### Query-Patterns

| ID | Pattern | Beispiel |
|----|---------|----------|
| T1 | `site:tiktok.com <DE Thema> <Stadt> [geheimtipps\|empfehlung\|beste] 2026` | `site:tiktok.com restaurants frankfurt geheimtipps 2026` |
| T2 | `site:tiktok.com/discover <EN Thema> <Stadt>` | `site:tiktok.com/discover best restaurants frankfurt` |
| T3 | `tiktok <EN Thema> <Stadt> best hidden gems` | `tiktok restaurants frankfurt best hidden gems` |
| T4 | `site:tiktok.com <Stadt> <Stadtteil1> <Stadtteil2> <Stadtteil3> <Thema>` | `site:tiktok.com frankfurt nordend bornheim sachsenhausen food` |

### Query-Anzahl nach Stadtgröße

| Stadtgröße | Queries | Beispiele |
|------------|---------|-----------|
| Groß (>500K) | 4-7 | Berlin, München, Hamburg, Frankfurt, Köln |
| Mittel (100K-500K) | 3 | Heidelberg, Darmstadt, Freiburg |
| Klein (<100K) | 2 | Marburg, Tübingen |

**Deep-Modus** (explizit "TikTok" im Prompt): Immer 6-7 Queries, unabhängig von Stadtgröße.

### Overlap-Scoring

Entitäten (Restaurants, Orte, Aktivitäten) die in **3+ Queries** auftauchen = Top-Empfehlungen.
Entitäten in 2 Queries = solide Empfehlungen. Einzelnennungen = erwähnenswert aber ohne Bestätigung.

### Stadtteil-Referenz (für T4-Pattern)

| Stadt | Stadtteile |
|-------|-----------|
| Berlin | Kreuzberg, Neukölln, Friedrichshain, Prenzlauer Berg, Mitte, Charlottenburg, Schöneberg, Wedding |
| München | Schwabing, Glockenbachviertel, Haidhausen, Maxvorstadt, Sendling, Isarvorstadt |
| Frankfurt | Nordend, Bornheim, Sachsenhausen, Bahnhofsviertel, Bockenheim, Westend, Ostend |
| Hamburg | Schanzenviertel, St. Pauli, Ottensen, Eimsbüttel, St. Georg, Winterhude, Barmbek |
| Köln | Ehrenfeld, Belgisches Viertel, Südstadt, Nippes, Deutz, Agnesviertel |
| Heidelberg | Altstadt, Weststadt, Neuenheim, Handschuhsheim, Bergheim |
| Darmstadt | Martinsviertel, Bessungen, Johannesviertel, Paulusviertel |

## Phase 3: Web Context (deterministisch — NICHT optional entscheiden)

Ergänzende Artikel/Blogs über fast-search.py + research-crawler.py:

```bash
./tools/fast-search.py "QUERY best 2026" "QUERY erfahrung 2026" \
  | ./tools/research-crawler.py --max-chars 18000 > /tmp/web-context.json
```

**Deterministisches Routing (KEIN extra LLM-Turn zum "Entscheiden ob nötig"):**
- Verwertbare Quellen aus Phase 2a+2c < 3 → **Web-Context PFLICHT**
- User hat "ausführlich", "vollständig", "deep" gesagt → **Web-Context PFLICHT**
- Sonst → **Web-Context ÜBERSPRINGEN** (direkt zu Phase 4)

## Phase 4: Synthesis

Alle Quellen zusammenführen:

1. **YouTube-Wissen**: Was erklären Experten? Welche Architektur/Patterns werden gezeigt?
2. **Reddit-Konsens**: Was sagt die Community? Wo gibt es Einigkeit/Streit?
3. **TikTok-Discoveries**: Welche Orte/Trends tauchen auf? Overlap-Score?
4. **Web-Context**: Fakten, Details, Aktualität
5. **Bewertung**: Eigene Einschätzung basierend auf Quellenlage — **explizit als "Eigene Einschätzung" kennzeichnen**

### Synthese-Verifikation (PFLICHT)

Jede faktische Aussage muss einer Plattform-Quelle zugeordnet werden:

| Typ | Kennzeichnung |
|-----|--------------|
| **YouTube-gestützt** | "(YouTube: @Channel / Videotitel)" |
| **Reddit-gestützt** | "(Reddit: r/subreddit, Ø X Upvotes)" |
| **TikTok-gestützt** | "(TikTok: Overlap X/Y Queries)" |
| **Web-gestützt** | "(Quelle: domain.com)" |
| **Eigene Inferenz** | "[Eigene Einschätzung]" |
| **Unbelegt** | "Hierzu lieferten die Quellen keine Daten." |

Keine faktische Behauptung ohne Quellenzuordnung. Bei Widersprüchen zwischen Plattformen: beide Positionen benennen.

### Output-Format

**Tech/AI Mode**: Strukturierte Vergleichstabelle + YouTube-Expertenwissen + Community-Sentiment + Empfehlung
**Urban/Social Mode**: Rangliste mit Overlap-Score + Stadtteil-Zuordnung + Insider-Tipps

## Phase 5: Tracking + Self-Heal (1 Bash-Call)

```bash
./tools/skill-tracker.py metrics-batch $RUN_ID '{
  "platform": "youtube+reddit|tiktok+reddit|all",
  "youtube_videos": 10,
  "youtube_transcripts": 2,
  "youtube_comments": 15,
  "reddit_posts": 5,
  "reddit_comments": 47,
  "tiktok_results": 12,
  "web_results": 8,
  "quality_avg": 7.8,
  "freshness_avg_days": 14
}' && \
./tools/skill-tracker.py complete $RUN_ID && \
./tools/skill-tracker.py auto-learn 2>&1 | tail -3
```

## Token Budget

### Tech/AI Mode (YouTube + Reddit)

| Phase | Calls | Tokens |
|-------|-------|--------|
| YouTube search (2c) | 1 | ~1,500 |
| YouTube transcripts (2c, 0-3) | 0-3 | ~0-15,000 |
| YouTube comments (2c, optional) | 0-2 | ~0-3,000 |
| Reddit research (2a, batch) | **1** | ~8,000-20,000 |
| Web context (optional) | 2 | ~10,000 |
| **Total** | **3-9** | **~10,000-48,000** |

### Urban/Social Mode (TikTok + Reddit)

| Phase | Calls | Tokens |
|-------|-------|--------|
| TikTok WebSearch (2b, 4-7) | 2-4 | ~3,000 |
| Reddit research (2a, batch) | **1** | ~8,000-20,000 |
| Web context (optional) | 2 | ~10,000 |
| **Total** | **5-9** | **~20,000-30,000** |

## Anti-Patterns

- **NIE** reddit-mcp-query.py `search` + mehrfach `post` wenn `research` reicht (verschwendet Inference-Roundtrips)
- **NIE** TikTok über fast-search.py (Startpage findet TikTok nicht zuverlässig) → WebSearch
- **NIE** nur eine Plattform wenn "both" geroutet wurde
- **NIE** Synthesis ohne Quellenangabe (welcher Reddit-Thread, welches YouTube-Video, welches TikTok)
- **NIE** im Tech/AI-Mode Reddit VOR YouTube abfragen (YouTube-Enrichment geht sonst verloren)
- **NIE** youtube-intel.py pipeline verwenden (zu viel Budget auf einmal; lieber search + selektiv transcript/comments)
- **IMMER** Overlap-Scoring bei TikTok Urban-Recherche
- **IMMER** Sentiment-Extraktion bei Reddit Tech-Recherche
- **IMMER** YouTube-Konzepte als Enrichment für Reddit-Queries im Tech/AI-Mode nutzen
