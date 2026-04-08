---
name: html-reports
description: "Erstellt standalone HTML-Deliverables im Warm Dark Editorial Design"
triggers:
  - "als Report"
  - "als HTML"
  - "Dashboard"
  - "Analyse-Bericht"
  - "Vergleichstabelle"
  - "visuell aufbereiten"
  - "Präsentation"
not_for:
  - "reine Textantworten"
  - "Code-only Output"
---

# HTML Reports -- Single Source of Truth

Zentralisiertes Skill für alle HTML-Report-Generierung UND das Design-System. Ersetzt duplizierte CSS-Tokens, HTML-Boilerplate und Animationen in system-check, session-recap, skill-stats und web-search. Gleichzeitig die einzige Quelle der Wahrheit für Design-Entscheidungen im "Warm Dark Editorial" System.

## Entscheidungsregel: HTML vs Plain Text

| Kriterium | Plain Text | HTML Report |
|-----------|-----------|-------------|
| Länge | <= 3 Sätze | > 3 Sätze oder strukturierte Daten |
| Datentyp | Einzelwert, Ja/Nein | Tabellen, Metriken, Vergleiche, Listen |
| Zielgruppe | Terminal-Output | Visueller Konsum (Browser) |
| Komplexität | Einfache Antwort | Mehrere Sektionen, KPIs, Charts |

**Faustregel:** Wenn die Antwort von visueller Hierarchie profitiert, generiere HTML.

## PFLICHT: Visuelle Elemente in JEDEM Report

**Kein Report darf reiner Fließtext sein.** Jeder Report MUSS mindestens 3 verschiedene visuelle Komponenten enthalten. Reiner Fließtext mit Überschriften ist KEIN akzeptabler Report.

### Minimum pro Report:
1. **Hero Section** mit gefüllten Stats (nicht leer!)
2. **Highlights** (3-4 Key Findings als nummerierte Liste)
3. Mindestens EINE der folgenden: Callout Box, Data Table, Bar Chart, Progress Bar, Key Insight, Stat Cards

### Bevorzugt den report-renderer.py verwenden:
Der Renderer (`./tools/report-renderer.py`) hat ein Auto-Enrichment das text-heavy Reports automatisch mit visuellen Elementen anreichert. JSON-Daten bereitstellen statt manuell HTML schreiben.

```bash
echo '<JSON>' | python3 ./tools/report-renderer.py render auto -o ~/shared/reports/TOPIC-YYYY-MM-DD.html
```

### Wenn manuell HTML geschrieben wird:
Vor dem Schreiben die Inhalte in visuelle Komponenten aufteilen:
- Aufzählungen → `items[]` (Bullet-Liste mit Accent-Dots)
- Zahlen/Metriken → Stat Cards oder KPI-Grid
- Warnungen → Callout Boxes (warn/tip/info)
- Vergleiche → Data Table oder Feature Matrix
- Kernaussagen → Key Insight Blocks oder Pullquotes

## Quick Start

1. `Read references/foundation.md` -- Boilerplate kopieren (PFLICHT für jeden Report)
2. Komponenten wählen (siehe Component Picker unten) -- **mindestens 3 verschiedene!**
3. Pattern wählen (siehe Pattern Picker unten)
4. Report schreiben nach `~/shared/reports/TOPIC-YYYY-MM-DD.html`

## Component Picker

| Datentyp | Komponente | Referenz |
|----------|-----------|----------|
| KPIs, Einzelwerte, Metriken | Metric Card Grid | `references/components.md` #2 |
| Listen, strukturierte Daten | Data Table | `references/components.md` #6 |
| Fortschritt, Auslastung | Progress Bar | `references/components.md` #3 |
| Numerische Vergleiche | Horizontal Bar Chart | `references/components.md` #4 |
| Service-Status, Health | Status Dot | `references/components.md` #8 |
| Warnungen, Hinweise | Callout Box | `references/components.md` #7 |
| Lange Details, optional | Collapsible Section | `references/components.md` #6 |
| Seitentitel, Kontext | Hero Section | `references/components.md` #1 |
| Gruppierte Inhalte | Card | `references/components.md` #9 |
| Report-Ende, Meta | Footer | `references/components.md` #10 |

## Pattern Picker

| Use Case | Pattern | Referenz |
|----------|---------|----------|
| System-Monitoring, Skill-Stats | Dashboard | `references/patterns.md` #1 |
| Recherche, Analyse, Fakten | Data Report | `references/patterns.md` #2 |
| Session-Recap, Chronologie | Timeline | `references/patterns.md` #3 |
| Produktvergleich, Market-Check | Comparison | `references/patterns.md` #4 |

## Output-Konvention

- Pfad: `~/shared/reports/TOPIC-YYYY-MM-DD.html`
- TOPIC in Kleinbuchstaben, Bindestriche (z.B. `system-check`, `flight-comparison`)
- Am Ende dem User den vollstaendigen Pfad ausgeben
- Datei muss standalone sein (kein externer JS, nur Google Fonts CDN)

## Referenz-Dateien laden

| Datei | Wann laden |
|-------|-----------|
| `references/foundation.md` | **IMMER** -- HTML-Boilerplate, CSS-Tokens, Animationen |
| `references/components.md` | Wenn Komponenten gebaut werden (fast immer) |
| `references/patterns.md` | Wenn ein ganzer Report-Typ gewaehlt wird |
| `references/philosophy.md` | Bei Design-Entscheidungen, Grenzfällen, neuen Komponenten |
| `references/interactive.md` | Nur wenn JS-Interaktivitaet benötigt (Sortierung, Tabs, Copy) |

## Quality Checklist

Vor dem Schreiben des Reports prüfen:

- [ ] Foundation-Boilerplate als Basis verwendet
- [ ] `<meta name="viewport">` vorhanden (responsive)
- [ ] Google Fonts Link korrekt (Newsreader + Outfit)
- [ ] Alle CSS-Werte aus Custom Properties (keine hardcoded Farben)
- [ ] `prefers-reduced-motion` Media Query vorhanden
- [ ] Hero Section als erstes sichtbares Element
- [ ] **Hero-Stats haben Werte** (keine leeren hero-stat-value Divs!)
- [ ] **Mindestens 3 verschiedene visuelle Komponenten** (nicht nur Fließtext!)
- [ ] **Bullet-Listen als items[], nicht als Fließtext mit Bindestrichen**
- [ ] Keine externen JS-Dependencies (nur Vanilla JS)
- [ ] Semantic HTML (`<main>`, `<section>`, `<header>`, `<footer>`)
- [ ] Responsive: Grid auf 1 Spalte bei < 768px
- [ ] Alle Farben WCAG AA konform (Kontrast >= 4.5:1)
- [ ] Output-Pfad folgt Konvention (`~/shared/reports/TOPIC-YYYY-MM-DD.html`)
