---
name: Agent Team tmux orchestration pattern fails with mid-conversation redirect
description: Agents spawned with direct-coding instructions ignore follow-up redirect to tmux orchestration mode — initial prompt anchors behavior
type: feedback
---

Agents that receive an initial "code directly on MCB" prompt AND a follow-up SendMessage saying "WICHTIG — Planänderung! Orchestriere stattdessen die tmux-Session via tmux send-keys" will ignore the redirect and continue coding directly.

**Why:** The initial Agent spawn prompt anchors behavior more strongly than follow-up messages. All 3 agents in the mcb-dev team (2026-03-22) read MCB code and made edits instead of using `tmux send-keys` to orchestrate existing sessions.

**How to apply:**
- If the goal is tmux orchestration, the INITIAL Agent spawn prompt must say "orchestrate via tmux" — not a follow-up redirect
- Never spawn agents with "code directly" and then try to redirect to "orchestrate tmux" — the redirect will be ignored
- For the orchestration pattern: spawn with explicit tmux send-keys/capture-pane instructions from the start, with NO mention of direct coding
- Consider: agents may not have Bash permissions to run tmux commands depending on mode — verify `mode: "auto"` or `"bypassPermissions"` is set
