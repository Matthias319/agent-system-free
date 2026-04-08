---
name: web-search
context: fork
description: "Recherchiert aktuelle öffentliche Web-Informationen (News, Preise, Specs, Vergleiche)"
triggers:
  - "recherchiere"
  - "was kostet neu"
  - "aktueller Stand"
  - "Faktencheck"
  - "Vergleich"
  - "stimmt es dass"
  - "Benchmark"
not_for:
  - "Reddit/YouTube/TikTok Meinungen"
  - "Gebrauchtpreise"
  - "Flugpreise"
delegates_to:
  - "social-research"
  - "market-check"
  - "flights"
bundle: research
---

# Kernprinzip

URL-Discovery via `fast-search.py` (Startpage, 60x schneller als native WebSearch).
Content-Extraktion via `research-crawler.py` mit --track (automatisches Skill-Tracking).

**KEIN WebFetch.** **KEIN natives WebSearch** (Ausnahmen siehe Phase 1).
Stattdessen: fast-search.py → research-crawler.py Pipe-Pattern (siehe Phase 2).

## Phase 0: End-to-End Tracking Init (1 Bash-Call, PFLICHT)

```bash
WS_RUN_ID=$(./tools/skill-tracker.py start web-search --context '{"query": "SUCHBEGRIFF", "mode": "quick|standard|deep|ultra"}')
```

Am Ende der Recherche (Phase 5):
```bash
./tools/skill-tracker.py metrics-batch $WS_RUN_ID '{"mode": "standard", "queries": 3, "urls_crawled": 15, "urls_ok": 12, "quality_avg": 7.2, "rounds": 2}' && \
./tools/skill-tracker.py complete $WS_RUN_ID
```

Dies trackt die **gesamte** Skill-Laufzeit end-to-end, nicht nur die Crawler-Batches.

## Proaktive Recherche

**Nicht auf explizite Suchanfragen warten.** Diesen Skill SELBSTSTÄNDIG einsetzen wenn:
- Eine Behauptung im Gespräch verifizierbar ist → Fakten-Check starten
- Ein Produkt/Tool erwähnt wird und Alternativen existieren könnten → Alternativen-Suche
- Eine Entscheidung ansteht und aktuelle Daten die Qualität der Antwort verbessern → recherchieren
- Trainingswissen veraltet sein könnte (Tech, Preise, Gesetze) → aktuellen Stand prüfen

**Research-Ergebnisse als Grundlage für Empfehlungen nutzen** — der Agent denkt MIT den Quellen, nicht nur ÜBER sie.

# Phase -1: Input-Prä-Check

| URL-Pattern | Aktion | Tool |
|-------------|--------|------|
| `reddit.com/r/*/comments/*` | Reddit MCP | `./tools/reddit-mcp-query.py post "URL" --comments 20` |
| `reddit.com/r/*/s/*` | Reddit MCP (Short-URL) | selbe wie oben |
| `github.com/*` | gh CLI | `gh pr view`, `gh issue view`, etc. |
| `arxiv.org/abs/*` | research-crawler.py | Direkt crawlen |

Keine spezielle URL: Weiter mit Routing.

# Ecosystem-Delegation

**VOR der eigenen Suche prüfen ob ein spezialisierter Skill besser passt.**
Wenn keiner zutrifft und keine Web-Info nötig → direkt antworten (kein Skill).

| Trigger-Keywords | Delegieren an | Begründung |
|------------------|---------------|-------------|
| Meinungen, Erfahrungen, Community, Geheimtipps, Trends, YouTube-Reviews, Reddit-Diskussion, TikTok | `/social-research` | Plattform-native Extraktion (youtube-intel.py, reddit-mcp-query.py) liefert strukturiertere Ergebnisse als Web-Crawling |
| Gebrauchtpreis, Marktwert, Kleinanzeigen, "was kostet gebraucht", Verkaufspreis | `/market-check` | market-scraper.py mit Preis-DB ist präziser als generische Suche |
| Paper, Studie, Forschung, arXiv, peer-reviewed, Meta-Analyse, Citation, DOI | `academic-search.py` | `./tools/academic-search.py "query"` durchsucht arXiv + OpenAlex gezielt |
| Flugpreise, günstig fliegen, Reiseziel | `/flights` | Spezialisierte Flug-Suche |
| API-Docs einer Library | Context7 MCP | `resolve-library-id` → `query-docs` |

**Kombination möglich:** "Was sagen Leute auf Reddit zu X?" → `/social-research` für Community-Meinungen, dann `/web-search` für Fakten-Check der Behauptungen.

# Routing

## Modus-Routing (Quick / Standard / Deep / Ultra)

**Standard ist der Default.** Jede Suche startet mindestens auf Standard-Niveau. Quick NUR für triviale Einzelfakten (Höhe Eiffelturm, Hauptstadt von X). Deep bei Vergleich, Forschung, Entscheidung. Ultra bei komplexen Multi-Aspekt-Themen wo maximale Tiefe und Breite gefragt sind.

| Modus | Wann | Queries | Sprachen | URL-Ziel | ~Tokens (in/out) | Crawl-Strategie |
|-------|------|---------|----------|----------|-------------------|-----------------|
| **Quick** | NUR triviale Einzelfakten | 1 | DE oder EN | 3-9 | ~9K in / ~1K out | `--depth quick --max-chars 6000` |
| **Standard** | **Default für alle Suchen** | 2-3 | EN+DE | 8-15 | ~45K in / ~2K out | `--max-chars 18000` (<20 URLs), Funnel (>=20 URLs) |
| **Deep** | Vergleich, Forschung, Entscheidung, Kaufberatung | 3-5 | EN+DE+CN | 20-35 | ~120K in / ~5K out | `--depth deep` + Funnel (`--funnel 500,18000 --quality-threshold 4`) |
| **Ultra** | Komplexe Multi-Aspekt-Themen, maximale Abdeckung | 5-8 | EN+DE+CN | 30-50 | ~250K in / ~8K out | `--depth ultra` + `--follow-links 15` + `--cross-ref` + Query-Expansion |

