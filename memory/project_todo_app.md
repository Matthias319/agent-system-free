---
name: Todo App im MCV4
description: Intelligente To-Do-App als Teil des MCV4-Dashboards mit Eisenhower-Matrix, Inbox-Verarbeitung, Quick-Capture und Agent Question Queue
type: project
---

## To-Do-App (MCV4-integriert)

Matthias hat eine lokale To-Do-App im MCV4-Dashboard (Port 8200). Kein Notion, alles lokal auf dem Pi.

**Zugriff:**
- HTML-Seite: `https://[hostname]:8200/todo`
- API: `https://[hostname]:8200/api/tasks/...`
- Sidebar-Panel: Tasks-Panel im MCV4-Dashboard

**Datenbank:** `~/.claude/data/tasks.db` (SQLite, Schema v3)

**Eisenhower-Felder:** `importance` (high/low) × `urgency` (high/low) — DB und API auf Englisch, UI auf Deutsch.

**Bereiche:** `work` (Job, Pi-Projekte, Coding) / `personal` (Familie, Gemeinde, Ehrenämter, Sport, Haushalt)

**Quick-Capture:** In JEDER Session kann ein Task direkt erstellt werden:
```bash
curl -s -b ~/.claude/data/mcv4-cookie -X POST https://localhost:8200/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"title": "...", "importance": "high|low", "urgency": "high|low", "area": "work|personal", "created_by": "agent"}'
```

**Agent Question Queue (v3):** Agents können Rückfragen an Matthias stellen, die als swipeable Cards in der Todo-App erscheinen:
```bash
# Agent erstellt Frage
curl -s -X POST https://localhost:8200/api/tasks/questions \
  -H "Content-Type: application/json" \
  -d '{"question_text": "...", "source_context": "...", "created_by": "opus-4.6"}'
# Agent holt beantwortete Fragen ab
curl -s https://localhost:8200/api/tasks/questions?answered=1&picked_up=0
# Agent markiert als abgeholt
curl -s -X POST https://localhost:8200/api/tasks/questions/{id}/pickup
```

**Skill:** `/todo-extract` — verarbeitet Inbox-Ordner (`~/.claude/data/tasks-inbox/`), extrahiert Tasks aus beliebigen Assets (Text, Audio, Video, PDF, Bilder).

**Why:** Matthias braucht ein zentrales System für alle Aufgaben (Work + Privat). Claude agiert als intelligenter Router — Extraktion, Priorisierung, Einordnung. Die Question Queue ermöglicht asynchrone Agent-User-Kommunikation.

**How to apply:** Bei "merk dir", "Task:", "Aufgabe:" → Quick-Capture nutzen. Bei "/todo-extract" → Inbox verarbeiten. Bei Rückfragen an den User → Question Queue API nutzen. Bestehende Tasks vorher laden für Cross-Referenz.
