---
name: presentation-system
description: Presentation System mit 3 Patterns (Product/Deep Research/Lokal-Guide) wurde am 14.03.2026 eingeführt — definiert wie HTML-Reports visuell aufgebaut werden
type: project
---

Am 14.03.2026 wurde das Presentation System für HTML-Reports eingeführt mit 3 bewährten Patterns:

1. **Product Presentation** (Mockup E): Hero + Tabs + Idealo-Links + Comparison Tables
2. **Deep Research** (Mockup F v2): Verified-Badges, Pull Quotes, Key-Fact Callouts, Confidence Gauge, Source Quality Bars, Scroll-Reveal
3. **Lokal-Guide** (Mockup G v2): Quick-Compare Strip, Route Banner, Action Cards, Atmosphere Tags, Insider-Tipps

**Why:** Matthias sieht HTML-Reports als den primären Kommunikationskanal von Claude zu ihm. Reiner Fließtext ist langweilig — visuelle Anker (Pull Quotes, Key-Facts, Stat Cards) verbessern den Lesefluss erheblich.

**How to apply:**
- Pattern-Routing: `~/.claude/skills/web-search/references/presentation-system.md`
- Patterns sind kombinierbar (Mixing-Rules im Dokument)
- Kernregel: Kein Report darf reiner Fließtext sein
- Verified-Badges IMMER einbauen wenn Verifikations-Agent gelaufen ist
- Referenz-Implementierungen: `~/shared/reports/design-showcase.html` (Mockups A-G)
- Idealo-Links funktionieren über Suchseite: `idealo.de/preisvergleich/MainSearchProductCategory.html?q=PRODUKT`

**Report-Renderer (14.03.2026 erweitert):**
- `report-renderer.py` unterstützt jetzt 7 Template-Typen: research, comparison, dashboard, guide, generic, **deep-research-v2**, **lokal-guide**
- Auto-Detection erkennt Pattern anhand JSON-Keys (verified/pullquotes/keyfacts → deep-research-v2, locations/route → lokal-guide)
- 13 neue Generatoren: verified-badge, verified-footer, pullquote, keyfact, conflict-box, kernaussage, insider-tip, route-banner, locations, quickcompare, source-bars, confidence-gauge, mood-tags
- Scroll-Reveal JS-Modul (IntersectionObserver) wird automatisch für v2/guide-Templates injiziert
- Pipeline: SKILL.md → report-mode.md → presentation-system.md → report-renderer.py
