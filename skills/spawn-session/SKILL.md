---
name: spawn-session
disable-model-invocation: false
description: "Startet separate Claude Code Session als MCB Tab für parallele/Hintergrund-Arbeit"
triggers:
  - "in eigenem Tab"
  - "parallel"
  - "im Hintergrund"
  - "lass mal laufen"
  - "delegieren"
  - "eigene Session"
not_for:
  - "Tasks <2 min"
  - "Tasks die sofortige Ergebnisse brauchen"
---

# Spawn Session — Autonome MCB Tabs

Startet eine neue Claude Code Session als Tab in Mission Control V3.
Die Session bekommt Kontext injiziert und arbeitet autonom.

**MCB API**: `http://127.0.0.1:8205`

## Wann nutzen

- Aufgabe die parallel laufen soll (Research, Code-Review, lange Builds)
- Aufgabe die den aktuellen Context nicht belasten soll
- User sagt "mach das in einem eigenen Tab", "lass das mal laufen", "recherchiere parallel"

## Wann NICHT nutzen

- Aufgabe die <2 Minuten dauert → direkt hier erledigen
- Aufgabe die sofortige Ergebnisse braucht → Agent-Tool stattdessen
- Aufgabe die den aktuellen Workspace-State braucht → hier bleiben

## Ablauf

### Step 1: Session erstellen

```bash
SESSION=$(curl -s http://127.0.0.1:8205/api/sessions \
  -X POST -H "Content-Type: application/json" \
  -d '{"name": "SESSION_NAME"}')
```

Aus der Response extrahieren:
- `id` — Session-ID für API-Calls
- `tmux_name` — tmux-Session-Name (z.B. `mc5-a1b2c3d4`)
- `cwd` — Workdir-Pfad (z.B. `/home/maetzger/mcb-workdirs/mc5-a1b2c3d4`)

### Step 2: Kontext injizieren (Structured Handoff)

`session-context.md` in das Workdir schreiben — Claude liest diese Datei automatisch beim Start.

**PFLICHT: Routing-Block immer einbinden!** Die session-context.md MUSS den Skill-Routing-Block enthalten.

**Format: Structured YAML Handoff** — kompakter und token-effizienter als freies Markdown.
Basiert auf dem OpenAI Agents SDK Handoff-Pattern und Continuous-Claude-v3 YAML Handoffs.

```bash
ROUTING_BLOCK=$(cat ./data/skill-routing-block.md)

cat > /home/maetzger/mcb-workdirs/TMUX_NAME/session-context.md << CONTEXT
# Session Handoff

\`\`\`yaml
task: "Kurzer Auftragstitel"
objective: "Was genau erreicht werden soll — 1-2 Sätze"
context:
  - "Fakt 1 den die Session wissen muss"
  - "Fakt 2 — keine ganzen Absätze, nur Kerninfo"
decisions_made:
  - "Entscheidung X wurde bereits getroffen (Grund)"
relevant_files:
  - "./skills/web-search/SKILL.md"
  - "/home/maetzger/project/src/main.py"
constraints:
  - "Keine AskUserQuestion — autonomer Modus"
  - "Committe einzeln pro Feature"
next_steps:
  - "Step 1: ..."
  - "Step 2: ..."
open_questions: []
\`\`\`

$ROUTING_BLOCK
CONTEXT
```

**Warum strukturiert statt Freitext:**
- ~40% weniger Tokens als äquivalenter Markdown-Kontext
- Felder zwingen zum Komprimieren statt Copy-Paste aus Chat-Verlauf
- `decisions_made` verhindert dass die Kind-Session Entscheidungen neu trifft
- `constraints` definiert Leitplanken klar

**Wichtig**: Der Kontext muss ALLES enthalten was die Session braucht.
Sie hat keinen Zugriff auf den Chat-Verlauf der Eltern-Session.
Der Routing-Block stellt sicher, dass die Kind-Session Skills korrekt nutzt.

### Step 2b: History Compression (bei langem Kontext)

Bei langen Sessions wird der Kontext-Handoff schnell zu groß. `compress-handoff.py`
komprimiert den Kontext auf ein Token-Budget (Standard: 2000 Tokens).

**Wann nutzen:**
- Aktuelle Session hat >50 Nachrichten/Turns
- Es existiert bereits eine `session-context.md` (z.B. aus Recycling) die weitergegeben werden soll
- Der manuell geschriebene YAML-Handoff wird zu lang (>30 Zeilen)

**Komprimierung einer bestehenden session-context.md:**
```bash
# Bestehenden Kontext komprimieren + Routing-Block anhängen
./tools/compress-handoff.py \
  "$CWD/session-context.md" \
  --with-routing \
  -o "$CWD/session-context.md"
```

**Komprimierung mit angepasstem Budget:**
```bash
# Kleineres Budget für einfache Tasks
./tools/compress-handoff.py \
  "$CWD/session-context.md" \
  --budget 1000 \
  -o "$CWD/session-context.md"
```

