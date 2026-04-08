# Prompting Rules (on-demand geladen via Rules Router)

Empirisch getestet am 30.03.2026 mit 50+ Groq API-Calls auf gpt-oss-120b.
Blind-validiert auf unabhängigen Codex-generierten Testdaten.
Anwendbar auf Extraktions-Tasks, Meeting-Verarbeitung, Diktat-Formatierung.

## Die 7 Goldenen Regeln

### 1. Evidence-Pflicht im Schema (stärkster Hebel)
Ein `evidence`-Feld im JSON-Schema erzwingt Zitate aus dem Input.
Wenn das Modell zitieren MUSS, kann es nicht halluzinieren.
```json
{"task": "string", "owner": "string", "evidence": "string"}
```
**Messung**: 0 erfundene Items mit evidence vs. 1-3 ohne. +10 Prozentpunkte im Blind-Test.

### 2. Flachtext > XML-Tags (bei gpt-oss-120b)
XML-Tags bringen keine Qualitätsverbesserung, kosten +40% Latenz.
YAML crasht mit JSON-Schema. Markdown verleitet zur Formatierung statt Extraktion.
**Empfehlung**: Einfacher Flachtext mit klaren Absätzen.
**Caveat**: Claude-Modelle profitieren oft von XML — bei Modell-Wechsel neu testen.

### 3. Constraints in User-Message > System-Prompt
- User-only: schneller + korrekter
- System-only: langsamer, mehr Fehler
- BEIDE: VERSCHLECHTERT das Ergebnis (Redundanz verwirrt)
**Regel**: System = nur Rolle + statische Regeln. User = alles Dynamische + Constraints.

### 4. Rolle "Experte/Tool" > "Assistent"
Sachliche, autoritäre Rollen produzieren präzisere Outputs:
- Gut: "Datenextraktions-Tool", "erfahrener Jurist und Analyst"
- Schlecht: "hilfreicher Assistent", "freundlicher Helfer"
- Ohne Rolle: verliert Fakten komplett

### 5. Reasoning-Effort adaptiv einsetzen
- `low`: Echtzeit-Tasks (Diktat), einfache Extraktion
- `medium`: Meeting-Verarbeitung, komplexe Zuordnung
- `high`: Nur wenn user_name-Zuordnung kritisch (5.7x langsamer)

### 6. Granularität explizit fordern
Ohne Anweisung fasst das Modell zusammen: "A macht X, Y und Z" → 1 Item.
Fix: `"JEDE Zuweisung = 1 separates Item. 'A macht X und Y' = 2 Items."`

### 7. Context-Feld mit Pflichtfeldern + Beispielen
Ein `context`-Feld im Schema + explizite Aufforderung:
```
context MUSS enthalten: Aktenzeichen (z.B. "7 IN 234/25"),
Paragraphen (z.B. "§ 94 InsO"), Geldbeträge (z.B. "380.000 Euro")
```
Konkrete Beispiele im Prompt verdoppeln die Fakten-Beibehaltung.

## Owner-Guardrails (bei Sprecher-Zuordnung)

Wenn ein Aufnehmender (user_name) = Sprecher 1 ist:
```
Sprecher 1 fasst oft zusammen: "Dr. Weber kümmert sich um X"
→ Owner = Dr. Weber, NICHT der Aufnehmende

Aufnehmender nur bei Selbstzuweisung:
→ "ich werde...", "das mache ich", "ich informiere..."
```
Explizite Beispiele im Prompt helfen dem Modell bei der Unterscheidung.

## Anti-Halluzinations-Taxonomie

Was KEIN Item sein darf (als Ausschlussliste im Prompt):
1. Geparkte Themen ("parken wir", "verschieben wir")
2. Diskutierte Ideen ohne Beschluss ("man könnte", "wäre sinnvoll")
3. Organisatorische Selbstverständlichkeiten (Kalender, Einladungen)
4. Nebengespräche (Weihnachtsfeier, Smalltalk)
5. Reine Besprechungspunkte ohne Übernahme

## Optimaler Prompt-Stack

```
System:  1 Satz — Rolle + Priorität
         "Du bist ein Datenextraktions-Tool für juristische Meeting-Transkripte.
          Präzision bei Zahlen, Normen und Zuordnungen ist kritisch."

User:    Constraints + Granularität + Evidence-Pflicht + Context-Pflichtfelder
         + Owner-Guardrails + Ausschluss-Taxonomie + Input
         Alles Flachtext, KEINE XML-Tags.

Schema:  Strukturiert mit evidence + context Feldern.
         {items: [{task, owner, deadline, priority, evidence, context}]}

Params:  temperature=0.1, reasoning_effort="low"/"medium"
```

## Benchmark-Ergebnisse (Referenz)

| Prompt-Variante | Eigene Test-Sets | Blind-Test (Codex) |
|----------------|-----------------|-------------------|
| Naiver Prompt (kein Evidence) | ~65% | 84% |
| Golden (Evidence + Flachtext) | 89% | **94%** |
| Ultimate (alle Regeln) | **95%** | 92% |

Golden ist robuster über verschiedene Kontexte. Ultimate performt besser auf bekannten Daten.
**Empfehlung**: Golden als Default, Ultimate-Techniken bei Bedarf hinzuschalten.

## Detaillierte Research-Daten

Vollständige Versuchsreihe mit allen 8 Dimensionen und Rohdaten:
`~/.claude/projects/-home-maetzger/memory/prompt_engineering_gpt_oss_120b.md`