**Ultra-Modus — Wann:** Expliziter User-Wunsch ("recherchiere ausführlich", "tiefe Analyse"), oder wenn Standard/Deep die Frage nicht vollständig beantworten können. Ultra nutzt den 1M-Token-Kontext bewusst aus:
- **5-8 Queries** in 3+ Sprachen, inklusive Synonym- und Gegenposition-Queries
- **Query-Expansion** nach Runde 1: Aus den Ergebnissen neue Suchbegriffe extrahieren (siehe Phase 2.5)
- **Link-Following**: `--follow-links 15` extrahiert referenzierte URLs aus gecrawlten Seiten
- **Cross-Referencing**: `--cross-ref` für automatische Claim-Validierung über Quellen
- **Max 4 Runden** (statt 3), jede Runde mit gezielten Folge-Queries

**Max-Chars nach Modus:** Quick=6000, Standard/Deep/Ultra=18000. Bei 6K werden 73% der Seiten gekürzt, bei 18K nur 27% — kein Speed-Unterschied. **Cache:** Wiederholte URLs werden instant aus SQLite-Cache serviert (TTL: news=1h, blog=6h, docs=24h).

**URL-Ziel steuern:** Quick: `--depth quick` (8/query, 2/host, 10 target). Standard: Default (10/query, 3/host, 15 target). Deep: `--depth deep` (15/query, 4/host, 25 target). Ultra: `--depth ultra` (20/query, 5/host, 50 target). `--no-cache` erzwingt frischen Fetch.

**Eskalations-Trigger** (nach Quick-Auswertung prüfen):

| Signal in Quick-Ergebnis | Eskalation |
|--------------------------|------------|
| Quellen einig, Frage beantwortet | Keine — Abschluss |
| Quellen widersprechen sich | → Standard (2. Query für Gegenposition) |
| Expliziter Vergleich gefragt, Quick hat nur eine Seite | → Standard (Queries für beide Seiten) |
| Standard/Deep reicht nicht, Thema hat 3+ Aspekte | → Ultra (5-8 Queries, Link-Following, Cross-Ref) |
| User sagt "ausführlich", "tiefe Analyse", "alles was es gibt" | → Ultra |
| >30% Boilerplate oder <3 verwertbare Quellen | → Standard (alternative Domains, siehe Phase 3 Boilerplate-Strategie) |
| Multi-Perspektive/Forschung nötig, Standard reicht nicht | → Deep (3-5 Queries, Funnel) |

## Freshness-Weight (--freshness-weight \<WERT\>)
`FW` im Pipe-Pattern ist ein **Placeholder** — ersetze ihn durch einen Float aus dieser Tabelle:

| Query-Typ | FW | Begründung |
|-----------|-----|------------|
| AI/Tech/News | 2.0 | Wöchentlich veraltet |
| Produkt-Info | 1.5 | Monatszyklen |
| How-To | 1.0 | Stabil |
| Akademisch | 0.5 | Peer-Review ist langsam |

## Platform-Routing (NUR wenn Ecosystem-Delegation NICHT greift)

| Signal im User-Prompt | Extension laden | Warum nicht delegiert? |
|------------------------|-----------------|----------------------|
| TikTok-Snippets als Ergänzung zu Web-Suche | `Read ./skills/web-search/extensions/tiktok.md` | TikTok ist Zusatz, nicht Hauptquelle (sonst → /social-research) |
| Paper-Kontext neben Web-Quellen | `Read ./skills/web-search/extensions/academic.md` | Beiläufige Paper-Referenz, nicht dedizierte Forschung (sonst → academic-search.py) |
| GitHub, Repo, trending, open source | `Read ./skills/web-search/references/github-patterns.md` | — |
| Preis, günstig, Bestpreis, EUR, Geizhals, Specs | `Read ./skills/web-search/extensions/geizhals.md` | Neupreis/Specs, nicht Gebrauchtmarkt (sonst → /market-check) |
| "HTML-Report", "als Report", "als Bericht" | `Read ./skills/web-search/references/report-mode.md` + `Read ./skills/web-search/references/presentation-system.md` | — |

## Query-Optimierung

Aus der User-Anfrage 2-5 optimierte Suchbegriffe ableiten:

1. **Haupt-Query**: Exakte Formulierung + Jahr (2026)
2. **Synonym-Query**: Alternative Begriffe / englische Übersetzung
3. **Spezifisch-Query**: Fachbegriffe, Paper-Titel (bei Deep)
4. **Gegenposition** (nur bei Fakten-Check): Gegenteilige Behauptung

### Sprach-Routing mit Beispielen

| Kategorie | Sprachen | User-Anfrage → Queries |
|-----------|----------|------------------------|
| **Tech/AI** | EN+DE | "beste GPU 2026" → `"best GPU 2026 benchmark"`, `"beste Grafikkarte 2026 Test"` |
| **Gesetze/Lokal** | DE | "Mietpreisbremse Berlin" → `"Mietpreisbremse Berlin 2026 Regelung"`, `"Mietpreisbremse Ausnahmen Berlin"` |
| **Hardware/Specs** | EN+CN | "Raspberry Pi NVMe Speed" → `"Raspberry Pi 5 NVMe benchmark 2026"`, `"树莓派5 NVMe 速度测试"` |
| **Preise** | DE | "günstig Kopfhörer" → `"beste Kopfhörer unter 100 Euro 2026"`, `"Kopfhörer Bestpreis Geizhals"` |
| **Wissenschaft** | EN | "LLM Halluzinationen" → `"LLM hallucination mitigation 2026"`, `"reducing confabulation large language models"` |

