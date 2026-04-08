---
name: HP ProDesk 600 G3 Server Tuning
description: Iterativ getestete Performance-Optimierungen für den HP ProDesk 600 G3 (i7-6700) im Serverraum — sysctl, C-States, Scheduler, I/O
type: project
---

## Server Performance Tuning (2026-03-17)

Iterativer Benchmark-Loop mit 19 Iterationen. Composite-Score: 96.0 → 99.6 (+3.7%).

**Akzeptierte Änderungen:**
- dirty_ratio 10, dirty_bg_ratio 3 (SSD-optimiert, größter Einzeleffekt +3.1)
- vfs_cache_pressure 200
- zone_reclaim_mode 1
- rcu_expedited 1
- cfs_bandwidth_slice_us 3000 (zweitgrößter Effekt +1.1)
- min_free_kbytes 262144
- Watchdogs off, HWP dynamic boost on, C-States C3-C8 disabled
- Network: tcp_fastopen 3, no slow_start_after_idle, backlog 5000
- I/O: mq-deadline, read_ahead 32, nr_requests 256

**Abgelehnt:** THP always, Hugepages, PL1-Erhöhung (Multiplikator ist Bottleneck, nicht Power), aggressive dirty_expire, watermark_scale, compaction_proactiveness

**Persistenz:** `/etc/sysctl.d/99-server-tuning.conf` + `/etc/systemd/system/server-tuning.service`

**Why:** Server steht im kühlen Serverraum (29°C idle, 73°C max load). i7-6700 non-K kann nicht übertaktet werden — 3.7 GHz all-core ist Hardware-Limit.

**How to apply:** Bei zukünftigen Performance-Fragen: Diese Baseline kennen. Keine weiteren CPU-Gains möglich ohne Hardware-Upgrade.
