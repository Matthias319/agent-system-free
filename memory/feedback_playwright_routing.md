---
name: Playwright CLI für Screenshots, MCP für Interaktion
description: Reine Screenshots per npx playwright CLI (schneller), Playwright MCP nur wenn Interaktion nötig (klicken, navigieren, Formulare)
type: feedback
---

Playwright-Routing nach Use-Case:

- **Reine Screenshots**: `npx playwright screenshot --viewport-size=430,932 --full-page URL datei.png`
- **Interaktion nötig** (klicken, Formulare, navigieren): Playwright MCP Server

**Why:** MCP hat Overhead für einfache Screenshots. CLI ist schneller und reicht für Preview/Dokumentation.

**How to apply:** Default = CLI für Screenshots. MCP nur wenn ich mit der Seite interagieren muss.
