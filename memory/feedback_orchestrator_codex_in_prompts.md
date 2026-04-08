---
name: Orchestrator Worker-Prompts müssen Codex-Konsultation explizit enthalten
description: Worker-Sessions folgen Task-Prompts stärker als globalen CLAUDE.md Rules — Codex-Pflicht muss direkt im Prompt stehen
type: feedback
---

Orchestrator-Worker-Sessions laden zwar ~/.claude/CLAUDE.md (mit Codex-Regel), aber folgen ihren spezifischen Task-Prompts stärker. Die globale Regel "Codex konsultieren bei >50 Zeilen" wird von Workern oft ignoriert.

**Why:** Bei Phase 2 des ActScriber-Rollouts (2026-03-26) hatten die Task-Prompts keinen expliziten Codex-Hinweis. Matthias hat das bemerkt und gefragt ob die Agents Codex einbeziehen.

**How to apply:** In JEDEN Orchestrator-Task-Prompt diesen Block einfügen:
```
CODEX-KONSULTATION (PFLICHT bei >50 Zeilen Code-Änderung):
Nutze den /codex Skill als Sparringspartner bevor du größere Code-Änderungen schreibst.
Codex-Profil rotieren: uv run ~/.claude/tools/codex-multi.py auto -q
```
Gilt auch für den Orchestrator-Skill selbst — dort als Standard-Block in Phase 2 (Brief) einbauen.
