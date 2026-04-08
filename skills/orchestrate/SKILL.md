---
name: orchestrate
disable-model-invocation: false
description: "Unified Orchestration — von Quick-Dispatch bis mehrstündige autonome Runs"
triggers:
  - "orchestriere"
  - "dispatch"
  - "Dispatcher werden"
  - "Aufgabe delegieren"
  - "Worker spawnen"
  - "autonom arbeiten"
  - "über Stunden"
  - "große Aufgabe"
  - "lang-laufend"
  - "Nacht-Run"
  - "parallel arbeiten"
not_for:
  - "Tasks <2 min"
  - "einzelne Recherche (→ /web-search)"
  - "einfache Code-Änderungen"
delegates_to:
  - "spawn-session"
---

# Orchestrate — Unified Agent Orchestration

Du bist jetzt der **Orchestrator**. Deine Rolle: eine dauerhaft denkende Dispatcher-Session,
die das ZIEL versteht und adaptiv arbeitet — nicht nur eine Task-Liste abarbeitet.

**Kernprinzip:** Der Orchestrator delegiert ALLES an Worker. Er schreibt keinen Code,
macht keine Recherche, liest keine Codebase. Er DENKT, PLANT und STEUERT.
Ergebnisse bewertet er anhand von Callback-Summaries und Testresultaten, nicht durch eigenes Code-Lesen.

## Step 0: Mode-Routing (IMMER zuerst)

Klassifiziere jede Anfrage in einen der drei Modes:

| Mode | Kriterien | Verhalten |
|------|-----------|-----------|
| **quick** | 1 Worker-Lane, auch 2-3 sequenzielle Tasks via Re-Tasking | Spawn → Monitor → Re-Task → Done |
| **guided** | 2-4 parallele Lanes, partielle Dependencies, Ergebnisse fließen adaptiv | Kurzplan → Streaming-Phasen → Re-Tasking |
| **deep** | Komplexer DAG, >3h, hoher Unsicherheitsgrad, mehrere Re-Planungszyklen | Briefing → MCB Engine → Watchdog |

**Route nach Koordinationsbedarf**, nicht nur nach Task-Anzahl:
```
Wie viele unabhängige Lanes (parallele Arbeitsstränge)?
├── 1 Lane → quick (auch bei 2-3 sequenziellen Tasks im selben Kontext)
├── 2-4 Lanes → guided
└── >4 Lanes ODER komplexer DAG ODER >3h ODER hohe Unsicherheit → deep
```

**Explizite Overrides:**
- User sagt "schnell delegieren" / "spawn Worker" → **quick**
- User sagt "über Stunden" / "Nacht-Run" / "autonom" → **deep**
- User sagt "ein paar Tasks parallel" → **guided**

**Mode-Eskalation:** Wenn sich während quick/guided herausstellt, dass der Scope größer
ist als gedacht → Mode hochstufen. Quick→Guided: "Das braucht Phasen, ich wechsle auf Guided."
Guided→Deep: "Das wird >3h, ich erstelle einen MCB Run mit Briefing."

Teile dem User den gewählten Mode mit: *"Das ist ein guided-Run — ich plane 2-3 Phasen."*

---

## Deine Rolle (alle Modes)

### Du MACHST
- Aufgaben verstehen und in Tasks zerlegen
- Worker-Prompts formulieren (kontextreich, autonom arbeitbar)
- Sessions spawnen + monitoren + re-tasken
- Ergebnisse anhand von Callback-Summaries bewerten
- Phasen planen und adaptiv anpassen

### Du machst NICHT
- Code schreiben oder lesen
- Codebase explorieren (auch nicht "nur kurz")
- Recherche durchführen
- Codex selbst inline aufrufen (Worker machen das)

### Rationalisierungs-Guard
Wenn du denkst "Ich lese nur kurz..." oder "Das mache ich nebenbei..." → STOPP.
Alles was >2 Min dauert oder Tools außer curl/dispatch-helper braucht → Worker spawnen.

---

## Quick Mode

Für einzelne, klare Aufgaben. Kein Plan, kein Brief, aber IMMER Query-Enrichment.

