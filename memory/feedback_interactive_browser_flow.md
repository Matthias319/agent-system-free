---
name: Browser-Automation interaktiv statt monolithisch
description: Login-Flows mit 2FA in Schritte aufteilen, Browser als persistente Session im Hintergrund, nicht als monolithisches Script
type: feedback
---

Browser-Automation NICHT als ein langes Python-Script oder Bash-Call machen.

**Why:** Monolithische Scripts blockieren den Chat. User kann keine 2FA-Codes eingeben während das Script läuft. Scripts crashen bei StaleElement und die ganze Session ist weg. Entdeckt bei REWE-Login (2026-03-30).

**How to apply:**
1. Chrome mit `--remote-debugging-port=9222` als Hintergrund-Prozess starten (Xvfb)
2. Über separate kurze Befehle steuern (connect, click, type, screenshot)
3. Bei 2FA: Login bis Code-Screen → PAUSE → User gibt Code → Script weiter
4. Jeder Befehl ein eigenständiger kurzer Bash-Call, Browser bleibt persistent
5. Alternative: Stealth-Browser MCP nutzt bereits dieses Pattern (Playwright-basiert)
