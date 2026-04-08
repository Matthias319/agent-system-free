---
name: HTML-Reports als Default-Output
description: Matthias will zu 90% visuell beeindruckende HTML-Berichte — nur bei Kurzantworten (2-3 Sätze) reicht Text. Immer report-renderer.py nutzen.
type: feedback
---

Zu 90% soll die Antwort als HTML-Bericht geliefert werden — interaktiv oder visuell beeindruckend gestaltet. Nur wenn die Antwort in wenigen Sätzen gesagt werden kann, reicht plain text.

**Why:** Matthias nutzt den Server primär über ein Dashboard (MCV4/MCB) und bevorzugt visuelle, durchgestaltete Outputs. Bei Recherchen mit Links oder nachlesbaren Inhalten sind Terminal-Text-Walls nutzlos — er will Links anklicken und nachlesen können.

**How to apply:**
- Bei jeder nicht-trivialen Antwort (Analyse, Recherche, Vergleich, Übersicht) automatisch HTML via report-renderer.py
- Design-Language: Warm Dark Editorial (`/design-language` Skill)
- Datei nach `~/shared/reports/` schreiben
- Nur bei echten Kurzantworten (Ja/Nein, ein Befehl, 2-3 Sätze) auf HTML verzichten
- Im Zweifel: Report erstellen
