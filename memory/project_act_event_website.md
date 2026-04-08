---
name: act legal Event-Website (Strato)
description: Aktuelle Events auf event.act.legal — Kicker 21.05.2026, Tennis 18.06.2026. CGI-Backend, Power Automate Email, SQLite-Registrierung.
type: project
---

## Aktuelle Events (Stand 2026-03-29)

| Event | Datum | URL-Pfad |
|-------|-------|----------|
| **KICK & CONNECT — Private Equity Tischkicker Night** | 21.05.2026, 17:00 | `/kicker` |
| **4. ACT Frankfurt Open** (Tennis) | 18.06.2026 | `/tennis` |

## Architektur

- **Hosting**: event.act.legal auf Strato (Details in `reference_strato_subdomains.md`)
- **Frontend**: Single-File HTML pro Event (inline CSS+JS), act legal Design (Ladislav/Corbel Fonts, #5483ad)
- **Backend**: Python-CGI (`cgi-bin/app.py`) — Registrierung → SQLite + Power Automate Email
- **Admin**: https://event.act.legal/cgi-bin/app.py/admin (Basic Auth)
- **Lokales Projekt**: `/home/maetzger/Projects/act-event-poc/` (FastAPI-PoC, nicht Strato-Produktion)

### Struktur auf dem Server

```
event.act.legal/
├── kicker/index.html + danke.html
├── tennis/index.html + danke.html
├── cgi-bin/app.py + data/
├── assets/ (Logos, Fonts, Hero-Bilder)
└── registrations.db
```

**Why:** Primäre Quelle für "die Webseite" / "act legal Event" — immer Strato-Hosting gemeint.

**How to apply:** Für Details zum SFTP-Workflow: siehe `reference_strato_subdomains.md`. Für neue Events: Ordner anlegen, HTML aus bestehendem Event kopieren, CGI-Backend erweitern.