## Spezialisierte Query-Typen

Erkennung anhand der User-Anfrage — jeder Typ hat eine eigene Query-Strategie:

### Fakten-Check
**Trigger:** "stimmt es dass", "ist es wahr", Behauptung prüfen, Mythos, Gerücht
**Strategie:** Haupt-Query für die Behauptung + Gegenposition-Query mit gegenteiliger Formulierung. Beide Seiten crawlen, Quellen-Credibility vergleichen.
```
"Kaffee dehydriert" → Q1: "does coffee dehydrate 2026 study"
                     → Q2: "coffee hydration myth debunked"
```

### Vergleich / Competitive
**Trigger:** "A vs B", "A oder B", "Unterschied zwischen", Vergleich, Alternative
**Strategie:** 3 Queries — (1) direkter Vergleich `"A vs B 2026"`, (2) Review/Test von A, (3) Review/Test von B. Antwort als strukturierte Gegenüberstellung mit Kategorien (Preis, Leistung, Ökosystem).
```
"M4 Mac Mini vs Framework Desktop" → Q1: "M4 Mac Mini vs Framework Desktop 2026"
                                    → Q2: "M4 Mac Mini review benchmark 2026"
                                    → Q3: "Framework Desktop review benchmark 2026"
```

### Decision-Support (Kaufberatung / Entscheidungshilfe)
**Trigger:** "soll ich", "lohnt sich", "welches X für Y", Empfehlung, Kaufberatung, "was nehmen"
**Strategie:** (1) Bestenliste/Ranking-Query `"best X for Y 2026"`, (2) Erfahrungsbericht-Query `"X Erfahrung Langzeit"`, (3) Preis-Leistung-Query `"X Preis-Leistung Vergleich"`. Antwort mit klarer Empfehlung + Pro/Contra-Liste.
```
"welcher 3D-Drucker für Einsteiger" → Q1: "best 3D printer beginner 2026"
                                     → Q2: "3D Drucker Einsteiger Erfahrung"
                                     → Q3: "3D Drucker unter 300 Euro Vergleich 2026"
```

### Caveat-Runde (EMPFOHLEN bei Decision-Support / Kaufberatung)

**Nach der Hauptrecherche** (Queries 1-3) und Identifikation des Top-Kandidaten: Automatisch 2 gezielte Problem-Queries starten.

**Queries:**
1. `"[Top-Kandidat] problems issues cons disadvantages"` (EN)
2. `"[Top-Kandidat] real world test long term experience"` (EN+DE: `"[Top-Kandidat] Probleme Erfahrung Langzeit"`)

**Ziel:** Herstellerversprechen mit realen Nutzererfahrungen abgleichen. Typische Findings: Firmware-Bugs, Verarbeitungsmängel, Verschleiß nach 6+ Monaten, Kompatibilitätsprobleme, versteckte Kosten (Zubehör, Abo).

**Crawl-Strategie:** Flat `--max-chars 18000`, bevorzugt Forum-/Reddit-/Erfahrungsbericht-URLs. Herstellerseiten für Caveat-Queries ignorieren (`source_type: "manufacturer"` = irrelevant für Schwächen).

**Ergebnis-Integration:**
- Findings in eigenen Abschnitt "Caveats & Einschränkungen" zusammenfassen
- Nur substanzielle Probleme aufnehmen (≥2 unabhängige Quellen oder 1 Test-Quelle mit `domain_tier: "high"`)
- Bei 0 substanziellen Problemen: Positiv vermerken ("Keine wiederkehrenden Probleme in N Quellen gefunden")
- Caveat-Findings können die Empfehlung ändern — wenn schwere Mängel auftauchen, Alternativ-Empfehlung geben

## Kreative Alternativensuche

**Lösungsraum erweitern** — nicht nur das gefragte Produkt bewerten, sondern unerwartete Alternativen aufdecken.

**Wann:** Spezifisches Produkt → Alternativen prüfen. Problem/Ziel → breiter suchen. A vs B → prüfen ob C beide schlägt.

**Query-Muster:**
1. **Kategorie-Erweiterung**: Eine Ebene höher denken (`"Stehpult" → auch "Laptop-Erhöhung"`)
2. **"Alternative zu"**: `"best alternative to X 2026"`, `"X alternative reddit"`
3. **Nischen-Discovery**: `"underrated X 2026"`, `"hidden gem X"`
4. **Cross-Category**: Eigentliches Ziel identifizieren, lateral denken

**Antwort:** Immer einen **"Außerdem interessant"**-Abschnitt anfügen wenn Alternativen gefunden. Keine → ehrlich sagen.

## Adaptive Query-Expansion (EMPFOHLEN bei Standard/Deep)

**Nach Runde 1 die Ergebnisse analysieren und Folge-Queries ableiten.** Nicht blind die gleichen Queries variieren, sondern gezielt Coverage-Lücken schließen.

### Expansions-Typen

