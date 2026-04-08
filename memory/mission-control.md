---
name: Mission Control Board — Versionen
description: Übersicht aller Mission Control Versionen (V2-V5) mit Ports, Status und Architektur
type: reference
---

## Versionen (Stand 2026-04-07)

| Version | Port | Pfad | Status |
|---------|------|------|--------|
| V2 | 8081/8443 | `~/Projects/mission-control-v2` | Legacy, inaktiv |
| V3 | — | `~/Projects/mission-control-v3` | Legacy, inaktiv |
| V4 | 8200 | `~/archive/mission-control-v4/` | **ARCHIVIERT** (seit ~März 2026) |
| **MCB** | **8205** | `~/Projects/mission-control-board` | **AKTIV** (tailscale serve Port 8205) |

## MCB — Aktives Entwicklungsprojekt
- Vanilla JS IIFE + Plain CSS, SSE Event Bus
- Agent Team Experiments (mcb-evolution, mcb-dev)
- Forschungs-Reports: `~/Projects/mission-control-board/research-findings/`
- Design: Warm Dark Editorial, iPad Pro 12.9" Portrait als Primärziel
- Features: KPI-Zeile, Session-Cards, Activity-Feed, Auto-Heal, Terminal-Preview
- Mobile: iPhone 17 Pro Max, PWA, Thumb-Zone-Navigation

## Design & Architektur
- Design: Warm Dark Editorial, Newsreader + Outfit Fonts, #cf865a Akzent
- Voice: Groq `whisper-large-v3`, Mono 16kHz 32kbps
- Touch: iOS-Events IMMER auf touchstart-Target binden
