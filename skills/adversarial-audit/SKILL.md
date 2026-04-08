---
name: adversarial-audit
disable-model-invocation: false
description: "Attack/Defense Ping-Pong Security Audit mit zwei isolierten AI-Sessions"
triggers:
  - "adversarial audit"
  - "security audit"
  - "pentest"
  - "attack/defense"
  - "code audit"
  - "red team"
not_for:
  - "einfache Code-Reviews"
  - "einmalige Security-Fragen"
  - "Compliance-Checklisten"
---

# Adversarial Audit — Attack/Defense Ping-Pong Framework

Du bist jetzt der **Audit-Orchestrator**. Deine Rolle: ein strukturiertes Attack/Defense Audit konfigurieren, Attacker- und Defender-Sessions spawnen, Reports einsammeln, State mergen und auf Konvergenz prüfen.

**Kernidee:** Attacker und Defender sind isolierte AI-Sessions die sich gegenseitig nicht sehen. Der Attacker sucht Schwachstellen, der Defender fixt sie. Über mehrere Runden konvergiert die Codebase gegen einen sicheren Zustand. Alle Kommunikation läuft über strukturierte JSON-Reports.

**Isolation (v1):** Die Isolation ist per Prompt erzwungen, nicht technisch. Reports liegen im Target-Repo und Worker könnten theoretisch fremde Reports lesen. Für den Single-User-Einsatz auf diesem Server ist das akzeptabel — die Prompt-Isolation reicht, weil es keinen Anreiz zum Schummeln gibt. Für höhere Isolation: Worktrees oder getrennte Artifact-Verzeichnisse pro Rolle nutzen.

## State Machine

```
INIT → ATTACK(1) → DEFEND(1) → VERIFY(1) → ATTACK(2) → DEFEND(2) → VERIFY(2) → ... → [CONVERGED | MAX_ROUNDS]
```

| State | `current_phase` | `lifecycle_state` | Beschreibung |
|-------|----------------|-------------------|-------------|
| `INIT` | `attacker` | `planned` | Config erstellen, Artifact-Verzeichnisse anlegen, initialen State schreiben |
| `ATTACK(n)` | `attacker` | `running` | Attacker-Session(s) spawnen, `round-report.json` einsammeln |
| `DEFEND(n)` | `defender` | `running` | Defender-Session(s) spawnen, `fix-report.json` einsammeln |
| `VERIFY(n)` | `attacker` | `running` | Orchestrator mergt State, berechnet Convergence, entscheidet: nächste Runde oder Stop. Kein eigener Phase-Wert — der Orchestrator setzt `current_phase` direkt auf `attacker` für die nächste Runde. |
| `CONVERGED` | `complete` | `converged` | Alle Thresholds erfüllt — Audit erfolgreich abgeschlossen |
| `MAX_ROUNDS` | `complete` | `max_rounds_reached` | Max-Runden erreicht ohne Konvergenz — offene Findings dokumentieren |

**Hinweis:** `current_phase` zeigt immer die **nächste auszuführende** Phase. INIT und VERIFY sind Orchestrator-intern und brauchen keinen eigenen Phase-Wert.

## Phase 0: Briefing (mit Matthias)

Frage mindestens ab:

1. **Target**: Was wird auditiert? (Repo-Pfad, Branch, Art)
2. **Scope**: Welche Pfade/Surfaces rein, welche raus?
3. **Tiefe**: Max Runden? Code-Änderungen erlaubt?
4. **Schwellwerte**: Ab welcher Severity muss gefixt werden? Wann ist konvergiert?
5. **Parallelismus**: Wie viele Attacker/Defender gleichzeitig?

Erstelle daraus eine `audit-config.json` (Schema: `schemas/audit-config.schema.json`) und zeige sie Matthias zur Bestätigung.

## Phase 1: INIT

Nach Bestätigung der Config:

```bash
# 1. Artifact-Verzeichnisse im Target-Repo anlegen
TARGET_ROOT="<aus config.target.root_path>"
BASE_DIR="$TARGET_ROOT/<aus config.artifact_paths.base_dir>"
mkdir -p "$BASE_DIR" "$TARGET_ROOT/<round_reports_dir>" "$TARGET_ROOT/<fix_reports_dir>"

# 2. Config speichern
# audit-config.json → $BASE_DIR/audit-config.json

# 3. Initialen audit-state.json schreiben
# lifecycle_state: "planned", state_revision: 0, current_logical_round: 1
# Leere finding_index, round_index, queues
```