| Lücke erkannt | Expansion-Strategie | Beispiel |
|---------------|---------------------|----------|
| **Zeitliche Lücke**: Alle Quellen >6 Monate alt | Datum-spezifische Query `"X March 2026"` oder `"X latest news"` | "RTX 5090 March 2026 review" |
| **Perspektiv-Lücke**: Nur eine Meinungsrichtung | Gegenposition-Query formulieren | "RTX 5090 problems" wenn nur Lob-Reviews |
| **Typ-Lücke**: Fehlen bestimmter Source-Types | Zielgerichtete `site:`-Query | `"site:arxiv.org"` wenn akademisch fehlt |
| **Sprach-Lücke**: Nur EN-Quellen | DE-/CN-spezifische Query | Deutsche Fachbegriffe bei lokalem Thema |
| **Tiefe-Lücke**: Oberflächliche Ergebnisse | Fachbegriff-Query mit technischen Termen | Technische Keywords statt Marketing-Sprache |
| **Widerspruch**: Quellen widersprechen sich | Verifikations-Query zum strittigen Punkt | Direkter Fachbegriff + "measurement" / "benchmark" |

### Mechanik

1. Runde 1 crawlen und Ergebnisse analysieren (Source-Types, Sprachen, Daten, Qualität)
2. Coverage-Gap-Analyse: Welche Quelltypen fehlen? Welche Perspektiven fehlen?
3. 1-3 gezielte Expansions-Queries formulieren (NICHT generisch, sondern lückenspezifisch)
4. Runde 2 crawlen, Ergebnisse mergen
5. Bei Deep: ggf. Runde 3 (max 3 Runden total, Caveat-Runde zählt nicht)

### Coverage-Check (nach jeder Runde)

```
Source-Types: ☑ review ☑ docs ☐ academic ☐ forum → Expansion: "site:arxiv.org X" + "X forum discussion"
Sprachen:    ☑ EN ☐ DE → Expansion: "X Test deutsch 2026"
Perspektive: ☑ Pro ☐ Contra → Expansion: "X problems disadvantages"
Zeitraum:    ☑ 2025 ☐ 2026 → Expansion: "X 2026 latest"
```

## Cross-Referencing (EMPFOHLEN bei Deep, optional bei Standard)

**Behauptungen über Quellen hinweg validieren.** Nicht blind der ersten Quelle vertrauen, sondern Übereinstimmungen zählen.

### Automatisch (--cross-ref Flag)

Im Deep-Modus `--cross-ref` an research-crawler.py übergeben. Der Crawler extrahiert automatisch:
- Zahlen mit Einheiten (z.B. "500 mm/s", "22h Akku")
- Prozentangaben
- Vergleichsaussagen ("X ist besser als Y")
- Bewertungen/Scores ("8.5/10")

Output: `cross_referenced_claims[]` mit Quellenzählung. Claims mit ≥3 Quellenbestätigungen sind "gesichert", 2 = "bestätigt", 1 = "Einzelquelle".

### Manuell (bei Text-Analyse)

Bei der Synthese aktiv prüfen:
1. **Kernbehauptung identifizieren** (z.B. "Akkulaufzeit 40h")
2. **Quellenanzahl zählen**: Wie viele unabhängige Quellen bestätigen das?
3. **Konfidenz zuweisen**:
   - ≥3 Quellen (unabhängig) = **Gesichert** ✓
   - 2 Quellen = **Bestätigt** (○)
   - 1 Quelle = **Einzelquelle** — explizit markieren
   - 0 Quellen, eigene Inferenz = **[Eigene Einschätzung]**
4. **Widersprüche benennen**: "Quelle A: 40h, Quelle B: 22h" → Kontext klären (Marketing vs. Test)

### Cross-Ref in der Antwort

Claims mit Konfidenz-Level kennzeichnen:
- "Die Akkulaufzeit beträgt laut unabhängigen Tests 22-25h [Q2, Q5, Q8] — der Hersteller gibt 40h an [Q1]."
- "Nur eine Quelle berichtet über Firmware-Probleme [Q7] — mit Vorsicht behandeln."

# Phase 1: URL-Discovery

**Tool: fast-search.py** (Startpage-basiert, 0.5s/Query)
```bash
# Standard (2-3 Queries)
./tools/fast-search.py "query1" "query2" "query3"

# Deep-Modus: --depth deep setzt max=15, diversity_target=25, domain_cap=4
./tools/fast-search.py --depth deep "query1" "query2" "query3" "query4" "query5"

# Ultra-Modus: maximale Abdeckung (max=20, diversity_target=50, domain_cap=5)
./tools/fast-search.py --depth ultra "query1" "query2" "query3" "query4" "query5"
```

| Preset | max/query | domain_cap | diversity_target | Typischer Use-Case |
|--------|-----------|------------|-----------------|-------------------|
| `quick` | 8 | 2 | 10 | Triviale Einzelfakten |
| `standard` | 10 | 2 | 15 | Default (kein --depth nötig) |
| `deep` | 15 | 4 | 25 | Vergleich, Forschung, Entscheidung |
| `ultra` | 20 | 5 | 50 | Tiefenanalyse, Multi-Perspektive |

Automatische Filterung: youtube, twitter, facebook, instagram, linkedin, pinterest.
Automatische Blocklist aus skill_learnings (domain_block) — siehe Self-Healing.

Für erweiterte CLI-Flags: `Read ./skills/web-search/references/tools.md`

## Wann WebSearch STATT fast-search.py

NUR für diese 2 Fälle (60x langsamer!):
- **TikTok `site:tiktok.com`-Queries**
- **Reddit `site:reddit.com`-Queries**

## Failure Recovery (0 URLs oder nur irrelevante Treffer)

| Situation | Aktion |
|-----------|--------|
| **0 URLs** von fast-search.py | 1. Query vereinfachen (weniger Terme, kein Jahr). 2. Andere Sprache versuchen (DE→EN oder umgekehrt). 3. Falls immer noch 0: User informieren — "Keine Ergebnisse für [Query]. Mögliche Ursachen: zu spezifisch, Startpage-Rate-Limit, Thema zu nischig." |
| **Nur irrelevante URLs** (alle boilerplate/error nach Crawl) | 1. Alternative Synonym-Queries formulieren. 2. Spezifischere `site:`-Suche versuchen (z.B. `site:reddit.com`, `site:stackexchange.com`). 3. Wenn 2 Runden fehlschlagen: Abbruch + User transparent informieren was versucht wurde. |
| **<3 verwertbare Quellen** nach Crawl | Warnung ausgeben: "Nur N Quellen verfügbar — Ergebnis mit Vorsicht behandeln." Trotzdem beste verfügbare Antwort geben. |

