#!/home/maetzger/.claude/tools/.venv/bin/python
"""
Zettelkasten Memory System — inspiriert von A-Mem (Feb 2026).

SQLite + FTS5, strukturierte Notizen mit Tags, Keywords, Cross-Links.
Automatische Evaluierung, Decay und MEMORY.md-Generierung.

Verwendung:
    python3 zettel.py add "Title" "Content" [--tags '["x"]'] [--keywords '["y"]']
    python3 zettel.py search "query" [--limit 10]
    python3 zettel.py get ID
    python3 zettel.py update ID [--content "..."] [--tags '["x"]'] [--importance 1.5]
    python3 zettel.py archive ID [--reason "..."]
    python3 zettel.py link ID1 ID2 [--relation related]
    python3 zettel.py suggest-links ID [--limit 5]
    python3 zettel.py evaluate "Neuer Fakt oder Erkenntnis"
    python3 zettel.py decay
    python3 zettel.py export-memory [--output PATH]
    python3 zettel.py migrate [--dir PATH]
    python3 zettel.py stats
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path.home() / ".claude/data/zettel.db"
MEMORY_DIR = Path.home() / ".claude/projects/-home-maetzger/memory"
MEMORY_MD = MEMORY_DIR / "MEMORY.md"
MEMORY_MAX_LINES = 180

RECENCY_HALF_LIFE = 30  # Tage bis Recency-Score auf 50% fällt

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    keywords TEXT NOT NULL DEFAULT '[]',
    tags TEXT NOT NULL DEFAULT '[]',
    source TEXT NOT NULL DEFAULT 'session',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')),
    access_count INTEGER NOT NULL DEFAULT 0,
    importance REAL NOT NULL DEFAULT 1.0,
    archived INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES notes(id),
    target_id INTEGER NOT NULL REFERENCES notes(id),
    relation TEXT NOT NULL DEFAULT 'related',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')),
    UNIQUE(source_id, target_id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    title, content, keywords, tags,
    content='notes',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

-- FTS5 Sync-Trigger
CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
    INSERT INTO notes_fts(rowid, title, content, keywords, tags)
    VALUES (new.id, new.title, new.content, new.keywords, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, title, content, keywords, tags)
    VALUES ('delete', old.id, old.title, old.content, old.keywords, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, title, content, keywords, tags)
    VALUES ('delete', old.id, old.title, old.content, old.keywords, old.tags);
    INSERT INTO notes_fts(rowid, title, content, keywords, tags)
    VALUES (new.id, new.title, new.content, new.keywords, new.tags);
END;

CREATE INDEX IF NOT EXISTS idx_notes_tags ON notes(tags);
CREATE INDEX IF NOT EXISTS idx_notes_importance ON notes(importance);
CREATE INDEX IF NOT EXISTS idx_notes_archived ON notes(archived);
CREATE INDEX IF NOT EXISTS idx_notes_updated ON notes(updated_at);
CREATE INDEX IF NOT EXISTS idx_links_source ON links(source_id);
CREATE INDEX IF NOT EXISTS idx_links_target ON links(target_id);
"""


def get_db() -> sqlite3.Connection:
    db = sqlite3.connect(str(DB_PATH))
    db.execute("PRAGMA foreign_keys=ON")
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def _compute_recency(updated_at: str) -> float:
    """Exponentieller Recency-Decay: exp(-days * ln(2) / half_life).

    Ergebnis: 1.0 = heute, 0.5 = vor 30 Tagen, 0.25 = vor 60 Tagen.
    """
    try:
        updated = datetime.fromisoformat(updated_at)
        days = max((datetime.now() - updated).total_seconds() / 86400, 0)
        return math.exp(-days * math.log(2) / RECENCY_HALF_LIFE)
    except (ValueError, TypeError):
        return 0.5  # Fallback bei ungültigem Datum


