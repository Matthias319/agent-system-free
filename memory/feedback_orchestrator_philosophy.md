---
name: Orchestrator-Philosophie
description: Matthias' Vision für den Orchestrator — intensive Planungsphase, dann volle Autonomie. Worker sollen Codex konsultieren. Kein API-Limit-Problem (Claude Max Plan, ~20% Nutzung/Woche).
type: feedback
---

Orchestrator soll wie ein "richtig guter Assistent" funktionieren:
- **Anfangs viele Fragen stellen** — Scope verstehen, Präferenzen lernen, Transferwissen aufbauen
- **Dann volle Autonomie** — eigenständig Entscheidungen treffen basierend auf dem gelernten Kontext
- **Rückfragen an Worker sind GUT** — zwingt zu tieferem Nachdenken, beleuchtet mehrere Aspekte
- **Codex-Konsultation ist PFLICHT** für Worker bei komplexen Coding-Fragen (wir haben die Assets, müssen sie nutzen)
- **Kein API-Limit-Problem** — Claude Max Plan, typisch ~20% Woche. "Let's go, Vollgas geben"
- **Laufzeit: mehrere Stunden** (nicht 24/7, aber 2-4h autonome Arbeit)
- **User-Eingriff nur bei echten strategischen Entscheidungen**, nicht bei "darf ich Datei X bearbeiten"

**Why:** Matthias will nicht Micro-Manager spielen. Die kleinen Unterbrechungen (Permission-Prompts, triviale A/B-Fragen) sollen weg. Aber die inhaltlich wertvollen Rückfragen (die zum Nachdenken zwingen) sollen vom Orchestrator beantwortet werden, nicht wegoptimiert.

**How to apply:** Orchestrator-Skill muss eine intensive "Briefing-Phase" haben wo er den User ausfragt. Danach wird dieses Briefing zum Entscheidungsrahmen für alle Worker-Fragen.
