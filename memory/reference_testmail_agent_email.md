---
name: testmail.app — Agent Email System
description: API-basiertes Email-Postfach für autonome Tests (PA-Mails prüfen, Registrierungen verifizieren). Kein Login, kein IMAP, kein 2FA nötig.
type: reference
---

## testmail.app — Agent Email (eingerichtet 2026-03-25)

**Zweck:** Autonomes Postfach für den Agent — Mails empfangen und per HTTP API lesen. Kein Browser-Login, kein IMAP, kein 2FA.

### Credentials (in ~/.env-agent)

```
TESTMAIL_API_KEY=4b7b5150-2fc5-4266-8156-fa5ce7af0b5f
TESTMAIL_NAMESPACE=ycukk
TESTMAIL_ADDRESS=ycukk.agent@inbox.testmail.app
```

### Adressen-Schema

`ycukk.{tag}@inbox.testmail.app` — der Tag kann frei gewählt werden und erstellt automatisch ein separates virtuelles Postfach.

| Adresse | Zweck |
|---------|-------|
| `ycukk.agent@inbox.testmail.app` | Standard-Adresse |
| `ycukk.kicker@inbox.testmail.app` | Kicker-Event Tests |
| `ycukk.tennis@inbox.testmail.app` | Tennis-Event Tests |
| `ycukk.{beliebig}@inbox.testmail.app` | On-the-fly für jeden Zweck |

### API-Nutzung

```bash
# Alle Mails im Namespace
curl -s "https://api.testmail.app/api/json?apikey=$TESTMAIL_API_KEY&namespace=ycukk&pretty=true"

# Nach Tag filtern (= virtuelles Postfach)
curl -s "https://api.testmail.app/api/json?apikey=$TESTMAIL_API_KEY&namespace=ycukk&tag=agent"

# Pagination
&limit=5&offset=0

# Zeitfilter (Unix-Timestamp in Millisekunden)
&timestamp_from=1774470000000

# EML-Rohdatei downloaden
# → downloadUrl Feld in jedem Mail-Objekt
```

### Verfügbare Mail-Felder

`subject`, `from`, `from_parsed`, `to`, `to_parsed`, `cc`, `html`, `text`, `attachments`, `date`, `timestamp`, `tag`, `namespace`, `messageId`, `envelope_from`, `envelope_to`, `SPF`, `dkim`, `downloadUrl`, `id`

### Limits (Free Plan)

- **100 Emails/Monat** empfangen + parsen
- Unbegrenzte API-Calls
- 1 Namespace, 1 API-Key
- Attachments bis 10MB
- **Emails werden nach 24h gelöscht** — bei Bedarf sofort lesen
- Kein Wildcard-Tag-Filter (nur exakter Match oder kein Tag = alle)

### Typischer Workflow: PA-Mail prüfen

```python
import json, urllib.request, os

API_KEY = os.getenv("TESTMAIL_API_KEY")
url = f"https://api.testmail.app/api/json?apikey={API_KEY}&namespace=ycukk&tag=kicker"
data = json.loads(urllib.request.urlopen(url).read())
for mail in data["emails"]:
    print(f'{mail["subject"]} — von {mail["from"]}')
    print(mail["text"][:200])
```

### Account-Verwaltung

- **Login:** Passwordless via `olyn.miguel@minafter.com` (10-Minuten-Mail, verfallen)
- **Zugang wiederherstellen:** Neuen Account mit neuer Temp-Mail erstellen (30 Sekunden)
- **Dashboard:** https://testmail.app/console/ (nur wenn eingeloggt)
- **Docs:** https://testmail.app/docs/

### Warum testmail.app statt Gmail/IMAP?

- Gmail blockiert Playwright (headless browser), IMAP braucht App-Password + 2FA
- testmail.app braucht nur einen HTTP GET-Request — funktioniert überall
- Registrierung mit Wegwerf-Email möglich — kein Google-Account nötig
