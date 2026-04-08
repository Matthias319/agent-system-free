---
name: Matthias wants self-improving agent system with long-running orchestrated sessions
description: Goal is agents that keep Claude Code sessions productive as long as measurable MCB improvements happen — continuous development loop
type: user
---

Matthias explicitly wants agents that:
1. Take over existing running Claude Code tmux sessions
2. Keep them running ("möglichst lange am Laufen halten")
3. Continue as long as there are "messbare Ergebnisse" (measurable results)
4. Focus on MCB bot and agent system self-improvement

This is not just task delegation — it's a continuous development loop where agents orchestrate other Claude instances. The pattern is: Agent Team (TeamCreate) → each agent controls one tmux session → monitors output → feeds new tasks → reports back to team lead.

Key sessions involved (2026-03-22): mc4-7b711d4e (infra), mc4-489ba7ba (agent system), mc4-8880ba8b (research).
