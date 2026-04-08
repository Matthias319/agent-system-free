---
name: Playwright Screenshots statt DOM-Snapshots
description: Bei großen Seiten Screenshots statt Snapshots nutzen, dann gezielt mit httpx+selectolax scrapen
type: feedback
---

Bei großen Webseiten (>50K Zeichen DOM) Screenshots statt `browser_snapshot` verwenden. Snapshots erzeugen 90K+ Zeichen Output und crashen das Tool.

**Why:** mein-aldi.de hat 91K Zeichen DOM-Output → Tool-Error. Screenshots sind ~100x kleiner und reichen für Navigation.

**How to apply:**
1. Mit `browser_take_screenshot` visuell navigieren (klicken, scrollen)
2. Sobald die richtige Seite/URL gefunden ist: URLs extrahieren
3. Dann mit httpx+selectolax die Produktdaten scrapen (kein Playwright-Overhead)
4. Dynamisch zwischen Playwright (Navigation) und httpx (Scraping) wechseln
