---
name: Facharbeit Vero — Adultismus in der Kita
description: Veros Facharbeit über Adultismus mit LaTeX-Quellen, Zitatprüfung, und bekannten Fehlern
type: project
---

Matthias hilft Veronika (Vero) bei ihrer Facharbeit zur Erzieherinnen-Ausbildung: "Adultismus in der Kita: Machtverhältnisse zwischen Erwachsenen und Kindern im Kita-Alltag".

**Why:** Vero hat die Facharbeit eingereicht/schreibt sie, Matthias prüft Zitate und korrigiert. Vero selbst hat rot markierte Stellen identifiziert, die sie im Buch nicht verifizieren konnte.

## Dateien

- **LaTeX-Projekt (Kapitel):** `/home/maetzger/Projects/Facharbeit/` — `main.tex` bindet Kapitel aus `chapters/` ein
- **v7 Single-File:** `/home/maetzger/shared/facharbeit/Facharbeit_Adultismus_v7.tex` (420 Zeilen) — aktuellste Version, eigenständig kompilierbar
- **Quellen-PDFs + Buchfotos:** `/home/maetzger/shared/facharbeit/quellen/`

## Quellen-Mapping

| Quelle | Datei | Abdeckung |
|--------|-------|-----------|
| Keßel 2022 (nifbe Nr. 38) | `nifbe - Adultismus_online.pdf` | Komplett (S. 3-20) |
| Finger 2023 (kiga heute 4/2023) | `Adultismus - kindergarten-heute-2024 (2).pdf` | S. 10-14 = Finger, S. 22-25 = Dittrich! |
| Winkelmann 2019 (Machtgeschichten) | `Leseprobe-Fortbildungsbuch_ machtgeschichten.pdf` + JPEGs | Leseprobe: S. 5-6, 15-25. Fotos: S. 28-29, 42-52, 55-66 |
| Boll/Remsperger-Kehm 2024 (wissen kompakt) | `Adultismus und Sprache - KiGa heute Heft.pdf` | Komplett (62 S.) |
| Hubrig 2025 | Symlink `/tmp/hubrig.pdf` (Unicode-Name) | Nur S. 25, 50-58 |

## Bekannte Zitatfehler (Stand 2026-03-25)

1. **Finger/Dittrich-Verwechslung:** "Vorwurfsfreier Tag" (S. 22-25) wird `finger2023` zugeordnet, ist aber von Willi Dittrich. Betrifft ~4 Zitate.
2. **Boll S. 26 für "Sensitive Responsivität":** S. 26 = Verhaltensampel-Kapitel, nicht Sensitive Responsivität (die steht im Vorwort S. 1).
3. **Winkelmann-Pronomen:** "Er stellt" statt "Sie stellt" — Winkelmann ist weiblich.
4. **Keßel S. 3 fragwürdig:** S. 3 = Abstract/Gliederung, spezifischer Beleg für "Tagesgestaltung, Sprache, Abläufe" fehlt dort.

## Prüfergebnis

Systematische Prüfung aller ~63 Zitate am 2026-03-25 durchgeführt (Team aus 4 Agents). Keßel und Winkelmann-Seitenzahlen zu >95% korrekt. Hauptproblem ist die Finger/Dittrich-Zuordnung, nicht die Seitenzahlen.

**How to apply:** Bei Fortsetzung der Facharbeit-Arbeit: v7.tex ist die aktuelle Arbeitsdatei. Korrekturen dort einarbeiten, nicht in den chapter-Dateien.
