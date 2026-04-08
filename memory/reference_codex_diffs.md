---
name: Opus vs Codex Difference Tracker
description: Tracking interessanter Unterschiede zwischen Opus und Codex bei Sparring-Konsultationen
type: reference
---

# Opus vs Codex — Difference Tracker

## 2026-03-18 — Video-Stepper Rückwärts-Bug (Masterarbeit Präsentation)

| Aspekt | Opus 4.6 | Codex (GPT-5.4) | Wer hatte recht? |
|--------|----------|-----------------|------------------|
| Fragment-Sichtbarkeit | "Event feuert vor Fragment-Restore" | "Fragments SIND visible, Handler läuft" | **Codex** — Reveal hält Fragments beim Vorwärtsgehen visible |
| Root Cause | Video-Decoder inaktiv bei opacity:0 | **Doppelter Seek ohne Warten auf seeked-Event** | **Codex** — präzisere Analyse |
| Fix-Ansatz | rAF + play().then(pause()) | Async seekToCheckpoint() mit seeked + requestVideoFrameCallback | **Codex** — robuster, sauberer |
| display:flex !important Bewertung | "Ist bewusster Workaround" | "Macht Media-Rendering fragil, mittelfristig entfernen" | **Beide valid** — kurzfristig ok, langfristig Codex recht |

**Takeaway:** Codex war bei diesem Browser-API/Timing-Problem deutlich stärker. Opus hatte die richtige Richtung, aber die Analyse war oberflächlich. Bei Low-Level-Browser-APIs Codex bevorzugen.