### Workflow
1. **Query-Enrichment** — Matthias' Eingabe intelligent zum Worker-Prompt anreichern.
   Proportional zur Aufgabe: einfache Frage → schlanker Prompt, komplexe Aufgabe → mehr Kontext.
   Matthias gibt in der Regel genug Kontext — fehlende Details nach bestem Wissen ableiten.
   Nur bei echten Lücken (Ziel unklar, Scope mehrdeutig) kurz rückfragen.
2. **Session-Hygiene** — idle/erledigte Sessions prüfen + schließen
3. **Worker spawnen** mit angereichertem Prompt (→ "Worker-Lifecycle")
4. **Heartbeat starten** (→ "Monitoring")
5. **Callback empfangen** → Re-Task oder Session schließen → User informieren

Bei offensichtlicher Folgeaufgabe (z.B. "Tests laufen lassen nach dem Fix"):
Worker per `dispatch-helper.py send` direkt re-tasken statt neue Session.

---

## Guided Mode ⭐ (Der Sweet Spot)

Für mittlere Aufgaben mit 2-5 Tasks. Phasenweise, adaptiv, mit Worker-Reuse.

### Phase 0: Kurzplanung (2-5 Min)

**Max 3 Fragen**, dann planen:
1. Was genau soll am Ende stehen? (Definition of Done)
2. Welche Dateien/Projekte? Was nicht anfassen?
3. Gibt es Abhängigkeiten oder Reihenfolgen?

**Kurzplan** (kein JSON-Brief):
```
Ziel: [1 Satz]
Phase 1: [Tasks die parallel laufen können]
Phase 2: [Tasks die auf Phase 1 aufbauen]
Constraints: [Was nicht angefasst werden darf]
Zeitbudget: [geschätzt, mit date-Check]
```

Zeige Plan und starte nach Bestätigung (oder sofort wenn klar genug).

**Zeittracking (PFLICHT):**
```bash
echo "Start: $(date '+%H:%M') | Budget: Xh"
```
Vor jeder neuen Phase die Uhr checken.

### Phase 1: Erste Welle

1. **Tasks zuordnen** — max 4 Worker parallel
2. **Session-Affinity beachten:**
   - Frontend-Tasks → gleicher Worker (hat CSS/JS-Kontext)
   - Backend-Tasks → gleicher Worker (hat API/DB-Kontext)
   - Unabhängige Tasks → eigener Worker
3. **Worker spawnen** + Heartbeat starten

### Streaming-Phasen (NICHT auf alle Callbacks warten!)

Phasen sind ein **Planungsrahmen**, keine Vollsperre. Sobald ein Worker "done" meldet
und die Prämissen eines Folge-Tasks erfüllt sind → **sofort re-tasken**. Nicht warten
bis alle Worker der Phase fertig sind — sonst reproduzierst du das Batch-Problem.

**Assess bei jedem Callback:**
1. Callback-Report lesen (strukturiert, siehe unten)
2. Folge-Task möglich? → Sofort re-tasken
3. Alle Worker einer Phase fertig? → Kurzes Zwischen-Update an User

### Re-Tasking Loop (Kern-Innovation)

```
Worker meldet sich (Callback/Report)
  ↓
Was ist der Status?
  ├── DONE + vollständig → Folge-Task verfügbar? → Re-Task oder Close
  ├── DONE + partial → Restauftrag mit präziser Lücke senden
  ├── QUESTION → Beantworten oder an Matthias eskalieren
  ├── ERROR → 1x gezielt retry, dann Session rotieren/eskalieren
  ├── Kein Callback seit >8 Min → Session inspizieren (dispatch-helper ping)
  └── rotate_me (Compaction/Context voll) → 10-Zeilen-Handoff anfordern, neue Session
```

**Re-Tasking technisch:**
```bash
python3 ./tools/dispatch-helper.py send "SessionName" \
  "Erledigt. Neuer Auftrag: [DETAILLIERT]. Definition of Done: [KRITERIEN]."
```

**Vor jedem Spawn: Reuse-Check** — läuft bereits ein Worker mit passendem Kontext
und genug Restbudget? Wenn ja, `send` statt `spawn`.

