---
name: MCB Research Findings and Roadmap
description: GitHub-Research für MCB Verbesserungen — 3 unabhängige Streams, priorisierter Verbesserungsplan, Quick Wins implementiert 2026-03-20
type: project
---

Research completed 2026-03-20 with 3 independent streams (agent team, Codex #1, Codex #2 + web-search).
6-Agent research squad evaluated ~30 repos across 5 domains. Result: 7 ADOPT, 10 STEAL PATTERN, 15 REJECT.

**Why:** MCB needed feature gap analysis against the Claude Code dashboard ecosystem.

**Key Finding:** MCB braucht keine neuen Frameworks. Alle wertvollen Patterns sind mit nativem HTML/CSS/JS implementierbar. Einzige Library-Adoptionen: xterm.js Addons (trivial via CDN). Größte Lücke: "durable introspection" (session timeline, global search, tool inspector).

**Top Projects:** agent-deck, claude-code-viewer, 1code, WebTmux.

## Quick Wins (implementiert 2026-03-20)
1. addon-unicode11 + addon-clipboard (CDN + JS)
2. CSS Glassmorphism + Neon Glow + Grid Background + Status Colors
3. StatusPanel in Session Tabs (per-session tokens/cost)
4. SSE Reconnect (ring buffer + Last-Event-ID) + BroadcastChannel Multi-Tab + exponential backoff

## Remaining Roadmap (Weeks 2-4)
- Week 2: AG-UI Event Schema (Backend Pydantic), Session Status State Machine, Layout Serialization
- Week 3: Chainlit Step Pattern (Tool-Call Accordion), Dify StatusPanel (full), Reconnect Pipeline
- Week 4: CopilotKit Renderer Registry, Langfuse Trace Tree, Phoenix optional Viewer

## Key Architecture Decisions
- dockview REJECTED as library (Big-Bang Rewrite risk) — steal serialization pattern instead
- CopilotKit state-driven rendering = Game Changer (state objects instead of log streams)
- AG-UI Event Schema = most valuable long-term investment (typed SSE events with trace_id/span_id)
- Native SSE + BroadcastChannel beats Socket.IO/Mercure for our use case

## Full Report
/home/maetzger/Projects/mission-control-board/research-findings/triage/FINAL-REPORT.md

**How to apply:** Follow the prioritized task order in research-findings/. Reports in /home/maetzger/Projects/mission-control-board/research-findings/.
