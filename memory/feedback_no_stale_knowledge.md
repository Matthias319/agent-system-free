---
name: Kein veraltetes Wissen — immer recherchieren
description: Bei APIs, AI-Models, Produkten und Events IMMER aktuelle Quellen prüfen, nie Trainingswissen verwenden
type: feedback
---

Trainingswissen ist veraltet (Cutoff ~Mai 2025). Bei APIs, AI-Models, Produkten und aktuellen Events IMMER recherchieren.

**Why:** Mehrfach falsche Model-Namen (llama-3.3-70b-versatile statt existierendem Modell), veraltete API-Formate (Hue v1 vs v2), und fälschlich "gibt es noch nicht"-Behauptungen (iPhone 17 Pro Max). Matthias hat das mehrfach korrigiert.

**How to apply:**
- Bei Produkten/Releases/Events mit >5% Unsicherheit: `/web-search` BEVOR eine Aussage kommt
- Bei API-Integrationen: Docs lesen (context7, WebFetch, /web-search), nie raten
- Bei AI-Models: Modellnamen, Endpoints, Parameter immer verifizieren — API-Docs nie >1 Woche alt
- Ergebnisse (Model-Namen, Pricing, API-Format) in Memory schreiben
- Nie "das gibt es noch nicht" sagen ohne Recherche
