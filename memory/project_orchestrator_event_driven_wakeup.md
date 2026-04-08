---
name: Orchestrator Event-Driven Wakeup
description: MCB Feature — Orchestrator-Session automatisch aufwecken wenn Child-Session Entscheidung braucht (statt Polling)
type: project
---

Orchestrator soll event-driven aufgeweckt werden statt nur per Polling.

**Auslöser:** MCB hat bereits ein "needs attention" Notification-System (Sound + Desktop-Notification + Notification-Bar). Dieses Event soll für Orchestrator-Child-Sessions an den Orchestrator weitergeleitet werden.

**Architektur-Optionen:**
- **A (einfach):** MCB-Backend löst Permission-Dialoge in Orchestrator-Child-Sessions automatisch auf (die laufen mit --dangerously-skip-permissions, sollten eigentlich keine Prompts zeigen — das ist selbst ein Bug)
- **B (mächtig):** Event wird an Orchestrator-Session als Nachricht weitergeleitet. Orchestrator entscheidet eigenständig.

**Vorhandene Pieces:**
- `sessions.parent_run_id` (noch zu implementieren, siehe Child-Session-UI Memory)
- `orchestrator_tasks.session_id` → Zuordnung existiert
- `send_to_session()` in core/session_runtime.py → kann Befehle senden
- Notification-System erkennt "attention needed" bereits

**Why:** Beim Feldversuch 2026-03-24 hing ein Worker 10h weil ein Permission-Prompt nicht beantwortet wurde. Polling alle 5min hat es gefunden, aber event-driven wäre sofort.

**How to apply:** MCB core/auto_heal.py oder neues core/orchestrator_events.py — Event-Listener der bei "attention" Events prüft ob die Session zu einem Orchestrator-Run gehört und dann den Orchestrator aufweckt.
