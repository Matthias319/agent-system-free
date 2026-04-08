---
name: tasks
description: "Verwaltet persistente Task-Liste in tasks.db (erstellen, auflisten, erledigen)"
triggers:
  - "neue Aufgabe"
  - "was steht an"
  - "erledigt"
  - "Todo"
  - "füge hinzu"
  - "was ist offen"
  - "Aufgabenliste"
not_for:
  - "Session-internes Progress-Tracking"
  - "Projektplanung"
delegates_to:
  - "todo-extract"
exports:
  - "list"
  - "add"
  - "complete"
---

# Task Management Skill

Verwalte Tasks die in `./data/tasks.db` gespeichert werden und im MCB Dashboard erscheinen.

## Befehle

### Auflisten

```bash
python3 -c "
import sqlite3
db = sqlite3.connect('$HOME/.claude/data/tasks.db')
rows = db.execute('SELECT id, title, priority, status, due_date, project FROM tasks WHERE status=\"open\" ORDER BY CASE priority WHEN \"high\" THEN 1 WHEN \"medium\" THEN 2 WHEN \"normal\" THEN 3 ELSE 4 END').fetchall()
for r in rows: print(f'[{r[0]}] {r[2].upper():6s} {r[1]} {(\"-> \"+r[4]) if r[4] else \"\"} {(\"(\"+r[5]+\")\") if r[5] else \"\"}')
if not rows: print('Keine offenen Tasks.')
"
```

### Hinzufügen

```bash
python3 -c "
import sqlite3, sys
db = sqlite3.connect('$HOME/.claude/data/tasks.db')
db.execute('INSERT INTO tasks (title, priority, due_date, project, created_by) VALUES (?, ?, ?, ?, ?)',
    (sys.argv[1], sys.argv[2] if len(sys.argv)>2 else 'normal', sys.argv[3] if len(sys.argv)>3 else None, sys.argv[4] if len(sys.argv)>4 else None, 'agent'))
db.commit()
print(f'Task erstellt: {sys.argv[1]}')
" "TASK_TITLE" "PRIORITY" "DUE_DATE" "PROJECT"
```

Argumente:
- `TASK_TITLE`: Pflicht
- `PRIORITY`: optional (high, medium, normal, low). Default: normal
- `DUE_DATE`: optional (YYYY-MM-DD)
- `PROJECT`: optional (Name eines bestehenden Projekts)

### Erledigen

```bash
python3 -c "
import sqlite3, sys, datetime
db = sqlite3.connect('$HOME/.claude/data/tasks.db')
db.execute('UPDATE tasks SET status=\"done\", completed_at=? WHERE id=?', (datetime.datetime.now().isoformat(), sys.argv[1]))
db.commit()
print(f'Task {sys.argv[1]} erledigt')
" "TASK_ID"
```

### Inbox prüfen (Drag-Drop Bucket)

> **Delegation:** Für Inbox-Verarbeitung (Dateien analysieren, Action-Items extrahieren, Eisenhower-Einordnung) nutze den `/todo-extract` Skill. Dieser Skill bietet die vollständige Pipeline inkl. Duplikat-Erkennung, Audio/Video-Transkription und Verrottungs-Check.

Kurz-Check ob Dateien in der Inbox liegen:
```bash
ls -la ./data/tasks-inbox/ 2>/dev/null | grep -v "^d" | grep -v "^total"
```
Wenn Dateien vorhanden → `/todo-extract` aufrufen.

### Extract (Session-Ende)

Am Ende einer Session: Analysiere den bisherigen Verlauf und extrahiere Action-Items als Tasks.

```
Gehe den Verlauf durch und erstelle Tasks für:
- Explizit genannte TODOs oder Aufgaben
- Offene Fragen die Recherche brauchen
- Follow-up Arbeiten die besprochen wurden
```
