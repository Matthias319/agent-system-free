---
name: Explore Agents immer Opus
description: Explore Subagents MÜSSEN immer model opus verwenden, nie Sonnet oder Haiku
type: feedback
---

Explore Agents IMMER mit `model: "opus"` spawnen.

**Why:** Matthias hat explizit gesagt "Benutze bitte für Explore Opus 4.6 Agents für jetzt und für die Zukunft." Haiku/Sonnet ist zu schwach für Explore.

**How to apply:** Bei jedem `subagent_type: "Explore"` immer `model: "opus"` setzen. Überschreibt die bisherige Regel aus core.md die Sonnet empfahl.