## Browser-Eskalation (Stealth Browser MCP)

Nach dem Crawl: Prüfe ob wichtige Quellen fehlgeschlagen sind (403, 503, leerer Body, JS-only).
**Nicht automatisch eskalieren** — intelligent entscheiden welche Quellen den Browser-Aufwand wert sind.

**Entscheidungslogik:**

| Kriterium | Eskalieren? | Beispiel |
|-----------|-------------|---------|
| Hochwertige Domain + passendes Snippet + keine Alternative | **Ja** | Offizielle Produkt-Doku hinter Cloudflare |
| Einzige Quelle für einen kritischen Aspekt | **Ja** | Einziger unabhängiger Benchmark-Test |
| Random Blog, Duplicate Content vorhanden | **Nein** | Blog-Repost eines vorhandenen Artikels |
| Genug andere Quellen decken das Thema ab | **Nein** | 8 gute Quellen, eine 9. geblockt |
| SPA/JS-App die httpx nicht rendern kann | **Ja, wenn relevant** | Interaktiver Preisvergleicher |

**Ablauf bei Eskalation:**
1. Identifiziere max 2-3 wertvolle fehlgeschlagene URLs aus dem Crawl-Output
2. Nutze Stealth Browser MCP: `browser_navigate` → `browser_look` (Screenshot + Snapshot)
3. Text extrahieren: `browser_evaluate("document.body.innerText")` oder `browser_get_text`
4. Bei Cookie-Walls/Consent: `browser_click_text("Akzeptieren")` → dann Content lesen
5. Ergebnisse in die Synthese einbeziehen — Quelle als "[Browser-Extraktion]" kennzeichnen

**Token-Budget:** Browser-Eskalation kostet ~800-1500 Tokens/Seite (vs. ~200-500 bei httpx). Max 2-3 Eskalationen pro Recherche. Nur wenn der erwartete Informationsgewinn den Token-Aufwand rechtfertigt.

**Nicht eskalieren wenn:** Genug Quellen (≥5 mit quality ≥6), Thema vollständig abgedeckt, fehlgeschlagene URL ist nur Duplikat.

# Phase 2: Content-Extraktion

**Pipe-Pattern (IMMER bevorzugen — 1 Bash-Call statt 3):**

**Run-ID setzen** (isoliert parallele Recherchen):
```bash
RUN_ID=$(date +%s%N | head -c13) && mkdir -p /tmp/ws-${RUN_ID}
```

```bash
# Standard-Modus
./tools/fast-search.py "query1" "query2" \
  | ./tools/research-crawler.py --max-chars 18000 --track web-search \
    --freshness-weight FW > /tmp/ws-${RUN_ID}/result.json

# Deep-Modus: --depth deep steuert automatisch domain_cap + diversity
./tools/fast-search.py --depth deep \
  "query1" "query2" "query3" "query4" "query5" \
  | ./tools/research-crawler.py --max-chars 18000 --cross-ref --track web-search \
    --freshness-weight FW > /tmp/ws-${RUN_ID}/result.json

# Ultra-Modus: Maximale Tiefe + Link-Following + Cross-Ref
./tools/fast-search.py --depth ultra \
  "q1_en" "q2_en" "q3_de" "q4_synonym" "q5_gegenposition" "q6_cn" \
  | ./tools/research-crawler.py --max-chars 18000 --cross-ref --follow-links 15 \
    --track web-search --freshness-weight FW > /tmp/ws-${RUN_ID}/result.json
```
**Stderr:** `2>` Redirects werden von fast-search.py automatisch erkannt und ignoriert. Stderr fließt ins Terminal.

**Neue Flags:**
- **`--depth quick|standard|deep|ultra`**: Steuert automatisch max/query, domain_cap und diversity_target. Ersetzt manuelle `--max --diversity-target --domain-cap` Kombination.
- **`--follow-links N`**: Extrahiert bis zu N Outbound-Links aus gecrawlten Seiten (bevorzugt high-tier Domains), crawlt sie als Zusatz-Quellen. Markiert als `"followed_link": true`. Nur Ergebnisse mit Q>=5 werden behalten.
- **`--cross-ref`**: Extrahiert faktische Behauptungen (Zahlen, Bewertungen, Vergleiche) und zählt quellenübergreifende Übereinstimmungen. Output wird zum Wrapper-Objekt: `{"sources": [...], "cross_referenced_claims": [...], "meta": {...}}`.

**Default: Flat 18000 chars** (ProDesk-Benchmark: 0% Speed-Verlust, 73%→27% weniger Kürzungen).
Quick-Modus: `--max-chars 6000`. Bei >=20 URLs: `--funnel 500,18000 --quality-threshold 4`.
**Cache:** Ergebnisse werden automatisch in SQLite gecacht (TTL nach source_type). `--no-cache` zum Erzwingen frischer Daten.

# Phase 2.5: Query-Expansion (Deep + Ultra)

**Nach Runde 1:** Ergebnisse analysieren und neue Suchbegriffe ableiten. Nicht einfach mehr vom Gleichen — sondern gezielt Lücken füllen.

