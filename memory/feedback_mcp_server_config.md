---
name: MCP Server Konfiguration
description: Custom MCP Server gehören in ~/.claude.json (User-Scope), NICHT in settings.json. Setup via claude mcp add.
type: feedback
---

Custom MCP Server in `~/.claude.json` registrieren, NICHT in `~/.claude/settings.json`.

**Why:** `settings.json` → `mcpServers` wird nur für Plugin-bereitgestellte MCP-Server geladen. Custom MCP-Server werden dort ignoriert — kein Fehler, einfach still nicht geladen.

**How to apply:**

Setup-Befehl:
```bash
claude mcp add --transport stdio --scope user <server-name> -- <command> <args...>
```

Das schreibt in `~/.claude.json` unter `mcpServers`. Danach `env` manuell in `~/.claude.json` ergänzen falls nötig (z.B. `"env": {"DISPLAY": ":99"}`).

Verifikation: `claude mcp list` — muss `✓ Connected` zeigen.

| Konfigurationsort | Zweck |
|---|---|
| `~/.claude.json` → `mcpServers` | **Custom MCP-Server (User-Scope, alle Sessions)** |
| `.mcp.json` im Projekt-Root | Projekt-spezifische MCP-Server |
| `~/.claude/settings.json` → `mcpServers` | NUR Plugin-MCP-Server (NICHT für Custom) |
| `~/.claude/settings.json` → `enabledPlugins` | Plugins aktivieren/deaktivieren |

Gelernt am 30.03.2026 beim Stealth Browser MCP Setup — 3 Versuche bis die richtige Location gefunden war.
