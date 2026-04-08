# Tutorial-Pipeline: Wissen & Regeln

> Gesammeltes Wissen aus der Entwicklung des Annotation-Tools, Report-Renderers,
> und der Tutorial-Erstellung (Teams-Webinar, SharePoint-Tracking).
> Stand: März 2026.

## Toolchain-Übersicht

```
Recherche → Screenshots → Annotieren → JSON → Rendern → Check → Fertig
   |             |             |           |         |         |
fast-search  Playwright   annotate-   report-   report-   report-
 + crawler    browser    screenshot  renderer   renderer   check.py
                .py          .py       .py       .py
```

## 1. Recherche

- **Immer** `fast-search.py` + `research-crawler.py` Pipe-Pattern
- Pipe funktioniert: `fast-search.py "q1" "q2" | research-crawler.py --max-chars 6000`
- stdout/stderr sauber trennen: `> result.json 2>stats.log` (NIE `2>&1` in result!)
- MS Support/Learn URLs sind oft 404 oder Auth-geschützt → kein Bot-Protection-Problem
- Für SharePoint/Teams-Docs: Oft bessere Infos auf Drittseiten (office365itpros.com, sharepointmaven.com)

## 2. Screenshots capturen

- **Playwright MCP** für Web-Screenshots (MS-Doku-Seiten mit embedded UI)
- MS-Portale (purview.microsoft.com, admin.microsoft.com) brauchen Auth → keine Screenshots möglich
- Bei Auth-geschützten Portalen: Text-basierte Steps statt Screenshots (trotzdem klar und effektiv)
- `browser_take_screenshot` mit `fullPage: true` für Gesamtseite
- **Token-Sparregel**: Screenshot ZUERST (token-leicht), DOM-Snapshot NUR bei Auffälligkeiten

## 3. Screenshot-Annotation

### Tool: `~/.claude/tools/annotate-screenshot.py`

**Config-JSON Format:**
```json
{
    "input": "/tmp/screenshot.png",
    "output": "/tmp/annotated.png",
    "title": "Schritt N: Titel",
    "padding": {"right": 260, "left": 10, "top": 10, "bottom": 10},
    "scale": 2,
    "annotations": [
        {
            "num": 1,
            "label": "Beschreibung der Aktion",
            "target": [x, y],
            "badge": [x_badge, y_badge],
            "highlight": [x1, y1, x2, y2]
        }
    ]
}
```

### Design-Regeln
- **Max 3 Annotations** pro Screenshot — weniger = klarer
- **Badge-Y ≈ Target-Y** → horizontale Pfeile, kein Content-Crossing
- **Padding** rechts (260px) für Badges, wenn Badges rechts vom Bild sitzen
- **Rendering**: 2x deviceScaleFactor via System-Chromium (`/usr/bin/chromium`)
- **Stil**: Copper Accent `#cf865a`, Dark BG `#1f1e1c` (aus Report Design-System)

### Wann KEINE Annotations
- Wenn das Bild für sich selbst spricht (z.B. Lobby-Wartescreen)
- Trotzdem Title setzen + in Report einbinden (Kontext-Bild)

## 4. Report-JSON erstellen

### Renderer-API (ZUERST lesen, dann JSON bauen!)

**Guide-Template** (`type: "guide"`):
```json
{
    "type": "guide",
    "title": "...",
    "subtitle": "...",
    "prerequisites": ["...", "..."],
    "steps": [
        {
            "title": "Step-Titel",
            "body": "Markdown + HTML (img, details, strong, code)",
            "tip": "Optionaler Tipp (grüne Callout-Box)",
            "warning": "Optionale Warnung (gelbe Callout-Box)",
            "code": "Optionaler Code-Block (copyable)"
        }
    ],
    "sources": [
        {"url": "https://...", "title": "Quellen-Titel"}
    ],
    "metrics": {"Recherche": "N Quellen, Q X/10", "Stand": "Monat Jahr"}
}
```

