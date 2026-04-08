---
name: Autoresearch Codex-Integration Status
description: Stand der Codex-Review und Codex-Verify Integration im autoresearch-Loop (Iter 5+)
type: project
---

Codex ist als Review- und Verify-Agent in autoresearch.py integriert (seit 2026-03-15, Iter 5).

**Implementiert:**
- codex-review: Pairwise A/B Diff-Bewertung (SKILL + Tool-Diffs)
- codex-verify: Unabhängiger Faktencheck mit Impact-gewichtetem Claim-Schema
- Bootstrap-Skip bei leerem Diff (kein sinnloser Codex-Call)
- Hard-Fail bei high-impact wrong Claims (impact≥4)
- Parallel-Execution via ThreadPoolExecutor (max 2 Workers auf Pi 5)
- Tools (fast-search.py, research-crawler.py) werden ins Backup kopiert für Diffs

**Offene Verbesserungen (mittelfristig):**
- Regression-Memory: Falsche Claims als dauerhafte Testfälle speichern
- Source-Credibility-Scoring durch Codex
- Widerspruchserkennung zwischen Quellen
- Automatischer Code-Review bei jeder Iteration

**Why:** Codex fand im ersten echten Run einen falschen Preisclaim (Elegoo Centauri Carbon 250-280€ statt real 306-319€). Der Mehrwert ist bewiesen.

**How to apply:** Bei autoresearch-Runs immer die vollen 8 Checks laufen lassen (3 Trial + 2 Skill-Trial + 1 Codex-Review + 2 Codex-Verify).
