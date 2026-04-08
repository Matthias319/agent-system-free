---
name: Audio-Transkription IMMER via Groq API
description: Audio/Video-Transkription NIEMALS lokal mit Whisper, IMMER über Groq API (whisper-large-v3). Schnell, kostenlos, integriert.
type: feedback
---

Audio-Transkription IMMER über Groq API, NIE lokal mit Whisper.

**Why:** Groq ist integraler Bestandteil des Workflows. Lokale Modelle sind langsam, brauchen RAM, und das Whisper-Modell-Cache ist oft korrupt. Groq liefert in <2s. Matthias hat das mehrfach explizit betont (Zettel #60, Session vom 2026-03-18).

**How to apply:**
1. Bei Audio/Video-Aufgaben ZUERST pi-search/Memory-Router für bestehende Workflows checken
2. Groq Key: `GROQ_API_KEY` aus `~/.env-agent`
3. Endpoint: `https://api.groq.com/openai/v1/audio/transcriptions`
4. Model: `whisper-large-v3` als Safe Default. `whisper-large-v3-turbo` ist schneller — Report `whisper-v3-turbo-vs-v3-deutsch.html` (2026-04-04) hat die Deutsch-Qualität evaluiert.
5. Audio-Optimierung: Mono 16kHz, 32kbps Opus — minimal für Sprache
6. Max Aufnahme: 5 Minuten, Timeout: 60s
7. Nie `pip install whisper` oder lokale Modelle vorschlagen
