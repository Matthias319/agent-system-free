# agent-system-free

Zweitsystem zum Primärsystem [agent-system](https://github.com/Matthias319/agent-system) (Claude Code).
Läuft mit **OpenCode** als Runtime — komplett unabhängig von Anthropic/Claude.

## Was ist das?

Ein vollständiges Agent-System mit 21 Skills, 49 Python-Tools, Rules, Memory und Hooks.
Portiert vom Claude Code basierten Primärsystem. Gleiche Fähigkeiten, anderes LLM-Backend.

**Zwei Zwecke:**
1. **Notfall-Ersatz** — wenn Anthropic-Server down sind (passiert regelmäßig)
2. **Modell-Benchmarking** — wie gut funktioniert unser System mit anderen LLMs?

## Architektur

```
OpenCode (Runtime) → Ollama Cloud / Groq → LLM (Kimi K2, GLM 5.1, etc.)
     ↓
  AGENTS.md (System-Prompt) + rules/ + skills/ + tools/ + memory/
```

- **OpenCode** übernimmt die Rolle von Claude Code (Tool-Calling, File I/O, Bash, Sub-Agents)
- **Ollama Cloud** oder **Groq** routet zu den LLM-Backends
- **AGENTS.md** ist das Äquivalent zu CLAUDE.md
- Skills, Tools und Memory sind vom Primärsystem portiert

## Getestete + empfohlene Modelle

### Groq (Firma zahlt, schnellste Inference)

| Modell | T1 Read+Write | T2 Create 3 | T3 Edit 3 | T4 Skill | Config | Empfehlung |
|--------|--------------|-------------|-----------|----------|--------|------------|
| **Qwen3 32B** | **8.5s** ✓ | **8.5s** 3/3 | **10.6s** ✓ | **39s** ✓ | Keine | **EMPFOHLEN — Allrounder** |
| GPT-OSS 20B | **6.2s** ✓ | **6.9s** 3/3 | 31s ✓ | 61s ✓ | --variant minimal | Schnellste einfache Tasks |
| GPT-OSS 120B | 56s ✓ | 56s 3/3 | 113s ✓ | 50s ✓ | --variant minimal | Für lange Outputs (65K) |
| Kimi K2 | 10s ✓ | 8s 3/3 | 12s ✓ | 21s ✓ | Keine | ⚠️ Wird ~15.04. abgesetzt |

### Ollama Cloud (kostenlos/günstig, bessere Qualität)

| Modell | T1 Read+Write | T2 Create 3 | T3 Edit 3 | T4 Skill | Bug-Test | Empfehlung |
|--------|--------------|-------------|-----------|----------|----------|------------|
| **GLM 5.1** | 57s ✓ | **11s** 3/3 | 33s ✓ | 70s ✓ | ✓ Gefunden+Gefixt+Verifiziert | **EMPFOHLEN — beste Qualität** |
| Kimi K2.5 | 25s ✓ | 16s 3/3 | 18s ✓ | 69s ✓ | nicht getestet | Schneller Allrounder |
| Gemma 4 31B | 23s ✓ | 57s 3/3 | 67s ✓ | 21s ✓ | nicht getestet | Solide Google-Alternative |
| MiniMax M2.7 | **29s** ✓ | 25s 3/3 | 33s ✓ | **44s** ✓ | ✗ Hängt bei Multi-Turn | Nur für einfache Tasks |

### Empfohlenes Setup

| Situation | Modell | Warum |
|-----------|--------|-------|
| **Default (Notfall)** | Qwen3 32B (Groq) | Schnell, keine Hacks, Firma zahlt |
| **Qualität zählt** | GLM 5.1 (Ollama Cloud) | Beste Antworten, Bug-Debugging, Quellenangaben |
| **Quick Tasks** | GPT-OSS 20B (Groq) | 6s für Read/Write, aber --variant minimal nötig |
| **Groq + Ollama down** | Gemma 4 31B (Ollama Cloud) | Solide Backup-Option |

### Bekannte Probleme

- **GPT-OSS (120B/20B)**: Reasoning-Modelle, brauchen `--variant minimal` sonst stoppen sie nach erstem Tool-Call
- **MiniMax M2.7**: Hängt bei komplexen Multi-Turn Agent-Workflows (3+ Turns) wegen `reasoning` Feld im Response
- **Ollama Free Tier**: 1 Concurrent Model, Session-Limits (5h Session, 7-Tage Reset). Pro ($20/mo) für intensiven Einsatz

## Quick Start

### 1. Prerequisites installieren

```bash
# OpenCode (Runtime)
curl -fsSL https://opencode.ai/install | bash

# Ollama (für Cloud-Modelle)
curl -fsSL https://ollama.com/install.sh | sh
ollama signin  # Browser öffnet sich, Account erstellen/einloggen
```

### 2. Repo klonen

```bash
git clone https://github.com/Matthias319/agent-system-free.git
cd agent-system-free
```

### 3. .env einrichten

```bash
cp .env.example .env
# Dann .env editieren und Keys eintragen:
# - GROQ_API_KEY (Pflicht für Groq-Provider)
# - Strato + Agent-Mail Keys (optional, für Deploy/Mail-Skills)
```

### 4. Cloud-Modelle registrieren

```bash
ollama pull glm-5.1:cloud
ollama pull kimi-k2.5:cloud
ollama pull minimax-m2.7:cloud
ollama pull gemma4:31b-cloud
ollama pull gpt-oss:120b-cloud
ollama pull qwen3.5:397b-cloud
```

### 5. Starten

```bash
# Empfohlen — sourced .env automatisch:
./start.sh

# Oder für einzelne Aufgaben:
./start.sh run -m "groq/moonshotai/kimi-k2-instruct-0905" --dangerously-skip-permissions "Deine Aufgabe"
```

## Repo-Struktur

```
agent-system-free/
├── AGENTS.md                  # System-Instruktionen (= CLAUDE.md Äquivalent)
├── opencode.json              # Provider-Config (Ollama Cloud + Groq)
├── start.sh                   # Wrapper — sourced .env, startet OpenCode
├── .env                       # API-Keys (gitignored, aus .env.example erstellen)
├── .env.example               # Template für .env
│
├── rules/                     # Verhaltensregeln
│   ├── core.md                # Tool-Vorrang, Anti-Halluzination, Reversibility
│   └── coding-style.md        # Python/JS Konventionen, Ruff, uv
├── rules-lib/                 # Optionale Rules (bei Bedarf laden)
│   ├── agent.md               # Sub-Agent Regeln
│   ├── web.md                 # Web-Recherche Regeln
│   ├── output.md              # HTML/Report Regeln
│   ├── code-nav.md            # LSP/Grep/AST Regeln
│   ├── groq.md                # Groq-spezifische Regeln
│   └── prompting.md           # Prompt Engineering Regeln
│
├── skills/                    # 21 Skill-Workflows (je ein SKILL.md)
│   ├── web-search/            # Web-Recherche mit Crawler
│   ├── html-reports/          # HTML-Report Generierung
│   ├── social-research/       # Reddit/YouTube/TikTok Analyse
│   ├── anti-hallucination/    # Fakten-Verifikation
│   ├── autoresearch/          # Iterative Optimierungsloops
│   ├── adversarial-audit/     # Security Audit
│   ├── orchestrate/           # Multi-Agent Orchestrierung
│   ├── tasks/                 # Task-Management
│   ├── deploy/                # SFTP Deploy auf Strato
│   ├── log-analyse/           # Server-Log Analyse
│   ├── system-check/          # System Health Check
│   ├── market-check/          # Gebrauchtpreis-Recherche
│   ├── flights/               # Flugpreis-Recherche
│   ├── grocery/               # Einkaufslisten + Warenkorb
│   ├── browser-scrape/        # JS-heavy Seiten scrapen
│   ├── todo-extract/          # Action-Points aus Dokumenten
│   ├── pi-search/             # Session-History Suche
│   ├── session-labels/        # Terminal-Tab Benennung
│   ├── spawn-session/         # Parallele Sessions
│   └── ...
│
├── tools/                     # 49 Python-Tools (standalone)
│   ├── research-crawler.py    # Bulk-URL Crawler mit Qualitäts-Scoring
│   ├── report-renderer.py     # HTML-Report aus JSON + Template
│   ├── zettel.py              # Zettelkasten (SQLite Wissensspeicher)
│   ├── skill-tracker.py       # Skill-Nutzung tracken
│   ├── memory-router.py       # Memory-Lookup vor Tool-Nutzung
│   ├── fast-search.py         # Parallele Web-Suche
│   ├── web-search-v2.py       # Erweiterte Recherche
│   ├── social-research-runner.py
│   ├── youtube-intel.py
│   ├── deploy.py
│   ├── log-analyse.py
│   ├── system-check.py
│   └── ...
│
├── memory/                    # Persistenter Wissensspeicher
│   ├── MEMORY.md              # Memory-Index
│   └── *.md                   # Einzelne Memories (Markdown + YAML Frontmatter)
│
├── hooks/                     # Event-Hooks (Bash, Original)
│   ├── session-start.sh
│   ├── session-end.sh
│   ├── format-python.sh
│   └── skill-track.sh
│
├── .opencode/
│   └── plugins/
│       └── agent-system.ts    # Hook-Bridge: Bash-Hooks → OpenCode Events
│
└── data/
    ├── skill-routing-block.md # Skill-Routing für Sub-Agents
    └── worker-base-context.md # Basis-Kontext für Worker
```

## Provider-Konfiguration

Die `opencode.json` definiert zwei Provider:

**Ollama Cloud** — 6 Modelle, kein API-Key nötig (nur `ollama signin`):
- glm-5.1:cloud, kimi-k2.5:cloud, minimax-m2.7:cloud
- gemma4:31b-cloud, gpt-oss:120b-cloud, qwen3.5:397b-cloud

**Groq** — Schnellster Provider, API-Key via `GROQ_API_KEY` Env-Variable:
- moonshotai/kimi-k2-instruct-0905 (262K Context, 16K Output)
- openai/gpt-oss-120b

### Modell wechseln

```bash
# In der TUI: Modell-Picker nutzen

# Oder per CLI:
./start.sh run -m "ollama-cloud/glm-5.1:cloud" "Deine Aufgabe"
./start.sh run -m "groq/moonshotai/kimi-k2-instruct-0905" "Deine Aufgabe"
```

## Was funktioniert (getestet)

| Fähigkeit | Status | Notiz |
|-----------|--------|-------|
| AGENTS.md + Rules laden | ✓ | Automatisch |
| Skills laden + ausführen | ✓ | web-search vollständig getestet |
| File Read/Write/Edit | ✓ | Multi-File-Edit funktioniert |
| Bash/Shell | ✓ | Python-Tools aufrufbar |
| Tool-Calling Ketten | ✓ | Glob → Read → Edit → Write |
| Error-Recovery | ✓ | Modell korrigiert sich selbst |
| Python-Tools (Crawler, Tracker) | ✓ | Über Bash aufrufbar |
| Groq Rate-Limits | ✓ | 5 Rapid-Fire Calls, kein Throttling |
| Kontext-Stress (~120K Tokens) | ✓ | 7 große Dateien gelesen + zusammengefasst |

## Was noch nicht getestet / eingerichtet ist

- MCP-Server (context7, stealth-browser) — Config-Format muss angepasst werden
- Sub-Agent Spawning via OpenCode TaskTool
- Hooks-Plugin (.opencode/plugins/) — existiert aber ungetestet
- Alle 21 Skills einzeln durchspielen
- Windows-Kompatibilität

## Unterschiede zum Primärsystem

| Aspekt | Primärsystem (Claude Code) | Dieses Repo (OpenCode) |
|--------|---------------------------|----------------------|
| Runtime | Claude Code CLI | OpenCode |
| LLM | Claude Opus 4.6 (nur Anthropic) | Kimi K2, GLM 5.1, etc. (austauschbar) |
| Config | ~/.claude/settings.json | opencode.json |
| System-Prompt | CLAUDE.md | AGENTS.md |
| API-Keys | ~/.claude/.env | .env im Repo-Root |
| Hooks | Bash in settings.json | TypeScript Plugins |
| Codex-Sparring | Ja (GPT-5.4) | Nein (entfernt) |
| Pfade | ~/.claude/tools/X.py | ./tools/X.py (relativ) |

## Coding-Konventionen

- Python 3.12+, uv für Packages, Ruff für Formatting (88 chars)
- SQLite für Persistenz
- Kein Docker, kein Over-Engineering
- Deutsche Texte: Echte UTF-8-Umlaute (ä ö ü), NIEMALS ae oe ue