Config-Hash berechnen und in `audit-state.json → config_ref.sha256` speichern:
```bash
sha256sum "$BASE_DIR/audit-config.json" | cut -d' ' -f1
```

## Phase 2: ATTACK(n) — Attacker-Sessions spawnen

Für jede Attacker-Instanz (bis `config.execution.parallelism.attacker_instances_max`):

### Session spawnen (MCB API)

```bash
RESP=$(curl -sk https://127.0.0.1:8205/api/sessions \
  -X POST -H "Authorization: Bearer admin" -H "Content-Type: application/json" \
  -d '{"name": "audit-atk-r<ROUND>-<INSTANCE>"}')
SID=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
TMUX=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['tmux_name'])")
CWD="/home/maetzger/mcb-workdirs/$TMUX"
```

### Attacker-Prompt (in session-context.md)

Der Attacker bekommt:
- Die `audit-config.json` (vollständig)
- Den aktuellen `audit-state.json` (vollständig)
- Alle bisherigen `fix-report.json` der letzten Runde (falls vorhanden)
- **Nicht:** Vorherige `round-report.json` anderer Attacker (Isolation!)

**Attacker-Anweisungen:**

```
Du bist ein Security-Attacker in einem strukturierten Adversarial Audit.

DEINE ROLLE:
- Analysiere den Code im Target-Repository auf Schwachstellen
- Prüfe ob vom Defender behauptete Fixes tatsächlich wirken
- Erstelle einen round-report.json nach dem Schema

REGELN:
- Du darfst den Code LESEN aber NICHT ÄNDERN
- Jedes Finding braucht: Reproduktionsschritte, Evidence, CWE-Klassifikation
- Verwende finding_id = <PREFIX>-<sha256(canonical_key)[:12]>
- canonical_key = weakness.id|normalized_path|symbol|attack_surface|exploit_vector
- Bereits verified_fixed Findings nicht erneut reporten
- Bei Fixes die du verifizieren sollst: attacker_verdict = "verified_fixed" oder "reopened"
- Neue Findings die durch Fixes eingeführt wurden: introduced_by_fix_ids setzen

OUTPUT:
Schreibe deinen Report als JSON nach: <round_reports_dir>/rr-<ROUND>-<INSTANCE_ID>.json
Dann Callback senden.
```

### Report einsammeln

Nach Callback: `round-report.json` aus dem Artifact-Verzeichnis lesen und validieren.

## Phase 3: DEFEND(n) — Defender-Sessions spawnen

Für jede Defender-Instanz (bis `config.execution.parallelism.defender_instances_max`):

### Defender-Prompt (in session-context.md)

Der Defender bekommt:
- Die `audit-config.json`
- Den aktuellen `audit-state.json`
- Alle `round-report.json` dieser Runde
- **Nicht:** Vorherige `fix-report.json` anderer Defender (Isolation!)

**Defender-Anweisungen:**

```
Du bist ein Security-Defender in einem strukturierten Adversarial Audit.

DEINE ROLLE:
- Analysiere die Findings aus den Attacker-Reports
- Implementiere Fixes für Findings ab Severity "<fix_required_at_or_above>"
- Erstelle einen fix-report.json nach dem Schema

REGELN:
- Du darfst den Code ÄNDERN wenn config.execution.allow_code_changes = true
- Jedes Finding braucht eine Disposition: claimed_fixed, wontfix, mitigated, etc.
- Bei wontfix: wontfix_reason_code und compensating_controls PFLICHT
- Validiere deine Fixes (Tests, manuelle Prüfung)
- Dokumentiere target_snapshot_before und target_snapshot_after
- Achte darauf, keine neuen Schwachstellen durch deine Fixes einzuführen

OUTPUT:
Schreibe deinen Report als JSON nach: <fix_reports_dir>/fr-<ROUND>-<INSTANCE_ID>.json
Committe deine Code-Änderungen auf Branch: audit/r<ROUND>-fixes
Dann Callback senden.
```