**Ablauf:**
1. Runde 1 Ergebnisse lesen (`/tmp/ws-${RUN_ID}/result.json`)
2. **Entitäten extrahieren**: Produkt-/Personennamen, Fachbegriffe, Technologien die in den Quellen prominent erwähnt werden aber nicht in den Original-Queries waren
3. **Lücken identifizieren**: Fehlende Quelltypen (kein Review? kein akademisches Paper?), fehlende Perspektiven (nur Pro, kein Contra?), fehlende Sprachen
4. **2-4 Expansions-Queries formulieren**:
   - Entitäts-basiert: `"[neu entdeckter Fachbegriff] 2026"`
   - Lücken-basiert: `"site:arxiv.org [Thema]"` wenn akademische Quellen fehlen
   - Contra-basiert: `"[Top-Kandidat] problems issues"`
   - Cross-Domain: Querverweise auf verwandte Themen die in den Quellen auftauchen

**Beispiel:**
```
Runde 1: "best 3D printer 2026" → Ergebnisse nennen "Bambu Lab A1 mini" + "Klipper firmware"
Expansion-Queries:
  → "Bambu Lab A1 mini long term review 2026" (Entitäts-basiert)
  → "Klipper vs Marlin firmware comparison" (Cross-Domain)
  → "A1 mini problems issues reddit" (Contra, wenn Deep/Ultra)
  → "3D Drucker Einsteiger Erfahrung Forum" (Fehlende Sprache DE + fehlender Typ Forum)
```

# Phase 3: Analyse + Qualitätsmaximierung

Lies `/tmp/ws-${RUN_ID}/result.json`. **Format-Check:** Wenn Root ein Objekt ist (bei `--cross-ref`), analysiere `sources[]` als Quellen-Array und `cross_referenced_claims[]` separat. Wenn Root ein Array ist (ohne `--cross-ref`), direkt als Quellen-Array lesen.

```python
# Parse-Regel für --cross-ref Wrapper
data = json.load(f)
if isinstance(data, dict) and "sources" in data:
    sources = data["sources"]
    claims = data.get("cross_referenced_claims", [])
    meta = data.get("meta", {})
else:
    sources = data  # Flat Array (ohne --cross-ref)
    claims = []
```

Ignoriere `"boilerplate": true` oder `"error"` in den Sources.
Fokus auf Quellen mit `quality >= 5`. **ALLE gecrawlten URLs analysieren** — nicht nur Top-N.
Bei `--follow-links`: Ergebnisse mit `"followed_link": true` sind Sekundärquellen — nützlich für Tiefe, aber Primärquellen (aus Suchergebnissen) bei Widersprüchen bevorzugen.
Bei `--cross-ref`: Claims mit `source_count >= 3` als "gesichert" behandeln, `source_count == 2` als "bestätigt". Claims fließen in die Synthese als Vertrauensindikator ein.

## Quellenvielfalt (PFLICHT bei Standard/Deep)

Aktiv verschiedene Quelltypen ansteuern — nicht nur die ersten Google-Treffer:
- **Offizielle Docs/Hersteller** (authoritative, aber manchmal biased)
- **Unabhängige Reviews/Tests** (Fachmagazine, Benchmarks)
- **Community/Foren** (Langzeiterfahrungen, Edge Cases)
- **Akademische Quellen** (bei Forschungsthemen)

Mindestens **3 verschiedene Quelltypen** pro Standard/Deep-Suche. Bei <3 Quelltypen: Folge-Query gezielt auf fehlenden Typ ausrichten.

## Multi-Perspektive

**Nicht nur den Konsens wiedergeben.** Aktiv suchen nach:
- Gegenargumenten und Kritik
- Minderheitenmeinungen (oft in Foren, Blogs, Nischen-Reviews)
- Nuancen und Einschränkungen ("funktioniert, ABER...")
- Regionale/kontextuelle Unterschiede

Bei Vergleich/Entscheidung: Pro UND Contra für JEDE Option.

## Domänenspezifische Strategien

| Domäne | Query-Strategie | Bevorzugte Quelltypen |
|---------|----------------|----------------------|
| **Tech/AI** | Benchmarks + Changelogs + Docs | GitHub, offizielle Docs, Benchmark-Sites, HN/Reddit |
| **Consumer/Produkte** | Reviews + Specs + Preise + Langzeittests | Testmagazine, Geizhals, Foren-Erfahrungsberichte |
| **Recht/Regulierung** | Gesetzestexte + Kommentare + Urteile | Gesetze-im-Internet, juristische Kommentare, Anwaltsblogs |
| **Gesundheit/Medizin** | Studien + Leitlinien + Meta-Analysen | PubMed, WHO, Fachgesellschaften, Cochrane |
| **Finanzen** | Marktdaten + Analysten + Regulierung | Börsenseiten, BaFin, Finanztest, Fachpresse |
| **DIY/Maker** | Anleitungen + Erfahrungsberichte + Specs | Instructables, Foren, YouTube-Transcripts, Datenblätter |

## Erschöpfende Abdeckung + Auto-Eskalation

- **IMMER** mindestens 2 Queries stellen (auch bei scheinbar einfachen Fragen)
- **IMMER** auf Widersprüche zwischen Quellen prüfen
- Bei Lücken: **automatisch Folgerunde** starten (ohne User-Aufforderung)
- **Bei Decision-Support/Kaufberatung:** Nach Identifikation des Top-Kandidaten **automatisch Caveat-Runde** starten (siehe Query-Typ "Caveat-Runde"). Zählt NICHT zum 3-Runden-Limit.
- **Max 3 Runden** bei Standard/Deep, **max 4 Runden** bei Ultra. Danach Lücken transparent kommunizieren.

**Quality-Floor-Regel:** Nach dem Crawl `quality`-Werte in `/tmp/ws-${RUN_ID}/result.json` prüfen:

