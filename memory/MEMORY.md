# Auto Memory — HP ProDesk 600 G3

*Auto-generiert am 2026-04-08 12:05 aus 24 aktiven Notizen*

## KRITISCH

- **Deutsche Umlaute** (I=2.0)
  IMMER echte UTF-8-Umlaute: ä, ö, ü, Ä, Ö, Ü, ß. Gilt für ALLE Texte: HTML, Kommentare, Fließtext. NIEMALS ASCII-Ersatz (
- **Trainingsdaten nicht aktuell** (I=2.0)
  Trainingsdaten enden ca. Mai 2025, wir haben 2026. IMMER dem User vertrauen bei aktuellen Produkten/Fakten. Bei Unsicher
- **WebSearch durch httpx+trafilatura ersetzen** (I=1.9)
  User-Regel: WebSearch-Tool NIEMALS verwenden wenn httpx+trafilatura funktioniert. WebSearch nur als allerletzter Fallbac
- **Report-Renderer: Token-effizientes HTML-Template-System** (I=1.8)
  report-renderer.py nimmt JSON + Template-Typ und generiert vollständige HTML-Reports im Warm Dark Editorial Design. 5 Te
- **Self-Healing Skills System** (I=1.8)
  skill-tracker.py erweitert um Self-Healing-Engine (v2026-03-02):
- **Primacy-Effekt: Schreibreihenfolge steuert Recherche-Tiefe** (I=1.8)
  Cross-Model-Experiment (Codex GPT-5.4 + Claude Opus 4.6, März 2026) belegt: Die Formatanweisung (chronologisch vs. umgek

## Prompt Engineering

- **Prompt Engineering: 7 Goldene Regeln für gpt-oss-120b (Groq)** [#67]
  Empirisch getestete Prompt-Regeln (50+ API-Calls, Blind-Test validiert). Stärkster Hebel: Evidence-Pflicht im JSON-Schem

## Tools

- **Screenshot Annotation Tool (Playwright)** [#50]
  ~/.claude/tools/annotate-screenshot.py — Browser-basiertes Annotationstool. TECHNIK: Playwright HTML-Overlay mit SVG-Pfe

## Workflow

- **Workflow: Instagram/Video → Transkript** [#61]
  Instagram Reels (und andere Videos) transkribieren:

## Autoresearch

- **Autoresearch v2: Codex-Review + Skill-Trial Fixes** [#63]
  Autoresearch-System erweitert (2026-03-15):

## Codex

- **Codex Multi-Account Rotation** [#64]
  codex-multi.py verwaltet 3 ChatGPT Business Seats (main=matthias.kuehn@actlegal-germany.com, backup1=matze29595@gmail.co
- **Codex-Konsultation: Reihenfolge der Code-Präsentation beeinflusst Review-Fokus** [#66]
  Abgeleitet aus dem Primacy-Effekt-Experiment (März 2026): Wenn Codex Code reviewed, fokussiert es am stärksten auf den z

## Feedback

- **Audio-Transkription: IMMER Groq API statt lokal** [#60]
  Audio/Video-Transkription IMMER über Groq Cloud API (whisper-large-v3), NIE lokal auf dem Pi.

## System Setup

- **Meilisearch auf Pi 5** [#48]
  Meilisearch v1.38.0 — serverweite Suche (läuft auf HP ProDesk + Pi 5).

## Report

- **Report System: Dark/Light Toggle + Bild-Embedding** [#52]
  Seit März 2026 erweitert: 1) DARK/LIGHT TOGGLE: _base.css hat [data-theme=light] Block mit hellen Variablen. js/theme-to

## Begriffe

- **Agent System = ~/.claude Repo** [#57]
  Wenn Matthias 'Agent System' sagt, meint er das gesamte ~/.claude/ Framework: CLAUDE.md, Rules (rules/, rules-lib/), Ski

## User Feedback

- **User-Präferenzen: Qualität + Visuelle Prüfung** [#59]
  Matthias' Feedback (konsolidiert aus Workspace-Memories):

## Tools

- **Web-Search: Reddit URL Routing** [#46]
  web-search Skill erweitert (v2026-03-02):
- **Tool-Stack Web-Content** [#36]
  research-crawler.py (Bulk, IMMER statt WebFetch) > httpx+trafilatura (Einzel-URL) > httpx+selectolax (CSS-Selektoren) > 
- **Skill-Tracker** [#38]
  Zentrales SQLite-Tracking aller Skills: ~/.claude/jarvis/skill-tracker.py. Integriert in: web-search, market-check, syst

## Web Dev

- **Research-Crawler: Credibility Scoring** [#39]
  compute_quality() erweitert um Domain-Authority-Tiers (high/medium/standard) und Source-Type-Klassifikation (academic/do
- **Web-Search Skill: Query-Enrichment Phase** [#40]
  Phase 0.5 im web-search Skill ergänzt (OpenAI Instruction Builder Pattern): Query-Typ-Klassifikation (Fakten-Check, Verg

## Design

- **Design-Language Skill: v2 mit Rückfragen + Research** [#41]
  Skill komplett überarbeitet: Phase 0 mit AskUserQuestion (Seitentyp, Layout, Komponenten), kontextabhängiges Komponenten

## System

- **Session-Analyse Baseline (W09-W10 2026)** [#49]
  Baseline-Daten der automatischen Session-Analyse (session-analyzer.py).

---
*Zettelkasten CLI: `~/.claude/tools/zettel.py {add|search|get|update|evaluate|stats}`*
