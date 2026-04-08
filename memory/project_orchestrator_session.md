---
name: MCB Orchestrator Session — Idee
description: Konzept für eine permanente, angeheftete MCB-Session die als Smart Router fungiert — Query Enrichment + automatisches Session-Spawning
type: project
---

Idee (2026-03-28): Permanente Orchestrator-Session im MCB-Board.

**Konzept:**
- Eine Session die immer läuft und angeheftet ist
- Einzige Aufgabe: Eingehende Prompts mit Query Enrichment optimieren
- Optimierten Prompt an eine neue, frisch gespawnte Session weiterleiten
- Session wird automatisch geöffnet

**Why:** Matthias will einen Management-Layer, damit er Aufgaben nicht immer selbst orchestrieren/dispatchen muss. Die Orchestrator-Session übernimmt die Prompt-Optimierung und das Routing.

**How to apply:** Bei der Implementierung berücksichtigen: bestehende Query-Enrichment-Logik aus dem web-search Skill wiederverwenden, spawn-session Skill als Basis für Session-Spawning, MCB-Board-API für Pinning/Permanenz.
