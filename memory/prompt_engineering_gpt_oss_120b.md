---
name: Prompt Engineering Rules — gpt-oss-120b (Groq)
description: Empirisch getestete Prompt-Regeln für das openai/gpt-oss-120b Modell auf Groq. 30+ A/B-Tests, 8 Dimensionen, 3-Way-Benchmark. Anwendbar auf ActScriber und ähnliche Extraktion-Tasks.
type: feedback
---

# Prompt Engineering Rules — gpt-oss-120b auf Groq

Getestet am 30. März 2026 mit 50+ echten API-Calls. Ergebnisse aus systematischer 8-Dimensionen-Research + 3-Way-Benchmark (Golden vs. Opus vs. Codex GPT-5.4).

## Die 7 Goldenen Regeln

### 1. Evidence-Pflicht ist der stärkste Anti-Halluzinations-Mechanismus
- Ein `evidence`-Feld im JSON-Schema erzwingt Zitate aus dem Input
- Wenn das Modell zitieren MUSS, kann es nicht halluzinieren
- Kein Prompt-Trick ersetzt diesen strukturellen Zwang
- **Messung**: 0 erfundene Items mit evidence vs. 1-3 ohne

### 2. Flachtext > XML-Tags > YAML > Markdown
- Flachtext (897ms) ist gleichwertig oder schneller als XML (921ms) bei gleicher Qualität
- YAML crasht mit JSON-Schema response_format (inkompatibel)
- Markdown-Prompts: Modell formatiert statt zu extrahieren (Fakten gehen verloren)
- **Empfehlung**: Einfacher Flachtext mit klaren Abschnitten

### 3. Constraints gehören in die User-Message, nicht in den System-Prompt
- User-only (428ms, korrekt) > System-only (486ms, Fehler) > Beide (1086ms, verwirrt!)
- Redundanz verschlechtert das Ergebnis — nie doppelt platzieren
- System-Prompt: nur Rolle und statische Regeln. User-Message: alles Dynamische + Constraints.

### 4. Rolle "Experte/Maschine" > "Assistent/Formatter"
- "Erfahrener Jurist und Meeting-Analyst" (426ms, 3/5 Fakten) >> "Hilfreicher Assistent" (459ms, 2/5)
- "Datenextraktions-Tool" (443ms, 3/5) funktioniert genauso gut
- "Kein Role" verliert ALLE Fakten
- Sachliche, autoritäre Rollen produzieren präzisere Outputs

### 5. Reasoning-Effort "low" reicht für Echtzeit, "medium"/"high" für komplexe Logik
- low (625ms): Schnell, aber user_name-Zuordnung oft falsch
- high (3598ms): user_name korrekt, 5.7x langsamer
- **Empfehlung**: "low" für Diktat (Echtzeit), "medium" für Meeting-Verarbeitung

### 6. Granularität muss explizit gefordert werden
- "JEDE Zuweisung = 1 Item" verhindert, dass das Modell zusammenfasst
- Ohne: "Dr. Klein macht A, B und C" = 1 Item. Mit: = 3 Items.
- Beispiele im Prompt helfen: `"A macht X und Y" = 2 Items, nicht 1`

### 7. Context-Feld mit Pflichtfeldern erzwingt Fakten-Beibehaltung
- Ein `context`-Feld im Schema + explizite Aufforderung "MUSS Aktenzeichen, Paragraphen, Geldbeträge enthalten"
- Mit wörtlichen Beispielen: `(z.B. "7 IN 234/25", "380.000 Euro", "§ 94 InsO")`
- **Messung**: 100% Score in einem Run vs. 65% ohne Context-Pflicht

## Optimaler Prompt-Stack

```
System:  "Du bist ein Datenextraktions-Tool für juristische Meeting-Transkripte.
          Präzision und Vollständigkeit sind kritisch."

User:    [Constraints + Granularitätsregel + Evidence-Pflicht + Context-Pflichtfelder
          + Owner-Guardrails + user_name + Transkript]
         Alles in Flachtext, KEINE XML-Tags

Schema:  {items: [{task, owner, deadline, priority, evidence, context}]}

Params:  temperature=0.1, reasoning_effort="low" (Diktat) / "medium" (Meeting)
```

## Owner-Guardrails (Codex-Beitrag)

Wenn ein Aufnehmender (z.B. "Dr. Schuster") = Sprecher 1 ist:
- Sprecher 1 fasst oft zusammen: "Frau Dr. Weber kümmert sich um X" → Owner = Dr. Weber, NICHT Dr. Schuster
- Dr. Schuster nur bei Selbstzuweisung: "ich werde...", "das mache ich"
- Explizite Beispiele im Prompt helfen:
  ```
  'Herr Baumann macht ...' → owner: Herr Baumann
  'Dr. Klein macht ...' → owner: Dr. Klein
  'Ich informiere ...' → owner: Dr. Schuster
  ```

## Anti-Patterns (was NICHT funktioniert)

| Anti-Pattern | Warum schlecht |
|-------------|---------------|
| Negative Constraints ("Erfinde NICHT") | Schwächer als positive + Evidence-Pflicht |
| XML-Tags für Strukturierung | Keine Qualitätsverbesserung, +40% Latenz |
| Constraints verdoppeln (System + User) | VERSCHLECHTERT die Ergebnisse (1/5 Fakten statt 3/5) |
| "Assistent"-Rolle | Weniger präzise als "Experte"/"Tool" |
| YAML im Prompt | Crasht mit JSON-Schema response_format |
| Markdown als Prompt-Format | Modell formatiert statt zu extrahieren |

## Übertragbarkeit auf andere Modelle

Diese Regeln wurden für gpt-oss-120b getestet. Erwartete Übertragbarkeit:
- **Evidence-Pflicht**: Universell (struktureller Zwang, nicht modell-spezifisch)
- **Schema-Design**: Universell (JSON Schema wird von allen modernen Modellen unterstützt)
- **Flachtext > XML**: Möglicherweise modell-spezifisch. Claude-Modelle profitieren oft von XML-Tags.
- **Constraint-Platzierung**: Wahrscheinlich modell-spezifisch. Bei Groq-Caching ist System-Prompt statisch.
- **Rollen-Framing**: Wahrscheinlich universell (sachliche Rollen > dienende)

**Why:** Empirische Tests mit 50+ API-Calls zeigten signifikante Qualitätsunterschiede zwischen Prompt-Varianten. Diese Regeln vermeiden Halluzinationen, verbessern Fakten-Beibehaltung und stabilisieren die user_name-Zuordnung.

**How to apply:** Bei jedem neuen Prompt für ActScriber (oder ähnliche Extraktions-Tasks) diese Regeln als Checkliste verwenden. Bei Modell-Wechsel (z.B. auf Llama 4) die XML-Tag und Constraint-Platzierung-Regeln neu testen.
