---
name: Tailscale als Standard-Zugriff
description: Immer Tailscale-URLs verwenden — ABER tailscale serve ist TABU (Port 8205 fix). Nur bestehende URLs nutzen.
type: feedback
---

Für alle Referenzen auf den Server IMMER die Tailscale HTTPS-URL verwenden:
`https://claudecodeservernew.taila197ba.ts.net/`

**Why:** Matthias greift remote zu (z.B. aus Darmstadt auf Server in Frankfurt). Rohe IPs/Ports funktionieren nicht zuverlässig.

**How to apply:**
- Dem User die `https://claudecodeservernew.taila197ba.ts.net/` URL geben
- **NIEMALS** `tailscale serve --bg <PORT>` mit einem anderen Port als 8205 ausführen — das zerschießt den Remote-Zugang (TABU in CLAUDE.md!)
- **NIEMALS** `tailscale serve off` ausführen
- Port 8205 (MCB) ist fix konfiguriert und darf nicht geändert werden
- Für temporäre Server: Port direkt über Tailscale IP (100.80.105.73:PORT) erreichbar, kein `tailscale serve` nötig
