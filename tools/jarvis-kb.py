#!/home/maetzger/.claude/tools/.venv/bin/python
"""Jarvis Knowledge Base CLI — query, insert, prune, stats."""

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path.home() / ".claude/data/knowledge.db"
STATUS_PATH = Path.home() / ".claude/data/status.json"


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def cmd_query(args):
    db = get_db()
    rows = db.execute(
        "SELECT id, topic, category, content, relevance, use_count "
        "FROM knowledge WHERE topic LIKE ? AND relevance > ? "
        "ORDER BY relevance DESC LIMIT ?",
        (f"%{args.topic}%", args.min_relevance, args.limit),
    ).fetchall()
    for r in rows:
        print(
            f"[{r['id']}] ({r['relevance']:.2f}) [{r['topic']}/{r['category']}] "
            f"{r['content'][:120]}"
        )
    db.close()


def cmd_add(args):
    db = get_db()
    db.execute(
        "INSERT INTO knowledge (topic, category, content, source) VALUES (?, ?, ?, ?)",
        (args.topic, args.category, args.content, args.source),
    )
    db.commit()
    print(f"Added to {args.topic}/{args.category}")
    db.close()


def cmd_use(args):
    db = get_db()
    db.execute(
        "UPDATE knowledge SET use_count = use_count + 1, "
        "relevance = MIN(2.0, relevance + 0.2), last_used = datetime('now') "
        "WHERE id = ?",
        (args.id,),
    )
    db.commit()
    db.close()


def cmd_prune(args):
    db = get_db()
    # Apply decay
    db.execute("UPDATE knowledge SET relevance = relevance * 0.95")
    # Hard decay for old unused
    cutoff = (datetime.now() - timedelta(days=30)).isoformat()
    db.execute(
        "UPDATE knowledge SET relevance = relevance * 0.5 "
        "WHERE last_used IS NULL AND created_at < ?",
        (cutoff,),
    )
    # Count archived
    archived = db.execute(
        "SELECT count(*) as c FROM knowledge WHERE relevance < 0.1"
    ).fetchone()["c"]
    active = db.execute(
        "SELECT count(*) as c FROM knowledge WHERE relevance >= 0.1"
    ).fetchone()["c"]
    db.commit()
    print(f"Pruned. Active: {active}, Archived (relevance<0.1): {archived}")
    db.close()


def cmd_stats(args):
    db = get_db()
    active = db.execute(
        "SELECT count(*) as c FROM knowledge WHERE relevance >= 0.1"
    ).fetchone()["c"]
    archived = db.execute(
        "SELECT count(*) as c FROM knowledge WHERE relevance < 0.1"
    ).fetchone()["c"]
    topics = db.execute(
        "SELECT topic, count(*) as c FROM knowledge GROUP BY topic ORDER BY c DESC"
    ).fetchall()
    projects = db.execute("SELECT count(*) as c FROM projects").fetchone()["c"]
    pending = db.execute(
        "SELECT count(*) as c FROM jarvis_tasks WHERE status = 'pending'"
    ).fetchone()["c"]

    print(f"Knowledge: {active} active, {archived} archived")
    print(f"Projects: {projects} tracked")
    print(f"Pending tasks: {pending}")
    print("Topics:")
    for t in topics:
        print(f"  {t['topic']}: {t['c']} entries")

    # Update status.json
    status = {}
    if STATUS_PATH.exists():
        try:
            status = json.loads(STATUS_PATH.read_text())
        except Exception:
            pass
    status["knowledge_stats"] = {"active": active, "archived": archived}
    STATUS_PATH.write_text(json.dumps(status, indent=2))
    db.close()


def cmd_sync_projects(args):
    import subprocess

    db = get_db()
    projects_dir = Path.home() / "Projects"
    for d in sorted(projects_dir.iterdir()):
        if not d.is_dir() or not (d / ".git").exists():
            continue
        name = d.name
        # Get latest commit
        result = subprocess.run(
            ["git", "-C", str(d), "log", "--oneline", "-1"],
            capture_output=True,
            text=True,
        )
        commit = result.stdout.strip() if result.returncode == 0 else None
        # Upsert
        existing = db.execute(
            "SELECT last_commit FROM projects WHERE path = ?", (str(d),)
        ).fetchone()
        if existing:
            if existing["last_commit"] != commit:
                db.execute(
                    "UPDATE projects SET last_commit = ?, last_synced = datetime('now') "
                    "WHERE path = ?",
                    (commit, str(d)),
                )
                print(f"Updated: {name} -> {commit}")
            else:
                print(f"Unchanged: {name}")
        else:
            db.execute(
                "INSERT INTO projects (path, name, last_commit, last_synced) "
                "VALUES (?, ?, ?, datetime('now'))",
                (str(d), name, commit),
            )
            print(f"New: {name} -> {commit}")
    db.commit()
    db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Jarvis Knowledge Base CLI")
    sub = p.add_subparsers(dest="cmd")

    q = sub.add_parser("query", help="Query knowledge")
    q.add_argument("topic", nargs="?", default="")
    q.add_argument("--min-relevance", type=float, default=0.1)
    q.add_argument("--limit", type=int, default=20)

    a = sub.add_parser("add", help="Add knowledge entry")
    a.add_argument("topic")
    a.add_argument("category")
    a.add_argument("content")
    a.add_argument("--source", default="manual")

    u = sub.add_parser("use", help="Mark knowledge as used")
    u.add_argument("id", type=int)

    sub.add_parser("prune", help="Apply relevance decay")
    sub.add_parser("stats", help="Show statistics")
    sub.add_parser("sync-projects", help="Sync git projects")

    args = p.parse_args()
    if not args.cmd:
        p.print_help()
        sys.exit(1)

    globals()[f"cmd_{args.cmd.replace('-', '_')}"](args)
