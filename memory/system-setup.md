---
name: System Setup & Infrastructure
description: Server-Konfiguration für HP ProDesk 600 G3 (primär) und Pi 5 (sekundär) — RAM, Swap, Tuning, Agents
type: reference
---

## HP ProDesk 600 G3 SFF (Primärer Server, seit 2026-03-12)

- **CPU**: Intel i7-6700 @ 3.40 GHz (non-K, nicht übertaktbar, 3.7 GHz all-core Turbo)
- **RAM**: 32 GB DDR4
- **Disk**: 906 GB SATA SSD (4% belegt)
- **Swap**: 31 GB
- **OS**: Debian 13 (trixie)
- **Tailscale**: 100.80.105.73 (claudecodeservernew)
- **Tuning**: `/etc/sysctl.d/99-server-tuning.conf` — Details in server-tuning-hp-prodesk.md
- **Temperatur**: ~36°C idle, ~73°C max load (Serverraum, gute Kühlung)

### Agent-Teams: Komfortabel
- 32 GB RAM → 5+ Agents gleichzeitig kein Problem
- Kein earlyoom nötig (war Pi-spezifisch)

## Raspberry Pi 5 (Sekundärer Server)

- **CPU**: Cortex-A76 @ 3.1 GHz OC
- **RAM**: 8 GB (Limit für Agents!)
- **Swap**: 18 GB (2 GB zram + 16 GB NVMe)
- **earlyoom**: Aktiv, killt bei 5% RAM frei
- **Max 3 Agents** gleichzeitig empfohlen
- Details: overclocking.md, benchmark-baseline.md

## Claude Code Trust-Dialog
- Trust-State in `~/.claude.json` unter `projects.*.hasTrustDialogAccepted`
- Home-Dir `/home/maetzger` muss `true` sein
