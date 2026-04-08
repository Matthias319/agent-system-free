#!/home/maetzger/.claude/tools/.venv/bin/python
"""Lessons System — Auto-learn from failures and successes.

Manages a lessons database that captures trigger → action → evidence patterns.
Lessons are injected into sessions via SessionStart and logged from failures.

Usage:
    lessons.py add "trigger" "action" [--evidence "..."] [--source "..."]
    lessons.py list [--format md|json] [--active-only]
    lessons.py inject                    # Output active lessons for SessionStart
    lessons.py prune [--days 90]         # Remove stale lessons
    lessons.py stats                     # Show lesson statistics
    lessons.py deactivate ID             # Deactivate a lesson
    lessons.py log-failure "tool" "error" # Auto-create lesson from failure pattern
"""

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path.home() / ".claude" / "data" / "lessons.db"


def make_dedupe_key(*parts):
    """Create a normalized dedupe key from parts."""
    normalized = "|".join(p.strip().lower()[:80] for p in parts if p)
    return hashlib.md5(normalized.encode()).hexdigest()[:12]


def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("""
        CREATE TABLE IF NOT EXISTS lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trigger TEXT NOT NULL,
            action TEXT NOT NULL,
            evidence TEXT DEFAULT '',
            source TEXT DEFAULT 'manual',
            category TEXT DEFAULT 'general',
            dedupe_key TEXT,
            active INTEGER DEFAULT 1 CHECK(active IN (0, 1)),
            hit_count INTEGER DEFAULT 0 CHECK(hit_count >= 0),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_hit TEXT,
            deactivated_at TEXT
        )
    """)
    # Partial unique index: one active lesson per dedupe_key
    db.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_lessons_dedupe
        ON lessons(dedupe_key) WHERE active = 1 AND dedupe_key IS NOT NULL
    """)
    db.commit()
    return db


def cmd_add(args):
    db = get_db()
    key = make_dedupe_key(args.trigger)
    # Check for duplicate via dedupe_key
    existing = db.execute(
        "SELECT id, action FROM lessons WHERE dedupe_key = ? AND active = 1",
        (key,),
    ).fetchone()
    if existing:
        print(
            f"⚠ Ähnliche aktive Lesson #{existing['id']} existiert: {existing['action'][:60]}",
            file=sys.stderr,
        )
        db.execute(
            "UPDATE lessons SET action = ?, evidence = ?, last_hit = datetime('now') WHERE id = ?",
            (args.action, args.evidence or "", existing["id"]),
        )
        db.commit()
        print(json.dumps({"updated": existing["id"]}))
        return

    db.execute(
        "INSERT INTO lessons (trigger, action, evidence, source, category, dedupe_key) VALUES (?, ?, ?, ?, ?, ?)",
        (
            args.trigger,
            args.action,
            args.evidence or "",
            args.source or "manual",
            args.category or "general",
            key,
        ),
    )
    db.commit()
    row_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    print(json.dumps({"created": row_id}))


def cmd_list(args):
    db = get_db()
    query = "SELECT * FROM lessons"
    if args.active_only:
        query += " WHERE active = 1"
    query += " ORDER BY hit_count DESC, created_at DESC"
    rows = db.execute(query).fetchall()

    if args.format == "json":
        print(json.dumps([dict(r) for r in rows], indent=2, ensure_ascii=False))
    else:
        if not rows:
            print("Keine Lessons vorhanden.")
            return
        for r in rows:
            status = "✓" if r["active"] else "✗"
            print(f"[{status}] #{r['id']} (hits: {r['hit_count']})")
            print(f"  WENN: {r['trigger']}")
            print(f"  DANN: {r['action']}")
            if r["evidence"]:
                print(f"  WEIL: {r['evidence']}")
            print()


def cmd_inject(args):
    """Output active lessons in compact format for SessionStart injection."""
    db = get_db()
    rows = db.execute(
        "SELECT trigger, action FROM lessons WHERE active = 1 ORDER BY hit_count DESC LIMIT 15"
    ).fetchall()
    if not rows:
        return

    lines = ["# Active Lessons (auto-injected)", ""]
    for r in rows:
        lines.append(f"- **WENN** {r['trigger']} → **DANN** {r['action']}")
    print("\n".join(lines))


def cmd_prune(args):
    db = get_db()
    # Use SQLite datetime consistently (UTC) to avoid timezone mismatch
    result = db.execute(
        """UPDATE lessons SET active = 0, deactivated_at = datetime('now')
           WHERE active = 1 AND hit_count = 0
           AND created_at < datetime('now', ? || ' days')""",
        (f"-{args.days}",),
    )
    db.commit()
    pruned = result.rowcount
    print(json.dumps({"pruned": pruned, "cutoff_days": args.days}))


def cmd_stats(args):
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
    active = db.execute("SELECT COUNT(*) FROM lessons WHERE active = 1").fetchone()[0]
    total_hits = db.execute(
        "SELECT COALESCE(SUM(hit_count), 0) FROM lessons"
    ).fetchone()[0]
    top = db.execute(
        "SELECT trigger, hit_count FROM lessons WHERE active = 1 ORDER BY hit_count DESC LIMIT 3"
    ).fetchall()

    stats = {
        "total": total,
        "active": active,
        "inactive": total - active,
        "total_hits": total_hits,
        "top_lessons": [
            {"trigger": r["trigger"][:50], "hits": r["hit_count"]} for r in top
        ],
    }
    print(json.dumps(stats, indent=2, ensure_ascii=False))


def cmd_deactivate(args):
    db = get_db()
    db.execute(
        "UPDATE lessons SET active = 0, deactivated_at = datetime('now') WHERE id = ?",
        (args.id,),
    )
    db.commit()
    print(json.dumps({"deactivated": args.id}))


def cmd_log_failure(args):
    """Auto-create a lesson from a tool failure pattern."""
    db = get_db()
    key = make_dedupe_key(args.tool, args.error[:50])

    # Check via dedupe_key (no LIKE wildcards)
    existing = db.execute(
        "SELECT id, hit_count FROM lessons WHERE dedupe_key = ? AND active = 1",
        (key,),
    ).fetchone()

    if existing:
        db.execute(
            "UPDATE lessons SET hit_count = hit_count + 1, last_hit = datetime('now') WHERE id = ?",
            (existing["id"],),
        )
        db.commit()
        print(
            json.dumps({"hit": existing["id"], "new_count": existing["hit_count"] + 1})
        )
        return

    # Create new lesson — hit_count starts at 1 (this IS the first occurrence)
    trigger = f"{args.tool} Fehler: {args.error[:100]}"
    action = f"Vermeide diesen {args.tool}-Aufruf oder prüfe Vorbedingungen"

    db.execute(
        """INSERT INTO lessons (trigger, action, evidence, source, category, dedupe_key, hit_count, last_hit)
           VALUES (?, ?, 'Automatisch geloggt', 'auto-failure', 'tool-error', ?, 1, datetime('now'))""",
        (trigger, action, key),
    )
    db.commit()
    row_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    print(json.dumps({"created": row_id, "auto": True}))


def main():
    parser = argparse.ArgumentParser(description="Lessons System")
    sub = parser.add_subparsers(dest="command", required=True)

    # add
    p_add = sub.add_parser("add")
    p_add.add_argument("trigger", help="When this happens...")
    p_add.add_argument("action", help="Do this instead...")
    p_add.add_argument("--evidence", help="Why (optional)")
    p_add.add_argument("--source", default="manual")
    p_add.add_argument("--category", default="general")

    # list
    p_list = sub.add_parser("list")
    p_list.add_argument("--format", choices=["md", "json"], default="md")
    p_list.add_argument("--active-only", action="store_true")

    # inject
    sub.add_parser("inject")

    # prune
    p_prune = sub.add_parser("prune")
    p_prune.add_argument("--days", type=int, default=90)

    # stats
    sub.add_parser("stats")

    # deactivate
    p_deact = sub.add_parser("deactivate")
    p_deact.add_argument("id", type=int)

    # log-failure
    p_fail = sub.add_parser("log-failure")
    p_fail.add_argument("tool", help="Tool name that failed")
    p_fail.add_argument("error", help="Error message")

    args = parser.parse_args()
    cmd_map = {
        "add": cmd_add,
        "list": cmd_list,
        "inject": cmd_inject,
        "prune": cmd_prune,
        "stats": cmd_stats,
        "deactivate": cmd_deactivate,
        "log-failure": cmd_log_failure,
    }
    cmd_map[args.command](args)


if __name__ == "__main__":
    main()
