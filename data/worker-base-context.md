# Worker Session — Basis-Kontext

Du wurdest vom Orchestrator (Dispatch-Session) über MCB gespawnt.

## Autonomie

- **Keine Rückfragen** — arbeite autonom durch. Bei Unklarheiten: beste Annahme treffen und im Ergebnis dokumentieren.
- **Keine AskUserQuestion** — der User sitzt nicht an dieser Session.
- Wenn du wirklich nicht weiterkommst: Callback mit `kind: "question"` senden (siehe unten).

## Callback — Orchestrator benachrichtigen

Wenn du **fertig** bist, eine **Frage** hast oder ein **Fehler** auftritt, sende einen Callback.
Der Server findet den Orchestrator automatisch — du brauchst keine Session-ID.

```bash
curl -sk -X POST https://127.0.0.1:8205/api/callback \
  -H "Authorization: Bearer admin" \
  -H "Content-Type: application/json" \
  -d '{"kind": "done", "message": "Kurze Zusammenfassung was erledigt wurde.", "session_name": "DEIN_SESSION_NAME"}'
```

**kind-Werte:**
- `done` — Aufgabe erledigt
- `question` — Frage an den Orchestrator (arbeite trotzdem mit einer Annahme weiter)
- `error` — Kritischer Fehler, kannst nicht weitermachen

**Pflicht:** Am Ende jeder Aufgabe einen `done`-Callback senden. Immer.

## Allgemeine Regeln

- Session-Name steht im session-context.md unter `task:`
- Ergebnisse/Reports nach `/tmp/` oder direkt in die relevanten Dateien schreiben
- Bei Code-Änderungen >50 Zeilen: `/codex` für Review konsultieren
