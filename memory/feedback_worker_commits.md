---
name: Worker-Änderungen sofort committen
description: Bei Änderungen durch Worker-Sessions oder Linter immer committen und pushen
type: feedback
---

Bei Änderungen an Dateien (durch Worker-Sessions, Linter-Hooks, oder andere externe Modifikationen) immer committen und pushen, nicht warten.

**Why:** Matthias will dass Änderungen sofort im Git landen, damit der Build-Agent auf dem anderen PC immer den neuesten Stand hat.

**How to apply:** Wenn system-reminder meldet dass Dateien modifiziert wurden → prüfen ob Worker noch arbeitet. Falls Worker fertig: sofort committen+pushen. Falls Worker noch aktiv: Worker committen lassen, nicht dazwischenfunken.
