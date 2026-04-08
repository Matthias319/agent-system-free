---
name: actlegal-events.com Domain & Hosting
description: Eigene Domain actlegal-events.com via Cloudflare Tunnel, self-hosted auf HP ProDesk. Koexistiert mit Strato-Hosting (event.act.legal).
type: project
---

**actlegal-events.com** ist die selbst-gehostete Domain für act legal.

- **Registrar**: Cloudflare (ca. 7€/Jahr .com)
- **Zugang**: Cloudflare Named Tunnel "act-events" (ID: 490ab05a-2cdd-410e-b207-2ba57b2286f6)
- **Backend**: FastAPI-App auf Port 8070 (systemd: `act-event.service`)
- **Tunnel-Service**: systemd `cloudflared.service` (auto-start bei Boot)
- **Config**: `/etc/cloudflared/config.yml`
- **SSL**: Automatisch via Cloudflare (Universal SSL)

**Koexistenz mit Strato (Stand 2026-03-29):**
- **event.act.legal** (Strato): Statische HTML-Formulare + CGI-Python → aktuelle Event-Anmeldeseiten (Kicker, Tennis)
- **actlegal-events.com** (Cloudflare/Self-hosted): FastAPI-App → ältere Event-App + Freelancer-Audit-Hosting (audit.actlegal-events.com)

**Why:** Azure-Deployment wurde verworfen (Subscription-Probleme). Strato kam als zweiter Hosting-Weg hinzu (2026-03-25) für einfachere statische Seiten.

**How to apply:** Neue Events auf Strato (event.act.legal). actlegal-events.com bleibt aktiv für Bestandsseiten und das Freelancer-Audit.