## Phase 4: VERIFY(n) — State mergen und Convergence prüfen

Nach Eingang aller Reports einer Runde:

### 1. State-Merge — Vollständige Transition-Tabelle

**Attacker-Verdicts → State-Updates:**

| `attacker_verdict` | `workflow_status` | `risk_status` | `current_owner` | Zusätzlich |
|--------------------|-------------------|---------------|-----------------|------------|
| `open` (neues Finding) | `open` | `active` | `defender` | Neuen Eintrag in `finding_index` anlegen |
| `open` (bekanntes Finding) | unverändert | unverändert | unverändert | `last_seen_round` aktualisieren |
| `reopened` | `open` | `active` | `defender` | `reopen_count += 1`, in `pending_defender_action` |
| `verified_fixed` | `verified_fixed` | `mitigated` | `none` | Aus allen Queues entfernen |
| `not_reproducible` | `not_reproducible` | `closed` | `none` | History-Event loggen |
| `duplicate` | `duplicate` | `closed` | `none` | `duplicate_of_finding_id` setzen |

**Defender-Dispositions → State-Updates:**

| `defender_status` | `workflow_status` | `risk_status` | `current_owner` | Zusätzlich |
|-------------------|-------------------|---------------|-----------------|------------|
| `claimed_fixed` | `fixed_pending_verification` | `active` | `attacker` | In `pending_attacker_verification` |
| `partially_fixed` | `open` | `active` | `defender` | Bleibt in `pending_defender_action` |
| `mitigated` | `open` | `mitigated` | `shared` | Attacker soll Mitigation prüfen |
| `wontfix` | `wontfix` | `accepted` | `none` | `wontfix_reason_code` + `compensating_controls` PFLICHT |
| `duplicate` | `duplicate` | `closed` | `none` | `duplicate_of_finding_id` PFLICHT |
| `needs_more_info` | `open` | `active` | `attacker` | In `pending_attacker_verification` |
| `deferred` | `open` | `active` | `defender` | Bleibt offen, wird nicht geblockt |

**Bei jedem State-Update IMMER:**
- `history`-Array um neuen Event ergänzen (logical_round, event, source_report_id, status_after, risk_status_after)
- `latest_round_report_id` bzw. `latest_fix_report_id` aktualisieren
- `linked_fix_ids` ergänzen wenn Defender einen Fix verlinkt

### 2. Parallel-Merge (bei mehreren Attacker-Instanzen)

**v1: Nur `dedupe-by-canonical-key` ist implementiert.** Die anderen Strategien sind für spätere Versionen reserviert.

- **dedupe-by-canonical-key** (einzige v1-Strategie): Findings mit gleichem `canonical_key` werden dedupliziert. Höhere Severity gewinnt. Bei gleicher Severity: höhere Confidence gewinnt.

**v1-Einschränkung für parallele Defender:**
Wenn `allow_code_changes = true`, dann `defender_instances_max = 1` (erzwungen). Mehrere Defender auf demselben Branch erzeugen Race Conditions. Mehrere read-only Defender (Analyse ohne Code-Änderungen) sind erlaubt.

### 3. Convergence-Score berechnen

```
convergence_score = 1.0 - open_risk_weight - regression_penalty - verification_backlog_penalty
```

Wobei (Severity-Ordnung: Critical > High > Medium > Low):
- `open_risk_weight` = gewichtete Summe offener Findings (Critical=1.0, High=0.6, Medium=0.3, Low=0.1), normalisiert auf [0,1]
- `regression_penalty` = reopened_findings / max(total_findings, 1) (Regression = besonders schlecht)
- `verification_backlog_penalty` = fixed_pending_verification / max(total_findings, 1)

Bei `total_findings = 0` (leere Runde): `convergence_score = 1.0` (keine Findings = konvergiert).

### 4. Stop-Entscheidung

Audit ist **konvergiert** wenn ALLE Bedingungen erfüllt:
- Keine neuen Findings >= `converged_when.no_new_findings_at_or_above`
- Null offene Findings >= `converged_when.open_findings_must_be_zero_at_or_above`
- `consecutive_clean_rounds` >= `converged_when.required_consecutive_attacker_rounds`
- `convergence_score` >= `converged_when.minimum_convergence_score`

