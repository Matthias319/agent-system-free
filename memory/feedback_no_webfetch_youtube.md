---
name: Kein WebFetch für YouTube
description: YouTube-URLs nie mit WebFetch abrufen — immer youtube-intel.py verwenden
type: feedback
---

Nie WebFetch für YouTube-URLs verwenden. Stattdessen `youtube-intel.py` (transcript, video, comments).

**Why:** WebFetch scheitert an YouTube (303 Redirect, kein Content), und der User hat ein dediziertes Tool dafür.

**How to apply:** Bei YouTube-Links immer: `uv run ~/.claude/tools/youtube-intel.py transcript VIDEO_ID --lang en,de` für Transkripte, `video VIDEO_ID` für Metadaten.
