---
name: Immer Opus für Eval-Tests verwenden
description: Bei A/B-Tests und Skill-Evaluationen immer Opus nutzen, nie Sonnet — Sonnet hat andere Stärken/Schwächen und die Ergebnisse sind nicht übertragbar
type: feedback
---

Bei Skill-Format-Tests und Evaluationen IMMER Opus 4.6 als Test-Agent verwenden, nicht Sonnet.

**Why:** Sonnet und Opus verarbeiten strukturierte Instruktionen unterschiedlich. Ein Ergebnis mit Sonnet ist nicht auf Opus übertragbar — und Opus ist unser Production-Modell. Der JSON-vs-Markdown A/B-Test (2026-04-01) lief mit Sonnet, was die Aussagekraft einschränkt.

**How to apply:** In A/B-Test-Scripts `--model opus` statt `--model sonnet` setzen. Kostet mehr Tokens/Zeit, liefert aber die relevanten Daten.
