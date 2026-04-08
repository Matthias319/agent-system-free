---
name: Agent E-Mail (mail.tm)
description: Disposable Agent-E-Mail mcb-agent@sharebot.net — für VAPID, Registrierungen, Verifikationen. Agent kann Inbox selbst per REST API lesen.
type: reference
---

**Agent-E-Mail**: `mcb-agent@sharebot.net`

Erstellt am 2026-04-04 via mail.tm REST API. Credentials in `~/.claude/.env` unter `AGENT_EMAIL`, `AGENT_EMAIL_PASS`, `AGENT_EMAIL_ID`.

## Wann nutzen
- Wenn Matthias "Agent-Mail" oder "Agent-E-Mail" sagt → das ist diese Adresse
- Für Web-Service-Registrierungen (TikTok, APIs, etc.)
- Für VAPID Claims (Web Push Notifications) — aktuell in MCB `.env` und `core/config.py`
- Für Verifikations-Mails die der Agent selbst lesen soll

## Inbox lesen (REST API)

```bash
# 1. Token holen
source ~/.claude/.env
TOKEN=$(curl -s -X POST https://api.mail.tm/token \
  -H "Content-Type: application/json" \
  -d "{\"address\": \"$AGENT_EMAIL\", \"password\": \"$AGENT_EMAIL_PASS\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

# 2. Inbox abrufen
curl -s https://api.mail.tm/messages -H "Authorization: Bearer $TOKEN"

# 3. Einzelne Mail lesen
curl -s https://api.mail.tm/messages/{MESSAGE_ID} -H "Authorization: Bearer $TOKEN"
```

## Hinweis
- mail.tm Domains rotieren — `sharebot.net` könnte irgendwann ablaufen
- Bei Domain-Wechsel: neuen Account erstellen, Credentials updaten
- API-Docs: https://docs.mail.tm
