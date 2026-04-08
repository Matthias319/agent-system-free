---
name: session-labels
description: "Benennt offene MCB Terminal-Tabs mit smarten, themenbasierten Labels um"
triggers:
  - "Tabs umbenennen"
  - "Sessions labeln"
  - "Übersicht aufräumen"
  - "Tab-Namen"
not_for:
  - "neue Sessions erstellen"
  - "Session-Inhalt durchsuchen"
---

# Session Labels — Smart Tab-Benennung für Mission Control V3

Du benennst alle offenen Terminal-Sessions in Mission Control V3 mit kurzen, aussagekräftigen Namen,
damit der User auf einen Blick sieht, worum es in jeder Session geht.

## Phase 1: Sessions + Kontext abrufen

```bash
# 1. Alle aktiven Sessions mit Claude-Session-IDs holen
curl -s http://localhost:8205/api/sessions | jq -r '.[] | select(.is_active == true) | "\(.id)\t\(.name)\t\(.claude_session_id)\t\(.tmux_name)"'
```

## Phase 2: Thema jeder Session erkennen

Für jede Session: Die ersten User-Messages aus dem JSONL-Transcript lesen.

```bash
# Pro Session: Erste 3 User-Nachrichten extrahieren (reicht für Thema-Erkennung)
JSONL=./projects/-home-maetzger/CLAUDE_SESSION_ID.jsonl
grep '"type":"user"' "$JSONL" 2>/dev/null | head -3 | jq -r '
  .message.content | if type == "array" then
    [.[] | select(.type == "text") | .text] | join(" ")
  else tostring end
' 2>/dev/null | head -c 500
```

**Für die AKTUELLE Session:** Du kennst den Kontext bereits aus dem Chatverlauf — kein Transcript nötig.

**Falls JSONL leer/nicht vorhanden:** Session ist neu/idle → Name: "Neue Session".

## Phase 3: Namen generieren

Regeln:
- **Max 20 Zeichen** (passt in die Tab-Breite)
- **Deutsch** bevorzugt, Englisch bei Tech-Begriffen ok
- **Spezifisch**, nicht generisch — "UFW Audit" statt "Sicherheit", "Thesis Kap. 3" statt "Masterarbeit"
- **Keine Nummerierung** — kein "Terminal 1", kein "#1"
- **Neue/leere Sessions:** "Neue Session"
- **Beispiele guter Namen:** "Advocatus Diaboli", "Anthropic Papers", "MCB Tabs", "Git Backup"

## Phase 4: Tabs umbenennen

```bash
# Pro Session: PATCH-Request an MCB API
curl -s -X PATCH http://localhost:8205/api/sessions/SESSION_ID \
  -H "Content-Type: application/json" \
  -d '{"name": "Neuer Name"}'
```

## Phase 5: Ergebnis anzeigen

Zeige eine kompakte Tabelle:

| Vorher | Nachher | Thema |
|--------|---------|-------|
| Terminal 1 | Advocatus Diaboli | Systemaudit + UFW-Fixes |
| Terminal 2 | Anthropic Papers | Forschungs-Recherche |
| Terminal 3 | Neue Session | (leer) |
