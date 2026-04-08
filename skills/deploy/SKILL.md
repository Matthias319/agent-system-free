---
name: deploy
description: "Deployt Dateien/Reports auf Strato-Subdomains (quickshare, project, event) via SFTP"
triggers:
  - "deploy"
  - "hochladen"
  - "veröffentlichen"
  - "online stellen"
  - "teilen"
  - "share"
  - "auf quickshare"
  - "auf project"
  - "auf event"
not_for:
  - "lokale Dateioperationen"
  - "Git Push"
  - "Tailscale-Konfiguration"
---

# Deploy — Strato SFTP Deployment

Deployt Dateien und Reports auf die 3 act legal Strato-Subdomains.

**Helper**: `./tools/deploy.py`
**Credentials**: `./.env` (STRATO_*)

## Tracking + Self-Heal (PFLICHT)

```bash
RUN_ID=$(./tools/skill-tracker.py start deploy --context '{"target": "TARGET", "files": N}')
./tools/skill-tracker.py heal deploy
```

Am Ende:

```bash
./tools/skill-tracker.py metrics-batch $RUN_ID '{"target": "TARGET", "files_uploaded": N, "total_size_kb": N}'
./tools/skill-tracker.py complete $RUN_ID
```

## Target-Routing

| Target | Subdomain | Wann nutzen |
|--------|-----------|-------------|
| **quickshare** | quickshare.act.legal | HTML-Reports, schnell Dateien teilen, Dashboards |
| **project** | project.act.legal | Kanzlei-Projekte mit eigenem Ordner (z.B. `/relaunch/`) |
| **event** | event.act.legal | Event-Seiten, Einladungen, Anmeldungsformulare |

**Auto-Detect**: Wenn kein Target angegeben → aus Dateiname/Pfad ableiten:
- `event`, `einladung`, `anmeldung` im Pfad → event
- `project`, `kanzlei`, `relaunch` im Pfad → project
- Alles andere → quickshare (Default)

## Schritt 1: Target bestimmen

Aus dem User-Prompt oder $ARGUMENTS das Target ableiten:
- Explizit genannt ("auf quickshare", "nach project") → Target direkt verwenden
- Nicht genannt → `auto` nutzen (Helper leitet ab)

## Schritt 2: Upload

```bash
source ./.env
uv run ./tools/deploy.py upload <TARGET> <LOKALER_PFAD> [--remote-dir <ORDNER>]
```

**Beispiele:**

```bash
# Report auf quickshare (direkt ins Root)
uv run ./tools/deploy.py upload quickshare ~/shared/reports/system-check.html

# Projekt-Seite in Unterordner
uv run ./tools/deploy.py upload project ~/Projects/relaunch/dist/ --remote-dir relaunch

# Event-Seite
uv run ./tools/deploy.py upload event /tmp/einladung-sommerfest.html

# Auto-Detect Target
uv run ./tools/deploy.py upload auto ~/shared/reports/analyse.html
```

## Schritt 3: Ergebnis melden

Lies das JSON-Output und formatiere:

```
Deploy erfolgreich ✓
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Target:  quickshare.act.legal
Dateien: 1 hochgeladen
URL:     https://quickshare.act.legal/system-check.html
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Bei Fehler: stderr aus dem JSON anzeigen und Troubleshooting-Hinweis geben.

## Weitere Befehle

### Dateien auf Remote auflisten

```bash
source ./.env
uv run ./tools/deploy.py list <TARGET> [--remote-dir <ORDNER>]
```

### Verfügbare Targets anzeigen

```bash
uv run ./tools/deploy.py targets
```

## Token-Budget: 1-2 Calls

| Aktion | Calls | Tools |
|--------|-------|-------|
| Upload | 1 | Bash (source + upload) |
| Upload + Verify (list) | 2 | Bash (upload) + Bash (list) |
| **Max Total** | **2** | — |

## Fehlerbehandlung

- **"Missing credentials"**: `./.env` existiert nicht oder STRATO_*-Variablen fehlen
- **SFTP timeout**: Netzwerk-Problem, Strato down, oder falsche Credentials
- **"Local path not found"**: Datei/Verzeichnis existiert nicht → Pfad prüfen
- **Permission denied**: SFTP-User hat keine Schreibrechte im Zielverzeichnis
