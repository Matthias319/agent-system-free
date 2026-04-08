---
name: skill-routing-improvement
description: Skill-Routing für neue Sessions/Agents verbessert — Descriptions aufgewertet, Routing-Block erstellt, spawn-session Auto-Injection, Custom Subagent
type: project
---

Am 2026-03-22 wurde das Skill-Routing-System verbessert, damit neue Sessions und Subagents die verfügbaren Skills besser finden und nutzen.

**Why:** Neue Session-Agents wussten nicht welche Skills verfügbar sind, weil: (1) Agents keine Rules-Files erben, (2) system-reminder Skill-Descriptions zu generisch waren, (3) spawn-session keinen Skill-Kontext injizierte.

**Änderungen:**
1. **Alle 13 SKILL.md Descriptions** aufgewertet mit TRIGGER/NOT FOR/Example-Pattern (Few-Shot Best Practice nach LangChain-Research)
2. **Routing-Block** erstellt: `~/.claude/data/skill-routing-block.md` — kompakte Tabelle (~500 Tokens) für Injection in session-context.md und Agent-Prompts
3. **spawn-session SKILL.md** aktualisiert: Routing-Block wird automatisch in session-context.md eingebettet
4. **Custom Subagent** `~/.claude/agents/skill-aware-research.md` erstellt: Research-Agent der Skills statt native Tools nutzt
5. **CLAUDE.md** erweitert: Hinweis auf skill-aware-research Subagent und Routing-Block-Injection
6. **Skill-Router Index** neu gebaut (Embeddings refreshed)

**How to apply:** Bei Problemen mit Skill-Routing in neuen Sessions → zuerst prüfen ob Routing-Block in session-context.md vorhanden ist. Bei Research-Agents → skill-aware-research Subagent bevorzugen.