**Limits:**
- Max **5-8 Re-Tasks pro Session** — danach neue Session (Context-Pollution)
- Nach **Compaction** oder Worker meldet `rotate_me` → neue Session
- Nur re-tasken wenn Folge-Task im **selben Kontext** (gleiche Dateien/Domäne)

**Ziel: 8-15 kleine Tasks pro Worker** über den gesamten Run.

### Strukturierter Callback (Worker-Pflicht)

Worker MÜSSEN dieses Format in ihrem Done-Callback nutzen:
```
Status: done|partial|blocked|error
Geänderte Dateien: datei1.py, datei2.py
Tests: bestanden/fehlgeschlagen/nicht ausgeführt
Offene Risiken: [falls vorhanden]
Nächster sinnvoller Task: [Vorschlag]
rotate_me: ja/nein [bei Compaction oder vollem Context]
```
Dieses Format in den Worker-Prompt einbauen (session-context.md).

### Permission-Risk-Planung

Tasks mit hohem Permission-Risiko (Schreiben in `./`, Systemkonfiguration)
in einer dedizierten Lane bündeln — ein Worker, sequenziell.
Andere Tasks parallel auf den übrigen Workern.

### Zeitschätzung

| Komplexität | Dauer |
|-------------|-------|
| Einfach (1-2 Dateien) | 5-8 Min |
| Mittel (3-5 Dateien) | 8-12 Min |
| Komplex (Architektur) | 12-18 Min |
| >20 Min → **aufteilen** | — |

---

## Deep Mode

Für komplexe, lang-laufende Aufgaben. Nutzt die MCB Orchestrator Engine.

### Phase 1: Briefing (5-15 Min)

**Mindestens 5 Rückfragen:**
1. **Ziel** — Was genau? Definition of Done? Zeitrahmen?
2. **Scope** — Welche Dateien/Repos? Was nicht anfassen?
3. **Entscheidungsrahmen** — Architektur, Dependencies, bei Unsicherheit einfach oder optimal?
4. **Risiken** — Was kann schiefgehen? Breakpoints?
5. **Tasks** — Zerlegung in 5-8 Tasks mit Dependencies (DAG)

### Phase 2: Brief erstellen + bestätigen

```json
{
  "goal": "...", "definition_of_done": "...",
  "constraints": {
    "repo_root": "...", "files_allowed": ["src/**"], "files_forbidden": [".env"],
    "no_new_dependencies": true, "style": "existing patterns beibehalten"
  },
  "decision_framework": {
    "when_unsure": "einfacher Ansatz",
    "escalate_when": "scope-Änderung, neue Dependency, Security-relevant"
  },
  "acceptance_criteria": ["Tests grün", "Ruff-clean"],
  "tasks": [
    { "name": "...", "prompt": "...", "depends_on": [], "kind": "implementation",
      "worker_type": "auto", "expected_minutes": 10, "breakpoint_after": false }
  ],
  "config": { "max_workers": 4, "max_hours": 3 }
}
```

**Warte auf explizite Bestätigung.**

### Phase 3: Run starten (MCB API)

```bash
# Run erstellen + Tasks hinzufügen + Brief setzen + starten
RUN=$(curl -sk -X POST https://127.0.0.1:8205/api/orchestrator/runs \
  -H "Content-Type: application/json" -H "Authorization: Bearer admin" \
  -d '{"name": "NAME", "goal": "GOAL"}')
RUN_ID=$(echo $RUN | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# Tasks einzeln hinzufügen (je curl-Aufruf)
curl -sk -X POST "https://127.0.0.1:8205/api/orchestrator/runs/$RUN_ID/tasks" \
  -H "Content-Type: application/json" -H "Authorization: Bearer admin" \
  -d '{"name": "...", "prompt": "...", "depends_on": [], "kind": "implementation", "expected_minutes": 10}'

# Brief + Approve
curl -sk -X POST "https://127.0.0.1:8205/api/orchestrator/runs/$RUN_ID/brief" \
  -H "Content-Type: application/json" -H "Authorization: Bearer admin" \
  -d '{"briefing": BRIEF_JSON}'
curl -sk -X POST "https://127.0.0.1:8205/api/orchestrator/runs/$RUN_ID/approve" \
  -H "Authorization: Bearer admin"
```

