---
name: Groq API First
description: Bei Audio/Transkription IMMER zuerst Groq API nutzen, nie lokale Modelle. Memory-Router und Zettel-System vor Tooling-Entscheidungen checken.
type: feedback
---

Bei Audio-Transkription IMMER Groq Whisper API nutzen, nie lokale Modelle (faster-whisper etc.).

**Why:** Groq ist integraler Bestandteil des Workflows. Lokale Modelle sind langsam, brauchen RAM, und das Whisper-Modell-Cache ist auf dem Pi oft korrupt. Groq liefert in <2s.

**How to apply:**
1. Bei Audio/Video-Aufgaben ZUERST pi-search/Memory-Router für bestehende Workflows checken
2. Groq Key: `GROQ_API_KEY` aus `~/.env-agent` oder `~/Projects/mission-control-v4/.env`
3. Endpoint: `https://api.groq.com/openai/v1/audio/transcriptions`
4. Model: `whisper-large-v3` (oder `whisper-large-v3-turbo`)
5. Language-Parameter setzen wenn nicht Deutsch (default ist `de` in MCV3/4)
6. MCV3 hat funktionierenden Proxy: `curl localhost:8084/api/transcribe -F file=@audio.m4a` (aber hardcoded `language=de`)
7. Generell: Bei Tooling-Fragen IMMER zuerst Memories/Zettel checken — nicht raten oder neu erfinden
