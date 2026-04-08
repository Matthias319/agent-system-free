# Web-Entwicklung — Learnings

Gesammelt aus MC3-Debugging-Sessions. Diese Fehler sind SYSTEMATISCH und
müssen bei JEDER Web-App-Entwicklung beachtet werden.

## 1. Prozess-Management bei systemd + Python multiprocessing

### Problem
`KillMode=process` tötet nur den Haupt-PID. Child-Prozesse (z.B. HTTP-Port
via `multiprocessing.Process`) überleben Restarts und servieren ALTEN Code.

### Checkliste nach JEDEM Restart
```bash
# IMMER prüfen: Läuft nur EIN Prozess-Paar?
ps aux | grep 'SERVICE_NAME.*app.py' | grep -v grep
# Erwartung: genau 2 Zeilen (Main + Child)
# Wenn mehr: kill ALTE PIDs, dann nochmal restarten
```

### Prävention
- SIGTERM-Handler im Python-Code, der Child-Prozesse explizit killt
- Nach jedem `systemctl restart`: Prozessliste prüfen
- Neuen API-Endpunkt testen: `curl localhost:PORT/api/NEW_ENDPOINT`

## 2. Browser-Cache bei Web-Entwicklung

### Problem
Browser (besonders iOS Safari) cachen JS/CSS aggressiv. Geänderter Code
wird nicht geladen. Symptom: "Fix funktioniert nicht" — aber Fix war nie aktiv.

### Prävention
- Cache-Control-Middleware MUSS in jeder Web-App sein:
  ```python
  @app.middleware("http")
  async def cache_control(request, call_next):
      response = await call_next(request)
      if request.url.path.startswith("/static/"):
          response.headers["Cache-Control"] = "no-store, must-revalidate"
      return response
  ```
- Bei jedem Deploy-relevanten Bug: ZUERST prüfen ob neuer Code geladen wird
- Im Browser-Console: `fetch('/static/js/main.js').then(r => r.text()).then(t => console.log(t.slice(0,100)))`

## 3. xterm.js vs. tmux Scrollback

### Problem
Full-Screen-TUI-Apps (Claude Code, vim, htop) nutzen den Alternate Screen Buffer.
xterm.js hat dann nur wenige Zeilen Scrollback (baseY ~ 0-5). `term.scrollLines()`
bewegt zwar viewportY, aber es gibt fast nichts zu sehen.

### Lösung
Fuer echtes Scrolling in TUI-Apps: tmux copy-mode nutzen.
```python
# Enter copy mode
tmux copy-mode -t SESSION
# Scroll
tmux send-keys -t SESSION -X -N 5 scroll-up
# Exit
tmux send-keys -t SESSION q
```

### Diagnose
```javascript
// Im Browser-Console: Scrollback prüfen
const buf = term.buffer.active;
console.log('baseY=' + buf.baseY + ' viewportY=' + buf.viewportY);
// baseY < 10 = kaum Scrollback = tmux copy-mode nötig
```

## 4. iOS Safari Touch-Events

### Problem
iOS Safari dispatcht touchmove/touchend zum touchstart-Target-Element,
NICHT zum Element unter dem Finger. `document.addEventListener('touchmove')`
empfängt die Events NICHT zuverlässig.

### Regel
**ALLE Touch-Event-Listener auf das GLEICHE Element wie touchstart.**
```javascript
// FALSCH:
ball.addEventListener('touchstart', ...);
document.addEventListener('touchmove', ...);  // iOS: unreliable!

// RICHTIG:
ball.addEventListener('touchstart', ...);
ball.addEventListener('touchmove', ...);  // Same element!
ball.addEventListener('touchend', ...);   // Same element!
```

### Ausnahme
Drag-Handles (Height Slider) wo der Finger das Element verlässt:
Dort MUSS man `document` verwenden, aber mit Guard (`if (!dragging) return`).
Funktioniert nur weil der Handle gross genug ist und der initiale touchstart
darauf registriert ist.

## 5. Playwright-Testing: Limitationen auf Touch-Features

### Problem
Playwright emuliert Desktop (pointer: fine). Touch-only Features
(scroll orb, virtual keys, height slider) sind unsichtbar/inaktiv.

### Workarounds
- **Logik testen**: API-Endpunkte direkt mit `fetch()` via `browser_evaluate`
- **xterm.js testen**: `MCB.terminal.scroll(N)` via evaluate (prüft ob scrollLines wirkt)
- **Touch NICHT testbar**: Server-seitiges Debug-Logging einbauen,
  User testen lassen, Logs remote auslesen
- **Debug-Overlay**: Temporäres `<pre>` Element mit Live-Daten für iPad-Testing
- **Server-Side Log-API**: POST-Endpunkt wo Client Debug-Daten hinschickt

### Debug-Pattern für Touch-Features
```javascript
// 1. Debug-Log-Funktion mit Server-Sync
function debugLog(msg) {
  console.log(msg);
  // Batch-POST an /api/debug/log
  fetch('/api/debug/log', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({lines: [msg]}),
  }).catch(() => {});
}

// 2. GET-Endpunkt zum Auslesen
// curl localhost:PORT/api/debug/log
```

## 6. Deployment-Verifikation (IMMER nach Code-Änderungen)

### Checkliste
1. **Prozesse prüfen**: `ps aux | grep SERVICE | grep -v grep` — nur erwartete PIDs
2. **Endpunkt testen**: `curl localhost:PORT/api/health` — 200 OK
3. **Neuer Code aktiv?**: Neuen Endpunkt/Feature direkt testen
4. **Cache**: Bei Web-Apps den Browser-Cache prüfen (Cache-Control Header)
5. **Logs**: `journalctl -u SERVICE --since "30s ago" -f` — keine Errors

### Anti-Pattern
NIEMALS: Code ändern → restart → User testen lassen → "geht nicht" → repeat
STATTDESSEN: Code ändern → restart → SELBST verifizieren → User testen lassen

## 7. Groq Whisper API

- **Modell für Deutsch**: `whisper-large-v3` (NICHT `-turbo`, das ist nur Englisch)
- **Audio-Optimierung**: Mono 16kHz, 32kbps Opus — minimal für Sprache, schneller Upload
- **Timeout**: 60s (große Dateien brauchen Zeit)
- **Max Aufnahme**: 5 Minuten (VOICE_MAX_DURATION = 300000ms)
