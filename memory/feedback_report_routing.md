---
name: HTML-Report Routing und Pattern-Wahl
description: Bei Produkt-/Marktrecherchen IMMER HTML-Report erstellen. Template-Wahl: deep-research-v2 für alles mit Produkten/Preisen, research nur für Text-Briefings.
type: feedback
---

Bei Produkt-, Markt- oder Kaufberatungssuchen IMMER einen HTML-Report erstellen statt nur Text-Antwort.

**Why:** Matthias will polierte, browsbare Ergebnisse. Text-Walls im Terminal sind nutzlos bei Links und Vergleichen. Agent wählte einmal `research` (simpelstes Template) für Kaufberatung — Ergebnis war visuell extrem simpel.

**How to apply:**
1. Erst Pattern bestimmen (Product/Deep/Lokal/Hybrid)
2. Dann Renderer-Typ ableiten (fast immer `deep-research-v2` — hat ALLE visuellen Komponenten)
3. `research` NUR bei reinem Fließtext ohne Produkte/Preise/Deals
4. Für deep-research-v2 PFLICHT: pullquotes[], keyfacts[], source_bars[], kernaussage
5. Bei Agents: REPORT_ROUTE vor Spawn festlegen, Agent darf nicht neu routen
6. Volle Doku: `Read ~/.claude/skills/web-search/references/presentation-system.md`
