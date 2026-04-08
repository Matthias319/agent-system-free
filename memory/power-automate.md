---
name: Power Automate — Schema, Connectors & Referenzen
description: Flow-Definition Schema, UI-Details, verifizierte Connector-IDs (Outlook/To Do/Azure OpenAI), Generator-Pfade und Tenant-Infos
type: reference
---

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

## Connector IDs (verifiziert März 2026)

### Outlook — When an email is flagged
| Property | Wert |
|----------|------|
| Connector | `shared_office365` |
| apiId | `/providers/Microsoft.PowerApps/apis/shared_office365` |
| operationId (stable) | `OnFlaggedEmailV3` |
| operationId (preview) | `OnFlaggedEmailV4` |
| Trigger-Typ | **Polling** → `"type": "OpenApiConnection"` + `recurrence` |

V2 ist DEPRECATED. V3 ist stabil, V4 ist Preview.

### Microsoft To Do — Add a to-do
| Property | Wert |
|----------|------|
| Connector | `shared_todo` |
| apiId | `/providers/Microsoft.PowerApps/apis/shared_todo` |
| operationId | `CreateToDoV3` |

V1/V2 sind DEPRECATED (alte Outlook Tasks API, seit Feb 2023 tot). V3 nutzt Graph To Do API.

Felder (Detail):
| Feld | Key | Required | Typ |
|------|-----|----------|-----|
| To-do List | folderId | Ja | string |
| Title | title | Ja | string |
| Due Date | dateTime | Nein | date-time (YYYY-MM-DDThh:mm:ss) |
| Importance | importance | Nein | string (low/normal/high) — Dropdown, fx möglich |
| Status | status | Nein | string |
| Content | content | Nein | html (Rich-Text-Editor, UI zeigt "Body Content") |
| Is Reminder On | isReminderOn | Nein | boolean |

### Azure OpenAI
| Property | Wert |
|----------|------|
| Connector | `shared_azureopenai` |
| apiId | `/providers/Microsoft.PowerApps/apis/shared_azureopenai` |
| operationId | `ChatCompletions_Create` |

Alternative: HTTP Action (kein Premium nötig) — manuell URI + api-key Header.

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

## ZIP-Paket Struktur
```
flow-package.zip
├── manifest.json
├── connections.json (optional)
└── Microsoft.Flow/flows/{GUID}/definition.json
```

## Generator & Referenz-ZIPs
- Generator: `/home/maetzger/shared/power-automate-generator/generate_flow_zip.py` (v7)
- 3-Connector: `/home/maetzger/shared/chat-images/20260313-143606_claudeetst_20260313133601.zip`
- AI Builder only: `/home/maetzger/shared/chat-images/20260313-135535_claudetest_20260313125519.zip`
- Button-Flow: `/home/maetzger/shared/chat-images/20260313-122244_testforclaude_20260313112238.zip`

## Tenant-Infos
- User: `mak@actlegal-germany.com`
- User-ID: `06b2e229-84cb-4fcc-abe2-9db144dd0a08`
- Tenant-ID: `68a08628-a2da-43cc-b5c5-8b81af134aaf`
- AI Builder Prompt-GUID: `79c029ca-7217-49be-baa6-4667ff1f3605`

## Workflow für neue Flows
1. Matthias erstellt Dummy-Flow in Power Automate mit den gewünschten Connectors/Actions
2. Export als ZIP → als Referenz an Claude geben
3. Generator nach Referenz anpassen, nie raten

## Quellen
- https://learn.microsoft.com/en-us/connectors/office365/
- https://learn.microsoft.com/en-us/connectors/todo/
- https://learn.microsoft.com/en-us/connectors/azureopenai/

## Strategie
- Niemand in der Community nutzt bisher AI-Agents für autonome Flow-Erstellung — Neuland
- Connection References sind das größte Hindernis (immer manuelles OAuth nötig)
- Kostenloser Developer Plan: 750 Runs/Monat, braucht Work/School-Account
