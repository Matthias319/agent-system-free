---
name: Dispatch tmux capture-pane Befehl
description: tmux capture-pane braucht -e -S -200 Flag, sonst leere Ausgabe bei kleinen Panes (46x23)
type: feedback
---

`tmux capture-pane -t "TMUX:0.0" -p` liefert bei kleinen Panes (46x23, MCB Default) oft leeren Output.

**Korrekter Befehl:**
```bash
tmux capture-pane -t "$TMUX:0.0" -p -e -S -200 2>/dev/null | tail -20
```

**Why:** Dispatch-Session hat Permission-Prompts übersehen weil capture-pane ohne Scrollback-Flags nur den sichtbaren Bereich zeigt — der bei 46x23 oft komplett leer ist (Claude rendert im Scrollback).

**How to apply:** Bei JEDEM Dispatcher-Ping immer `-e -S -200` verwenden. Nie ohne Scrollback-Flags capturen.
