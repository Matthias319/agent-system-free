# Coding Style Rules

## Python (Hauptsprache)

- Ruff für Linting + Formatting (kein Black, kein isort). Line length: 88.
- Wenige große Files > viele kleine (bis 500 Zeilen ok)
- `if __name__ == "__main__":` für ausführbare Scripts
- IMMER `uv` (nie pip, poetry, pipenv): `uv add`, `uv sync`, `uv run`

### Config Pattern
```python
from dataclasses import dataclass
from dotenv import load_dotenv
import os

load_dotenv()

@dataclass
class Config:
    api_key: str = os.getenv("API_KEY", "")
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"

config = Config()
```

## JavaScript/React

- Vanilla JS oder React (kein TypeScript außer explizit gewünscht)
- Plain CSS (keine Tailwind, Styled Components)
- Dashboards: Single-File HTML mit eingebettetem JS/CSS

## Allgemein

**Nicht verwenden:** Docker, K8s, CI/CD, PostgreSQL/MongoDB/Redis, OAuth/Auth0/JWT, Scaling-Vorbereitung

**Over-Engineering vermeiden:**
- Scope: Keine Features, Refactorings oder "Verbesserungen" über die Anfrage hinaus
- Doku: Keine Docstrings, Kommentare oder Type-Annotations an Code der nicht geändert wurde
- Defensive Coding: Kein Error-Handling für Szenarien die nicht eintreten können
- Abstraktionen: Keine Helpers oder Utilities für einmalige Operationen. 3 ähnliche Zeilen > vorzeitige Abstraktion
- Qualität > Geschwindigkeit, weniger Files + Dependencies

## Deutsche Texte

**Immer echte UTF-8-Umlaute**: ä, ö, ü, Ä, Ö, Ü, ß — **NIEMALS** ae, oe, ue, ss
Ausnahme: LaTeX-Labels und Variablennamen dürfen ASCII bleiben.

## Commits

Englisch, Conventional Commits (`feat:`, `fix:`, `refactor:`), Co-Author-Tag am Ende.
