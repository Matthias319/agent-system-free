---
name: Sequential research for purchase decisions
description: Bei Kaufberatung/Recherche sequentiell arbeiten statt parallel, damit spätere Schritte von früheren Erkenntnissen profitieren
type: feedback
---

Bei mehrstufiger Recherche (Research → Social → Marktsuche) SEQUENTIELL arbeiten, nicht parallel.

**Why:** Parallele Agents enrichen ihre Queries nur mit Trainingswissen/Inferenz. Wenn z.B. die Kleinanzeigen-Suche erst NACH der Web-Recherche läuft, kann sie gezielt nach den Modellen suchen, die sich als gut herausgestellt haben — nicht nur nach denen, die das Modell aus dem Training kennt. Die Qualität der späteren Schritte steigt massiv.

**How to apply:** Bei Kaufberatung, Produktrecherche, oder mehrstufigen Recherche-Tasks: Erst Wissen aufbauen (Web → Social), dann mit diesem Wissen die finale Suche (Markt/Kleinanzeigen) durchführen. Subagents nur für wirklich unabhängige Teilaufgaben.
