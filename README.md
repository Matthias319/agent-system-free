# agent-system-free

API-agnostisches Agent-System — funktioniert mit Ollama, OpenAI, Groq und anderen LLM-Backends.
Kein Anthropic/Claude. Läuft mit [OpenCode](https://opencode.ai) als Runtime.

## Zweck

1. **Notfall-Ersatz** wenn Anthropic-Server down sind
2. **Experiment** ob lokale/alternative Modelle mit unserem Agent-System funktionieren

## Unterstützte Modelle

### Cloud (via Ollama Cloud)
- GPT-OSS 120B
- GLM 5.1 (Zhipu)
- Kimi K2 (Moonshot)
- MiniMax M2.7
- DeepSeek V3.1

### Cloud (via Groq)
- GPT-OSS 120B

### Lokal (via Ollama)
- Gemma 4 31B / 26B / 4.5B

## Quick Start

```bash
# 1. OpenCode installieren
curl -fsSL https://opencode.ai/install | bash

# 2. Ollama installieren + anmelden
curl -fsSL https://ollama.com/install.sh | sh
ollama signin

# 3. Cloud-Modelle registrieren
ollama pull gpt-oss:120b-cloud
ollama pull glm-5.1:cloud
ollama pull kimi-k2:cloud

# 4. Repo klonen + starten
git clone https://github.com/Matthias319/agent-system-free.git
cd agent-system-free
opencode
```

## Struktur

```
├── AGENTS.md          # System-Instruktionen
├── opencode.json      # Provider + MCP Config
├── rules/             # Verhaltensregeln
├── skills/            # 22 Skill-Workflows (SKILL.md)
├── tools/             # 49 Python-Tools
├── memory/            # Persistenter Wissensspeicher
├── hooks/             # Event-Hooks (Bash)
├── data/              # Routing-Daten
└── .opencode/plugins/ # OpenCode Plugin (Hook-Bridge)
```

## Primärsystem

Das Primärsystem (Claude Code + Anthropic) lebt unter:
https://github.com/Matthias319/agent-system
