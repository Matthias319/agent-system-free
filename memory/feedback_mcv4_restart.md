---
name: mcv-restart-caution
description: Bei MCV4/MCB-Service-Restarts vorsichtig sein — erst prüfen ob tmux-Sessions überleben, User vorwarnen
type: feedback
---

Vor einem `systemctl restart mcv4` oder `systemctl restart mcb` IMMER den User vorwarnen und erklären was passiert.

**Why:** Matthias arbeitet selbst INNERHALB von MCB (aktiv) bzw. MCV4 (archiviert, aber noch aktiv auf Port 8200) — ein unüberlegter Restart kann seine aktive Session unterbrechen. tmux-Sessions überleben den Restart (kein ExecStop, WebSocket reconnected automatisch), aber das muss transparent kommuniziert werden.

**How to apply:**
- Vor jedem Restart: kurz erklären "tmux-Sessions bleiben, nur WebSocket reconnected kurz"
- Nie blind `systemctl restart` ausführen ohne Erklärung
- Bei strukturellen Änderungen (DB-Schema, neue Dependencies): extra vorsichtig, ggf. zuerst testen