Sonst: nächste Runde (zurück zu ATTACK(n+1)), es sei denn `max_rounds` erreicht.

### 5. State aktualisieren

- `state_revision += 1`
- `current_logical_round` und `current_phase` aktualisieren
- `round_index` ergänzen
- `queues` aktualisieren (pending_defender_action, pending_attacker_verification)
- `audit-state.json` schreiben

## Phase 5: Abschluss

Bei Konvergenz oder Max-Rounds:

1. `lifecycle_state` auf `"converged"` oder `"max_rounds_reached"` setzen
2. `current_phase` auf `"complete"` setzen
3. Finalen `audit-state.json` schreiben
4. **HTML-Report** generieren (via `/html-reports` Skill) mit:
   - Audit-Zusammenfassung (Runden, Findings, Convergence-Score)
   - Finding-Tabelle mit Lifecycle-Historie
   - Offene Findings hervorgehoben
   - Timeline der Runden
5. Matthias informieren

## Session-Spawning — Pflichtablauf

Folgt dem `/dispatch`-Pattern (4 Schritte, alle in einem Bash-Block):

```bash
# 1. Session erstellen
RESP=$(curl -sk https://127.0.0.1:8205/api/sessions \
  -X POST -H "Authorization: Bearer admin" -H "Content-Type: application/json" \
  -d '{"name": "audit-atk-r01-a"}')
SID=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
TMUX=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['tmux_name'])")
CWD="/home/maetzger/mcb-workdirs/$TMUX"

# 2. session-context.md schreiben
#    WICHTIG: Base-Context + Routing-Block IMMER einbinden, dann Audit-Handoff
BASE_CTX=$(cat ./data/worker-base-context.md 2>/dev/null || echo "")
ROUTING_BLOCK=$(cat ./data/skill-routing-block.md 2>/dev/null || echo "")

# session-context.md zusammenbauen:
# - $BASE_CTX (Autonomie, Callback-Anweisungen)
# - YAML-Handoff (task, objective, context, relevant_files, constraints, next_steps)
# - Rollenspezifische Anweisungen (Attacker oder Defender)
# - Schema-Referenz (inline oder als Dateipfad)
# - $ROUTING_BLOCK (Skill-Routing für Worker)
#
# NICHT: Heredoc mit Platzhalter-Text. IMMER real expandierte Inhalte.

cat > "$CWD/session-context.md" << CONTEXT
$BASE_CTX

# Session Handoff
... (YAML-Block mit task, objective, etc.)

# Rollenspezifische Anweisungen
... (Attacker- oder Defender-Block, siehe Phase 2/3)

$ROUTING_BLOCK
CONTEXT

# 3. Resize (Pflicht — sonst 10x5 und Claude unbrauchbar)
tmux resize-window -t "$TMUX" -x 120 -y 35

# 4. Warten + Prompt senden
sleep 8
curl -sk https://127.0.0.1:8205/api/terminal/send \
  -X POST -H "Authorization: Bearer admin" -H "Content-Type: application/json" \
  -d "{\"session_id\": \"$SID\", \"text\": \"Lies session-context.md und führe den Auftrag aus.\", \"submit\": true}"
```

**Session-Name-Konvention:** `audit-<rolle>-r<RR>-<instanz>`, z.B. `audit-atk-r01-a`, `audit-def-r02-a`.

## Heartbeat — Sessions überwachen

Wie beim `/dispatch` Skill: Alle Worker-Sessions per tmux-Inspektion überwachen.

```bash
for TMUX in $(tmux list-sessions -F '#{session_name}' 2>/dev/null | grep 'audit-'); do
  echo "=== $TMUX ==="
  tmux capture-pane -t "$TMUX:0.0" -p -e -S -200 2>/dev/null | grep -v '^$' | tail -12
  echo ""
done
```

- Permission-Prompts: Auto-Enter (`tmux send-keys -t "$TMUX:0.0" Enter`)
- Callback empfangen → Report lesen → Session schließen

### Timeout-Handling

