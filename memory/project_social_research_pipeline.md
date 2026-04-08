---
name: Social Research Pipeline — Groq-basiert
description: social-research-runner.py ersetzt Opus-Subagents durch Python+Groq Pipeline (22s statt 233s, 7/7 Qualität)
type: project
---

Social-Research-Pipeline von Opus-Subagents auf Python+Groq umgebaut (2026-04-07).

**Architektur:** `~/.claude/tools/social-research-runner.py`
1. YouTube search (yt-dlp, 8 Videos)
2. Groq GPT-OSS 120B Enrichment (~1s) — extrahiert Marken/Produkte aus Video-Metadaten
3. Parallel: Reddit (MCP) + YouTube deep-dive (Transcripts + Comments für Top-4-Videos)
4. Multi-Round: GPT-OSS 120B Gap-Analyse → Follow-Up-Queries → Runde 2-3
5. Finale Synthese: GPT-OSS 120B (131K Context, ~3s)

**Ergebnisse (A/B-Test):**
- Opus: 216s, $0.75, 61K Tokens — tiefere Analyse (MoE/Dense Tiers, Preise, Kontroversen)
- Groq v3: 22s, $0.008, ~5K Groq-Tokens — 7/7 Qualitätsmarker, Opus-Niveau

**Schlüssel-Insight:** 80% von Opus' Qualitätsvorsprung kam aus YouTube-Comments, nicht Synthese.

**Fixes in dieser Session:**
- Reddit MCP: `subreddit` (String) → `subreddits` (Array) — Filter war komplett kaputt
- YouTube-Comments: Deep-Dive holt jetzt Comments für Top-4-Videos parallel
- Synthese-Prompt: Tier-System, Preise, Kontroversen, YT-Comment-Zitate explizit angefordert
- Hardcaps: reddit (3 posts, 10 comments), youtube (8 search, 3 pipeline videos)
- End-to-end Tracking: web-search Skill hat jetzt skill-tracker start/complete
- YouTube Rate-Limit: von 10 auf 20/min erhöht

**Offene Codex-Fixes (delegiert an Worker-Session):**
- Fix 1: Enrichment entity_terms vs reviewer_terms trennen
- Fix 2: Gap-Analyse mit Comment-Snippets statt nur Titeln
- Fix 3: 2 parallele Follow-Up-Queries pro Runde
- Fix 4-6: Evidence-Ledger, Reddit-Comments strukturiert, Groq-Parameter

**Why:** Opus-Subagent-Overhead war 96% LLM-Inferenz, nur 4% Tool-Execution. Groq auf LPU ist 10x schneller für die gleiche Aufgabe.

**How to apply:** Bei social-research Tasks den Runner mit `--rounds 2 --synthesize` verwenden. Für maximale Qualität `--rounds 3`. Opus-Subagent nur noch für Edge-Cases ohne YouTube/Reddit-Coverage.
