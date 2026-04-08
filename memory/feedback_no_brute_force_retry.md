---
name: Kein Brute-Force-Retry bei Tool-Fehlern
description: Bei Fehler in Skill-Tools (research-crawler, fast-search) sofort debuggen statt blind wiederholen
type: feedback
---

Bei Tool-/Skill-Fehlern NIEMALS denselben Befehl leicht variiert wiederholen. Statt 3x Retry sofort Root-Cause-Analyse.

**Why:** Session vom 2026-03-13 — research-crawler.py schlug 3x fehl wegen `2>` Redirect-Bug und falschem Placeholder `FW`. Statt nach dem 1. Fehler zu debuggen, habe ich 3x blind wiederholt und massiv Tokens verbrannt.

**How to apply:**
1. Erster Fehler → Fehlermeldung analysieren, nicht wiederholen
2. Minimal-Reproduktion bauen (einzelne Variable isolieren)
3. Skill-Templates nicht blind kopieren — Placeholder (`FW`, `SKILL`, `N`) durch echte Werte ersetzen
4. `2>/path` Redirect in Pipes vermeiden (intermittenter Bug in Claude Code Bash-Tool)