| Ø Quality | Aktion |
|-----------|--------|
| >= 7.0 | Weiter mit Analyse |
| 6.0 – 6.9 | Warnung: "Quellenqualität unter Optimal" — Folgerunde mit Synonym-Queries |
| < 6.0 | **Automatisch Folgerunde**: Alternative Suchbegriffe, andere Sprache (DE↔EN), `site:`-Spezifizierung auf bekannte High-Quality-Domains (arxiv.org, chip.de, anthropic.com, blog.google) |

## Marketing vs. Real-World-Daten (EMPFOHLEN bei Produkten/Tech)

**Herstellerangaben sind Marketing, keine Fakten.** Immer unabhängige Messungen bevorzugen:

| Angabe | Marketing (Hersteller) | Real-World (Tests) |
|--------|----------------------|-------------------|
| Akkulaufzeit | "bis zu 40h" | Reale Messung unter Last (oft 50-70% davon) |
| Geschwindigkeit | "bis zu 500 mm/s" | Tatsächliche Druckqualität bei Speed |
| Lautstärke | "flüsterleise" | dB-Messung unter Last |
| Kamera-MP | "108 MP" | DXOMark/Testbild-Vergleich |
| Benchmark-Scores | Cherry-picked Best Case | Multi-Benchmark-Durchschnitt |

**Regeln:**
- `source_type: "manufacturer"` im Crawl-Output = Marketing-Quelle. **Nur für offizielle Specs nutzen, nie als Qualitätsurteil.**
- `source_type: "review"` bevorzugen für Leistungsaussagen. Wenn review-Quellen (`domain_tier: "high"/"medium"`) den Herstellerangaben widersprechen → Review gewinnt. Bei `domain_tier: "standard"` Reviews kritisch prüfen (Affiliate-Bias möglich).
- Bei widersprüchlichen Angaben explizit benennen: "Hersteller gibt X an, im Test gemessen: Y"
- **Keine Herstellersprache übernehmen** ("revolutionär", "game-changer", "best-in-class") — eigene neutrale Formulierung.

## Evidence-Hierarchie (Claim-typ-basiert, PFLICHT)

**Nicht alle Quellen sind für alle Claims gleich gut.** Die richtige Quelle hängt vom Claim-Typ ab:

| Claim-Typ | Primärquelle (gewinnt) | Sekundärquelle | Tie-Breaker |
|-----------|----------------------|---------------|-------------|
| **Spezifikationen/Features** | Herstellerseite, offizielle Docs | Unabhängige Reviews/Tests | Hersteller gewinnt (er definiert die Specs) |
| **Performance/Qualität** | Unabhängige Benchmarks, Tests | Hersteller-Marketing | Review/Test gewinnt (Hersteller ist biased) |
| **Preise/Verfügbarkeit** | Preisvergleicher (Geizhals, idealo), Shops | Reviews mit Preisangabe | Aktuellstes Datum gewinnt |
| **Medizinisch/Gesundheit** | Peer-reviewed Studien, Meta-Analysen | Fachgesellschaften, WHO/RKI | Höhere Evidenzstufe gewinnt |
| **Recht/Regulierung** | Gesetzestexte, Urteile | Juristische Kommentare | Primärrecht gewinnt |

**Konkret bei Widersprüchen:**
- Review sagt "Feature X fehlt", Hersteller listet "Feature X" → **Hersteller gewinnt** (Specs sind objektiv)
- Hersteller sagt "40h Akku", Test misst "22h" → **Test gewinnt** (Marketing vs. Realität)
- Quelle A sagt "Preis 250€", Quelle B sagt "Preis 319€" → **Aktuellere Preisquelle gewinnt** + Datum nennen
- **IMMER** bei Widerspruch: Beide Positionen benennen + welche Quelle warum gewinnt

## Credibility-Gewichtung (Fallback bei gleichem Claim-Typ)

1. `domain_tier: "high"` > `"medium"` > `"standard"`
2. `source_type: "academic"/"docs"` > `"blog"` > `"forum"`
3. Bei gleichem Tier: Aktualität entscheidet (2026 > 2025)

**Boilerplate-Strategie:** Bei >30% Boilerplate-Rate: alternative Domains versuchen, `site:`-Spezifizierung nutzen, oder `--quality-threshold 5` setzen.

Sonderfall: Nur Editorial, keine Specs → Runde 2 mit `"site:geizhals.de SPECS"`.

# Phase 4: Antwort + Präsentation

## HTML-Report (Default bei Standard/Deep)

**PFLICHT:** Bei Standard- und Deep-Modus wird IMMER ein HTML-Report generiert.
Nur bei Quick-Modus (triviale Einzelfakten, 1-3 Sätze) bleibt es Text-only.

| Modus | Output |
|-------|--------|
| **Quick** | Text: 1-3 Sätze + Quelle. Keine Einleitung, direkt die Antwort. |
| **Standard** | **HTML-Report** via `report-renderer.py` + kurze Text-Zusammenfassung (2-3 Sätze) |
| **Deep** | **HTML-Report** via `report-renderer.py` + TL;DR (2-3 Sätze) |

### Report-Generierung (Standard + Deep)

1. Recherche-Ergebnisse als kompaktes JSON aufbereiten (Compact-Aliases nutzen: `t`, `s`, `hl`, `sx`, `src`)
2. JSON nach `/tmp/research-data.json` schreiben
3. Report generieren:
```bash
./tools/report-renderer.py render auto /tmp/research-data.json -o ~/shared/reports/TOPIC-$(date +%Y-%m-%d).html
```
4. User den Report-Link mitteilen

### Renderer-Patterns nach Recherche-Typ

Der Renderer unterstützt erweiterte Content-Patterns — nutze die passenden JSON-Keys je nach Recherche:

