---
name: JSON Skills Format — Experiment abgeschlossen
description: JSON-Skills-Experiment (skill.v1 Schema) wurde per A/B-Test widerlegt. Markdown bleibt Prompt-Format, JSON optional als Companion.
type: project
---

Am 2026-03-31 wurde begonnen, alle Skills von Markdown auf ein strukturiertes JSON-Format (`skill.v1`) umzustellen. **A/B-Test am 2026-04-01 hat gezeigt: Markdown ist klar besser als JSON als LLM-Prompt-Format.**

## A/B-Test-Ergebnis (2026-04-01, anti-hallucination Skill, Claude Sonnet 4.6)

| Metrik | Markdown | JSON |
|--------|----------|------|
| Trigger-Rate | 100% | 75% |
| Routing-Korrektheit | 100% | 50% |
| Constraint-Violations | 0 | 3 |
| Quality Score | 5.0 | 4.5 |
| Latenz | 190s | 120s (schneller, aber schlechter) |

**Fazit:** LLMs verstehen tief verschachteltes JSON schlechter als natürlichsprachliche Prosa. `match_any`-Arrays und verschachtelte `workflow.phases.steps` werden weniger zuverlässig befolgt als Markdown-Überschriften.

## Entscheidung

- **SKILL.md bleibt das Prompt-Format** (wird dem LLM serviert)
- **SKILL.json ist optional** als maschinenlesbares Companion (Routing-Daten, Validierung, exports, Tests)
- Bei neuen Skills: Markdown zuerst, JSON nur wenn Tooling-Bedarf besteht

## Schema: skill.v1 (für Companion-JSONs)

**Required**: `schema_version` ("skill.v1"), `metadata`, `activation`, `workflow`
**Optional**: `routing`, `tools`, `exports`, `constraints`, `budgets`, `tracking`, `output_contract`, `resources`, `tests`

Schlüsselfelder:
- **activation**: `when_to_use[]`, `not_for[]`, `examples[{input, should_activate}]`
- **routing**: Graph aus decision/action/terminal Nodes, `entry`-Point, `branches` mit `match_any`-Hints
- **tools**: Typisiert als `bash|mcp|skill|builtin`, mit `priority` und `capture_stdout_as`
- **exports**: Macht Skills als Sub-Tools aufrufbar (`entry_phase`, `input_schema`, `output_schema`)
- **constraints**: `must[]`, `must_not[]`, `anti_patterns[]`
- **tests**: Eingebettete Eval-Cases (`id`, `input`, `checks[]`)

Vollständiges Schema: `/home/maetzger/.claude/skills/docs/2026-04-01-json-skills-design.md`
Codex-Designentscheidungen: `/tmp/claude-1001/...` (Sitzungsoutput, flüchtig)

## Status (2026-04-01)

**Konvertiert (6 Skills):**
- `/home/maetzger/.claude/skills/session-labels/SKILL.json`
- `/home/maetzger/.claude/skills/tasks/SKILL.json`
- `/home/maetzger/.claude/skills/codex/SKILL.json`
- `/home/maetzger/.claude/skills/social-research/SKILL.json`
- `/home/maetzger/.claude/skills/anti-hallucination/SKILL.json`
- `/home/maetzger/.claude/skills/system-check/SKILL.json`

**Offen (laut Reihenfolge in Design-Doc):**
- market-check, web-search (letzter, größter Skill)

## Token-Overhead

JSON ist deutlich größer als Markdown:
- anti-hallucination: +150% (4.4KB → 11KB)
- system-check: +71% (4.2KB → 7.2KB)

Kein Token-Vorteil, schlechtere Qualität → Markdown gewinnt eindeutig.

## Kreative Möglichkeiten (Post-MVP)

- Skill-Composability: `{"$ref": "web-search#tools.fast_search"}` — Tools zwischen Skills teilen
- Auto-Routing-Engine: liest alle `activation`-Arrays, routet automatisch
- Skill-Linting: CI-Check ob Required Fields vollständig
- Export-Registry: alle `exports` als aufrufbare Funktions-Registry
