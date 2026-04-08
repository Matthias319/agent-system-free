# Skill-Routing (PFLICHT — vor Arbeit prüfen)

Du hast Zugriff auf spezialisierte Skills die BESSER sind als native Tools.
Prüfe bei JEDER Aufgabe ob ein Skill passt. Skills werden mit `/skill-name` aufgerufen.

| Aufgabe | Skill | NICHT verwenden wenn |
|---------|-------|---------------------|
| Web-Recherche, Fakten, Preise, Vergleiche | `/web-search` | Meinungen/Community → `/social-research` |
| Reddit/YouTube/TikTok Meinungen, Erfahrungen | `/social-research` | Reine Fakten → `/web-search` |
| Gebrauchtpreise (Kleinanzeigen) | `/market-check` | Neupreise → `/web-search` |
| Flüge, Reiseziele, Flugpreise | `/flights` | Travel-Tipps → `/social-research` |
| Code-Review, Architektur (>50 Zeilen) | `/codex` | Triviale Edits → direkt machen |
| Parallele Session in eigenem Tab | `/spawn-session` | Tasks <2 min → hier machen |
| Frühere Sessions/Arbeit finden | `/pi-search` | Web-Recherche → `/web-search` |
| HTML-Report/Dashboard erstellen | `/html-reports` | Plain Text → direkt antworten |
| System-Health-Check | `/system-check` | App-Debugging → direkt debuggen |
| Iterativ optimieren | `/autoresearch` | Einmaliger Fix → direkt machen |
| Aufgabe zur Task-Liste hinzufügen | `/tasks` | Session-interner Fortschritt → TaskCreate |
| Inbox-Dateien verarbeiten → Todos | `/todo-extract` | Einzelne Aufgabe → `/tasks` |
| MC V5 Tabs umbenennen | `/session-labels` | Neue Session → `/spawn-session` |
| Faktenverifikation, API-Docs, Versions-Claims | `/anti-hallucination` | Meinungsfragen → direkt antworten |
| Lang-laufende autonome Agent-Arbeit (Stunden) | `/orchestrate` | Agent-Tool für kurze Tasks |
| Deploy, hochladen, veröffentlichen, online stellen, teilen | `/deploy` | Lokale Dateioperationen, Git Push |
| Logs, journalctl, Fehler suchen, was ist passiert, warum crashed | `/log-analyse` | System-Health-Check → `/system-check` |

**Wichtig:**
- `/web-search` nutzt `fast-search.py` + `research-crawler.py` — 60x schneller als natives WebSearch
- `/social-research` nutzt `youtube-intel.py` + `reddit-mcp-query.py` — strukturierter als Web-Crawling
| JS-heavy Seite scrapen, SPA, Login-Flow, Formular, Cookie-Wall | `/browser-scrape` | Allgemeine Recherche → `/web-search` |
