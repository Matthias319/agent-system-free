---
name: autoresearch-system
description: Autoresearch-System (Karpathy-Loop) wurde am 14.03.2026 gebaut — Tool + Skill + Skill-Router-Integration für iterative Optimierung von Skills, Code und Configs
type: project
---

Am 14.03.2026 wurde das Autoresearch-System gebaut, inspiriert von Karpathy's auto_research und Nate Herk's Claude Code Adaptation.

**Komponenten:**
1. **Tool**: `~/.claude/tools/autoresearch.py` (~750 Zeilen) — CLI-Orchestrator mit 8 Commands (init, check, accept, reject, history, status, list, template)
2. **Skill**: `~/.claude/skills/autoresearch/SKILL.md` — Slash-Command `/autoresearch` mit Loop-Protokoll und Beispielen
3. **Skill-Router**: autoresearch im Index registriert, Score 0.79 auf "optimiere iterativ"

**3 Projekt-Typen:** skill (Prompts optimieren), code (Refactoring), config (Templates/CSS tunen)

**3 Check-Typen:** command (Shell Exit-Code), pattern (Regex auf Datei), agent (binäre Ja/Nein-Frage)

**Why:** Matthias will einen generischen Optimierungs-Framework der auf alles anwendbar ist — zuerst auf den Web-Search Skill, dann auf das MCV3 Board (großer Refactor + Design-Overhaul geplant).

**How to apply:**
- User sagt "optimiere X iterativ" → `/autoresearch` Skill laden
- Erster geplanter Test: MCV3 Board Refactor (code-Typ)
- Check-Qualität ist wichtiger als Check-Quantität (Goodhart-Warnung beachten)
- Daten landen in `~/.claude/data/autoresearch/<slug>/`