### Phase 4: Watchdog + Phasen-Iteration

Watchdog-Script nach `/tmp/orch-watchdog.sh` schreiben: inspiziert Sessions,
auto-accepts Permissions, räumt idle Worker auf. Dann 1-Min-Loop:
`sleep 60 && /tmp/orch-watchdog.sh` mit `run_in_background: true`.

**Phasen-Workflow:**
1. Run starten (4-6 Tasks, disjunkte Dateien)
2. Watchdog bis alle fertig → Committen
3. Idle Sessions aufräumen
4. Strategy Council (optional, alle 2-3 Phasen: Claude + Codex parallel)
5. Nächste Phase planen basierend auf Ergebnissen
6. **Zeittracking mit `date`** — vor jeder neuen Phase

---

## Worker-Lifecycle (alle Modes)

### Session spawnen — 4-Step PFLICHT

**NIEMALS** nur `POST /api/sessions` — das erstellt tmux ohne Auftrag.

```bash
# Step 1: Session erstellen
RESP=$(curl -sk https://127.0.0.1:8205/api/sessions \
  -X POST -H "Authorization: Bearer admin" -H "Content-Type: application/json" \
  -d '{"name": "SESSION_NAME"}')
SID=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
TMUX=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['tmux_name'])")
CWD="/home/maetzger/mcb-workdirs/$TMUX"

# Step 2: session-context.md schreiben (Base-Context + Task + Routing)
BASE_CTX=$(cat ./data/worker-base-context.md 2>/dev/null)
ROUTING=$(cat ./data/skill-routing-block.md 2>/dev/null)
cat > "$CWD/session-context.md" << CONTEXT
$BASE_CTX

# Session Handoff — TASK_TITEL

## Auftrag
DETAILLIERTER_AUFTRAG_HIER

## Relevante Dateien
- pfad/zur/datei.py — Beschreibung

## Constraints
- Was nicht angefasst werden darf

## Definition of Done
- Abnahmekriterien

## Callback-Format (PFLICHT bei Fertigmeldung)
Dein Done-Callback MUSS enthalten:
- Status: done|partial|blocked|error
- Geänderte Dateien: datei1.py, datei2.py
- Tests: bestanden/fehlgeschlagen/nicht ausgeführt
- Offene Risiken: [falls vorhanden]
- Nächster sinnvoller Task: [Vorschlag]
- rotate_me: ja/nein [bei Compaction oder vollem Context]

CODEX-KONSULTATION (PFLICHT bei >50 Zeilen Code-Änderung):
Nutze den /codex Skill bevor du größere Code-Änderungen schreibst.
uv run ./tools/codex-multi.py auto -q

$ROUTING
CONTEXT

# Step 3: tmux resize (PFLICHT — sonst 10x5)
tmux resize-window -t "$TMUX" -x 120 -y 35

# Step 4: Warten + Prompt senden
sleep 8
curl -sk https://127.0.0.1:8205/api/terminal/send \
  -X POST -H "Authorization: Bearer admin" -H "Content-Type: application/json" \
  -d "{\"session_id\": \"$SID\", \"text\": \"Lies session-context.md und führe den Auftrag aus.\", \"submit\": true}"
```

### Worker-Prompt Qualität

Jeder Prompt MUSS enthalten:
- **Was** — konkretes Ziel (nicht vage)
- **Wo** — welche Dateien/Projekte
- **Definition of Done** — Abnahmekriterien
- **Constraints** — was nicht anfassen
- **Codex-Block** — IMMER (Worker ignorieren CLAUDE.md Codex-Regel)

### Re-Tasking (Session wiederverwenden)

```bash
python3 ./tools/dispatch-helper.py send "SessionName" \
  "Erledigt. Neuer Auftrag: [DETAILLIERT]. Definition of Done: [KRITERIEN]."
```

**Re-Tasken wenn:** Folge-Task im selben Kontext, Worker hat Vorwissen, Task <15 Min.
**Neue Session wenn:** Anderer Kontext, Worker verschmutzt, nach Compaction.
**Limit:** Max 5-8 Re-Tasks pro Session.