def _ensure_json_array(value: str, field_name: str = "field") -> str:
    """Ensure value is a valid JSON array string. Convert comma-separated to array."""
    if not value or value.strip() == "":
        return "[]"
    value = value.strip()
    if value.startswith("["):
        # Validate it's proper JSON
        try:
            parsed = json.loads(value)
            if not isinstance(parsed, list):
                raise ValueError
            return json.dumps(parsed)
        except (json.JSONDecodeError, ValueError):
            print(
                f"WARNUNG: Ungültiges JSON in {field_name}, parse als CSV",
                file=sys.stderr,
            )
    # Treat as comma-separated
    items = [t.strip().strip('"').strip("'") for t in value.split(",") if t.strip()]
    return json.dumps(items)


# ── ADD ──────────────────────────────────────────────────────────────────


def cmd_add(args):
    """Neue Notiz hinzufügen."""
    if not args.title or not args.title.strip():
        print("Fehler: Titel darf nicht leer sein", file=sys.stderr)
        sys.exit(1)

    db = get_db()
    tags = _ensure_json_array(args.tags or "[]", "tags")
    keywords = _ensure_json_array(args.keywords or "[]", "keywords")
    importance = args.importance or 1.0

    cur = db.execute(
        """INSERT INTO notes (title, content, keywords, tags, source, importance)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (args.title, args.content or "", keywords, tags, args.source, importance),
    )
    db.commit()
    note_id = cur.lastrowid
    print(json.dumps({"id": note_id, "title": args.title}))
    print(f"Notiz #{note_id} erstellt", file=sys.stderr)


# ── SEARCH ───────────────────────────────────────────────────────────────


def _sanitize_fts_query(query: str) -> str:
    """Escape FTS5 special characters so user queries work reliably.

    FTS5 treats `-` as NOT, `*` as prefix, and bare special chars crash.
    Wrap each token in double-quotes to treat them as literals.
    """

    # Empty or whitespace-only query → return None to signal "no results"
    if not query or not query.strip():
        return None
    # If user already quoted the query, pass through
    if query.startswith('"') and query.endswith('"'):
        return query
    # Split on whitespace, quote each token
    tokens = query.split()
    quoted = [f'"{t}"' for t in tokens if t]
    return " ".join(quoted) if quoted else None


def cmd_search(args):
    """Volltextsuche über alle Notizen (FTS5)."""
    db = get_db()
    limit = args.limit or 10
    fts_query = _sanitize_fts_query(args.query)

    if fts_query is None:
        print("[]")
        print("0 Treffer (leere Suchanfrage)", file=sys.stderr)
        return

    rows = db.execute(
        """SELECT n.id, n.title, n.tags, n.importance, n.archived,
                  snippet(notes_fts, 1, '>>>', '<<<', '...', 30) as snippet,
                  rank
           FROM notes_fts f
           JOIN notes n ON f.rowid = n.id
           WHERE notes_fts MATCH ?
           ORDER BY rank
           LIMIT ?""",
        (fts_query, limit),
    ).fetchall()

    # access_count nur für den Top-Treffer erhöhen (nicht alle Ergebnisse)
    if rows:
        db.execute(
            "UPDATE notes SET access_count = access_count + 1 WHERE id = ?",
            (rows[0]["id"],),
        )
        db.commit()

    results = []
    for r in rows:
        results.append(
            {
                "id": r["id"],
                "title": r["title"],
                "tags": json.loads(r["tags"]),
                "importance": r["importance"],
                "archived": bool(r["archived"]),
                "snippet": r["snippet"],
            }
        )

    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"{len(results)} Treffer", file=sys.stderr)


# ── GET ──────────────────────────────────────────────────────────────────


def cmd_get(args):
    """Einzelne Notiz abrufen (erhöht access_count)."""
    db = get_db()
    note = db.execute("SELECT * FROM notes WHERE id = ?", (args.id,)).fetchone()
    if not note:
        print(f"Notiz #{args.id} nicht gefunden", file=sys.stderr)
        sys.exit(1)

    db.execute(
        "UPDATE notes SET access_count = access_count + 1 WHERE id = ?",
        (args.id,),
    )
    db.commit()

    # Links laden
    outgoing = db.execute(
        """SELECT l.target_id, l.relation, n.title
           FROM links l JOIN notes n ON l.target_id = n.id
           WHERE l.source_id = ?""",
        (args.id,),
    ).fetchall()
    incoming = db.execute(
        """SELECT l.source_id, l.relation, n.title
           FROM links l JOIN notes n ON l.source_id = n.id
           WHERE l.target_id = ?""",
        (args.id,),
    ).fetchall()

    result = dict(note)
    result["keywords"] = json.loads(result["keywords"])
    result["tags"] = json.loads(result["tags"])
    result["archived"] = bool(result["archived"])
    result["links_out"] = [
        {"id": r["target_id"], "relation": r["relation"], "title": r["title"]}
        for r in outgoing
    ]
    result["links_in"] = [
        {"id": r["source_id"], "relation": r["relation"], "title": r["title"]}
        for r in incoming
    ]

    print(json.dumps(result, ensure_ascii=False, indent=2))


# ── UPDATE ───────────────────────────────────────────────────────────────


def cmd_update(args):
    """Notiz aktualisieren."""
    db = get_db()
    note = db.execute("SELECT * FROM notes WHERE id = ?", (args.id,)).fetchone()
    if not note:
        print(f"Notiz #{args.id} nicht gefunden", file=sys.stderr)
        sys.exit(1)

    updates = []
    params = []
    if args.title is not None:
        updates.append("title = ?")
        params.append(args.title)
    if args.content is not None:
        updates.append("content = ?")
        params.append(args.content)
    if args.tags is not None:
        updates.append("tags = ?")
        params.append(_ensure_json_array(args.tags, "tags"))
    if args.keywords is not None:
        updates.append("keywords = ?")
        params.append(_ensure_json_array(args.keywords, "keywords"))
    if args.importance is not None:
        updates.append("importance = ?")
        params.append(args.importance)

    if not updates:
        print("Nichts zu aktualisieren", file=sys.stderr)
        return

    updates.append("updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')")
    params.append(args.id)

    db.execute(f"UPDATE notes SET {', '.join(updates)} WHERE id = ?", params)
    db.commit()
    print(f"Notiz #{args.id} aktualisiert", file=sys.stderr)


# ── ARCHIVE ──────────────────────────────────────────────────────────────


def cmd_archive(args):
    """Notiz archivieren."""
    db = get_db()
    note = db.execute("SELECT id FROM notes WHERE id = ?", (args.id,)).fetchone()
    if not note:
        print(f"Notiz #{args.id} nicht gefunden", file=sys.stderr)
        sys.exit(1)

    reason = args.reason or ""
    content_suffix = f"\n\n[Archiviert: {reason}]" if reason else ""

    db.execute(
        """UPDATE notes SET
             archived = 1,
             content = content || ?,
             updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')
           WHERE id = ?""",
        (content_suffix, args.id),
    )
    db.commit()
    print(f"Notiz #{args.id} archiviert", file=sys.stderr)


# ── LINK ─────────────────────────────────────────────────────────────────


def cmd_link(args):
    """Zwei Notizen verknüpfen."""
    db = get_db()
    for nid in (args.id1, args.id2):
        if not db.execute("SELECT id FROM notes WHERE id = ?", (nid,)).fetchone():
            print(f"Notiz #{nid} nicht gefunden", file=sys.stderr)
            sys.exit(1)

    relation = args.relation or "related"
    try:
        db.execute(
            "INSERT INTO links (source_id, target_id, relation) VALUES (?, ?, ?)",
            (args.id1, args.id2, relation),
        )
        db.commit()
        print(f"Link #{args.id1} \u2192 #{args.id2} ({relation})", file=sys.stderr)
    except sqlite3.IntegrityError:
        print("Link existiert bereits", file=sys.stderr)


# ── SUGGEST-LINKS ───────────────────────────────────────────────────────


def cmd_suggest_links(args):
    """Verknüpfungsvorschläge basierend auf FTS5-Ähnlichkeit."""
    db = get_db()
    note = db.execute("SELECT * FROM notes WHERE id = ?", (args.id,)).fetchone()
    if not note:
        print(f"Notiz #{args.id} nicht gefunden", file=sys.stderr)
        sys.exit(1)

    # Suchbegriffe aus Titel + Keywords zusammenbauen
    try:
        keywords = json.loads(note["keywords"]) if note["keywords"] else []
    except (json.JSONDecodeError, TypeError):
        keywords = [k.strip() for k in note["keywords"].split(",") if k.strip()]
    search_terms = note["title"]
    if keywords:
        search_terms += " " + " ".join(keywords)

    # Einfache Wörter extrahieren (FTS5-kompatibel)
    words = re.findall(r"\w{3,}", search_terms)
    if not words:
        print("[]")
        return

    # OR-Query für maximale Abdeckung
    query = " OR ".join(words[:10])

    existing = db.execute(
        "SELECT target_id FROM links WHERE source_id = ?", (args.id,)
    ).fetchall()
    existing_ids = {r["target_id"] for r in existing}
    existing_ids.add(args.id)  # sich selbst ausschließen

    rows = db.execute(
        """SELECT n.id, n.title, n.tags, rank
           FROM notes_fts f
           JOIN notes n ON f.rowid = n.id
           WHERE notes_fts MATCH ? AND n.archived = 0
           ORDER BY rank
           LIMIT ?""",
        (query, (args.limit or 5) + len(existing_ids)),
    ).fetchall()

    suggestions = []
    for r in rows:
        if r["id"] not in existing_ids:
            suggestions.append(
                {
                    "id": r["id"],
                    "title": r["title"],
                    "tags": json.loads(r["tags"])
                    if r["tags"].startswith("[")
                    else [t.strip() for t in r["tags"].split(",") if t.strip()],
                }
            )
            if len(suggestions) >= (args.limit or 5):
                break

    print(json.dumps(suggestions, ensure_ascii=False, indent=2))
    print(f"{len(suggestions)} Vorschläge", file=sys.stderr)


# ── EVALUATE (A-Mem Kern + Recency-Aware) ──────────────────────────────


def cmd_evaluate(args):
    """Neuen Fakt evaluieren: ADD, UPDATE, ARCHIVE oder NOOP?

    Berücksichtigt Recency: Alte Matches (geringe Recency) werden als
    weniger relevant behandelt, sodass veraltete Notizen eher durch
    neue ersetzt werden (ADD) statt aktualisiert (UPDATE/NOOP).
    """
    db = get_db()
    text = args.text

    # FTS5-Suche nach ähnlichen Notes
    words = re.findall(r"\w{3,}", text)
    if not words:
        print(
            json.dumps({"action": "ADD", "reason": "keine Suchbegriffe", "matches": []})
        )
        return

    query = " OR ".join(words[:15])
    rows = db.execute(
        """SELECT n.id, n.title, n.content, n.tags, n.importance,
                  n.archived, n.updated_at, n.access_count, rank
           FROM notes_fts f
           JOIN notes n ON f.rowid = n.id
           WHERE notes_fts MATCH ?
           ORDER BY rank
           LIMIT 5""",
        (query,),
    ).fetchall()

    if not rows:
        print(
            json.dumps(
                {
                    "action": "ADD",
                    "reason": "kein Match in bestehenden Notizen",
                    "matches": [],
                },
                ensure_ascii=False,
            )
        )
        return

    # Negationswörter erkennen
    negations = re.findall(
        r"\b(disabled?|removed?|obsolet|veraltet|deaktiviert|gelöscht|entfernt|nicht mehr)\b",
        text,
        re.IGNORECASE,
    )

    matches = []
    for r in rows:
        recency = _compute_recency(r["updated_at"])
        matches.append(
            {
                "id": r["id"],
                "title": r["title"],
                "importance": r["importance"],
                "archived": bool(r["archived"]),
                "rank": round(r["rank"], 2),
                "recency": round(recency, 3),
                "days_old": round(
                    max(
                        (
                            datetime.now() - datetime.fromisoformat(r["updated_at"])
                        ).total_seconds()
                        / 86400,
                        0,
                    )
                )
                if r["updated_at"]
                else None,
            }
        )

    best = rows[0]
    best_rank = abs(best["rank"])
    best_recency = _compute_recency(best["updated_at"])

    # FTS5 BM25 rank: negativer = besserer Match, abs() macht positiv = höher ist besser.
    # Recency-adjustierte Schwellen: Alte Matches brauchen stärkeren FTS-Rank
    # um als "relevant genug" für UPDATE/NOOP zu gelten.
    # Bei recency=1.0 (heute): Schwellen bleiben wie bisher.
    # Bei recency=0.5 (30 Tage alt): Schwellen verdoppelt (strengerer Match nötig).
    # Bei recency=0.25 (60 Tage alt): Schwellen vervierfacht.
    recency_factor = max(best_recency, 0.1)  # Floor bei 0.1 um Division zu vermeiden
    adj_threshold_strong = 10.0 / recency_factor  # Basis: abs(rank) > 10 = stark
    adj_threshold_moderate = 5.0 / recency_factor  # Basis: abs(rank) > 5 = moderat

    # Entscheidungslogik mit Recency-Adjustment
    # Höherer best_rank (abs) = besserer FTS-Match
    if negations and best_rank > 5.0:
        action = "ARCHIVE"
        reason = (
            f"Negation erkannt ({', '.join(negations)}), "
            f"starker Match auf #{best['id']}"
        )
        target_id = best["id"]
    elif best_rank > adj_threshold_strong:
        # Sehr starker Match (recency-adjustiert) — Update oder Duplikat
        if len(text) > len(best["content"]) * 0.5:
            action = "UPDATE"
            reason = (
                f"starker Match auf #{best['id']}, neuer Content erweitert "
                f"(recency={best_recency:.2f})"
            )
            target_id = best["id"]
        else:
            action = "NOOP"
            reason = (
                f"Info wahrscheinlich bereits in #{best['id']} enthalten "
                f"(recency={best_recency:.2f})"
            )
            target_id = best["id"]
    elif best_rank > adj_threshold_moderate:
        action = "UPDATE"
        reason = (
            f"moderater Match auf #{best['id']}, könnte ergänzt werden "
            f"(recency={best_recency:.2f})"
        )
        target_id = best["id"]
    else:
        action = "ADD"
        if best_recency < 0.3:
            reason = (
                f"bester Match #{best['id']} zu alt "
                f"(recency={best_recency:.2f}, {matches[0].get('days_old', '?')}d), "
                f"neue Notiz empfohlen"
            )
        else:
            reason = "kein ausreichend starker Match"
        target_id = None

    result = {
        "action": action,
        "reason": reason,
        "matches": matches,
    }
    if target_id:
        result["target_id"] = target_id

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"Empfehlung: {action}", file=sys.stderr)


# ── DECAY ────────────────────────────────────────────────────────────────


def cmd_decay(args):
    """Importance-Abfall + Auto-Archivierung."""
    db = get_db()
    now = datetime.now()
    week_ago = (now - timedelta(days=7)).isoformat()
    month_ago = (now - timedelta(days=30)).isoformat()

    # Geschützt: letzte 7 Tage accessed oder importance >= 1.8
    # Standard-Decay: 0.95
    db.execute(
        """UPDATE notes SET
             importance = importance * 0.95,
             updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')
           WHERE archived = 0
             AND importance < 1.8
             AND updated_at < ?""",
        (week_ago,),
    )

    # Aggressiver Decay: unbenutzt + > 30d alt
    db.execute(
        """UPDATE notes SET
             importance = importance * 0.5,
             updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')
           WHERE archived = 0
             AND access_count = 0
             AND importance < 1.8
             AND updated_at < ?""",
        (month_ago,),
    )

    # Auto-Archivierung: importance < 0.1
    archived = db.execute(
        """UPDATE notes SET
             archived = 1,
             content = content || char(10) || char(10) || '[Auto-archiviert: importance < 0.1]',
             updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')
           WHERE archived = 0 AND importance < 0.1"""
    ).rowcount

    db.commit()

    total = db.execute("SELECT COUNT(*) as n FROM notes WHERE archived = 0").fetchone()[
        "n"
    ]
    print(
        f"Decay durchgeführt. {total} aktive Notizen, {archived} auto-archiviert.",
        file=sys.stderr,
    )


# ── EXPORT-MEMORY ────────────────────────────────────────────────────────


def cmd_export_memory(args):
    """MEMORY.md aus DB generieren (max MEMORY_MAX_LINES Zeilen)."""
    db = get_db()
    output_path = Path(args.output) if args.output else MEMORY_MD

    notes = db.execute(
        """SELECT id, title, content, tags, keywords, importance, access_count
           FROM notes
           WHERE archived = 0 AND importance >= 1.0
           ORDER BY importance DESC, access_count DESC"""
    ).fetchall()

    if not notes:
        print("Keine aktiven Notizen vorhanden.", file=sys.stderr)
        return

    # Nach erstem Tag gruppieren
    groups: dict[str, list] = {}
    for n in notes:
        try:
            tags = json.loads(n["tags"]) if n["tags"] else []
        except (json.JSONDecodeError, TypeError):
            tags = []
        group = tags[0] if tags else "Allgemein"
        groups.setdefault(group, []).append(n)

    # KRITISCH-Items (importance >= 1.8) immer zuerst, eigene Gruppe
    critical = [n for n in notes if n["importance"] >= 1.8]
    # Aus anderen Gruppen entfernen
    for group in groups:
        groups[group] = [n for n in groups[group] if n["importance"] < 1.8]
    # Leere Gruppen entfernen
    groups = {k: v for k, v in groups.items() if v}

    lines = []
    lines.append("# Auto Memory — HP ProDesk 600 G3")
    lines.append("")
    lines.append(
        f"*Auto-generiert am {datetime.now().strftime('%Y-%m-%d %H:%M')} "
        f"aus {len(notes)} aktiven Notizen*"
    )
    lines.append("")

    # Kritische Items
    if critical:
        lines.append("## KRITISCH")
        lines.append("")
        for n in critical:
            lines.append(f"- **{n['title']}** (I={n['importance']:.1f})")
            # Erste Zeile des Contents
            first_line = n["content"].split("\n")[0].strip() if n["content"] else ""
            if first_line and len(first_line) > 10:
                lines.append(f"  {first_line[:120]}")
        lines.append("")

    # Gruppen nach Wichtigkeit sortieren
    sorted_groups = sorted(
        groups.items(),
        key=lambda kv: max((n["importance"] for n in kv[1]), default=0),
        reverse=True,
    )

    for group_name, group_notes in sorted_groups:
        if len(lines) >= MEMORY_MAX_LINES - 10:
            break
        lines.append(f"## {group_name.replace('-', ' ').title()}")
        lines.append("")
        for n in group_notes:
            if len(lines) >= MEMORY_MAX_LINES - 5:
                lines.append("*... weitere Notizen in DB*")
                break
            # Kompaktformat: Titel [#ID]
            lines.append(f"- **{n['title']}** [#{n['id']}]")
            # Saubere Preview: Keine Code-Blöcke, keine Markdown-Header
            content = n["content"]
            # Code-Blöcke entfernen
            content = re.sub(r"```[\s\S]*?```", "", content)
            # Markdown-Header entfernen
            content = re.sub(r"^#{1,4}\s+.*$", "", content, flags=re.MULTILINE)
            content_lines = [
                line.strip()
                for line in content.split("\n")
                if line.strip()
                and not line.strip().startswith(("- [", "```", "|", "---"))
            ]
            if content_lines:
                preview = content_lines[0][:120]
                lines.append(f"  {preview}")
        lines.append("")

    # Footer
    lines.append("---")
    lines.append(
        "*Zettelkasten CLI: `./tools/zettel.py {add|search|get|update|evaluate|stats}`*"
    )

    # Budget einhalten
    if len(lines) > MEMORY_MAX_LINES:
        lines = lines[: MEMORY_MAX_LINES - 2]
        lines.append("")
        lines.append("*[gekürzt — weitere Notizen in zettel.db]*")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"MEMORY.md generiert: {len(lines)} Zeilen, {len(notes)} Notizen",
        file=sys.stderr,
    )


# ── MIGRATE ──────────────────────────────────────────────────────────────


def cmd_migrate(args):
    """Bestehende .md-Files in Zettelkasten importieren."""
    db = get_db()
    source_dir = Path(args.dir) if args.dir else MEMORY_DIR

    md_files = sorted(source_dir.glob("**/*.md"))
    if not md_files:
        print("Keine .md-Dateien gefunden.", file=sys.stderr)
        return

    total_notes = 0
    for md_file in md_files:
        # MEMORY.md überspringen (wird auto-generiert)
        if md_file.name == "MEMORY.md":
            continue

        content = md_file.read_text(encoding="utf-8")
        if not content.strip():
            continue

        # Dateiname → Tag
        stem = md_file.stem.lower()
        if md_file.parent.name == "topics":
            base_tag = md_file.parent.name + "/" + stem
        else:
            base_tag = stem

        # Nach ## Headers aufteilen
        sections = re.split(r"^## (.+)$", content, flags=re.MULTILINE)

        # Erster Block (vor erstem ##) = Datei-Header
        preamble = sections[0].strip()
        section_pairs = []
        for i in range(1, len(sections), 2):
            if i + 1 < len(sections):
                section_pairs.append((sections[i].strip(), sections[i + 1].strip()))

        if not section_pairs and preamble:
            # Keine ## Headers — ganzes File als eine Note
            section_pairs = [(md_file.stem.replace("-", " ").title(), preamble)]

        for title, body in section_pairs:
            if not body or len(body) < 10:
                continue

            # Keywords aus **bold** und `backtick` extrahieren
            bold = re.findall(r"\*\*([^*]+)\*\*", body)
            backtick = re.findall(r"`([^`]+)`", body)
            keywords = list(dict.fromkeys(bold[:5] + backtick[:5]))  # dedupliziert

            # Importance basierend auf Markers
            importance = 1.0
            if "KRITISCH" in title.upper() or "KRITISCH" in body[:100].upper():
                importance = 2.0
            elif "WICHTIG" in body[:100].upper() or "IMMER" in body[:100].upper():
                importance = 1.5

            tags = json.dumps([base_tag])
            kw_json = json.dumps(keywords[:10], ensure_ascii=False)

            # Duplikat-Check
            existing = db.execute(
                "SELECT id FROM notes WHERE title = ? AND source = 'migration'",
                (title,),
            ).fetchone()
            if existing:
                print(f"  Übersprungen (existiert): {title}", file=sys.stderr)
                continue

            db.execute(
                """INSERT INTO notes (title, content, keywords, tags, source, importance)
                   VALUES (?, ?, ?, ?, 'migration', ?)""",
                (title, body, kw_json, tags, importance),
            )
            total_notes += 1
            print(f"  + [{base_tag}] {title} (I={importance})", file=sys.stderr)

    db.commit()

    # Suggest-Links für alle neuen Notes
    all_notes = db.execute("SELECT id FROM notes WHERE source = 'migration'").fetchall()

    link_count = 0
    for note in all_notes:
        n = db.execute("SELECT * FROM notes WHERE id = ?", (note["id"],)).fetchone()
        keywords = json.loads(n["keywords"])
        words = re.findall(r"\w{3,}", n["title"])
        if keywords:
            words.extend(re.findall(r"\w{3,}", " ".join(keywords[:5])))
        if not words:
            continue

        query = " OR ".join(words[:8])
        try:
            matches = db.execute(
                """SELECT n.id FROM notes_fts f
                   JOIN notes n ON f.rowid = n.id
                   WHERE notes_fts MATCH ? AND n.id != ?
                   ORDER BY rank LIMIT 3""",
                (query, note["id"]),
            ).fetchall()

            for m in matches:
                try:
                    db.execute(
                        "INSERT INTO links (source_id, target_id, relation) VALUES (?, ?, 'related')",
                        (note["id"], m["id"]),
                    )
                    link_count += 1
                except sqlite3.IntegrityError:
                    pass
        except Exception:
            pass

    db.commit()
    print(
        f"\nMigration abgeschlossen: {total_notes} Notizen, {link_count} Links",
        file=sys.stderr,
    )


# ── STATS ────────────────────────────────────────────────────────────────


def cmd_stats(args):
    """Statistiken über die Zettelkasten-DB."""
    db = get_db()

    total = db.execute("SELECT COUNT(*) as n FROM notes").fetchone()["n"]
    active = db.execute(
        "SELECT COUNT(*) as n FROM notes WHERE archived = 0"
    ).fetchone()["n"]
    archived = total - active
    links = db.execute("SELECT COUNT(*) as n FROM links").fetchone()["n"]

    # Tags aggregieren
    all_tags = set()
    for row in db.execute("SELECT tags FROM notes WHERE archived = 0"):
        try:
            for t in json.loads(row["tags"]):
                all_tags.add(t)
        except (json.JSONDecodeError, TypeError):
            pass  # Skip notes with invalid tags format

    # Importance-Verteilung
    critical = db.execute(
        "SELECT COUNT(*) as n FROM notes WHERE importance >= 1.8 AND archived = 0"
    ).fetchone()["n"]
    high = db.execute(
        "SELECT COUNT(*) as n FROM notes WHERE importance >= 1.0 AND importance < 1.8 AND archived = 0"
    ).fetchone()["n"]
    low = db.execute(
        "SELECT COUNT(*) as n FROM notes WHERE importance < 1.0 AND archived = 0"
    ).fetchone()["n"]

    avg_importance = (
        db.execute(
            "SELECT AVG(importance) as avg FROM notes WHERE archived = 0"
        ).fetchone()["avg"]
        or 0
    )

    print("=" * 50)
    print("  ZETTELKASTEN STATS")
    print("=" * 50)
    print(
        f"  Notizen:      {active:>5d} aktiv / {archived} archiviert / {total} gesamt"
    )
    print(f"  Links:        {links:>5d}")
    print(f"  Tags:         {len(all_tags):>5d} unique")
    print(f"  Importance:   \u00d8 {avg_importance:.2f}")
    print(f"    Kritisch (>=1.8): {critical}")
    print(f"    Hoch (>=1.0):     {high}")
    print(f"    Niedrig (<1.0):   {low}")
    if all_tags:
        print(f"  Tags: {', '.join(sorted(all_tags)[:15])}")
    print("=" * 50)


# ── MAIN ─────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Zettelkasten Memory CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # add
    p = sub.add_parser("add", help="Neue Notiz")
    p.add_argument("title")
    p.add_argument("content", nargs="?", default="")
    p.add_argument("--tags", default=None)
    p.add_argument("--keywords", default=None)
    p.add_argument("--source", default="session")
    p.add_argument("--importance", type=float, default=None)

    # search
    p = sub.add_parser("search", help="Volltextsuche")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=10)

    # get
    p = sub.add_parser("get", help="Notiz abrufen")
    p.add_argument("id", type=int)

    # update
    p = sub.add_parser("update", help="Notiz aktualisieren")
    p.add_argument("id", type=int)
    p.add_argument("--title", default=None)
    p.add_argument("--content", default=None)
    p.add_argument("--tags", default=None)
    p.add_argument("--keywords", default=None)
    p.add_argument("--importance", type=float, default=None)

    # archive
    p = sub.add_parser("archive", help="Notiz archivieren")
    p.add_argument("id", type=int)
    p.add_argument("--reason", default=None)

    # link
    p = sub.add_parser("link", help="Notizen verknüpfen")
    p.add_argument("id1", type=int)
    p.add_argument("id2", type=int)
    p.add_argument(
        "--relation",
        default="related",
        choices=["related", "supersedes", "contradicts", "extends"],
    )

    # suggest-links
    p = sub.add_parser("suggest-links", help="Verknüpfungsvorschläge")
    p.add_argument("id", type=int)
    p.add_argument("--limit", type=int, default=5)

    # evaluate
    p = sub.add_parser("evaluate", help="Neuen Fakt evaluieren")
    p.add_argument("text")

    # decay
    sub.add_parser("decay", help="Importance-Decay + Auto-Archivierung")

    # export-memory
    p = sub.add_parser("export-memory", help="MEMORY.md generieren")
    p.add_argument("--output", default=None)

    # migrate
    p = sub.add_parser("migrate", help="Bestehende .md-Files importieren")
    p.add_argument("--dir", default=None)

    # stats
    sub.add_parser("stats", help="DB-Statistiken")

    args = parser.parse_args()

    commands = {
        "add": cmd_add,
        "search": cmd_search,
        "get": cmd_get,
        "update": cmd_update,
        "archive": cmd_archive,
        "link": cmd_link,
        "suggest-links": cmd_suggest_links,
        "evaluate": cmd_evaluate,
        "decay": cmd_decay,
        "export-memory": cmd_export_memory,
        "migrate": cmd_migrate,
        "stats": cmd_stats,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
