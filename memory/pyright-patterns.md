# Pyright: Häufige Fehler-Patterns und Fixes

## Setup

```bash
# Ausführen
cd /path/to/project && ~/.local/share/uv/tools/pyright/bin/pyright app.py

# Projekt-Config (PFLICHT für venv-Erkennung)
# pyrightconfig.json im Projekt-Root:
{"venvPath": ".", "venv": ".venv", "pythonVersion": "3.13"}
```

## Pattern 1: json.loads() → dict[str, str] Inferenz

**Problem:** `json.loads()` gibt `Any` zurück, aber wenn ein Fallback-Dict wie `{"state": "error"}` im selben Scope ist, inferiert Pyright den Typ als `dict[str, str]`. Dann schlägt jede Zuweisung fehl, die keinen String-Wert hat.

```python
# FEHLER:
data = json.loads(text)      # Pyright: Any
data = {"state": "error"}    # Pyright: dict[str, str] (dominiert)
data["nested"] = {"a": 1}   # ERROR: dict != str

# FIX:
data: dict = json.loads(text)
```

## Pattern 2: **kwargs-Forwarding mit dict[str, str]

**Problem:** Ein leeres Dict `{}` wird als `dict[str, str]` inferiert wenn nur Strings zugewiesen werden. Beim Entpacken mit `**` in typisierte Funktionen (z.B. `uvicorn.run()`) entstehen dutzende Folgefehler.

```python
# FEHLER:
ssl_opts = {}                              # dict[str, str]
ssl_opts = {"ssl_certfile": str(cert)}     # bestätigt str-Werte
uvicorn.run(app, **ssl_opts)              # 24 Folgefehler!

# FIX:
ssl_opts: dict[str, Any] = {}
```

## Pattern 3: Fehlender typing-Import

Nach dem Hinzufügen von `Any`, `dict[str, Any]` etc. prüfen ob `from typing import Any` vorhanden ist. Python 3.13 erlaubt `dict` direkt (kein `Dict` aus typing nötig), aber `Any` muss immer importiert werden.

## Systematischer Workflow

1. `pyrightconfig.json` prüfen/anlegen
2. Pyright ausführen
3. Import-Fehler zuerst beheben (oft nur Config-Problem)
4. Echte Typ-Fehler kategorisieren (meist dict-Inferenz oder kwargs-Forwarding)
5. Minimal-invasiv fixen (Type-Annotation, nicht Code umbauen)
6. Erneut laufen lassen bis 0 errors