| Recherche-Typ | Renderer-Pattern | JSON-Keys |
|---|---|---|
| Research mit Quellen | Citation Trust-Levels | `sources[]` mit `trust_level`, `type`. Inline: `[Q1]` im Body |
| Preisrecherche | Price Cards | `price_cards[]` statt Preise als Fließtext |
| Feature-Vergleich | Comparison Table | `table.variant="comparison"` + `highlight_col` |
| Handlungsempfehlung | CTA Cards | `cta[]` mit `icon`, `description`, `variant` |
| How-To / Anleitung | Guide Cards | `guides[]` mit `steps[{text, code}]` |

**Keine manuellen HTML-Snippets** — der Renderer generiert die Patterns automatisch aus den JSON-Keys.
Vollständige Pattern-Doku: `Read ./skills/web-search/references/presentation-system.md` → Sektion "Verfügbare Report-Patterns".

Report-Modus-Details: `Read ./skills/web-search/references/report-mode.md`

## Text-Antwort (nur Quick-Modus)

| Modus | Antwort-Format |
|-------|---------------|
| **Quick** | 1-3 Sätze + Quelle. Keine Einleitung, direkt die Antwort. |

### Presentation-Routing (automatisch)

Bei HTML-Reports das passende Präsentations-Pattern wählen:
`Read ./skills/web-search/references/presentation-system.md`

| Content-Signal | Pattern |
|---|---|
| Produkte, Preise, Vergleich, Specs | **Product Presentation** (Hero + Tabs + Idealo) |
| Analyse, Forschung, Fakten, multi-source | **Deep Research** (Verified + Pull Quotes + Key Facts) |
| Orte, Restaurants, Routen, Maps | **Lokal-Guide** (Action Cards + Route Banner) |
| Gemischt | **Hybrid** — primäres Pattern + Komponenten des sekundären |

**Kernregel: Kein reiner Fließtext.** Jeder Report braucht mindestens:
- 1 Pull Quote ODER Key-Fact Callout (visuelle Anker)
- Verified-Badge wenn Verifikations-Agent gelaufen ist
- Scroll-Reveal Animationen auf Sektionen
- Light + Dark Mode Support

**Quellen-Regel**: Immer URLs der Top-5+ Quellen nennen. Min. 3 Quellen zitieren.

## Vollständigkeits-Check (vor Antwort prüfen)

Jeder Query-Typ hat Pflicht-Elemente. **Fehlende Elemente → ergänzen oder explizit begründen warum nicht möglich.**

| Query-Typ | Pflicht-Elemente |
|-----------|-----------------|
| **Fakten-Check** | Urteil (wahr/teilweise wahr/falsch) + Konfidenz-Einordnung, ≥2 Kernbelege mit `[Qx]`, Gegenposition oder Nuancen-Abschnitt, Ursprung des Mythos/der Behauptung (falls identifizierbar) |
| **Decision-Support** | TL;DR-Empfehlung (2-3 Sätze), Top-3 mit Specs-Tabelle + Pro/Contra je Option, Entscheidungsbaum (`Budget < X? → Y`), `Für wen`-Einordnung pro Empfehlung, **Caveats & Einschränkungen** des Top-Kandidaten (aus Caveat-Runde, ≥2 unabhängige Quellen pro Caveat) |
| **Vergleich** | Gegenüberstellungs-Tabelle (≥3 Kriterien), Gewinner pro Kategorie, Nuancen/Kontextabhängigkeit (`kommt drauf an ob...`) |
| **Tech/Wissenschaft** | Aktualitäts-Vermerk (Datum der Quellen), Einordnung in Forschungsstand, Code-Beispiele/Specs wenn relevant |

## Synthese-Verifikation (PFLICHT bei Analyse/Deep)

### Zitationsformat + Ablauf (PFLICHT)
1. Vergib beim Lesen jeder genutzten Quelle eine ID: `[Q1]`, `[Q2]`, `[Q3]` ...
2. Hänge an jede quellenbasierte Tatsachenbehauptung mindestens eine ID an: `... [Q2]`.
3. Markiere Schlussfolgerungen ohne direkte Quelle mit dem Suffix `[Eigene Inferenz]`.
4. Wenn Daten fehlen oder widersprüchlich bleiben, schreibe explizit: `Hierzu lieferten die Quellen keine belastbaren Daten.`
5. Schließe jede Antwort mit einem Block `Quellen` ab:
   - `[Q1] Titel | Domain | Datum (falls vorhanden) | URL`
   - `[Q2] Titel | Domain | Datum (falls vorhanden) | URL`

**Mindeststandard Fakten-Check:** Urteil (`wahr` / `teilweise wahr` / `falsch`) + 2 Kernbelege mit `[Qx]` + 1 Gegenbeleg oder Unsicherheits-Hinweis mit `[Qx]`.

# Phase 5: Tracking + Self-Healing

## Self-Healing (`--track` in Phase 2 aktiviert automatisches Tracking)

Domain mit >=3 Fehlschlägen → automatisches `domain_block`-Learning. fast-search.py filtert geblockte Domains automatisch.

| Aktion | Befehl |
|--------|--------|
| Auto-Learn triggern | `./tools/skill-tracker.py auto-learn web-search` |
| Quality-Drop diagnostizieren | `./tools/skill-tracker.py heal web-search` |
| Bestehende Learnings prüfen | `./tools/skill-tracker.py learnings web-search` |

Nur noch Temp-Files aufräumen:
```bash
rm -rf /tmp/ws-${RUN_ID}
```

**Metriken-Output** (kurz, am Ende):
```
Quellen: XX URLs (XX ok / XX fail) | Q X.X/10 | X Sprachen | X Runde(n)
```