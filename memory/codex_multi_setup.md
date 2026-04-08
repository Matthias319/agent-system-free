---
name: Codex Multi-Account Setup
description: 3 ChatGPT Business Seats für Codex CLI mit automatischer Rotation bei Rate Limits
type: project
---

Codex Multi-Account-Rotation eingerichtet (2026-03-20).

Tool: `~/.claude/tools/codex-multi.py`
Profile: `~/.codex/profiles/{main,backup1,backup2}/auth.json`

| Profil | Email | Zweck |
|--------|-------|-------|
| main | matthias.kuehn@actlegal-germany.com | Haupt-Account |
| backup1 | matze29595@gmail.com | Rotation |
| backup2 | matthiaskuehn9@gmail.com | Rotation |

**Why:** main-Account erreicht regelmäßig das Weekly Rate Limit. 3 Seats × Business-Plan = 3× Kapazität.

**How to apply:** `/codex` Skill hat Auto-Rotation als Step 0 eingebaut. Vor jeder Codex-Nutzung wird automatisch das Profil mit niedrigster Weekly-Auslastung gewählt. Business-Abo läuft bis 2026-04-15.