### Kritische Feldnamen
- Quellen: `"title"` (NICHT `"label"`)
- Steps: `"body"`, `"tip"`, `"warning"`, `"code"`
- Bilder im Body: `<img src="dateiname.png" alt="..." style="width:100%;max-width:700px;border-radius:6px;border:1px solid var(--border);margin-top:0.8rem">`
- Collapsibles: `<details class="collapse"><summary>Titel</summary><div class="collapse-body">Inhalt</div></details>`

### Content-Hierarchie (Matthias' Prinzip)
- **Haupttext**: Nur Kern-Aktionen, maximal concise
- **Collapsibles**: Details, Alternativen, Code, Vorlagen
- **Tips**: Zusätzliche nützliche Infos
- **Warnings**: Bekannte Probleme, Einschränkungen

## 5. Rendern + Verifizieren

### Optimierter 1-Zyklus-Flow
```bash
# 1. Rendern
python3 ~/.claude/tools/report-renderer.py render auto data.json -o ~/shared/reports/name.html

# 2. Automatischer Check
python3 ~/.claude/tools/report-check.py ~/shared/reports/name.html --fix

# 3. Visueller Check (Screenshot, NICHT DOM-Snapshot)
# HTTP-Server starten → Playwright Screenshot → Server stoppen
```

### report-check.py prüft automatisch
- SAFE-Marker-Leaks (Null-Byte und ohne)
- Leere Source-Links (falsche Feldnamen)
- Unbalancierte `<details>` Tags
- Fehlende Bilder (relative Pfade)
- Escaped HTML wo Tags sein sollten
- Step-Nummern-Sequenz

### Renderer-Bugs (gefixt, aber merken)
- **SAFE-Marker Restore**: MUSS in umgekehrter Reihenfolge (N→0), sonst verschwinden
  verschachtelte Tags (z.B. `<img>` in `<details>`)
- **`<details>` Protection**: Wurde in `md()` Funktion hinzugefügt (Zeile 67)

## 6. Bilder verwalten

- Annotierte Bilder nach `~/shared/reports/img-{projekt}-{step}.png` kopieren
- Dateinamen konsistent: `img-teams-step1.png`, `img-sharepoint-filter.png` etc.
- Bilder VOR dem Rendern kopieren (Renderer braucht sie nicht, aber MC3 Download-Endpoint schon)

## 7. Anti-Patterns (aus echten Fehlern)

| Anti-Pattern | Stattdessen |
|---|---|
| Pillow für Annotations | Playwright HTML-Overlay |
| 5+ Annotations/Screenshot | Max 3, nur was nicht offensichtlich ist |
| Feldnamen raten | Renderer-Code LESEN (`_sources_html()`, `render_guide()`) |
| `2>&1` in Result-Datei | stdout und stderr IMMER trennen |
| `grep -c` für Zählung | `grep -ao PATTERN \| wc -l` |
| DOM-Snapshot als Erst-Check | Screenshot zuerst (token-leicht) |
| Tool-Output nicht selbst lesen | JEDES Ergebnis auf Errors prüfen (0 OK, 404, etc.) |
| Auf falschem Ansatz iterieren | Pivot wenn Medium fundamental limitiert ist |
| Alle Infos auf einer Ebene | Collapsibles für Details, Haupttext nur Kern-Aktionen |

## 8. Tutorial-Typen (Referenz)

### Typ A: Visuelles Tutorial (wie Teams-Webinar)
- Zielgruppe: Endanwender, wenig technisch
- Viele annotierte Screenshots, wenig Text
- Jeder Step hat mindestens 1 Screenshot
- Collapsibles für Experten-Details

### Typ B: Admin-Tutorial (wie SharePoint-Tracking)
- Zielgruppe: IT-Admin, technisch versiert
- Text-basierte Steps, Code-Blöcke
- Screenshots nur wo UI nicht intuitiv
- PowerShell/CLI-Befehle in Collapsibles
- Antwort-Vorlage für den Endanwender

### Entscheidungsmatrix
| Signal | → Typ |
|---|---|
| Endanwender, UI-basiert | A (visuell) |
| Admin, CLI/Portal | B (text-basiert) |
| Screenshots verfügbar (keine Auth) | A |
| Portal braucht Auth | B |
| Wiederkehrendes Problem | B + Automation-Empfehlung |
