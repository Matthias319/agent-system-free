---
name: anti-hallucination
description: "Proaktive Faktenverifikation mit Decision Tree und Confidence Levels"
triggers:
  - "API/Library/Framework-Fragen"
  - "Versions-Claims"
  - "Preis-Claims"
  - "Datums-Claims"
  - "stimmt das"
  - "Faktencheck"
  - "technische Behauptungen"
not_for:
  - "Code schreiben"
  - "Meinungsfragen"
  - "kreative Aufgaben"
delegates_to:
  - "web-search"
bundle: research
---

# Anti-Hallucination — Proaktive Faktenverifikation

Dieses Skill ergänzt die passiven Anti-Halluzinations-Guards in `./rules/core.md`
um **aktive Verifikation** bevor Behauptungen gemacht werden.

## Tracking + Self-Heal (PFLICHT)

```bash
RUN_ID=$(./tools/skill-tracker.py start anti-hallucination)
./tools/skill-tracker.py heal anti-hallucination
```

Am Ende:
```bash
./tools/skill-tracker.py metrics-batch $RUN_ID '{
  "confidence_level": "HIGH|MEDIUM|LOW|UNKNOWN",
  "sources_checked": N,
  "verification_method": "context7|web-search|code-read|grep|none"
}'
./tools/skill-tracker.py complete $RUN_ID
```

## Decision Tree — Verifikationsrouting

Bevor du eine faktische Behauptung machst, klassifiziere die Frage:

```
┌─ Ist die Frage über eine API, Library oder Framework?
│  ├─ JA → Context7 MCP (resolve-library-id → query-docs)
│  │       Fallback: /web-search
│  └─ NEIN ↓
│
├─ Ist es eine Versions-, Preis- oder Datums-Behauptung?
│  ├─ JA → /web-search (Fakten-Check Modus)
│  │       Trainingsdaten enden Mai 2025 — ALLES danach MUSS verifiziert werden
│  └─ NEIN ↓
│
├─ Bezieht sich die Frage auf Code im aktuellen Projekt?
│  ├─ JA → Read/Grep/LSP — direkt im Code verifizieren
│  └─ NEIN ↓
│
├─ Ist es eine konfigurierbare Aussage (CLI-Flags, Config-Optionen)?
│  ├─ JA → Context7 MCP oder `--help` Output via Bash
│  └─ NEIN ↓
│
├─ Ist es eine Behauptung über Personen, Unternehmen, Ereignisse?
│  ├─ JA → /web-search
│  └─ NEIN ↓
│
└─ Allgemeinwissen / Konzeptfrage
   └─ Trainingswissen OK, aber Confidence Level angeben
```

## Confidence Levels

Nach Verifikation: Confidence Level bestimmen und kommunizieren.

| Level | Bedeutung | Wann |
|-------|-----------|------|
| **HIGH** | Verifiziert durch aktuelle Quelle | Context7 Treffer, Web-Quelle <6 Monate, Code gelesen |
| **MEDIUM** | Plausibel aber nicht direkt verifiziert | Trainingswissen konsistent mit Teilquellen |
| **LOW** | Unsicher, möglicherweise veraltet | Trainingswissen ohne Gegencheck, >12 Monate alt |
| **UNKNOWN** | Kann nicht verifiziert werden | Keine Quellen gefunden, widersprüchliche Infos |

### Kommunikationsregeln

- **HIGH**: Antwort direkt geben, Quelle als Link/Referenz anfügen
- **MEDIUM**: Antwort geben mit Hinweis "[Confidence: MEDIUM — basiert auf Trainingswissen, nicht aktuell verifiziert]"
- **LOW**: Explizit warnen: "Diese Information könnte veraltet sein. Empfehle Gegencheck."
- **UNKNOWN**: Ehrlich sagen: "Das kann ich nicht zuverlässig beantworten." Keine plausibel klingende Vermutung.

## Verifikations-Tools (Priorität)

1. **Context7 MCP** — Für Libraries/Frameworks/APIs (aktuellste Docs)
   ```
   mcp__plugin_context7_context7__resolve-library-id → library_id
   mcp__plugin_context7_context7__query-docs(library_id, topic)
   ```

2. **Code-Verifikation** — Für projektbezogene Behauptungen
   ```
   Read, Grep, LSP (goToDefinition, findReferences)
   ```

3. **Web-Search Skill** — Für aktuelle Fakten, Preise, Versionen
   ```
   /web-search im Fakten-Check-Modus
   ```

4. **Bash** — Für CLI-Flags, installierte Versionen
   ```
   command --help, command --version, dpkg -l, pip show
   ```

## Proaktive Trigger

Dieses Skill soll **proaktiv** aktiviert werden wenn du merkst, dass du:

- Eine Versionsnummer nennen willst (→ verifizieren)
- Einen API-Endpunkt oder Parameter beschreibst (→ Context7)
- Einen Preis oder ein Datum behauptest (→ Web-Search)
- Eine Config-Option empfiehlst (→ Docs oder --help)
- Sagst "X unterstützt Y" oder "X hat Feature Y" (→ verifizieren)

## Abgrenzung zu bestehenden Guards

| Bestehend (core.md) | Neu (dieser Skill) |
|----------------------|--------------------|
| Passiv: "Markiere Inferenz" | Aktiv: Verifiziere VOR der Antwort |
| Passiv: "Zitiere 3 Quellen" | Aktiv: Routing zu richtiger Verifikationsquelle |
| Passiv: "Kommuniziere Unsicherheit" | Aktiv: Confidence Level systematisch bestimmen |
| Regeln für Output-Format | Decision Tree für Verifikations-Workflow |
