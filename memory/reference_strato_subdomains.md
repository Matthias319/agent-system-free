---
name: Strato Webhosting — 3 Subdomains mit SFTP-Zugang
description: Schnellzugriff auf event.act.legal, quickshare.act.legal und project.act.legal — Credentials, Deploy-Workflow und Dateien bearbeiten.
type: reference
---

## Strato Webhosting — act legal

3 Subdomains auf Strato, alle per SFTP erreichbar. Credentials in `~/.claude/.env` (vorher `source ~/.claude/.env`).

### Subdomains

| Subdomain | Zweck | Env-Prefix | Typische Inhalte |
|-----------|-------|------------|------------------|
| **event.act.legal** | Kanzlei-Events (Anmeldeformulare, Danke-Seiten) | `STRATO_EVENT_*` | HTML-Formulare, CGI-Backend, SQLite |
| **quickshare.act.legal** | Schnell HTMLs/Dateien teilen (Reports, Dashboards) | `STRATO_QUICKSHARE_*` | Einzelne HTML-Dateien direkt ins Root |
| **project.act.legal** | Kanzlei-Projekte (je Projekt ein Ordner) | `STRATO_PROJECT_*` | Ordner pro Projekt, z.B. `/relaunch/` |

### Deploy-Workflow (für alle drei identisch)

```bash
# 1. Credentials laden
source ~/.claude/.env

# 2. Dateien herunterladen (Beispiel: event)
sshpass -p "$STRATO_EVENT_PASS" sftp -P 22 "$STRATO_EVENT_USER@$STRATO_SFTP_HOST" <<'EOF'
get pfad/auf/server lokaler-name
EOF

# 3. Lokal bearbeiten (Edit/Write Tools)

# 4. Hochladen
sshpass -p "$STRATO_EVENT_PASS" sftp -P 22 "$STRATO_EVENT_USER@$STRATO_SFTP_HOST" <<'EOF'
put lokaler-name pfad/auf/server
EOF
```

Für quickshare/project: `STRATO_QUICKSHARE_*` bzw. `STRATO_PROJECT_*` statt `STRATO_EVENT_*`.

### event.act.legal — Dateistruktur

```
event.act.legal/
├── cgi-bin/app.py          ← Python-CGI-Router (Registrierung, Dashboard, Email)
├── kicker/
│   ├── index.html          ← Kicker-Anmeldeformular
│   └── danke.html          ← Danke-Seite nach Anmeldung/Absage
├── tennis/
│   ├── index.html          ← Tennis-Anmeldeformular
│   └── danke.html          ← Danke-Seite
├── assets/
│   ├── event/
│   │   ├── act-logo-white.png
│   │   ├── calendar.ics    ← Tennis-Kalender
│   │   └── kicker-calendar.ics
│   ├── font-ladislav-*.woff2
│   ├── font-calibre-*.woff2
│   ├── font-corbel-*.woff2
│   └── favicon.ico
└── registrations.db        ← SQLite (Anmeldungen aller Events)
```

### event.act.legal — Admin-Dashboard

- **URL:** https://event.act.legal/cgi-bin/app.py/admin
- **Login:** Basic Auth (User/Pass im CGI-Script als `DASHBOARD_USER`/`DASHBOARD_PASS`)
- **Features:** Registrierungen ansehen, filtern nach Event, Excel-Export
- **Email-Versand:** Bestätigungsmails über Power Automate (URL im CGI-Script)

### Arbeitsweise für Änderungen

1. Dateien per SFTP in `/tmp/strato-*` herunterladen
2. Lokal bearbeiten und testen
3. Per SFTP hochladen
4. Im Browser verifizieren (Playwright)

**How to apply:** Bei jeder Arbeit an act legal Webseiten zuerst prüfen, welche Subdomain betroffen ist, dann den SFTP-Workflow nutzen. Keine lokale Kopie des Repos — alles lebt auf Strato.
