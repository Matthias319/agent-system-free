---
name: todo-extract
description: "Extrahiert Action-Points aus Inbox-Dateien und erstellt priorisierte Tasks mit Eisenhower-Matrix"
triggers:
  - "Inbox verarbeiten"
  - "Todos aus Dokument extrahieren"
  - "was muss ich tun aus dieser Datei"
  - "Aktionspunkte"
not_for:
  - "manuelle Task-Erstellung"
  - "allgemeines Dokument-Lesen"
---

# Todo Extract — Intelligente Inbox-Verarbeitung

Verarbeite den Inbox-Ordner und extrahiere intelligent Action Points als Tasks.

## Ablauf

### 1. Inbox scannen

Prüfe auf zwei Arten von Inbox-Einträgen:

**E-Mail-Ordner** (von Outlook-Pipeline — Unterordner mit `email.json` + Anhänge):
```bash
find ./data/tasks-inbox/ -maxdepth 2 -name "email.json" ! -path "*/processed/*" 2>/dev/null
```

**Flache Dateien** (manueller Upload, MCB Drag-Drop):
```bash
find ./data/tasks-inbox/ -maxdepth 1 -type f ! -name ".*" 2>/dev/null
```

Wenn beides leer: "Inbox ist leer. Keine Dateien zu verarbeiten."

### 2. Bestehende Tasks laden (Kontext)

```bash
curl -s -b ./data/mcb-cookie https://localhost:8205/api/tasks?status=open 2>/dev/null || echo "MCB nicht erreichbar"
```

Diesen Kontext nutzen für:
- Duplikat-Erkennung (ähnliche Titel = potentielles Duplikat)
- Cross-Referenzen (neuer Task ergänzt bestehenden)
- Bestehende Tags wiederverwenden

### 3a. E-Mail-Ordner verarbeiten

Für jeden Unterordner der eine `email.json` enthält:

1. **email.json lesen** (mit Read-Tool):
   - `subject`, `from`, `date`, `body` als Kontext für Extraktion
   - `message_id` für Duplikat-Erkennung
2. **Duplikat-Check**: Prüfe ob ein Task mit dieser `message_id` in `source_context` existiert → wenn ja, überspringen
3. **Anhänge verarbeiten**: Alle weiteren Dateien im Ordner nach Typ verarbeiten (wie in Schritt 3b)
4. **Task erstellen**: `source` = Ordnername, `source_context` enthält `"message_id: <ID>, from: <Absender>, subject: <Betreff>"`

### 3b. Flache Dateien verarbeiten

Für Dateien die direkt in tasks-inbox/ liegen (nicht in Unterordnern):

- **Text/Markdown** (.txt, .md): Mit Read-Tool lesen
- **PDF** (.pdf): Mit Read-Tool lesen
- **Bilder** (.png, .jpg, .webp): Mit Read-Tool lesen (multimodal)
- **Audio** (.mp3, .m4a, .wav, .ogg): Transkription via MCB:
  ```bash
  curl -s -b ./data/mcb-cookie -F "file=@PFAD" https://localhost:8205/api/transcribe
  ```
- **Video** (.mp4, .webm): Audio extrahieren, dann transkribieren:
  ```bash
  ffmpeg -i PFAD -vn -acodec libmp3lame /tmp/audio_extract.mp3 2>/dev/null
  curl -s -b ./data/mcb-cookie -F "file=@/tmp/audio_extract.mp3" https://localhost:8205/api/transcribe
  ```

### 4. Intelligente Extraktion

Pro Asset analysieren und Action Points identifizieren. Für jeden Action Point einen Task erstellen:

```bash
curl -s -b ./data/mcb-cookie -X POST https://localhost:8205/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "title": "TITEL AUF DEUTSCH",
    "importance": "high oder low",
    "urgency": "high oder low",
    "area": "work oder personal",
    "tags": ["tag1", "tag2"],
    "due_date": "YYYY-MM-DD oder null",
    "source": "DATEINAME",
    "source_context": "RELEVANTES ORIGINALZITAT",
    "notes": "ZUSÄTZLICHER KONTEXT",
    "created_by": "agent"
  }'
```

**Entscheidungsregeln:**
- **Titel**: Kurz, deutsch, aktiv formuliert ("Angebot an Firma X senden")
- **Bereich**: work = Berufliches, Pi-Projekte, Coding. personal = Familie, Gemeinde, Sport, Haushalt
- **Eisenhower**: Deadline nah oder explizit dringend → urgency: high. Langfristig wichtig → importance: high.
- **Tags**: Aus bestehendem Pool wiederverwenden. Neue Tags nur wenn nötig.
- **Granularität**: Claude entscheidet — ein Task mit Notizen vs. mehrere kleine Tasks
- **Duplikate**: Wenn ein sehr ähnlicher Task existiert → bestehenden per PATCH updaten statt neuen erstellen

### 5. Verrottungs-Check

```bash
curl -s -b ./data/mcb-cookie https://localhost:8205/api/tasks/stale
```

Wenn stale Tasks existieren: User informieren und für jeden fragen "Noch relevant, archivieren, oder löschen?"

### 6. Dateien archivieren

**E-Mail-Ordner:** Gesamten Unterordner verschieben:
```bash
mv ./data/tasks-inbox/ORDNERNAME ./data/tasks-inbox/processed/
```

**Flache Dateien:** Einzelne Datei verschieben:
```bash
mv ./data/tasks-inbox/DATEINAME ./data/tasks-inbox/processed/
```

**Bei Fehler:** Datei/Ordner NICHT verschieben. Im Bericht als Fehler melden.

### 7. Zusammenfassung

Dem User berichten:
- Wie viele Dateien verarbeitet
- Wie viele Tasks erstellt / aktualisiert / übersprungen (Duplikat)
- Fehler falls vorhanden
- Stale Tasks falls vorhanden

## Quick-Capture

> **Hinweis:** Für schnelle Task-Verwaltung ohne Datei-Verarbeitung (auflisten, erstellen, erledigen) kann auch der `/tasks` Skill genutzt werden. Quick-Capture hier ist für den Fall, dass der User mitten in einer Session beiläufig einen Task diktiert.

Wenn der User in einer beliebigen Session sagt "merk dir: X", "Task: X", oder "Aufgabe: X":

```bash
curl -s -b ./data/mcb-cookie -X POST https://localhost:8205/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"title": "...", "importance": "high", "urgency": "low", "area": "work oder personal", "created_by": "agent"}'
```

Keine Inbox nötig, kein Skill-Aufruf nötig. Direkt erstellen.

## Wochenrückblick

```bash
curl -s -b ./data/mcb-cookie https://localhost:8205/api/tasks/weekly-review
```

Ergebnis formatiert dem User präsentieren.