Wenn eine Worker-Session `round_timeout_minutes` überschreitet:
1. Session inspizieren (`tmux capture-pane`) — steckt sie fest oder arbeitet sie noch?
2. Wenn stuck: Session schließen, Runde mit vorhandenen Reports fortsetzen
3. Wenn arbeitend: Weitere 50% der Timeout-Zeit gewähren (einmalig)
4. Wenn kein Report geschrieben wurde: Runde als `aborted` loggen, `lifecycle_state` prüfen
5. Partial Reports (JSON valide aber unvollständige Findings): Akzeptieren und in State mergen

Start-Zeitstempel pro Worker merken:
```bash
WORKER_START=$(date +%s)
# ... in Heartbeat-Loop prüfen:
ELAPSED=$(( $(date +%s) - WORKER_START ))
TIMEOUT_SEC=$(( round_timeout_minutes * 60 ))
if [ "$ELAPSED" -gt "$TIMEOUT_SEC" ]; then echo "TIMEOUT: $TMUX"; fi
```

## Dateinamen-Konventionen

| Datei | Pfad | Wann |
|-------|------|------|
| Config | `<base_dir>/audit-config.json` | Einmalig bei INIT |
| State | `<base_dir>/audit-state.json` | Nach jeder Verify-Phase |
| Attacker-Report | `<round_reports_dir>/rr-<RR>-<INSTANCE_ID>.json` | Nach jeder Attack-Phase |
| Defender-Report | `<fix_reports_dir>/fr-<RR>-<INSTANCE_ID>.json` | Nach jeder Defend-Phase |

- `<RR>` = zweistellige Rundennummer (01, 02, ...)
- `<INSTANCE_ID>` = z.B. `attacker-a`, `defender-a`

## Finding-ID-Berechnung

```python
import hashlib
canonical_key = f"{weakness_id}|{normalized_path}|{symbol}|{attack_surface}|{exploit_vector}"
hash_hex = hashlib.sha256(canonical_key.encode()).hexdigest()[:12]
finding_id = f"{prefix}-{hash_hex}"
```

Gleicher `canonical_key` = gleiches Finding über alle Runden hinweg. Ermöglicht Lifecycle-Tracking (discovered → claimed_fixed → reopened → verified_fixed).

## Edge Cases

- **wontfix**: Nur im `fix-report.json` setzen. State-Merge: `workflow_status = "wontfix"`, `risk_status = "accepted"`. Pflichtfelder: `wontfix_reason_code`, `compensating_controls`.
- **Reopen**: Gleicher `finding_id`, gleicher `canonical_key`. `round-report.json`: `attacker_verdict = "reopened"`. State: `reopen_count += 1`.
- **Fix erzeugt neues Problem**: Neuer `finding_id`, aber `introduced_by_fix_ids` zeigt auf die `action_id` des Defender-Fixes.
- **Parallelbetrieb**: Mehrere Attacker/Defender liefern getrennte Reports mit gleichem `logical_round` und unterschiedlichem `producer.instance_id`. Merge läuft über `canonical_key`.
- **Snapshot-Regel**: Jede Datei enthält den gesamten Stand der Findings aus Sicht ihres Produzenten. Fehlende Findings in einem Report bedeuten nicht automatisch "gelöst".

## Regeln

- **IMMER** Config-Phase mit Matthias vor dem Start
- **IMMER** Attacker und Defender in getrennten Sessions (keine Kontamination)
- **IMMER** Reports gegen Schemas validieren bevor State-Merge
- **IMMER** `state_revision` inkrementieren bei jedem State-Update
- **NIE** Attacker und Defender den jeweils anderen Report zeigen (nur über State)
- **NIE** Code-Änderungen ohne `allow_code_changes = true`
- **NIE** Runden überspringen
- **IMMER** Sessions nach Report-Eingang schließen
- **IMMER** Heartbeat während Worker-Sessions aktiv sind

## Schemas

Die JSON-Schemas liegen unter `./skills/adversarial-audit/schemas/`:

| Schema | Datei |
|--------|-------|
| Audit-Konfiguration | `audit-config.schema.json` |
| Attacker Round-Report | `round-report.schema.json` |
| Defender Fix-Report | `fix-report.schema.json` |
| Audit-State (zentral) | `audit-state.schema.json` |

Schemas werden den Worker-Sessions als Referenz mitgegeben (inline im session-context.md oder als Dateipfad).
