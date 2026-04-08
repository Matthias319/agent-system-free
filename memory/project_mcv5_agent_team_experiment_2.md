---
name: MCV5 Agent Team experiment (2026-03-22)
description: First TeamCreate experiment with 3 agents targeting MCV5 development — results and what each agent actually changed
type: project
---

On 2026-03-22, Matthias requested an Agent Team (TeamCreate "mcv5-dev") with 3 agents to orchestrate 3 existing tmux sessions (mc4-7b711d4e, mc4-489ba7ba, mc4-8880ba8b) for continuous MCV5 improvement.

**What actually happened:** Agents coded directly instead of orchestrating tmux sessions (see feedback_agent_orchestration.md).

**Changes made to MCV5 (`/home/maetzger/Projects/mission-control-v5/`):**
- **infra-agent**: Added `_periodic_memory_consolidation()` to `app.py` lifespan — runs `~/.claude/tools/memory-consolidate.py` periodically
- **agent-system (session 534967a6)**: Enhanced `core/conversation_index.py` — added `re`, `datetime`, `HTMLParser` imports; expanded `conversation_stats()` with per-message model breakdown and top-tools ranking
- **research-agent (session 301e896d)**: Added `get_skill_inventory()` and `get_custom_agent_defs()` to `core/agents.py`; added `/api/agents/skills` and `/api/agents/definitions` API endpoints to `routes/agents.py`

**Why:** Matthias wants agents that keep running sessions alive for continuous improvement — a "self-developing" agent system. The orchestration-via-tmux pattern is the intended approach.

**How to apply:** These changes need review — agents made them autonomously without /codex consultation. Check if MCV5 service still runs cleanly after these edits. The new endpoints and periodic task may need integration testing.
