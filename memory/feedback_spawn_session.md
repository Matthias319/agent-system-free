---
name: Spawn-Session richtig nutzen — immer den vollständigen Skill-Ablauf
description: Beim Spawnen von Worker-Sessions IMMER den /spawn-session Skill verwenden, nicht nur die API direkt aufrufen
type: feedback
---

Session-Spawn erfordert 4 Steps — niemals nur die Session erstellen (POST /api/sessions) ohne Prompt zu senden.

**Why:** POST /api/sessions erstellt nur die tmux-Session mit Claude CLI. Das `prompt`-Feld im Request-Body wird vom Server IGNORIERT. Ohne die Folgeschritte sitzt Claude idle ohne Auftrag.

**How to apply:** IMMER den `/spawn-session` Skill verwenden oder manuell alle 4 Steps durchführen:
1. Session erstellen (POST /api/sessions)
2. session-context.md ins Workdir schreiben (Structured YAML Handoff + Routing-Block)
3. tmux resize-window -t TMUX_NAME -x 120 -y 35
4. sleep 8 + Prompt via POST /api/terminal/send senden

Kein Shortcut. Kein "nur schnell die API aufrufen".
