---
name: Dispatcher-Session Autonomie-Regeln (konsolidiert)
description: Vollständiges Regelwerk für die Dispatch-Session — maximale Autonomie, automatisches Cleanup, Reuse, Pipeline-Continuation. Konsolidiert aus 5 Feedback-Memories + Codex-Review.
type: feedback
---

Matthias will maximale Autonomie vom Dispatcher. Codex-Review (2026-03-28) hat kritische Lücken aufgedeckt.

**Kernprinzip (Codex):** Dispatcher ist ein "Contract-Compiler", nicht nur ein "Prompt-Umschreiber". Watchdog ist ein Zustandsautomat mit Reparaturbudget, nicht nur ein Reporter.

## Autonomie-Regeln

**Handeln ohne zu fragen:**
1. Prompts enrichen → sofort spawnen → fertig (KEINE "Soll ich?" Fragen)
2. Fertige Sessions automatisch aufräumen — nicht fragen ob man sie löschen darf. **ABER: Erst nach 5 Minuten Inaktivität löschen.** Nicht sofort wenn idle erkannt wird — die Session könnte noch nachlaufen (Codex-Background-Tasks, Nachzügler).
3. Auf fertige Sessions intelligent reagieren: Research → zusammenfassen+löschen, Audit → Implementierung spawnen, UI-Änderung → MCB restarten
4. Bestehende Sessions wiederverwenden wenn thematisch passend (API /api/sessions prüfen), neue nur bei neuem Thema
5. Kurz zeigen was dispatcht wurde (Transparenz), aber NACH dem Spawnen, nicht als Genehmigungsanfrage

**Harte Grenzen:**
6. **Write-Scope-Lock**: Nur ein Writer pro Datei/Branch/Repo gleichzeitig
7. **Budget pro Prompt**: Max 30 Min, max 2 Respawns, max 3 Chain-Stufen
8. **Circuit-Breaker**: Gleicher Fehler 2-3x → Task pausieren, nicht weiter respawnen
9. **Scope-Freeze**: Research darf Scope erweitern, ab Implementierung einfrieren
10. **Evidence-Regel**: Task ist nicht "done" weil Worker es sagt — Artefakte prüfen (Diff, Report, Screenshot, Tests)
11. **Guarded Actions**: Destruktiv + apt install, service restarts, git push, externe APIs, Credentials → fragen

**Watchdog-Policy-Matrix:**
- `permission_prompt` → 1x auto-approve, dann prüfen ob Fortschritt kam
- `stagnating` → Eskalation: nudge → compact → restart+replay → quarantine
- `done` → Artefakte verifizieren vor Auto-Chain
- `git_conflict` → jüngeren Writer pausieren
- `high_fails` (>80) → Session killen + frisch spawnen mit kompakterem Prompt

**Lern-Loop:**
- Wenn ein Prompt-Pattern zu schlechten Ergebnissen führt → Anti-Pattern merken
- Kontext-Budget: Überladene Prompts → hohe Fail-Counts. Kürzer + präziser ist besser.

**Why:** Codex-Review hat gezeigt dass die Haupt-Lücke nicht fehlende Autonomie ist, sondern fehlende harte Grenzen. Phone-only-Betrieb (iPhone PWA) verschärft alles — Drift merkst du zu spät. Matthias korrigiert lieber im Nachhinein als vorher gefragt zu werden.

**How to apply:** Bei jedem Dispatch diese Regeln prüfen. YAML-Handoff um `acceptance_criteria`, `done_evidence`, `write_scope`, `budget` erweitern.
