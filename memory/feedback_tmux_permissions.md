---
name: tmux-permission-handling
description: Bei Permission-Prompts in tmux-Sessions immer Option 2 wählen (allow for session) und danach verifizieren
type: feedback
---

Bei Permission-Prompts in anderen Sessions (via tmux send-keys):
1. Immer **Option 2** wählen (die "allow for session/project"-Variante) — Pfeil runter + Enter
2. **Danach IMMER prüfen** ob die Session wirklich weiterläuft (sleep 3 + tmux capture-pane)
3. Nicht blind annehmen dass der Tastendruck angekommen ist
4. **Mehrere Prompts möglich**: Nach Bestätigung kann sofort der nächste Permission-Prompt kommen. Loop: send-keys → sleep 3 → capture-pane → noch ein Prompt? → wieder send-keys. Erst wenn die Session tatsächlich arbeitet (kein Prompt mehr sichtbar) ist es erledigt.
5. Erst dem User Erfolg melden wenn per capture-pane verifiziert ist, dass die Session weiterarbeitet.

**Why:** Autonomie ist das Ziel. Option 1 führt zu wiederholten Permission-Prompts. tmux send-keys kann manchmal nicht ankommen oder es kommen mehrere Prompts hintereinander.

**How to apply:** Nach dem ersten send-keys eine **Poll-Schleife** laufen lassen — alle 5-10 Sekunden capture-pane prüfen, für mindestens 60-90 Sekunden. Erst wenn mehrere Checks hintereinander keinen Permission-Prompt zeigen UND die Session aktiv arbeitet, ist es erledigt. Nicht nach einem einzigen Check "erledigt" melden.

**Pattern (Bash):**
```
for i in $(seq 1 12); do
  sleep 5
  out=$(tmux capture-pane -t SESSION -p | tail -15)
  if echo "$out" | grep -q "Do you want"; then
    tmux send-keys -t SESSION Down Enter
  elif echo "$out" | grep -qE '(◼|✻|⏵)'; then
    echo "Session arbeitet"; break
  fi
done
```