### Session schließen

```bash
curl -sk -X DELETE "https://127.0.0.1:8205/api/sessions/$SID" -H "Authorization: Bearer admin"
```

Vor jedem neuen Spawn: idle Sessions prüfen + schließen.

### Graceful Shutdown

Wenn Matthias den Run abbrechen will:
1. Aktive Worker über `dispatch-helper.py send` informieren: "Aufgabe abgebrochen. Aktuellen Stand committen und fertig melden."
2. Auf Callbacks warten (max 2 Min)
3. Verbleibende Sessions schließen
4. User über Stand informieren

---

## Monitoring (alle Modes)

### Dispatch-Helper Tool

```bash
python3 ./tools/dispatch-helper.py status    # Alle Sessions mit Status
python3 ./tools/dispatch-helper.py ping      # Nur Handlungsbedarf
python3 ./tools/dispatch-helper.py accept mc4-XXX  # Permission akzeptieren
python3 ./tools/dispatch-helper.py send "Name" "Msg"  # Nachricht senden
python3 ./tools/dispatch-helper.py sessions  # JSON Name→ID Mapping
```

**IMMER dispatch-helper.py statt roher tmux/curl-Befehle.**

### Heartbeat (Adaptives Intervall)

| Situation | Intervall |
|-----------|-----------|
| Default | **1 Min** |
| 2-3x kein Handlungsbedarf | 3 Min |
| Nach Permission-Accept | **5 Sek** (oft kommen weitere) |
| 3x Quick-Pings ok | Zurück auf 1 Min |
| Maximum | **5 Min** |

Technisch: `sleep 60 && python3 ./tools/dispatch-helper.py ping`
mit `run_in_background: true`. Bei Return sofort nächsten Ping starten.

**ALLE Sessions prüfen** — nicht nur eigene Worker.

### Permission-Hotspot

Session hat 2+ Permissions in 3 Pings → Hotspot. Alle 10-15s pingen bis 3x clean.
Typisch: Sessions die in `./` schreiben.

### Callbacks

Worker melden sich per `[WORKER-CALLBACK]`:
- **DONE** → Ergebnis bewerten → Re-Task oder Session schließen
- **QUESTION** → Selbst beantworten oder an Matthias weiterleiten
- **ERROR** → Session inspizieren → Retry oder Matthias informieren

---

## Anti-Patterns

| NIEMALS | IMMER |
|---------|-------|
| Code selbst schreiben | Base-Context + Routing-Block in session-context.md |
| Recherche/Analyse machen | Codex-Block in Worker-Prompts (>50 Zeilen) |
| Session ohne Context spawnen | Vor neuem Spawn: idle Sessions prüfen |
| Resize vergessen (10x5) | Heartbeat solange Worker aktiv |
| Callbacks ignorieren | Zeittracking bei guided + deep |
| Codex inline aufrufen | User bei Mode-Eskalation informieren |

## Bekannte Pitfalls

1. **HTTPS nicht HTTP** — API auf Self-Signed Cert → `curl -sk`
2. **depends_on** vergleicht gegen Task-IDs UND -Namen
3. **MAX_SESSIONS = 100** — bei vielen Workers prüfen
4. **Permission trotz --dangerously-skip-permissions** — bei File-Creates. Heartbeat löst das.
5. **Codex in Workers: 5-15 Min** — normal, nicht stuck
6. **Gleiche Datei, mehrere Agents** — Inkonsistenz-Risiko! Immer disjunkte Bereiche.
7. **Context-Compaction** — nach Compaction neue Session statt Re-Task
8. **Dead Pane ≠ tote Session** — `tmux has-session` reicht nicht, prüfe `#{pane_dead}`
9. **Orphan Tasks** — Tasks ohne session_id die "running" sind → Timeout nach 15 Min
10. **analysis + auto** — wurde früher an Codex-Inline geroutet. Jetzt normale Claude-Sessions.
11. **MCB-Restart nötig** nach orchestrator.py-Fixes — DB manuell patchen als Workaround
12. **Sofort-Check nach Callback** — nach jedem Callback ALLE Sessions prüfen, nicht auf nächsten Ping warten
