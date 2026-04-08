---
name: Orchestrator Child-Session UI
description: MCB UI Feature-Idee — Orchestrator-Sessions zeigen gespawnte Worker-Sessions als aufklappbares Dropdown
type: project
---

Orchestrator-Sessions sollen ihre Worker-Sessions als **Child-Sessions** im UI gruppieren.

- Die Orchestrator-Session bekommt einen Dropdown-Pfeil (▶/▼)
- Aufklappen zeigt alle gespawnten Worker-Sessions darunter
- Worker-Sessions bleiben eigenständige Sessions (eigene Tabs, eigene Konversation)
- Rein visuelles Grouping — keine funktionale Abhängigkeit im Session-Modell
- Datenmodell: `orchestrator_tasks.session_id` → `sessions.id` Relation existiert bereits

**Why:** Bei Orchestrator-Runs mit 5-8 Workern wird die Session-Liste unübersichtlich. Parent-Child-Grouping macht sofort klar welche Sessions zusammengehören.

**How to apply:** MCB Frontend (templates/index.html oder sessions-Liste) erweitern. Backend: Orchestrator-Run-ID an Session anhängen (z.B. `sessions.parent_run_id`).