**Was das Tool macht:**
- Tabellen → einzeilige Zusammenfassungen (`[Tabelle: Spalten — N Zeilen]`)
- Konversations-Filler entfernen ("Lass mich...", "Gute Frage...", Trennlinien)
- Nur Entscheidungen, Ergebnisse und Schlussfolgerungen behalten
- Älteste Inhalte zuerst trimmen wenn Budget überschritten
- Routing-Block wird außerhalb des Token-Budgets angehängt

**Typische Komprimierung:** 60-75% Reduktion bei großen Session-Kontexten.

### Step 3: tmux-Fenster resizen (PFLICHT — Workaround)

MCB erstellt tmux-Fenster mit 10x5 wenn kein Browser-Client attached ist.
Das macht Claude unbrauchbar. **Immer resizen:**

```bash
tmux resize-window -t TMUX_NAME -x 120 -y 35
```

### Step 4: Prompt senden

Warte 5-8 Sekunden bis Claude gestartet ist, dann:

```bash
curl -s http://127.0.0.1:8205/api/terminal/send \
  -X POST -H "Content-Type: application/json" \
  -d '{"session_id": "SESSION_ID", "text": "PROMPT", "submit": true}'
```

Oder via tmux direkt:
```bash
tmux send-keys -t TMUX_NAME "PROMPT" Enter
```

**API-Variante bevorzugen** — geht durch MCB's Auth und Logging.

### Step 5: Status prüfen (optional)

```bash
tmux capture-pane -t TMUX_NAME -p -S -20
```

## Komplettes Beispiel (1 Bash-Block)

```bash
# 1. Session erstellen
RESP=$(curl -s http://127.0.0.1:8205/api/sessions \
  -X POST -H "Content-Type: application/json" \
  -d '{"name": "Research: Thema XY"}')
SID=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
TMUX=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['tmux_name'])")
CWD=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['cwd'])")

# 2. Structured Handoff injizieren (MIT Routing-Block!)
ROUTING_BLOCK=$(cat ./data/skill-routing-block.md)
cat > "$CWD/session-context.md" << CONTEXT
# Session Handoff

\`\`\`yaml
task: "Research: Thema XY"
objective: "Finde die Top-5 Alternativen zu Tool Z mit Preisvergleich"
context:
  - "Wir nutzen aktuell Tool Z v2.3"
  - "Budget: max 50€/Monat"
decisions_made: []
relevant_files: []
constraints:
  - "Ergebnis als HTML-Report (/html-reports)"
next_steps:
  - "Web-Recherche durchführen"
  - "Report erstellen"
open_questions: []
\`\`\`

$ROUTING_BLOCK
CONTEXT

# 2b. Optional: Kontext komprimieren (bei langem Eltern-Session-Verlauf)
# ./tools/compress-handoff.py "$CWD/session-context.md" --with-routing -o "$CWD/session-context.md"

# 3. Resize (Workaround für 10x5 Bug)
tmux resize-window -t "$TMUX" -x 120 -y 35

# 4. Warten + Prompt senden
sleep 8
curl -s http://127.0.0.1:8205/api/terminal/send \
  -X POST -H "Content-Type: application/json" \
  -d "{\"session_id\": \"$SID\", \"text\": \"Lies session-context.md und führe den Auftrag aus.\", \"submit\": true}"
```

## Beispiel: Session-Kontext aus Recycling komprimiert weiterreichen

Wenn eine Session recycled wurde und der Kontext an eine neue Session weitergegeben werden soll:

```bash
# Bestehende recycled session-context.md komprimieren
./tools/compress-handoff.py \
  /home/maetzger/mcb-workdirs/mc4-XXXXXXXX/session-context.md \
  --with-routing \
  --stats \
  -o "$CWD/session-context.md"
# Output: [compress-handoff] 1856 → 532 Tokens (71% Reduktion, Budget: 2000)
```

## Monitoring-Pattern

Mehrere Sessions gleichzeitig prüfen:
```bash
for s in $(tmux list-sessions -F '#{session_name}' | grep ^mc5-); do
  echo "=== $s ==="
  tmux capture-pane -t "$s" -p | tail -3
  echo
done
```

## Anti-Patterns

- **NIE** Session ohne Kontext spawnen — die Session weiß sonst nichts
- **NIE** das Resize vergessen — 10x5 macht Claude unbrauchbar
- **NIE** mehr als 3 Sessions parallel — RAM-Limit auf dem Pi (8GB)
- **NIE** den Prompt direkt im `tmux new-session` Command mitgeben — Claude braucht Startzeit
- **IMMER** prüfen ob die Session gestartet hat (Step 5) bevor du dem User sagst "läuft"
- **IMMER** History Compression nutzen wenn der Kontext >50 Zeilen wird
