---
name: Pi 5 Overclocking Results (historisch)
description: Raspberry Pi 5 OC auf 3100 MHz — ~30% Verbesserung. Nicht anwendbar auf HP ProDesk (aktuelles System).
type: project
---

**HINWEIS: Gilt für Raspberry Pi 5 — nicht für HP ProDesk 600 G3 (aktuelles System seit 2026-03-12).**

## FINAL OC: 3100 MHz (STABLE, war aktiv auf Pi 5)

| Benchmark | Stock 2400 | OC 3100 | vs Stock |
|-----------|-----------|---------|----------|
| Sysbench CPU 1T | 1008 | 1307 | +29.6% |
| Sysbench CPU 4T | 3191 | 4186 | +31.2% |
| Sysbench Memory | 8584 | 11713 | +36.4% |
| 7-Zip Total | 11951 | 15142 | +26.7% |

- arm_freq=3100, gpu_freq=900, over_voltage_delta=87500 (+87.5mV)
- Max temp: 76°C sustained, Throttle: 0x0, Headroom: 9°C to 85°C throttle
- 3200 MHz FAILED (would not boot)

**Why:** Historische Referenz für Matthias' Server-Evolution (Pi 5 → HP ProDesk → nächstes System).
