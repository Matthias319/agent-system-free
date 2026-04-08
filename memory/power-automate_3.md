# Power Automate — Wissen für zukünftige Sessions

## Flow-Definition Schema
- Basiert auf **Azure Logic Apps** Schema (stabil seit 2016)
- Schema-URL: `https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#`
- Reihenfolge im JSON irrelevant — nur `runAfter` bestimmt Ausführungsreihenfolge

## Neuer Designer (v3) — UI-Details (Stand März 2026)
- **Drei-Panel-Layout:** Links=Konfiguration, Mitte=Canvas, Rechts=Copilot
- **Parameters-Tab** links hat: Parameters | Settings | Code View | About
- **Dynamischer Inhalt:** Blitz-Icon, fx-Icon, oder `/` im Feld tippen
- **Apply to each** heißt auf dem Canvas "Foreach"
- **Code View ist read-only** — kein Paste-Import möglich
- Optional-Felder versteckt hinter "Advanced parameters: Show all"

## Add a to-do (V3) — Exakte Felder
| Feld | Key | Required | Typ |
|------|-----|----------|-----|
| To-do List | folderId | Ja | string |
| Title | title | Ja | string |
| Due Date | dateTime | Nein | date-time (YYYY-MM-DDThh:mm:ss) |
| Reminder Date-Time | dateTime | Nein | date-time |
| Importance | importance | Nein | string (low/normal/high) — Dropdown, fx möglich |
| Status | status | Nein | string |
| Content | content | Nein | html (Rich-Text-Editor, UI zeigt "Body Content") |
| Is Reminder On | isReminderOn | Nein | boolean |

## Parse JSON — Dynamischer Inhalt
- Felder mit `["string", "null"]` Typ werden NICHT im Dynamic-Content-Panel angezeigt!
- Fix: Schema-Typ auf einfach `"string"` setzen
- Ausgabe-Felder erscheinen als "Body {fieldname}" im Panel

## Run a prompt (AI Builder)
- Umbenannt Mai 2025 (vorher: "Create text with GPT using a prompt")
- Output-Feld heißt "Text" im Dynamic Content
- Bekannter Bug (Feb 2026): Extra-Parameter `item.item/source` → löschen wenn OData-Fehler

## Programmatische Flow-Erstellung — 3 Wege
1. **ZIP-Generierung** (kein Auth, sofort machbar): definition.json + manifest.json → ZIP → User importiert
2. **Dataverse Web API** (volle Automation): POST auf workflow-Tabelle, braucht Azure AD App + Developer Plan
3. **PAC CLI** (Hybrid): Solution-ZIP generieren → `pac solution import`

## ZIP-Paket Struktur
```
flow-package.zip
├── manifest.json
├── connections.json (optional)
└── Microsoft.Flow/flows/{GUID}/definition.json
```

## Action-JSON Grundstruktur
```json
{
  "type": "OpenApiConnection",
  "inputs": {
    "host": {
      "apiId": "/providers/Microsoft.PowerApps/apis/{connector}",
      "connectionName": "{connector}",
      "operationId": "{operation}"
    },
    "parameters": { ... },
    "authentication": "@parameters('$authentication')"
  },
  "runAfter": { "Previous_Step": ["Succeeded"] }
}
```

## Strategie-Report
- Vollständiger Report: `/home/maetzger/mcb-workdirs/mc3-cda8d49e/power-automate-ai-agent-research.md`
- Niemand in der Community nutzt bisher AI-Agents für autonome Flow-Erstellung — Neuland
- Connection References sind das größte Hindernis (immer manuelles OAuth nötig)
- Kostenloser Developer Plan: 750 Runs/Monat, braucht Work/School-Account
