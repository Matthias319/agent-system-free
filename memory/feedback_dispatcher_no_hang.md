---
name: Dispatcher darf nicht hängen nach Bash-Output
description: Nach Bash-Ergebnissen sofort weiter — nicht in Analyse versinken, kurze Zusammenfassung + nächster Ping
type: feedback
---

Als Dispatcher nach Bash-Output (Pings, Session-Checks) SOFORT weiter:
1. Ergebnis in 1-2 Sätzen zusammenfassen
2. Aktion wenn nötig (Permission akzeptieren)
3. Nächsten Ping planen
4. FERTIG

**Why:** Matthias hat beobachtet dass der Dispatcher sich nach Bash-Ergebnissen "aufhängt" — vermutlich weil zu viel Analyse/Text generiert wird und die Response zu lang wird oder ein Timeout greift.

**How to apply:** Ping-Ergebnisse maximal als Tabelle + 1 Satz. Keine mehrzeilige Analyse. Sofort nächsten Ping schedulen.
