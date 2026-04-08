---
name: Codex (GPT-5.4) — Pflicht-Sparringspartner
description: Codex ist MANDATORY bei allen nicht-trivialen Aufgaben. Sparring-Workflow mit parallelem Denken, Vergleich und Difference-Tracking.
type: feedback
---

Codex (GPT-5.4) ist MANDATORY, nicht optional. Immer konsultieren bei:
- Code-Änderungen >50 Zeilen
- Architektur- und Design-Entscheidungen
- Datenanalyse und -verarbeitung
- Bug-Diagnose bei nicht-trivialen Fehlern
- Jede Entscheidung mit langfristiger Auswirkung

## Sparring-Workflow (IMMER)

1. **Codex starten** mit vollständigem Kontext (Sachverhalt + relevante Dateien)
2. **Während Codex inferiert**: Eigene Analyse machen, Stichpunkte notieren
3. **Codex-Output lesen**, mit eigenen Stichpunkten **vergleichen**
4. **Interessante Differences tracken** — in reference_codex_diffs.md oder DB
5. **Synthese** dem User präsentieren: Wo stimmen wir überein, wo nicht, bester Ansatz

**Why:** Matthias will den Bias eines einzelnen Modells eliminieren. Zwei unabhängige LLMs senken die Fehlerrate quadratisch (5% × 5% = 0.25%). Codex hat komplementäre Stärken (besseres Code Review, konsistenter, stärker bei Terminal-Workflows). Matthias hat explizit gesagt: "du sollst es einfach selber machen" — nicht warten bis er Codex anfordert.

**How to apply:**
- **PROAKTIV**: Bei größeren Code-Änderungen, komplexen Entscheidungen, Faktenchecks → Codex eigenständig einbeziehen
- **Kontext ist King**: Codex hat kein Gedächtnis — immer vollen Kontext mitgeben
- Arbeitsteilung: Claude = Lead/Orchestrierung, Codex = Gatekeeper/Verifikation/Sparring
- factual-risk gewinnt immer vor Stil/Präferenz
- Skill `/codex` enthält vollständige Trigger-Regeln
- Multi-Account-Rotation: 3 Seats, `codex-multi.py auto -q` vor jeder Nutzung

**Domänen-Routing (User-Präferenz):**
- **Design/Visuell** → Claude allein (Matthias vertraut Opus hier)
- **Coding + intellektuelles Nachdenken** → IMMER Codex als paralleler Sparringspartner
