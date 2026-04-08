---
name: HTML-Dateien nach ~/shared/reports/ ablegen
description: Erstellte HTML-Dateien und zugehörige Assets IMMER nach ~/shared/reports/ ablegen mit Datums-Prefix, damit sie über MCV4 File Management Tab erreichbar sind
type: feedback
---

Erstellte HTML-Dateien (Reports, Einladungen, Guides etc.) IMMER nach `/home/maetzger/shared/reports/` kopieren.

**Namenskonvention:** `YYYY-MM-DD-beschreibung.html` (wie die bestehenden Dateien dort).

**Why:** Die MCB-Workdirs (`/home/maetzger/mcb-workdirs/mc4-*/`) sind über das MCV4 File Management Tab nicht sichtbar. `~/shared/reports/` ist der Sammelordner für alle HTML-Outputs und dort über MCV4 erreichbar.

**How to apply:** Nach dem Erstellen einer HTML-Datei im Workdir immer automatisch eine Kopie nach `~/shared/reports/` legen mit Datums-Prefix. Zugehörige Assets (Screenshots, Bilder) ebenfalls dorthin. Keine Rückfrage nötig — einfach machen.
