---
name: mcv4-restart-caution
description: Bei MCV4-Service-Restarts vorsichtig sein — erst prüfen ob tmux-Sessions überleben, User vorwarnen
type: feedback
---

Vor einem `systemctl restart mcv4` IMMER den User vorwarnen und erklären was passiert.

**Why:** Matthias arbeitet selbst INNERHALB von MCV4 — ein unüberlegter Restart kann seine aktive Session unterbrechen. Auch wenn tmux-Sessions den Restart überleben (kein ExecStop, WebSocket reconnected automatisch), muss das transparent kommuniziert werden.

**How to apply:**
- Vor jedem Restart: kurz erklären "tmux-Sessions bleiben, nur WebSocket reconnected kurz"
- Nie blind `systemctl restart` ausführen ohne Erklärung
- Bei strukturellen Änderungen (DB-Schema, neue Dependencies): extra vorsichtig, ggf. zuerst testen
