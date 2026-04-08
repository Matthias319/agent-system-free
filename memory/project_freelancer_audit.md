---
name: IT-Freelancer Scheinselbstständigkeit Audit — asambeauty GmbH
description: Vollständiges Audit-Projekt für act legal / Schwilden — 22 Freelancer, 8 Firmen, Vertragsanalyse, HTML-Report, Excel-Deliverable, Vertragsentwürfe
type: project
---

# IT-Freelancer Scheinselbstständigkeit Audit — asambeauty GmbH

## Projektüberblick

**Mandant:** asambeauty GmbH (Kosmetik/E-Commerce)
**Kanzlei:** act legal (Matthias' Arbeitgeber)
**Anwalt:** Stefan Schwilden (externer Anwalt, bearbeitet den Fall für act legal)
**Gegenstand:** Prüfung von 22 IT-Freelancern bei 8 Dienstleistern auf Scheinselbstständigkeit (§ 7 SGB IV, § 611a BGB, AÜG)
**Zeitraum:** März 2026 (Hauptarbeit 18.-20.03.2026)

## Beteiligte Firmen & Freelancer

| Firma | Freelancer (Excel-Zeilen) | Risiko (vertraglich) |
|-------|--------------------------|---------------------|
| cebesoft GmbH | Heindl, Bernhard (Row 6) | MITTEL-HOCH |
| Codesprint / Ostermeyr | Ostermeyr, Alexander (Row 7) | MITTEL-HOCH |
| basecom / redhotmagma | Dambacher + 4 weitere (Rows 8-12) | HOCH — Kettenkonstellation |
| Arnia Software SRL | Gemene, Bradescu (Rows 13-14) | MITTEL |
| Intertec GmbH/DOOEL | Ristovski + 4 weitere (Rows 15, 20-23) | HOCH — Vierparteienkette |
| Flex Group sp. z o. o. | Nepran + 3 weitere (Rows 16-19) | HOCH — arbeitnehmertypisch |
| NODECO-Solutions / Notzon | Notzon (Row 24) | MITTEL (↑hoch) — DRV-Vorbelastung |
| hubside Consulting GmbH | Droste + 2 weitere (Rows 25-27) | MITTEL (↓gering) |

## Dateien & Verzeichnisse

### Quelldokumente (Verträge)
```
/home/maetzger/shared/freelancer-audit/
├── Arnia Software SRL (IT)/          — Framework Agreement, SOWs, Bestätigung
├── basecom GmbH & Co. KG (IT-Bereich)/ — Rahmenvertrag basecom + rhm-Vertrag
├── cebesoft GmbH (Heindl, Bernhard)/ — DL-Vertrag + 2 Zusätze
├── Codesprint (Ostermeyr, Alexander)/ — DL-Vertrag + Rechnung
├── Flex Group sp. z o. o/            — Service Agreement + Addenda 1,3,4
├── hubside Consulting GmbH/          — Vertrag 2026 + ZV Nr. 1 (NOT SIGNED)
├── Intertec GmbH (IT-Bereich)/       — MSA, SOW, Struktur-PDF, Einschätzung
├── NODECO-Solutions (J.Notzon)/      — Aufhebungsvereinbarung + neuer Vertrag
├── analyse/                          — 7 Analyse-Markdown-Dateien (00-06)
└── rechtsgrundlage.md                — Rechtlicher Rahmen
```

### Analyse-Dateien
```
/home/maetzger/shared/freelancer-audit/analyse/
├── 00_gesamtuebersicht.md       — Gesamtübersicht aller 22 Freelancer
├── 01_cebesoft_codesprint.md    — Einzelanalyse cebesoft + Codesprint
├── 02_basecom.md                — Einzelanalyse basecom/rhm-Kette
├── 03_arnia_intertec.md         — Einzelanalyse Arnia + Intertec
├── 04_flex_hubside_nodeco.md    — Einzelanalyse Flex, hubside, NODECO
├── 05_excel_vertragsabgleich.md — Excel-Daten vs. Vertragsrealität
└── 06_rechtsverifikation.md     — Juristische Verifikation
```

### Deliverables

| Datei | Beschreibung | Zugriff |
|-------|-------------|---------|
| `/home/maetzger/shared/reports/freelancer-audit-2026-03-19.html` | **Haupt-Audit-Report** (~104 KB) — vollständige Analyse aller 8 Firmen mit Risikobewertungen, Vertragsdetails, Empfehlungen | `audit.actlegal-events.com` |
| `/home/maetzger/shared/reports/vertragsentwuerfe.html` | **Vertragsentwürfe** (~92 KB) — Änderungsvorschläge pro Firma mit Tabbed-UI, Schweregrad-Codierung, AÜG-Hinweisen | `audit.actlegal-events.com/vertragsentwuerfe.html` |
| `/home/maetzger/shared/chat-images/20260320-112601_Kopie von 260318_Checkliste act legal_IT-Freelancer (002).xlsx` | **Schwildens Excel** — seine Original-Checkliste, erweitert um Vertragsanalyse-Spalten + 8 Änderungs-Tabs | Lokal |
| `/home/maetzger/shared/freelancer-audit/260318_Checkliste act legal_IT-Freelancer.xlsx` | **Unsere Excel-Kopie** — eigene Risikobewertungs-Tab (separates Sheet) | Lokal |

### Meeting-Transkript
```
/tmp/schwilden_transcript.json    — Groq Whisper-Transkript vom 20.03.2026 (~12 Min)
```

### Server & Hosting
```
/home/maetzger/shared/reports/audit-server.py   — HTTP-Server mit Basic Auth
```

## Technische Infrastruktur

- **Hosting:** `audit.actlegal-events.com` via Cloudflare Tunnel (`490ab05a-2cdd-410e-b207-2ba57b2286f6`)
- **Auth:** HTTP Basic Auth — Passwort: `actlegalaudit2026` (beliebiger Username)
- **Server:** `audit-server.py` auf Port 8201 (NICHT Port 8200 — das ist MCV4!)
- **Font:** Source Sans 3 (Body), Calibri (Excel)

## Schwildens Excel-Struktur (nach Bearbeitung)

**Sheet "Tabelle1":** 53 Zeilen × 76 Spalten
- **Cols A–AN:** Schwildens Kriterien-Checkliste (Ja/Nein pro Freelancer)
- **Col AO (41):** Leerspalte / Trenner
- **Col AP (42):** Name (Freelancer)
- **Col AQ (43):** Schwildens vorläufige Risikobewertung (HOCH/MITTEL/GERING)
- **Col AR (44):** Seine Begründung
- **Col AS (45):** "Durchsicht Vertrag durch act legal ja/nein" → **befüllt mit Handlungsbedarf**
- **Col AT (46):** ⭐ NEU — Kritische Vertragspunkte (rote Schrift)
- **Col AU (47):** ⭐ NEU — Positive Vertragspunkte (grüne Schrift)
- **Col AV (48):** ⭐ NEU — Vertragliche Risikobewertung (farbcodiert)
- **Col AW (49):** Finale Risikobewertung durch act legal (Header)
- **Col AX (50):** Finale Risikobewertung — **befüllt mit Gesamtbewertung**
- **Col AY (51):** Sonstige Anmerkungen asambeauty

**Änderungs-Tabs (8 Stück):**
- Änd. Flex Group (8 Klauseln), Änd. Intertec (8), Änd. basecom-rhm (7)
- Änd. cebesoft (4), Änd. Codesprint (4), Änd. NODECO (5)
- Änd. Arnia (4), Änd. hubside (3)
- Jeder Tab: Vertragsklausel | Schweregrad (KRITISCH/WICHTIG/EMPFOHLEN) | Problem | Änderungsvorschlag

## Wichtige Kontextinformationen

1. **Schwildens vorläufige Bewertungen** basieren auf der Praxis (Checkliste). Unsere Vertragsanalyse weicht teils stark ab (z.B. er: GERING, wir: HOCH bei basecom/Flex/Intertec).
2. **Kettenkonstruktionen** sind das kritischste Thema: basecom→rhm→Entwickler und Asambeauty→Intertec GmbH→DOOEL→AN — jeweils ohne AÜG-Erlaubnis.
3. **E-Mail "no difference"** bei Arnia ist ein Schlüsseldokument für die DRV-Prüfung.
4. **NODECO/Notzon** hat DRV-Vorbelastung: Vorgängervertrag wurde als abhängig eingestuft, Rückabwicklung 43.622 EUR.
5. **hubside** hat die beste Vertragsgestaltung, zusätzlich eine AÜ-Erlaubnis als Rückfallposition.
6. **Codex-Review** wurde für die Vertragsentwürfe durchgeführt — 6 Findings, alle umgesetzt (AÜG-Anwaltshinweise, Klausel-Ergänzungen, ARIA).

## Scripts

- `/tmp/fill_excel.py` — Script das Schwildens Excel befüllt hat (618 Zeilen, openpyxl). Bereits erfolgreich ausgeführt am 20.03.2026.

**Why:** Mandantenprojekt mit Deadline. Schwilden geht den Report am 20.03.2026 mit Matthias durch.
**How to apply:** Bei Nachfragen zu diesem Projekt immer zuerst die HTML-Reports und die Excel-Datei als Primärquellen nutzen. Vertragsanalysen stecken in den analyse/*.md Dateien.
