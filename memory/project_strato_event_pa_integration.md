---
name: Strato Event — Power Automate Email Integration
description: CGI-Script auf event.act.legal sendet Bestätigungs-Emails über Power Automate nach Registrierung (Kicker + Tennis).
type: project
---

## Power Automate Integration (eingerichtet 2026-03-25)

**Why:** Teilnehmer sollen nach Registrierung eine designte HTML-Bestätigungsmail erhalten — wie bei der alten FastAPI-App, aber jetzt über Strato CGI.

**How to apply:** Bei Änderungen an Registrierungs-Flows oder Email-Templates diese Datei konsultieren.

### Architektur

```
User registriert sich → Strato CGI (app.py) → SQLite-Eintrag
                                             → urllib.request POST an PA-URL
                                             → Power Automate sendet HTML-Email
```

### PA-URL (1 Flow für alle Events)

Die URL ist im CGI-Script hardcodiert (`POWER_AUTOMATE_URL`). Der Flow unterscheidet Events über den Payload, nicht über separate URLs.

### Payload-Format

```json
{
    "to": "teilnehmer@email.de",
    "subject": "Anmeldebestätigung — EVENT TITEL",
    "body_html": "<html>...volles HTML-Template...</html>",
    "ics_content": "BEGIN:VCALENDAR...",
    "recipient_name": "Max Mustermann"
}
```

### Email-Templates (inline im CGI-Script)

- Dynamische Anrede via `_formal_salutation()` (Herr/Frau, Titel-Erkennung)
- Event-spezifischer Body je nach `participation_type` (active/spectator/decline)
- Veranstaltungsdetails-Card (Datum, Uhrzeit, Ort + Google Maps)
- Reminder-Box (Tennis: "Bitte mitbringen", Zuschauer: "Leibliches Wohl")
- Kalender-Link + ICS-Attachment
- Website-CTA (nur Tennis → Canva-Seite)
- Logo: `https://event.act.legal/assets/event/act-logo-white.png`
- Fonts: Ladislav von `https://event.act.legal/assets/font-ladislav-bold.woff2`

### Event-Konfiguration

| Event | Datum | Uhrzeit | Ort | ICS |
|-------|-------|---------|-----|-----|
| Kicker | 21.05.2026 | ab 17:00 Uhr | Zeppelinallee 77, Frankfurt | kicker-calendar.ics |
| Tennis | 18.06.2026 | ab 16:00 Uhr | SAFO, Kennedyallee 129, Frankfurt | calendar.ics |

### Strato-Dateien

```
event.act.legal/
├── cgi-bin/app.py          ← CGI-Router mit PA-Integration
├── kicker/index.html       ← Anmeldeformular
├── kicker/danke.html       ← Danke-Seite
├── tennis/index.html       ← Anmeldeformular
├── tennis/danke.html       ← Danke-Seite
├── assets/event/
│   ├── act-logo-white.png  ← Logo für Emails
│   ├── calendar.ics        ← Tennis ICS
│   └── kicker-calendar.ics ← Kicker ICS
└── assets/
    ├── font-ladislav-bold.woff2
    └── font-ladislav-regular.woff2
```

### Bekannte Einschränkungen

- CGI-Script schluckt PA-Fehler still (`except Exception: pass`) — Email-Versand darf Registrierung nicht blockieren
- ICS wird als `ics_content` im Payload geschickt — ob PA das als Attachment anhängt hängt vom Flow ab
- DKIM: `none` (PA sendet über Outlook, nicht über act.legal Domain)
