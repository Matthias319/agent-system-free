---
name: act Scriber Auto-Update auf Eis gelegt
description: Auto-Update deaktiviert, Rollout über MSI via IT-Kollege statt ZIP-Updates
type: project
---

Auto-Update-Mechanismus ist seit 2026-03-31 auf Eis gelegt (Notfall-Stopp aktiv, kein Release freigegeben).

**Why:** IT-Kollege deployt Updates lieber per MSI über das IT-Tool. Windows Defender Exclusions für den Updater-Temp-Pfad müssten auf allen Workstations konfiguriert werden. Aufwand lohnt sich aktuell nicht für 50 Laptops.

**How to apply:** Keine ZIP-Releases freigeben. Updates nur als MSI bauen und an IT-Kollegen geben. Der Auto-Update-Code bleibt im Projekt (nicht löschen), kann später reaktiviert werden wenn Defender-Exclusions zentral ausgerollt sind.

Defender-Exclusions die nötig wären für Auto-Update:
- `C:\Program Files\act Scriber\` (bereits gewhitelistet)
- `C:\Users\*\AppData\Local\Temp\actscriber_updater` (noch nicht)
