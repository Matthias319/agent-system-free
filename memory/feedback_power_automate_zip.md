---
name: Power Automate ZIP-Format Learnings
description: Kritische Erkenntnisse zum Power Automate ZIP-Export/Import-Format — AI Builder nutzt Dataverse, nicht shared_aibuilder
type: feedback
---

Bei Power Automate ZIP-Generierung IMMER echte Exports als Referenz nutzen, nie raten.

**Wichtigste Fehler die gemacht wurden:**
- AI Builder hat KEINEN eigenen Connector (`shared_aibuilder` existiert nicht für Import). Er läuft über `shared_commondataserviceforapps` (Dataverse).
- `apisMap.json` darf NICHT leer sein wenn Connectors vorhanden — muss Connector→API-GUID Mapping enthalten.
- `connectionReferences` Export-Format: `connectionName/source/id/tier/apiName/isProcessSimpleApiReferenceConversionAlreadyDone` (NICHT `runtimeSource/connection/api`).
- Placeholder-Strings wie "DEINE-GUID-HIER" werden beim Import validiert — immer echte GUIDs verwenden.
- Parameter in Actions müssen exakt den Prompt-Inputs entsprechen — keine erfundenen Parameter.

**Why:** 7 fehlgeschlagene Versionen (v1-v6) weil Format geraten statt von Referenz abgeleitet wurde. Matthias hatte sogar Referenz-ZIPs bereitgestellt die nicht genutzt wurden.

**How to apply:** Bei Power Automate oder ähnlichen Plattform-Formaten IMMER zuerst einen echten Export als Referenz anfordern und 1:1 nachbauen. Nie die Struktur aus Dokumentation oder Annahmen ableiten.
