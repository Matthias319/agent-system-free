---
name: Jarvis Voice Home — Sprachgesteuertes Smart Home System
description: Idee für BLE-Button + Whisper + Groq LLM + Structured Output → Hue API Steuerung unter 1 Sekunde Latenz
type: project
---

## Konzept: Jarvis Voice Home

Matthias will ein ultra-schnelles, sprachgesteuertes Smart-Home-System bauen.

### Flow
1. **BLE-Button** (z.B. Flic 2) — klein, immer dabei, lange Akkulaufzeit
2. **Drücken & Halten** → Mikrofon am Pi/Server nimmt auf
3. **Loslassen** → Audio sofort an Groq Whisper API (STT, ~200ms)
4. **Transkript** → An schnelles Groq-LLM (Llama 3.3 70B o.ä.) mit Structured Output (JSON-Schema)
5. **JSON-Befehl** → Direkt an Hue Bridge / Sync Box API ausführen (~50ms lokal)

### Latenz-Ziel: < 1 Sekunde End-to-End

### Structured Output Schema (Entwurf)
```json
{"action": "scene", "target": "Ocean"}
{"action": "brightness", "target": "all", "value": 50}
{"action": "syncbox", "mode": "music", "intensity": "intense"}
{"action": "off", "target": "all"}
```

### Voraussetzungen
- Hue Bridge API: Authentifiziert ✅ (Key in ~/.env-agent)
- Sync Box API: Authentifiziert ✅ (Token in ~/.env-agent)
- Groq Whisper: Funktioniert ✅ (Key in ~/.env-agent)
- 8 Szenen auf Bridge gespeichert ✅
- Hardware nötig: USB-Mikrofon + BLE-Button (Flic 2, ~35€)
- Pi 5 wird zum "always-on" Voice-Hub (nach Server-Migration)

### Hardware-Optionen für den Button
- **Flic 2** (~35€) — BLE, 18 Monate Akku, Linux SDK verfügbar
- **ESP32 Custom** (~8€) — eigener Button, maximale Kontrolle
- **Shelly Button1** (~12€) — WiFi, aber höherer Stromverbrauch

**Why:** Matthias will intelligent sein Smart Home steuern ohne lange Alexa-Befehle. Ein Wort/Satz reicht, Claude/LLM versteht den Intent.

**How to apply:** Wenn Matthias nach Voice-Steuerung, Smart Home, oder Hue fragt → dieses Konzept referenzieren. Nächster Schritt: Prototyp bauen (Pi + USB-Mic + Groq Pipeline, ohne Button erstmal).
