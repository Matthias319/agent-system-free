---
name: Philips Hue Smart Home — Setup & Präferenzen
description: Hue Bridge/Sync Box API-Zugang, 24 Lampen, 9 Räume, Custom-Szenen + Matthias' Licht-Philosophie und Farbpräferenzen
type: project
---

## Hue Bridge
- IP: 192.168.178.159 (Bridge v2, eckig)
- API Key: in ~/.env-agent (HUE_API_KEY)
- 24 Lampen, 9 Räume, 22+ Szenen (+ 8 neue Custom)

## Sync Box
- IP: 192.168.178.89 (HSB1, Firmware 2.5.4)
- Token: in ~/.env-agent (HUE_SYNCBOX_TOKEN)
- HDMI 1: Apple TV (eingesteckt), HDMI 2-4: frei
- WARNUNG: Powersave = kein HDMI-Signal! Immer Passthrough nutzen statt Powersave.

## DG-Raum "Oben" (Matthias' Wohnung)
Umbenannte Lampen:
- TV Licht (war: OLED Fernseher) — Lightstrip hinter TV
- Bar Links / Bar Mitte / Bar Rechts (waren: Hue Bar links/Mitte/rechts)
- Sofalampe (war: Sofa) — Wandlampe, direktes Licht
- Deckenlampe (war: Wohnzimmer) — Decke, direktes Licht
- Küchenlampe (war: Küche) — Decke
- Herdlicht (war: Hue lightstrip plus 1) — Strip über Herd

## Custom Szenen (Ein-Wort für Alexa)
Ocean, Sunset, Rose, Kupfer, Chillen, Film, Kochen, Hell

## Licht-Philosophie
- **Immer diffus/indirekt** — nie direkte Lampen abends (Sofalampe + Deckenlampe AUS)
- **Komplementärfarben** — keine random Farben, bewusste Farbtheorie
- **Flippig aber nicht krass** — lebendig, aber nicht Kirmes

## Farbprinzip
- **TV Backlight** = kühle Farbe (Teal, Jade, Cyan, Indigo) → erzeugt Tiefe
- **Bars links + rechts** = warme Farbe (Kupfer, Bernstein, Rosé, Korall) → symmetrisch, umhüllt
- **Bar Mitte** = Brückenfarbe (Mischung beider) → verbindet den Look
- **Herdlicht** = minimaler Hauch der Dominanten → Raum-Volumen

## Top-Szenen (Ranking)
1. Deep Ocean (Blau/Teal) — kühl, deep
2. Sunset Horizon (Bernstein/Magenta) — warm, einladend
3. Kupfer & Cyan (Split-Komplementär) — Hybrid aus 1+2
4. Rose & Jade (Rosé/Smaragd) — elegant, ungewöhnlich

## Musik-Kontext
- Hört Ben Böhmer, Melodic Techno
- Sync Box auf Music/Intense/melancholicEnergetic Palette
- Abends gedimmter, schöne Atmosphäre

**Why:** Matthias steuert sein Licht über Alexa mit kurzen Befehlen. Szenen sind auf diffuses/indirektes Licht optimiert.

**How to apply:** Bei Hue-Befehlen die neuen Lampennamen und Szenen verwenden. Sync Box nie auf Powersave wenn TV läuft.
