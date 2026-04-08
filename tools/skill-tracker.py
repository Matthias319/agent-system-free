#!/home/maetzger/.claude/tools/.venv/bin/python
"""
Skill-Tracker: Zentrales Tracking + Observability für Claude Code Skills.

SQLite-basiert, leichtgewichtig. Trackt Runs, Metriken, Fehler und
granulare Events für datenbasierte Skill-Optimierung.

Verwendung:
    # Run starten (gibt RUN_ID zurück)
    RUN_ID=$(python3 skill-tracker.py start web-search)

    # Metriken loggen
    python3 skill-tracker.py metric $RUN_ID urls_total 17
    python3 skill-tracker.py metrics-batch $RUN_ID '{"quality_avg": 7.4}'

    # Fehler loggen
    python3 skill-tracker.py error $RUN_ID timeout "URL xyz timed out" --url https://...

    # Run abschließen
    python3 skill-tracker.py complete $RUN_ID

    # Events (granulares Observability)
    python3 skill-tracker.py event crawler url_fetch --domain example.com --status ok --latency 150
    python3 skill-tracker.py events-batch '[{"source":"crawler","event_type":"url_fetch",...}]'

    # Auswertung
    python3 skill-tracker.py stats [skill_name]
    python3 skill-tracker.py dashboard
    python3 skill-tracker.py observe [--days 7]
    python3 skill-tracker.py trends [--days 30]
    python3 skill-tracker.py insights [--days 7]
    python3 skill-tracker.py efficiency [--days 30]

    # Wartung
    python3 skill-tracker.py prune [--days 90] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "skill-tracker.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')),
    completed_at TEXT,
    duration_seconds REAL,
    status TEXT NOT NULL DEFAULT 'running',
    error_message TEXT,
    context TEXT
);

CREATE TABLE IF NOT EXISTS skill_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES skill_runs(id),
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    metric_unit TEXT,
    UNIQUE(run_id, metric_name)
);

CREATE TABLE IF NOT EXISTS skill_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER REFERENCES skill_runs(id),
    skill_name TEXT NOT NULL,
    error_type TEXT NOT NULL,
    error_detail TEXT,
    url TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_runs_skill ON skill_runs(skill_name);
CREATE INDEX IF NOT EXISTS idx_runs_started ON skill_runs(started_at);
CREATE INDEX IF NOT EXISTS idx_runs_status ON skill_runs(status);
CREATE INDEX IF NOT EXISTS idx_metrics_run ON skill_metrics(run_id);
CREATE INDEX IF NOT EXISTS idx_errors_skill ON skill_errors(skill_name);
CREATE INDEX IF NOT EXISTS idx_errors_created ON skill_errors(created_at);

CREATE TABLE IF NOT EXISTS skill_learnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name TEXT NOT NULL,
    category TEXT NOT NULL,
    pattern TEXT NOT NULL,
    action TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'auto',
    confidence REAL NOT NULL DEFAULT 1.0,
    hit_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')),
    UNIQUE(skill_name, category, pattern)
);
CREATE INDEX IF NOT EXISTS idx_learnings_skill ON skill_learnings(skill_name);

CREATE TABLE IF NOT EXISTS skill_heal_state (
    skill_name TEXT PRIMARY KEY,
    last_error_id INTEGER NOT NULL DEFAULT 0,
    last_run_id INTEGER NOT NULL DEFAULT 0,
    last_heal_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')),
    source TEXT NOT NULL,
    event_type TEXT NOT NULL,
    run_id INTEGER,
    domain TEXT,
    status TEXT DEFAULT 'ok',
    latency_ms INTEGER,
    value_num REAL,
    value_text TEXT,
    meta TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_source ON events(source);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_domain ON events(domain);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id);
CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);

CREATE TABLE IF NOT EXISTS daily_agg (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    source TEXT NOT NULL,
    event_type TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    ok_count INTEGER NOT NULL DEFAULT 0,
    fail_count INTEGER NOT NULL DEFAULT 0,
    avg_latency REAL,
    avg_value REAL,
    p50_value REAL,
    p90_value REAL,
    top_domains TEXT,
    UNIQUE(date, source, event_type)
);

-- Reflexions-System (Stufe 2 der Self-Healing Pipeline)
CREATE TABLE IF NOT EXISTS reflections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER REFERENCES skill_runs(id),
    skill_name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'error_analysis',
    trigger TEXT NOT NULL DEFAULT 'manual',
    reflection TEXT NOT NULL,
    action_taken TEXT,
    confirmed INTEGER NOT NULL DEFAULT 0,
    confirm_count INTEGER NOT NULL DEFAULT 0,
    promoted_to_zettel INTEGER,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_reflections_skill ON reflections(skill_name);
CREATE INDEX IF NOT EXISTS idx_reflections_run ON reflections(run_id);
CREATE INDEX IF NOT EXISTS idx_reflections_category ON reflections(category);
CREATE INDEX IF NOT EXISTS idx_reflections_confirmed ON reflections(confirmed);
"""


_schema_initialized = False
_AGG_MARKER = DB_PATH.parent / ".last_agg"


def _maybe_auto_aggregate(db: sqlite3.Connection):
    """Automatische daily_agg Befüllung, maximal 1×/Tag."""
    from collections import Counter as _Counter

    today = datetime.now().strftime("%Y-%m-%d")
    if _AGG_MARKER.exists() and _AGG_MARKER.read_text().strip() == today:
        return
    # Events älter als 7 Tage aggregieren (nicht löschen)
    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    rows = db.execute(
        """SELECT DATE(ts) as d, source, event_type,
                  COUNT(*) as cnt,
                  SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) as ok_cnt,
                  SUM(CASE WHEN status!='ok' THEN 1 ELSE 0 END) as fail_cnt,
                  ROUND(AVG(latency_ms), 0) as avg_lat,
                  ROUND(AVG(value_num), 2) as avg_val,
                  GROUP_CONCAT(DISTINCT domain) as domains
           FROM events
           WHERE DATE(ts) < ? AND DATE(ts) NOT IN (SELECT DISTINCT date FROM daily_agg)
           GROUP BY DATE(ts), source, event_type""",
        (cutoff,),
    ).fetchall()
    if rows:
        for r in rows:
            domain_list = [d for d in (r["domains"] or "").split(",") if d]
            top = [d for d, _ in _Counter(domain_list).most_common(5)]
            db.execute(
                """INSERT OR IGNORE INTO daily_agg
                      (date, source, event_type, count, ok_count, fail_count,
                       avg_latency, avg_value, top_domains)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    r["d"],
                    r["source"],
                    r["event_type"],
                    r["cnt"],
                    r["ok_cnt"],
                    r["fail_cnt"],
                    r["avg_lat"],
                    r["avg_val"],
                    json.dumps(top) if top else None,
                ),
            )
        db.commit()
    _AGG_MARKER.write_text(today)


def get_db() -> sqlite3.Connection:
    global _schema_initialized
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    # WAL-Mode: 2-5× schnellere Writes, kein Blocking bei Reads
    db.execute("PRAGMA journal_mode = WAL")
    db.execute("PRAGMA synchronous = NORMAL")
    # Schema nur einmal pro Prozess initialisieren
    if not _schema_initialized:
        db.executescript(SCHEMA)
        _schema_initialized = True
        _maybe_auto_aggregate(db)
    return db


def cmd_start(args):
    """Neuen Skill-Run starten. Gibt RUN_ID aus."""
    db = get_db()
    context = args.context if args.context else None
    cur = db.execute(
        "INSERT INTO skill_runs (skill_name, context) VALUES (?, ?)",
        (args.skill_name, context),
    )
    db.commit()
    print(cur.lastrowid)


def cmd_metric(args):
    """Metrik zu einem Run hinzufügen."""
    db = get_db()
    db.execute(
        """INSERT INTO skill_metrics (run_id, metric_name, metric_value, metric_unit)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(run_id, metric_name) DO UPDATE SET
             metric_value = excluded.metric_value,
             metric_unit = excluded.metric_unit""",
        (args.run_id, args.name, args.value, args.unit),
    )
    db.commit()


def cmd_metrics_batch(args):
    """Mehrere Metriken auf einmal loggen (JSON auf stdin oder als Argument)."""
    db = get_db()
    data = json.loads(args.json_data)
    for name, value in data.items():
        unit = None
        if isinstance(value, dict):
            unit = value.get("unit")
            value = value.get("value", 0)
        db.execute(
            """INSERT INTO skill_metrics (run_id, metric_name, metric_value, metric_unit)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(run_id, metric_name) DO UPDATE SET
                 metric_value = excluded.metric_value,
                 metric_unit = excluded.metric_unit""",
            (args.run_id, name, float(value), unit),
        )
    db.commit()


def cmd_error(args):
    """Fehler zu einem Run loggen."""
    db = get_db()
    # Skill-Name aus dem Run holen
    run = db.execute(
        "SELECT skill_name FROM skill_runs WHERE id = ?", (args.run_id,)
    ).fetchone()
    skill_name = run["skill_name"] if run else "unknown"
    db.execute(
        """INSERT INTO skill_errors (run_id, skill_name, error_type, error_detail, url)
           VALUES (?, ?, ?, ?, ?)""",
        (args.run_id, skill_name, args.error_type, args.detail, args.url),
    )
    db.commit()


def cmd_complete(args):
    """Run als erfolgreich abschließen + Auto-Reflexions-Check."""
    db = get_db()
    run = db.execute(
        "SELECT started_at, skill_name FROM skill_runs WHERE id = ?", (args.run_id,)
    ).fetchone()
    if not run:
        print(f"Run {args.run_id} nicht gefunden", file=sys.stderr)
        sys.exit(1)
    started = datetime.fromisoformat(run["started_at"])
    now = datetime.now()
    duration = (now - started).total_seconds()
    db.execute(
        """UPDATE skill_runs SET
             status = 'completed',
             completed_at = strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'),
             duration_seconds = ?
           WHERE id = ?""",
        (duration, args.run_id),
    )
    db.commit()
    print(f"Run {args.run_id} abgeschlossen ({duration:.1f}s)")

    # Auto-Reflexions-Check: Metriken prüfen
    _auto_reflection_check(db, args.run_id, run["skill_name"])


def cmd_fail(args):
    """Run als fehlgeschlagen markieren + Auto-Reflexion."""
    db = get_db()
    run = db.execute(
        "SELECT started_at, skill_name FROM skill_runs WHERE id = ?", (args.run_id,)
    ).fetchone()
    if not run:
        print(f"Run {args.run_id} nicht gefunden", file=sys.stderr)
        sys.exit(1)
    started = datetime.fromisoformat(run["started_at"])
    duration = (datetime.now() - started).total_seconds()
    db.execute(
        """UPDATE skill_runs SET
             status = 'failed',
             completed_at = strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'),
             duration_seconds = ?,
             error_message = ?
           WHERE id = ?""",
        (duration, args.message, args.run_id),
    )
    db.commit()
    print(f"Run {args.run_id} fehlgeschlagen ({duration:.1f}s): {args.message}")

    # Auto-Reflexion: Failed Runs bekommen immer einen Nudge
    _auto_reflection_check(
        db, args.run_id, run["skill_name"], failed=True, error_msg=args.message
    )


def _auto_reflection_check(
    db: sqlite3.Connection,
    run_id: int,
    skill_name: str,
    failed: bool = False,
    error_msg: str | None = None,
) -> None:
    """Prüfe ob ein Run eine automatische Reflexion verdient.

    Generiert datenbasierte Reflexions-Nudges basierend auf:
    - Fail-Rate > 30%
    - Qualität unter Baseline
    - Run komplett fehlgeschlagen
    - Wiederholte Fehler-Patterns
    """
    issues: list[str] = []

    if failed:
        issues.append(f"Run fehlgeschlagen: {error_msg or 'unbekannt'}")

    # Metriken prüfen
    metrics = db.execute(
        """SELECT metric_name, metric_value FROM skill_metrics
           WHERE run_id = ?""",
        (run_id,),
    ).fetchall()
    metric_map = {m["metric_name"]: m["metric_value"] for m in metrics}

    # Fail-Rate prüfen
    urls_total = metric_map.get("urls_total", 0)
    urls_fail = metric_map.get("urls_failed", 0)
    urls_bp = metric_map.get("urls_boilerplate", 0)
    if urls_total > 0:
        fail_rate = (urls_fail + urls_bp) / urls_total
        if fail_rate > 0.3:
            issues.append(
                f"Hohe Ausfallrate: {fail_rate:.0%} "
                f"({int(urls_fail)} Fehler + {int(urls_bp)} Boilerplate von {int(urls_total)})"
            )

    # Qualität unter Baseline prüfen
    quality = metric_map.get("quality_avg")
    if quality is not None:
        baseline = db.execute(
            """SELECT action FROM skill_learnings
               WHERE skill_name = ? AND category = 'baseline'
               AND pattern = 'quality_baseline'""",
            (skill_name,),
        ).fetchone()
        baseline_val = 7.0  # Default
        if baseline:
            import re

            m = re.search(r"Ø Qualität (\d+\.?\d*)", baseline["action"])
            if m:
                baseline_val = float(m.group(1))
        if quality < baseline_val - 1.0:
            issues.append(
                f"Qualität unter Baseline: Ø{quality:.1f} vs. Baseline Ø{baseline_val:.1f}"
            )

    # Fehler dieses Runs prüfen
    run_errors = db.execute(
        """SELECT error_type, COUNT(*) as n,
                  GROUP_CONCAT(DISTINCT SUBSTR(error_detail, 1, 40)) as details
           FROM skill_errors WHERE run_id = ?
           GROUP BY error_type""",
        (run_id,),
    ).fetchall()
    if run_errors:
        for e in run_errors:
            issues.append(f"{e['error_type']} ({e['n']}x): {e['details'] or ''}")

    if not issues:
        return  # Alles gut, keine Reflexion nötig

    # Auto-Reflexion generieren
    context = ""
    run_ctx = db.execute(
        "SELECT context FROM skill_runs WHERE id = ?", (run_id,)
    ).fetchone()
    if run_ctx and run_ctx["context"]:
        try:
            context = json.loads(run_ctx["context"]).get("query", "")
        except Exception:
            pass

    # Kategorie bestimmen
    if failed:
        category = "error_analysis"
    elif quality is not None and quality < baseline_val - 1.0:
        category = "quality_insight"
    else:
        category = "error_analysis"

    reflection_text = (
        f"Auto-Reflexion Run #{run_id} ({skill_name})"
        + (f" [{context[:40]}]" if context else "")
        + ": "
        + " | ".join(issues)
    )

    db.execute(
        """INSERT INTO reflections
           (run_id, skill_name, category, trigger, reflection)
           VALUES (?, ?, ?, 'auto_nudge', ?)""",
        (run_id, skill_name, category, reflection_text),
    )
    db.commit()

    # Output als Nudge
    print(f"  ⚡ Auto-Reflexion: {category}")
    for issue in issues:
        print(f"     • {issue}")


def cmd_stats(args):
    """Statistiken anzeigen (gesamt oder pro Skill)."""
    db = get_db()

    where = ""
    params: list = []
    if args.skill_name:
        where = "WHERE skill_name = ?"
        params = [args.skill_name]

    # Runs pro Skill
    rows = db.execute(
        f"""SELECT
              skill_name,
              COUNT(*) as total,
              SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as ok,
              SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
              ROUND(AVG(CASE WHEN status = 'completed' THEN duration_seconds END), 1) as avg_duration,
              MIN(started_at) as first_run,
              MAX(started_at) as last_run
           FROM skill_runs {where}
           GROUP BY skill_name
           ORDER BY total DESC""",
        params,
    ).fetchall()

    if not rows:
        print("Keine Daten vorhanden.")
        return

    print("Skill-Statistiken")
    print("=" * 70)
    for r in rows:
        rate = r["ok"] / r["total"] * 100 if r["total"] > 0 else 0
        print(
            f"  {r['skill_name']:20s}  "
            f"{r['total']:3d} Runs  "
            f"{rate:5.1f}% OK  "
            f"Ø {r['avg_duration'] or 0:.1f}s  "
            f"(seit {r['first_run'][:10]})"
        )

    # Metriken-Durchschnitte pro Skill
    if args.skill_name:
        metrics = db.execute(
            """SELECT
                 m.metric_name,
                 ROUND(AVG(m.metric_value), 1) as avg_val,
                 ROUND(MIN(m.metric_value), 1) as min_val,
                 ROUND(MAX(m.metric_value), 1) as max_val,
                 m.metric_unit,
                 COUNT(*) as n
               FROM skill_metrics m
               JOIN skill_runs r ON m.run_id = r.id
               WHERE r.skill_name = ? AND r.status = 'completed'
               GROUP BY m.metric_name
               ORDER BY m.metric_name""",
            [args.skill_name],
        ).fetchall()
        if metrics:
            print(f"\nMetriken ({args.skill_name}):")
            print("-" * 70)
            for m in metrics:
                unit = m["metric_unit"] or ""
                print(
                    f"  {m['metric_name']:25s}  "
                    f"Ø {m['avg_val']:>8.1f} {unit:8s}  "
                    f"[{m['min_val']:.1f} – {m['max_val']:.1f}]  "
                    f"(n={m['n']})"
                )

    # Häufigste Fehler
    errors = db.execute(
        f"""SELECT error_type, COUNT(*) as n, MAX(created_at) as last
           FROM skill_errors
           {"WHERE skill_name = ?" if args.skill_name else ""}
           GROUP BY error_type
           ORDER BY n DESC
           LIMIT 10""",
        [args.skill_name] if args.skill_name else [],
    ).fetchall()
    if errors:
        print("\nHäufigste Fehler:")
        print("-" * 70)
        for e in errors:
            print(f"  {e['error_type']:20s}  {e['n']:3d}x  (zuletzt: {e['last'][:10]})")


def cmd_errors(args):
    """Fehler anzeigen."""
    db = get_db()

    conditions = []
    params: list = []
    if args.skill:
        conditions.append("skill_name = ?")
        params.append(args.skill)
    if args.error_type:
        conditions.append("error_type = ?")
        params.append(args.error_type)
    if args.last:
        days = int(args.last.rstrip("d"))
        since = (datetime.now() - timedelta(days=days)).isoformat()
        conditions.append("created_at >= ?")
        params.append(since)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = db.execute(
        f"""SELECT * FROM skill_errors {where}
           ORDER BY created_at DESC LIMIT {args.limit}""",
        params,
    ).fetchall()

    if not rows:
        print("Keine Fehler gefunden.")
        return

    print(f"Fehler ({len(rows)} Ergebnisse)")
    print("=" * 70)
    for r in rows:
        url_info = f"  URL: {r['url']}" if r["url"] else ""
        print(
            f"  [{r['created_at'][:16]}] "
            f"{r['skill_name']:15s} "
            f"{r['error_type']:15s} "
            f"{(r['error_detail'] or '')[:40]}"
            f"{url_info}"
        )


def cmd_history(args):
    """Letzte Runs eines Skills anzeigen."""
    db = get_db()
    runs = db.execute(
        """SELECT r.*, GROUP_CONCAT(m.metric_name || '=' || m.metric_value, ', ') as metrics_str
           FROM skill_runs r
           LEFT JOIN skill_metrics m ON r.id = m.run_id
           WHERE r.skill_name = ?
           GROUP BY r.id
           ORDER BY r.started_at DESC
           LIMIT ?""",
        (args.skill_name, args.limit),
    ).fetchall()

    if not runs:
        print(f"Keine Runs für '{args.skill_name}'.")
        return

    print(f"History: {args.skill_name} (letzte {args.limit})")
    print("=" * 70)
    for r in runs:
        status = {"completed": "OK", "failed": "FAIL", "running": "..."}.get(
            r["status"], r["status"]
        )
        dur = f"{r['duration_seconds']:.1f}s" if r["duration_seconds"] else "—"
        metrics = r["metrics_str"] or ""
        print(
            f"  #{r['id']:3d}  [{r['started_at'][:16]}]  {status:4s}  {dur:>7s}  {metrics[:50]}"
        )
        if r["error_message"]:
            print(f"        Fehler: {r['error_message'][:60]}")


def cmd_dashboard(args):
    """Kompaktes Dashboard über alle Skills."""
    db = get_db()

    # Gesamtübersicht
    total = db.execute("SELECT COUNT(*) as n FROM skill_runs").fetchone()["n"]
    if total == 0:
        print("Noch keine Skill-Runs erfasst.")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    month_ago = (datetime.now() - timedelta(days=30)).isoformat()

    today_runs = db.execute(
        "SELECT COUNT(*) as n FROM skill_runs WHERE started_at >= ?",
        (today,),
    ).fetchone()["n"]
    week_runs = db.execute(
        "SELECT COUNT(*) as n FROM skill_runs WHERE started_at >= ?",
        (week_ago,),
    ).fetchone()["n"]

    ok_total = db.execute(
        "SELECT COUNT(*) as n FROM skill_runs WHERE status = 'completed'"
    ).fetchone()["n"]
    fail_total = db.execute(
        "SELECT COUNT(*) as n FROM skill_runs WHERE status = 'failed'"
    ).fetchone()["n"]
    stale_total = db.execute(
        "SELECT COUNT(*) as n FROM skill_runs WHERE status = 'failed' "
        "AND error_message LIKE '%Stale Run%'"
    ).fetchone()["n"]
    real_fail = fail_total - stale_total
    error_total = db.execute("SELECT COUNT(*) as n FROM skill_errors").fetchone()["n"]

    # Erfolgsrate ohne Stale Runs (Infrastruktur-Ausfälle)
    effective_total = total - stale_total
    rate = ok_total / effective_total * 100 if effective_total > 0 else 0

    print("=" * 60)
    print("  SKILL TRACKER DASHBOARD")
    print("=" * 60)
    print(f"  Runs gesamt:     {total:>6d}  (heute: {today_runs}, Woche: {week_runs})")
    print(
        f"  Erfolgsrate:     {rate:>5.1f}%  ({ok_total} OK / {real_fail} Fail / {stale_total} Stale)"
    )
    print(f"  Fehler gesamt:   {error_total:>6d}")
    print()

    # Pro Skill (Stale Runs separat zählen für faire OK%)
    skills = db.execute(
        """SELECT
             skill_name,
             COUNT(*) as total,
             SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as ok,
             SUM(CASE WHEN status = 'failed' AND error_message LIKE '%Stale Run%' THEN 1 ELSE 0 END) as stale,
             ROUND(AVG(CASE WHEN status = 'completed' THEN duration_seconds END), 1) as avg_dur,
             COUNT(CASE WHEN started_at >= ? THEN 1 END) as week_runs
           FROM skill_runs
           GROUP BY skill_name
           ORDER BY total DESC""",
        (week_ago,),
    ).fetchall()

    print(f"  {'Skill':20s} {'Runs':>5s} {'OK%':>5s} {'Ø Dauer':>8s} {'7d':>4s}")
    print("  " + "-" * 46)
    for s in skills:
        effective = s["total"] - s["stale"]
        ok_pct = s["ok"] / effective * 100 if effective > 0 else 0
        dur = f"{s['avg_dur']:.1f}s" if s["avg_dur"] else "—"
        stale_mark = f" ({s['stale']}⏳)" if s["stale"] > 0 else ""
        print(
            f"  {s['skill_name']:20s} {s['total']:>5d} {ok_pct:>4.0f}% {dur:>8s} {s['week_runs']:>4d}{stale_mark}"
        )

    # Top-Metriken (aggregiert)
    print()
    top_metrics = db.execute(
        """SELECT
             r.skill_name,
             m.metric_name,
             ROUND(AVG(m.metric_value), 1) as avg_val,
             m.metric_unit
           FROM skill_metrics m
           JOIN skill_runs r ON m.run_id = r.id
           WHERE r.status = 'completed' AND r.started_at >= ?
           GROUP BY r.skill_name, m.metric_name
           ORDER BY r.skill_name, m.metric_name
           LIMIT 30""",
        (month_ago,),
    ).fetchall()

    if top_metrics:
        print("  Metriken (Ø letzte 30 Tage):")
        print("  " + "-" * 46)
        current_skill = ""
        for m in top_metrics:
            if m["skill_name"] != current_skill:
                current_skill = m["skill_name"]
                print(f"  {current_skill}:")
            unit = m["metric_unit"] or ""
            print(f"    {m['metric_name']:22s} Ø {m['avg_val']:>8.1f} {unit}")

    # Letzte Fehler
    recent_errors = db.execute(
        """SELECT skill_name, error_type, error_detail, created_at
           FROM skill_errors
           ORDER BY created_at DESC LIMIT 5"""
    ).fetchall()
    if recent_errors:
        print()
        print("  Letzte Fehler:")
        print("  " + "-" * 46)
        for e in recent_errors:
            detail = (e["error_detail"] or "")[:35]
            print(
                f"  [{e['created_at'][:10]}] {e['skill_name']:12s} "
                f"{e['error_type']:12s} {detail}"
            )

    print()
    print("=" * 60)


def _extract_domain(url: str) -> str:
    """Domain aus URL extrahieren."""
    if not url:
        return ""
    url = url.split("//", 1)[-1]  # Protokoll entfernen
    return url.split("/")[0].split("?")[0].lower()


def cmd_learn(args):
    """Manuell ein Learning hinzufügen."""
    db = get_db()
    db.execute(
        """INSERT INTO skill_learnings (skill_name, category, pattern, action, source, confidence)
           VALUES (?, ?, ?, ?, 'manual', 1.0)
           ON CONFLICT(skill_name, category, pattern) DO UPDATE SET
             action = excluded.action,
             source = 'manual',
             confidence = 1.0,
             updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')""",
        (args.skill_name, args.category, args.pattern, args.action),
    )
    db.commit()
    print(f"Learning gespeichert: [{args.category}] {args.pattern} → {args.action}")


def _get_watermark(db: sqlite3.Connection, skill: str | None) -> dict:
    """Watermark-State laden. Bestimmt, welche Daten bereits verarbeitet sind."""
    if skill:
        row = db.execute(
            "SELECT * FROM skill_heal_state WHERE skill_name = ?", (skill,)
        ).fetchone()
        if row:
            return dict(row)
    else:
        # Globaler Lauf: MIN über alle Skills (konservativ)
        row = db.execute(
            """SELECT COALESCE(MIN(last_error_id), 0) as last_error_id,
                      COALESCE(MIN(last_run_id), 0) as last_run_id
               FROM skill_heal_state"""
        ).fetchone()
        if row and (row["last_error_id"] > 0 or row["last_run_id"] > 0):
            return dict(row)
    return {"last_error_id": 0, "last_run_id": 0}


def _save_watermark(db: sqlite3.Connection, skill: str, error_id: int, run_id: int):
    """Watermark nach Verarbeitung aktualisieren."""
    db.execute(
        """INSERT INTO skill_heal_state (skill_name, last_error_id, last_run_id)
           VALUES (?, ?, ?)
           ON CONFLICT(skill_name) DO UPDATE SET
             last_error_id = MAX(skill_heal_state.last_error_id, excluded.last_error_id),
             last_run_id = MAX(skill_heal_state.last_run_id, excluded.last_run_id),
             last_heal_at = strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')""",
        (skill, error_id, run_id),
    )


def _upsert_learning(
    db: sqlite3.Connection,
    skill: str,
    category: str,
    pattern: str,
    action: str,
    confidence: float,
) -> bool:
    """Learning einfügen/aktualisieren. Gibt True bei neuem Learning zurück."""
    result = db.execute(
        """INSERT INTO skill_learnings (skill_name, category, pattern, action, source, confidence)
           VALUES (?, ?, ?, ?, 'auto', ?)
           ON CONFLICT(skill_name, category, pattern) DO UPDATE SET
             action = excluded.action,
             confidence = MAX(skill_learnings.confidence, excluded.confidence),
             updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')
           RETURNING (CASE WHEN created_at = updated_at THEN 'new' ELSE 'updated' END) as status""",
        (skill, category, pattern, action, confidence),
    ).fetchone()
    return bool(result and result["status"] == "new")


def cmd_auto_learn(args):
    """Fehler- und Metriken-Patterns inkrementell analysieren.

    Nutzt Watermarks: nur neue Daten seit letztem auto-learn werden verarbeitet.
    Mit --full wird alles neu analysiert (Reset).
    """
    db = get_db()
    force_full = getattr(args, "full", False)

    skill_filter = ""
    params: list = []
    if args.skill_name:
        skill_filter = "WHERE skill_name = ?"
        params = [args.skill_name]

    # Watermark laden (pro Skill oder global)
    wm = (
        _get_watermark(db, args.skill_name)
        if not force_full
        else {"last_error_id": 0, "last_run_id": 0}
    )
    wm_error = wm["last_error_id"]
    wm_run = wm["last_run_id"]

    # Prüfe ob es neue Daten gibt
    max_error = db.execute("SELECT COALESCE(MAX(id), 0) FROM skill_errors").fetchone()[
        0
    ]
    max_run = db.execute("SELECT COALESCE(MAX(id), 0) FROM skill_runs").fetchone()[0]

    if max_error <= wm_error and max_run <= wm_run and not force_full:
        print(
            f"Auto-Learn: Keine neuen Daten (Errors: {wm_error}/{max_error}, Runs: {wm_run}/{max_run})"
        )
        return

    new_learnings = 0
    updated_learnings = 0

    # === PHASE 1: Domain-Fehler analysieren (ALLE, nicht nur neue — für korrekte Counts) ===
    rows = db.execute(
        f"""SELECT skill_name, error_type, url, error_detail, COUNT(*) as n
           FROM skill_errors
           {skill_filter}
           GROUP BY skill_name, error_type, url
           HAVING COUNT(*) >= 1
           ORDER BY n DESC""",
        params,
    ).fetchall()

    domain_errors: dict[str, dict] = {}
    for r in rows:
        if not r["url"]:
            continue
        domain = _extract_domain(r["url"])
        if not domain:
            continue
        dkey = f"{r['skill_name']}::{domain}"
        if dkey not in domain_errors:
            domain_errors[dkey] = {
                "skill": r["skill_name"],
                "domain": domain,
                "types": {},
                "total": 0,
            }
        domain_errors[dkey]["types"][r["error_type"]] = (
            domain_errors[dkey]["types"].get(r["error_type"], 0) + r["n"]
        )
        domain_errors[dkey]["total"] += r["n"]

    for info in domain_errors.values():
        domain, skill, total, types = (
            info["domain"],
            info["skill"],
            info["total"],
            info["types"],
        )
        confidence = min(1.0, total / 5.0)

        if "http_error" in types:
            action = f"BLOCK (HTTP-Fehler, {total}x)"
        elif "timeout" in types:
            action = f"SLOW/BLOCK (Timeout, {total}x)"
        elif "cloudflare" in types:
            action = f"BLOCK (Cloudflare, {total}x)"
        elif "boilerplate" in types:
            action = f"LOW-QUALITY (Boilerplate, {total}x)"
        else:
            action = f"PROBLEMATISCH ({', '.join(types.keys())}, {total}x)"

        # Bekannte Workarounds
        if "reddit.com" in domain:
            action = "BLOCK → reddit-mcp-query.py nutzen"
            confidence = 1.0
        elif "medium.com" in domain:
            action = "BLOCK (Paywall, 403)"
            confidence = 1.0

        if _upsert_learning(db, skill, "domain_block", domain, action, confidence):
            new_learnings += 1
        else:
            updated_learnings += 1

    # === PHASE 1b: Events-basierte Domain-Analyse (crawler url_fetch) ===
    event_rows = db.execute(
        """SELECT domain,
               COUNT(*) as total,
               SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END) as ok,
               SUM(CASE WHEN status <> 'ok' THEN 1 ELSE 0 END) as fail,
               GROUP_CONCAT(DISTINCT CASE WHEN status <> 'ok' THEN value_text ELSE NULL END) as errors,
               ROUND(AVG(CASE WHEN status = 'ok' THEN value_num ELSE NULL END), 1) as avg_quality,
               ROUND(AVG(CASE WHEN status = 'ok' THEN latency_ms ELSE NULL END), 0) as avg_latency
        FROM events
        WHERE source = 'crawler' AND event_type = 'url_fetch' AND domain != ''
        GROUP BY domain HAVING total >= 3
        ORDER BY total DESC"""
    ).fetchall()

    for r in event_rows:
        domain = r["domain"]
        total, _ok, fail = r["total"], r["ok"], r["fail"]
        fail_rate = fail / total if total > 0 else 0

        # 100% Fail-Rate bei ≥3 Versuchen → BLOCK
        if fail_rate == 1.0 and fail >= 3:
            action = f"BLOCK ({r['errors'] or 'unbekannt'}, {fail}x/{total}x)"
            confidence = min(1.0, fail / 5.0)
            if _upsert_learning(
                db, "web-search", "domain_block", domain, action, confidence
            ):
                new_learnings += 1
            else:
                updated_learnings += 1

        # ≥80% Fail-Rate bei ≥5 Versuchen → BLOCK
        elif fail_rate >= 0.8 and total >= 5:
            action = f"UNRELIABLE ({fail}/{total} fail, {r['errors']})"
            confidence = min(1.0, fail / 5.0)
            if _upsert_learning(
                db, "web-search", "domain_block", domain, action, confidence
            ):
                new_learnings += 1
            else:
                updated_learnings += 1

    # === PHASE 2: URL-lose Fehler-Patterns ===
    url_filter = "WHERE (url IS NULL OR url = '')"
    if args.skill_name:
        url_filter += " AND skill_name = ?"
    type_rows = db.execute(
        f"""SELECT skill_name, error_type, COUNT(*) as n,
                   GROUP_CONCAT(DISTINCT SUBSTR(error_detail, 1, 50)) as details
           FROM skill_errors {url_filter}
           GROUP BY skill_name, error_type HAVING COUNT(*) >= 2
           ORDER BY n DESC""",
        params,
    ).fetchall()

    for r in type_rows:
        confidence = min(1.0, r["n"] / 5.0)
        action = f"Wiederkehrend ({r['n']}x): {(r['details'] or '')[:80]}"
        if _upsert_learning(
            db, r["skill_name"], "error_pattern", r["error_type"], action, confidence
        ):
            new_learnings += 1

    # === PHASE 3: Metriken-basierte Learnings (NEU) ===
    # Nur Runs seit letztem Watermark analysieren
    metric_runs = db.execute(
        f"""SELECT r.skill_name, r.id as run_id, r.context,
               MAX(CASE WHEN m.metric_name='urls_total' THEN m.metric_value END) as urls_total,
               MAX(CASE WHEN m.metric_name='urls_ok' THEN m.metric_value END) as urls_ok,
               MAX(CASE WHEN m.metric_name='urls_boilerplate' THEN m.metric_value END) as urls_bp,
               MAX(CASE WHEN m.metric_name='urls_failed' THEN m.metric_value END) as urls_fail,
               MAX(CASE WHEN m.metric_name='quality_avg' THEN m.metric_value END) as quality,
               MAX(CASE WHEN m.metric_name='scam_filtered' THEN m.metric_value END) as scam,
               MAX(CASE WHEN m.metric_name='inserate_raw' THEN m.metric_value END) as inserate_raw
           FROM skill_runs r
           JOIN skill_metrics m ON r.id = m.run_id
           WHERE r.status = 'completed' AND r.id > ?
           {"AND r.skill_name = ?" if args.skill_name else ""}
           GROUP BY r.id""",
        [wm_run] + (params if args.skill_name else []),
    ).fetchall()

    for r in metric_runs:
        skill = r["skill_name"]

        # Web-Search: Hohe Fail-Rate erkennen
        if r["urls_total"] and r["urls_total"] > 0:
            fail_count = (r["urls_bp"] or 0) + (r["urls_fail"] or 0)
            fail_rate = fail_count / r["urls_total"]
            if fail_rate > 0.3:
                ctx = ""
                if r["context"]:
                    try:
                        ctx = json.loads(r["context"]).get("query", "")[:40]
                    except Exception:
                        pass
                action = (
                    f"Hohe Fail-Rate ({fail_rate:.0%}) bei Run#{r['run_id']}: {ctx}"
                )
                _upsert_learning(
                    db,
                    skill,
                    "metrics_alert",
                    f"high_fail_rate_run{r['run_id']}",
                    action,
                    0.3,
                )

        # Web-Search: Niedrige Qualität erkennen
        if r["quality"] is not None and r["quality"] < 6.0:
            action = f"Niedrige Qualität (Ø{r['quality']:.1f}) bei Run#{r['run_id']}"
            _upsert_learning(
                db, skill, "metrics_alert", f"low_quality_run{r['run_id']}", action, 0.3
            )

        # Market-Check: Hohe Scam-Rate
        if r["scam"] is not None and r["inserate_raw"] and r["inserate_raw"] > 0:
            scam_rate = r["scam"] / r["inserate_raw"]
            if scam_rate > 0.15:
                action = f"Hohe Scam-Rate ({scam_rate:.0%}) — Filter verschärfen"
                _upsert_learning(
                    db,
                    skill,
                    "metrics_alert",
                    "high_scam_rate",
                    action,
                    min(1.0, scam_rate * 3),
                )

    # === PHASE 4: Metriken-Durchschnitte als Baselines speichern ===
    # Aggregierte Learnings aus allen Runs (nicht pro Run, sondern Trends)
    avg_metrics = db.execute(
        f"""SELECT r.skill_name,
               ROUND(AVG(CASE WHEN m.metric_name='quality_avg' THEN m.metric_value END), 1) as avg_quality,
               ROUND(AVG(CASE WHEN m.metric_name='urls_failed' THEN m.metric_value END), 1) as avg_fails,
               COUNT(DISTINCT r.id) as n_runs
           FROM skill_runs r
           JOIN skill_metrics m ON r.id = m.run_id
           WHERE r.status = 'completed'
           {"AND r.skill_name = ?" if args.skill_name else ""}
           GROUP BY r.skill_name""",
        params if args.skill_name else [],
    ).fetchall()

    for r in avg_metrics:
        if r["n_runs"] >= 5 and r["avg_quality"]:
            action = f"Baseline: Ø Qualität {r['avg_quality']}/10, Ø {r['avg_fails'] or 0:.0f} Fehler/Run ({r['n_runs']} Runs)"
            _upsert_learning(
                db, r["skill_name"], "baseline", "quality_baseline", action, 0.8
            )

    # === PHASE 5: Positive Learnings aus Events (domain_prefer) ===
    # Domains die konstant gute Qualität liefern → PREFER-Empfehlung
    good_domains = db.execute(
        """SELECT domain,
                  COUNT(*) as n,
                  ROUND(AVG(value_num), 1) as avg_q,
                  ROUND(AVG(latency_ms), 0) as avg_lat,
                  SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) as ok_cnt
           FROM events
           WHERE source='crawler' AND event_type='url_fetch'
             AND domain IS NOT NULL AND value_num IS NOT NULL
           GROUP BY domain
           HAVING COUNT(*) >= 3 AND AVG(value_num) >= 8.0
             AND SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) * 1.0 / COUNT(*) >= 0.9
           ORDER BY avg_q DESC, n DESC"""
    ).fetchall()

    for d in good_domains:
        action = (
            f"PREFER (Q{d['avg_q']}/10, {d['ok_cnt']}/{d['n']} OK, "
            f"Ø{d['avg_lat']}ms, {d['n']}x gesehen)"
        )
        confidence = min(1.0, d["n"] / 5.0)
        # Skill-Name aus Events ableiten (meistens web-search)
        skill = "web-search"
        if _upsert_learning(
            db, skill, "domain_prefer", d["domain"], action, confidence
        ):
            new_learnings += 1
        else:
            updated_learnings += 1

    # === PHASE 6: Stale-Run-Cleanup ===
    # Runs die >1h auf "running" stehen → als "failed" markieren
    stale_cutoff = (datetime.now() - timedelta(hours=1)).isoformat()
    stale_runs = db.execute(
        """SELECT id, started_at, skill_name FROM skill_runs
           WHERE status = 'running' AND started_at < ?""",
        (stale_cutoff,),
    ).fetchall()
    for sr in stale_runs:
        started = datetime.fromisoformat(sr["started_at"])
        duration = (datetime.now() - started).total_seconds()
        db.execute(
            """UPDATE skill_runs SET
                 status = 'failed',
                 completed_at = strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'),
                 duration_seconds = ?,
                 error_message = 'Auto-Cleanup: Stale Run (>1h running)'
               WHERE id = ?""",
            (duration, sr["id"]),
        )
        print(
            f"  Stale Run #{sr['id']} ({sr['skill_name']}) → failed ({duration:.0f}s)",
            file=sys.stderr,
        )

    # Watermarks aktualisieren
    skills_to_update = (
        [args.skill_name]
        if args.skill_name
        else [
            r[0]
            for r in db.execute("SELECT DISTINCT skill_name FROM skill_runs").fetchall()
        ]
    )
    for s in skills_to_update:
        _save_watermark(db, s, max_error, max_run)

    db.commit()
    print(
        f"Auto-Learn: {new_learnings} neu, {updated_learnings} aktualisiert (WM: E{wm_error}→{max_error}, R{wm_run}→{max_run})"
    )

    # Kompakte Übersicht
    all_learnings = db.execute(
        f"""SELECT * FROM skill_learnings
           {"WHERE skill_name = ?" if args.skill_name else ""}
           ORDER BY skill_name, confidence DESC""",
        params if args.skill_name else [],
    ).fetchall()
    if all_learnings:
        print(f"\nAktive Learnings ({len(all_learnings)}):")
        current_skill = ""
        for learning in all_learnings:
            if learning["skill_name"] != current_skill:
                current_skill = learning["skill_name"]
                print(f"\n  {current_skill}:")
            conf_bar = "█" * int(learning["confidence"] * 5) + "░" * (
                5 - int(learning["confidence"] * 5)
            )
            src = "M" if learning["source"] == "manual" else "A"
            print(
                f"    [{conf_bar}] [{src}] {learning['category']:15s} "
                f"{learning['pattern']:30s} → {learning['action'][:50]}"
            )


def cmd_heal(args):
    """Kompakte Learnings für Skill ausgeben (für Skill-Integration).

    Inkrementell: Führt auto-learn NUR aus wenn neue Daten existieren.
    Output ist minimal — eine Zeile pro Kategorie, direkt nutzbar.
    """
    db = get_db()

    # Prüfe ob neue Daten seit letztem heal existieren
    wm = _get_watermark(db, args.skill_name)
    max_error = db.execute("SELECT COALESCE(MAX(id), 0) FROM skill_errors").fetchone()[
        0
    ]
    max_run = db.execute("SELECT COALESCE(MAX(id), 0) FROM skill_runs").fetchone()[0]

    if max_error > wm["last_error_id"] or max_run > wm["last_run_id"]:
        # Neue Daten → auto-learn leise ausführen
        import io
        from contextlib import redirect_stdout

        class FakeArgs:
            skill_name = args.skill_name
            full = False

        with redirect_stdout(io.StringIO()):
            cmd_auto_learn(FakeArgs())

    # Learnings ausgeben (confidence >= 0.4, ohne per-Run-Alerts)
    learnings = db.execute(
        """SELECT category, pattern, action, confidence, source
           FROM skill_learnings
           WHERE skill_name = ? AND confidence >= 0.4
             AND category NOT IN ('metrics_alert')
           ORDER BY category, confidence DESC""",
        (args.skill_name,),
    ).fetchall()

    if not learnings:
        print(f"# {args.skill_name}: Keine Learnings")
        return

    # Gruppiere nach Kategorie
    categories: dict[str, list] = {}
    for learning in learnings:
        cat = learning["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(learning)

    print(f"# Self-Heal: {args.skill_name} ({len(learnings)} Regeln)")

    for cat, items in categories.items():
        if cat == "domain_block":
            blocks = []
            workarounds = []
            for item in items:
                if "→" in item["action"]:
                    workarounds.append(
                        f"{item['pattern']} → {item['action'].split('→')[1].strip()}"
                    )
                else:
                    blocks.append(item["pattern"])
            if blocks:
                print(f"BLOCK: {', '.join(blocks)}")
            if workarounds:
                print(f"WORKAROUND: {' | '.join(workarounds)}")
        elif cat == "domain_prefer":
            # Top 10 bevorzugte Domains ausgeben
            prefer_list = [
                f"{item['pattern']} ({item['action'].split('(')[1]}"
                if "(" in item["action"]
                else item["pattern"]
                for item in items[:10]
            ]
            print(f"PREFER: {', '.join(prefer_list)}")
        elif cat == "baseline":
            for item in items:
                print(f"BASELINE: {item['action'][:70]}")
        elif cat == "error_pattern":
            for item in items:
                print(f"PATTERN: {item['pattern']} — {item['action'][:60]}")
        else:
            for item in items:
                print(f"{cat.upper()}: {item['pattern']} — {item['action'][:60]}")

    # Reflexionen ausgeben (schließt den Self-Healing Loop)
    recent_reflections = db.execute(
        """SELECT id, category, trigger, reflection, confirm_count, created_at
           FROM reflections
           WHERE skill_name = ?
           ORDER BY created_at DESC LIMIT 5""",
        (args.skill_name,),
    ).fetchall()

    if recent_reflections:
        confirmed = [r for r in recent_reflections if r["confirm_count"] >= 2]
        unconfirmed = [r for r in recent_reflections if r["confirm_count"] < 2]

        if confirmed:
            print(f"REFLEXION ({len(confirmed)} bestätigt):")
            for r in confirmed:
                print(f"  ★ {r['reflection'][:120]}")
        if unconfirmed:
            print(f"REFLEXION ({len(unconfirmed)} offen):")
            for r in unconfirmed:
                print(f"  ○ {r['reflection'][:120]}")


def cmd_learnings(args):
    """Alle Learnings anzeigen (detailliert)."""
    db = get_db()

    where = ""
    params: list = []
    if args.skill_name:
        where = "WHERE skill_name = ?"
        params = [args.skill_name]

    rows = db.execute(
        f"""SELECT * FROM skill_learnings {where}
           ORDER BY skill_name, confidence DESC, hit_count DESC""",
        params,
    ).fetchall()

    if not rows:
        print("Keine Learnings vorhanden. `auto-learn` ausführen.")
        return

    print(f"Skill-Learnings ({len(rows)} Einträge)")
    print("=" * 80)
    current_skill = ""
    for r in rows:
        if r["skill_name"] != current_skill:
            current_skill = r["skill_name"]
            print(f"\n  {current_skill}:")
        src = "MANUAL" if r["source"] == "manual" else "AUTO"
        conf = f"{r['confidence']:.0%}"
        hits = f"{r['hit_count']}x" if r["hit_count"] else "—"
        print(
            f"    [{src:6s} {conf:>4s} hits:{hits:>4s}] "
            f"{r['category']:15s} {r['pattern']:30s}"
        )
        print(f"      → {r['action']}")


# ═══════════════════════════════════════════════════════════════════════
# Reflexions-System (Stufe 2 der Self-Healing Pipeline)
# Symptom (errors) → Reflexion (reflections) → Wissen (zettelkasten)
# ═══════════════════════════════════════════════════════════════════════

VALID_REFLECTION_CATEGORIES = {
    "error_analysis",
    "quality_insight",
    "strategy_learning",
    "anti_pattern",
}


def cmd_reflect(args):
    """Reflexion zu einem Run speichern.

    Geht über reines Error-Logging hinaus: NL-Analyse von
    WAS passiert ist, WARUM, und WAS beim nächsten Mal anders sein sollte.
    """
    db = get_db()

    category = args.category or "error_analysis"
    if category not in VALID_REFLECTION_CATEGORIES:
        print(
            f"Ungültige Kategorie '{category}'. "
            f"Erlaubt: {', '.join(sorted(VALID_REFLECTION_CATEGORIES))}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Skill-Name aus Run oder explizit
    skill_name = args.skill_name
    if args.run_id and not skill_name:
        run = db.execute(
            "SELECT skill_name FROM skill_runs WHERE id = ?", (args.run_id,)
        ).fetchone()
        if run:
            skill_name = run["skill_name"]
        else:
            print(f"Run #{args.run_id} nicht gefunden.", file=sys.stderr)
            sys.exit(1)
    if not skill_name:
        print("--skill oder run_id erforderlich.", file=sys.stderr)
        sys.exit(1)

    trigger = args.trigger or "manual"
    action_taken = args.action or None

    cur = db.execute(
        """INSERT INTO reflections
           (run_id, skill_name, category, trigger, reflection, action_taken)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (args.run_id, skill_name, category, trigger, args.reflection, action_taken),
    )
    db.commit()

    ref_id = cur.lastrowid
    print(f"Reflexion #{ref_id} gespeichert ({category}, {skill_name})")

    # Auto-Check: Gibt es ähnliche Reflexionen? (gleiche Kategorie, ähnliche Keywords)
    similar = _find_similar_reflections(
        db, skill_name, category, args.reflection, ref_id
    )
    if similar:
        # Confirm-Count der ähnlichen Reflexionen erhöhen
        for sim_id in similar:
            db.execute(
                """UPDATE reflections SET confirm_count = confirm_count + 1,
                   confirmed = CASE WHEN confirm_count + 1 >= 2 THEN 1 ELSE confirmed END
                   WHERE id = ?""",
                (sim_id,),
            )
        db.commit()
        print(
            f"  ↳ {len(similar)} ähnliche Reflexion(en) bestätigt "
            f"(IDs: {', '.join(str(s) for s in similar)})"
        )

        # Consolidation-Check: Wenn eine Reflexion ≥3x bestätigt → Hinweis
        for sim_id in similar:
            row = db.execute(
                "SELECT confirm_count, promoted_to_zettel FROM reflections WHERE id = ?",
                (sim_id,),
            ).fetchone()
            if row and row["confirm_count"] >= 3 and not row["promoted_to_zettel"]:
                print(
                    f"  ★ Reflexion #{sim_id} hat {row['confirm_count']}x Bestätigung "
                    f"→ `consolidate` empfohlen"
                )


def _find_similar_reflections(
    db: sqlite3.Connection,
    skill_name: str,
    category: str,
    reflection_text: str,
    exclude_id: int,
) -> list[int]:
    """Finde ähnliche Reflexionen basierend auf Keyword-Overlap."""
    # Einfaches Keyword-Matching (kein ML nötig — pragmatisch)
    words = set(reflection_text.lower().split())
    # Stoppwörter entfernen
    stop = {
        "der",
        "die",
        "das",
        "ein",
        "eine",
        "und",
        "oder",
        "aber",
        "weil",
        "ist",
        "war",
        "hat",
        "für",
        "von",
        "mit",
        "auf",
        "in",
        "zu",
        "nicht",
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "because",
        "is",
        "was",
        "has",
        "for",
        "of",
        "with",
        "on",
        "in",
        "to",
        "not",
        "it",
        "that",
        "this",
        "be",
        "at",
        "by",
        "from",
        "are",
        "were",
        "been",
        "being",
        "have",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
    }
    keywords = {w for w in words if len(w) > 3 and w not in stop}

    if not keywords:
        return []

    candidates = db.execute(
        """SELECT id, reflection FROM reflections
           WHERE skill_name = ? AND category = ? AND id != ?
           ORDER BY created_at DESC LIMIT 50""",
        (skill_name, category, exclude_id),
    ).fetchall()

    similar_ids = []
    for c in candidates:
        c_words = set(c["reflection"].lower().split())
        c_keywords = {w for w in c_words if len(w) > 3 and w not in stop}
        if not c_keywords:
            continue
        overlap = keywords & c_keywords
        # Jaccard-Ähnlichkeit > 0.25 = "ähnlich genug"
        jaccard = (
            len(overlap) / len(keywords | c_keywords) if keywords | c_keywords else 0
        )
        if jaccard > 0.25:
            similar_ids.append(c["id"])

    return similar_ids


def cmd_reflections(args):
    """Alle Reflexionen anzeigen (optional gefiltert nach Skill/Kategorie)."""
    db = get_db()

    where_parts = []
    params: list = []
    if args.skill_name:
        where_parts.append("r.skill_name = ?")
        params.append(args.skill_name)
    if args.category:
        where_parts.append("r.category = ?")
        params.append(args.category)
    if args.confirmed_only:
        where_parts.append("r.confirmed = 1")

    where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    rows = db.execute(
        f"""SELECT r.*, s.context as run_context
           FROM reflections r
           LEFT JOIN skill_runs s ON r.run_id = s.id
           {where}
           ORDER BY r.created_at DESC
           LIMIT ?""",
        params + [args.limit],
    ).fetchall()

    if not rows:
        print("Keine Reflexionen vorhanden.")
        return

    total = db.execute(
        f"SELECT COUNT(*) FROM reflections r {where}", params
    ).fetchone()[0]
    confirmed = db.execute(
        "SELECT COUNT(*) FROM reflections WHERE confirmed = 1"
    ).fetchone()[0]
    promoted = db.execute(
        "SELECT COUNT(*) FROM reflections WHERE promoted_to_zettel IS NOT NULL"
    ).fetchone()[0]

    print(f"Reflexionen ({total} gesamt, {confirmed} bestätigt, {promoted} → Zettel)")
    print("=" * 80)

    for r in rows:
        run_info = f"Run #{r['run_id']}" if r["run_id"] else "kein Run"
        ctx = ""
        if r["run_context"]:
            try:
                ctx = f" [{json.loads(r['run_context']).get('query', '')[:30]}]"
            except Exception:
                pass

        status_icon = "★" if r["confirmed"] else "○"
        promoted_tag = (
            f" → Zettel #{r['promoted_to_zettel']}" if r["promoted_to_zettel"] else ""
        )

        print(
            f"\n{status_icon} #{r['id']} [{r['category']}] {r['skill_name']} "
            f"({run_info}{ctx}) — {r['created_at'][:16]}"
        )
        print(
            f"  Trigger: {r['trigger']} | Bestätigungen: {r['confirm_count']}{promoted_tag}"
        )
        print(f"  {r['reflection']}")
        if r["action_taken"]:
            print(f"  → Aktion: {r['action_taken']}")


def cmd_ratchet(args):
    """Baselines prüfen: aktuelle Werte vs. gespeicherte Baselines.

    Wenn --update: bessere Werte als neue Baseline setzen (Ratchet).
    Gibt Regressionen als WARN aus.
    """
    db = get_db()

    # Tabelle anlegen falls noch nicht vorhanden
    db.execute(
        """CREATE TABLE IF NOT EXISTS quality_baselines (
            metric TEXT PRIMARY KEY,
            baseline_value REAL NOT NULL,
            set_at TEXT NOT NULL,
            set_by TEXT NOT NULL DEFAULT 'manual',
            previous_value REAL,
            notes TEXT
        )"""
    )

    baselines = {
        r["metric"]: r for r in db.execute("SELECT * FROM quality_baselines").fetchall()
    }

    if not baselines:
        print("Keine Baselines gesetzt. Nutze direkten DB-Insert oder Nachtschicht.")
        return

    # Aktuelle Werte berechnen
    current = {}

    # web_search success rate (letzte 7 Tage)
    ws_runs = db.execute(
        """SELECT COUNT(*) as total,
                  SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as ok
           FROM skill_runs
           WHERE skill_name='web-search'
             AND started_at > datetime('now', '-7 days', 'localtime')"""
    ).fetchone()
    if ws_runs and ws_runs["total"] > 0:
        current["web_search_success_rate"] = round(
            ws_runs["ok"] / ws_runs["total"] * 100, 1
        )

    # social_research success rate
    sr_runs = db.execute(
        """SELECT COUNT(*) as total,
                  SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as ok
           FROM skill_runs
           WHERE skill_name='social-research'
             AND started_at > datetime('now', '-7 days', 'localtime')"""
    ).fetchone()
    if sr_runs and sr_runs["total"] > 0:
        current["social_research_success_rate"] = round(
            sr_runs["ok"] / sr_runs["total"] * 100, 1
        )

    print("Quality Ratchet — Baseline-Vergleich")
    print("=" * 60)

    now = datetime.now().isoformat()
    for metric, bl in baselines.items():
        bl_val = bl["baseline_value"]
        cur_val = current.get(metric)

        if cur_val is None:
            print(
                f"  {metric}: Baseline={bl_val} | Kein aktueller Wert (zu wenig Daten)"
            )
            continue

        # Für error/anti_pattern rate: niedriger = besser
        lower_is_better = "rate" in metric and "success" not in metric
        if lower_is_better:
            improved = cur_val < bl_val
            regressed = cur_val > bl_val * 1.1  # 10% Toleranz
        else:
            improved = cur_val > bl_val
            regressed = cur_val < bl_val * 0.9

        if improved:
            status = "✅ IMPROVED"
            if args.update:
                db.execute(
                    """UPDATE quality_baselines
                       SET baseline_value = ?, previous_value = ?,
                           set_at = ?, set_by = 'ratchet',
                           notes = ?
                       WHERE metric = ?""",
                    (cur_val, bl_val, now, f"Ratchet: {bl_val} → {cur_val}", metric),
                )
                status += " → neue Baseline"
        elif regressed:
            status = "⚠️  REGRESSION"
        else:
            status = "→ stabil"

        print(f"  {metric}: {cur_val} (Baseline: {bl_val}) {status}")

    if args.update:
        db.commit()
        print("\nBaselines aktualisiert.")


def cmd_consolidate(args):
    """Bestätigte Reflexions-Patterns zu Zettelkasten-Einträgen + Learnings verdichten.

    Dreistufige Pipeline:
    1. Reflexionen mit confirm_count ≥ 3 identifizieren
    2. Daraus Learning (skill_learnings) + Zettel erzeugen
    3. Reflexion als 'promoted' markieren
    """
    db = get_db()

    # Finde reife Reflexionen (≥3 Bestätigungen, noch nicht promoted)
    candidates = db.execute(
        """SELECT r.*, s.context as run_context
           FROM reflections r
           LEFT JOIN skill_runs s ON r.run_id = s.id
           WHERE r.confirm_count >= ? AND r.promoted_to_zettel IS NULL
           ORDER BY r.confirm_count DESC, r.created_at ASC""",
        (args.threshold,),
    ).fetchall()

    if not candidates:
        print("Keine Reflexionen bereit zur Konsolidierung.")
        # Zeige nächste Kandidaten
        near = db.execute(
            """SELECT id, skill_name, category, confirm_count, reflection
               FROM reflections
               WHERE promoted_to_zettel IS NULL AND confirm_count > 0
               ORDER BY confirm_count DESC LIMIT 5"""
        ).fetchall()
        if near:
            print("\nNächste Kandidaten:")
            for n in near:
                print(
                    f"  #{n['id']} ({n['confirm_count']}x bestätigt) "
                    f"[{n['category']}] {n['reflection'][:60]}..."
                )
        return

    print(f"Konsolidierung: {len(candidates)} Reflexion(en) bereit")
    print("=" * 80)

    # Zettelkasten DB — kanonischer Pfad ist data/zettel.db
    zettel_db_path = Path.home() / ".claude" / "data" / "zettel.db"
    if not zettel_db_path.exists():
        # Legacy fallback
        zettel_db_path = Path(__file__).parent / "zettel.db"

    zettel_available = zettel_db_path.exists()

    new_learnings = 0
    new_zettels = 0

    for r in candidates:
        print(
            f"\n  #{r['id']} [{r['category']}] {r['skill_name']} "
            f"({r['confirm_count']}x bestätigt)"
        )
        print(f"  Reflexion: {r['reflection'][:120]}")

        if args.dry_run:
            print("  → [DRY RUN] Würde Learning + Zettel erzeugen")
            continue

        # 1. Learning erzeugen (im Skill-Tracker)
        learning_category = _reflection_to_learning_category(r["category"])
        pattern = _extract_pattern_from_reflection(r["reflection"])
        action = _extract_action_from_reflection(r["reflection"], r["action_taken"])

        if _upsert_learning(
            db, r["skill_name"], learning_category, pattern, action, 0.8
        ):
            new_learnings += 1
            print(f"  → Learning: [{learning_category}] {pattern} → {action[:60]}")

        # 2. Zettel erzeugen (wenn verfügbar)
        zettel_id = None
        if zettel_available:
            try:
                zettel_id = _create_zettel_from_reflection(
                    zettel_db_path,
                    r["skill_name"],
                    r["category"],
                    r["reflection"],
                    r.get("action_taken"),
                )
                if zettel_id:
                    new_zettels += 1
                    print(f"  → Zettel #{zettel_id} erstellt")
            except Exception as e:
                print(f"  ⚠ Zettel-Fehler: {e}", file=sys.stderr)

        # 3. Reflexion als promoted markieren
        db.execute(
            "UPDATE reflections SET promoted_to_zettel = ? WHERE id = ?",
            (zettel_id or -1, r["id"]),
        )

    db.commit()
    print(
        f"\nKonsolidiert: {new_learnings} Learnings, {new_zettels} Zettels"
        f"{' [DRY RUN]' if args.dry_run else ''}"
    )


def _reflection_to_learning_category(ref_category: str) -> str:
    """Mappe Reflexions-Kategorie auf Learning-Kategorie."""
    mapping = {
        "error_analysis": "error_pattern",
        "quality_insight": "optimization",
        "strategy_learning": "optimization",
        "anti_pattern": "error_pattern",
    }
    return mapping.get(ref_category, "optimization")


def _extract_pattern_from_reflection(reflection: str) -> str:
    """Extrahiere ein kurzes Pattern aus einer Reflexion.

    Nimmt die ersten 3-5 signifikanten Wörter als Pattern-Key.
    """
    words = reflection.split()
    # Signifikante Wörter (>4 Zeichen, kein Stoppwort)
    stop = {
        "weil",
        "dass",
        "hatte",
        "haben",
        "wurde",
        "waren",
        "nicht",
        "hätte",
        "sollte",
        "könnte",
        "dieser",
        "diese",
        "dieses",
        "because",
        "should",
        "could",
        "would",
        "nicht",
        "keine",
        "kein",
    }
    sig_words = [
        w.strip(".,;:!?()[]") for w in words if len(w) > 4 and w.lower() not in stop
    ]
    pattern = " ".join(sig_words[:5]).lower()
    return pattern[:60] if pattern else reflection[:60].lower()


def _extract_action_from_reflection(reflection: str, action_taken: str | None) -> str:
    """Extrahiere eine Action-Empfehlung aus Reflexion oder expliziter Action."""
    if action_taken:
        return action_taken[:120]
    # Versuche Empfehlung aus Text zu extrahieren (nach "→", "nächstes Mal", "besser")
    markers = [
        "→",
        "nächstes mal",
        "besser",
        "stattdessen",
        "instead",
        "should",
        "next time",
    ]
    lower = reflection.lower()
    for marker in markers:
        idx = lower.find(marker)
        if idx >= 0:
            rest = reflection[idx:].strip("→ ").strip()
            return rest[:120]
    # Fallback: letzter Satz
    sentences = reflection.replace("!", ".").replace("?", ".").split(".")
    last = [s.strip() for s in sentences if len(s.strip()) > 10]
    return last[-1][:120] if last else reflection[:120]


def _create_zettel_from_reflection(
    zettel_db_path: Path,
    skill_name: str,
    category: str,
    reflection: str,
    action_taken: str | None,
) -> int | None:
    """Erstelle einen Zettel aus einer bestätigten Reflexion."""
    zdb = sqlite3.connect(str(zettel_db_path))
    zdb.row_factory = sqlite3.Row

    title = f"[{skill_name}] {category}: {reflection[:50]}..."
    content = f"**Reflexion** ({category}):\n{reflection}"
    if action_taken:
        content += f"\n\n**Aktion**: {action_taken}"
    content += "\n\n*Quelle: Konsolidierte Reflexion aus Skill-Tracker*"

    keywords = json.dumps([skill_name, category, "reflexion", "self-heal"])
    tags = json.dumps(["reflexion", "auto-consolidated"])

    cur = zdb.execute(
        """INSERT INTO notes (title, content, keywords, tags, source, importance)
           VALUES (?, ?, ?, ?, 'consolidation', 1.5)""",
        (title, content, keywords, tags),
    )
    zdb.commit()
    zettel_id = cur.lastrowid
    zdb.close()
    return zettel_id


def cmd_event(args):
    """Einzelnes Event loggen (<20ms)."""
    db = get_db()
    meta = None
    if args.meta:
        meta = args.meta
    db.execute(
        """INSERT INTO events (source, event_type, run_id, domain, status,
           latency_ms, value_num, value_text, meta)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            args.source,
            args.event_type,
            args.run_id,
            args.domain,
            args.status or "ok",
            args.latency,
            args.value_num,
            args.value_text,
            meta,
        ),
    )
    db.commit()


def cmd_events_batch_new(args):
    """Batch-Insert von Events (JSON-Array)."""
    db = get_db()
    raw = args.json_data if args.json_data != "-" else sys.stdin.read()
    data = json.loads(raw)
    if not isinstance(data, list):
        data = [data]
    for ev in data:
        meta = ev.get("meta")
        db.execute(
            """INSERT INTO events (source, event_type, run_id, domain, status,
               latency_ms, value_num, value_text, meta)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ev.get("source", "unknown"),
                ev.get("event_type", "unknown"),
                ev.get("run_id"),
                ev.get("domain"),
                ev.get("status", "ok"),
                ev.get("latency_ms"),
                ev.get("value_num"),
                ev.get("value_text"),
                json.dumps(meta) if meta else None,
            ),
        )
    db.commit()
    print(f"{len(data)} Events eingefügt")


def cmd_prune(args):
    """Alte Events aggregieren in daily_agg und löschen."""
    db = get_db()
    cutoff = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")

    count = db.execute(
        "SELECT COUNT(*) FROM events WHERE DATE(ts) < ?", (cutoff,)
    ).fetchone()[0]

    if count == 0:
        print(f"Keine Events älter als {args.days} Tage.")
        return

    if args.dry_run:
        print(f"Würde {count} Events aggregieren und löschen (vor {cutoff})")
        return

    # Aggregieren: Tageswerte berechnen und in daily_agg speichern
    db.executescript("BEGIN;")
    rows = db.execute(
        """SELECT DATE(ts) as d, source, event_type,
                  COUNT(*) as cnt,
                  SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) as ok_cnt,
                  SUM(CASE WHEN status!='ok' THEN 1 ELSE 0 END) as fail_cnt,
                  ROUND(AVG(latency_ms), 0) as avg_lat,
                  ROUND(AVG(value_num), 2) as avg_val,
                  GROUP_CONCAT(DISTINCT domain) as domains
           FROM events
           WHERE DATE(ts) < ?
           GROUP BY DATE(ts), source, event_type""",
        (cutoff,),
    ).fetchall()

    for r in rows:
        # p50/p90 aus den Events berechnen
        values = [
            v[0]
            for v in db.execute(
                """SELECT value_num FROM events
                   WHERE DATE(ts)=? AND source=? AND event_type=? AND value_num IS NOT NULL
                   ORDER BY value_num""",
                (r["d"], r["source"], r["event_type"]),
            ).fetchall()
        ]
        p50 = values[len(values) // 2] if values else None
        p90 = values[int(len(values) * 0.9)] if len(values) >= 2 else p50

        # Top-Domains: häufigste 5
        domain_list = [d for d in (r["domains"] or "").split(",") if d]

        top = [d for d, _ in Counter(domain_list).most_common(5)]

        db.execute(
            """INSERT INTO daily_agg (date, source, event_type, count,
                  ok_count, fail_count, avg_latency, avg_value, p50_value, p90_value, top_domains)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(date, source, event_type) DO UPDATE SET
                  count = count + excluded.count,
                  ok_count = ok_count + excluded.ok_count,
                  fail_count = fail_count + excluded.fail_count,
                  avg_latency = excluded.avg_latency,
                  avg_value = excluded.avg_value,
                  p50_value = excluded.p50_value,
                  p90_value = excluded.p90_value,
                  top_domains = excluded.top_domains""",
            (
                r["d"],
                r["source"],
                r["event_type"],
                r["cnt"],
                r["ok_cnt"],
                r["fail_cnt"],
                r["avg_lat"],
                r["avg_val"],
                p50,
                p90,
                json.dumps(top) if top else None,
            ),
        )

    db.execute("DELETE FROM events WHERE DATE(ts) < ?", (cutoff,))
    db.commit()
    print(f"{count} Events aggregiert und gelöscht (vor {cutoff})")


def cmd_trends(args):
    """Zeitreihen-Analyse aus Events + daily_agg."""
    db = get_db()
    since = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")

    # Live Events
    live = db.execute(
        """SELECT DATE(ts) as date, source, event_type,
                  COUNT(*) as count,
                  SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) as ok,
                  SUM(CASE WHEN status!='ok' THEN 1 ELSE 0 END) as fail,
                  ROUND(AVG(latency_ms), 0) as avg_lat
           FROM events WHERE DATE(ts) >= ?
           GROUP BY DATE(ts), source, event_type""",
        (since,),
    ).fetchall()

    # Aggregierte Daten
    agg = db.execute(
        """SELECT date, source, event_type, count, ok_count as ok,
                  fail_count as fail, ROUND(avg_latency, 0) as avg_lat
           FROM daily_agg WHERE date >= ?""",
        (since,),
    ).fetchall()

    all_rows = [dict(r) for r in live] + [dict(r) for r in agg]
    if not all_rows:
        print(f"Keine Event-Daten der letzten {args.days} Tage.")
        return

    # Nach Source gruppieren
    by_source: dict[str, list] = {}
    for r in all_rows:
        key = r["source"]
        if key not in by_source:
            by_source[key] = []
        by_source[key].append(r)

    print(f"Event-Trends (letzte {args.days} Tage)")
    print("=" * 65)
    for source, rows in sorted(by_source.items()):
        total = sum(r["count"] for r in rows)
        ok = sum(r["ok"] for r in rows)
        _fail = sum(r["fail"] for r in rows)
        dates = sorted(set(r["date"] for r in rows))
        lats = [r["avg_lat"] for r in rows if r["avg_lat"]]
        avg_lat = sum(lats) / len(lats) if lats else 0

        types = {}
        for r in rows:
            t = r["event_type"]
            types[t] = types.get(t, 0) + r["count"]

        rate = ok / total * 100 if total else 0
        print(f"\n  {source}")
        print(
            f"    Events: {total:>5d}  OK: {rate:>5.1f}%  Ø Latenz: {avg_lat:>5.0f}ms"
        )
        print(f"    Tage aktiv: {len(dates)}  Zeitraum: {dates[0]} – {dates[-1]}")
        print(
            f"    Typen: {', '.join(f'{t}={n}' for t, n in sorted(types.items(), key=lambda x: -x[1]))}"
        )

    # Tagesverlauf (letzte 7 Tage)
    print("\n  Tagesaktivität:")
    print(f"  {'Datum':12s} {'Events':>7s} {'OK%':>5s} {'Ø ms':>6s}")
    print("  " + "-" * 34)
    day_data: dict[str, dict] = {}
    for r in all_rows:
        d = r["date"]
        if d not in day_data:
            day_data[d] = {"count": 0, "ok": 0, "fail": 0, "lat": []}
        day_data[d]["count"] += r["count"]
        day_data[d]["ok"] += r["ok"]
        day_data[d]["fail"] += r["fail"]
        if r["avg_lat"]:
            day_data[d]["lat"].append(r["avg_lat"])

    for d in sorted(day_data.keys())[-7:]:
        dd = day_data[d]
        rate = dd["ok"] / dd["count"] * 100 if dd["count"] else 0
        avg = sum(dd["lat"]) / len(dd["lat"]) if dd["lat"] else 0
        bar = "█" * min(30, dd["count"] // 2)
        print(f"  {d}  {dd['count']:>5d}  {rate:>4.0f}% {avg:>5.0f}  {bar}")


def cmd_insights(args):
    """Anomalie-Erkennung über Event-Daten."""
    db = get_db()
    since = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")
    insights = []

    # 1. Domains mit hoher Fehlerrate
    domain_errors = db.execute(
        """SELECT domain, status, COUNT(*) as n
           FROM events WHERE DATE(ts) >= ? AND domain IS NOT NULL
           GROUP BY domain, status""",
        (since,),
    ).fetchall()
    domain_stats: dict[str, dict] = {}
    for r in domain_errors:
        d = r["domain"]
        if d not in domain_stats:
            domain_stats[d] = {"ok": 0, "fail": 0}
        if r["status"] == "ok":
            domain_stats[d]["ok"] += r["n"]
        else:
            domain_stats[d]["fail"] += r["n"]

    for domain, stats in domain_stats.items():
        total = stats["ok"] + stats["fail"]
        if total >= 3 and stats["fail"] / total > 0.5:
            insights.append(
                f"FEHLER-DOMAIN: {domain} ({stats['fail']}/{total} fehlgeschlagen, "
                f"{stats['fail'] / total:.0%})"
            )

    # 2. Latenz-Ausreißer (>2x Durchschnitt)
    lat_stats = db.execute(
        """SELECT source, event_type,
                  AVG(latency_ms) as avg_lat,
                  MAX(latency_ms) as max_lat,
                  COUNT(*) as n
           FROM events WHERE DATE(ts) >= ? AND latency_ms IS NOT NULL
           GROUP BY source, event_type
           HAVING COUNT(*) >= 3""",
        (since,),
    ).fetchall()
    for r in lat_stats:
        if r["max_lat"] and r["avg_lat"] and r["max_lat"] > r["avg_lat"] * 3:
            insights.append(
                f"LATENZ-SPIKE: {r['source']}/{r['event_type']} "
                f"max={r['max_lat']}ms vs Ø{r['avg_lat']:.0f}ms ({r['n']} Events)"
            )

    # 3. Neue Domains (erstmals gesehen in den letzten 2 Tagen)
    recent = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    new_domains = db.execute(
        """SELECT domain, COUNT(*) as n FROM events
           WHERE DATE(ts) >= ? AND domain IS NOT NULL
           AND domain NOT IN (
               SELECT DISTINCT domain FROM events
               WHERE DATE(ts) < ? AND domain IS NOT NULL
           )
           GROUP BY domain ORDER BY n DESC LIMIT 10""",
        (recent, recent),
    ).fetchall()
    for r in new_domains:
        insights.append(f"NEU: Domain {r['domain']} ({r['n']}x seit {recent})")

    # 4. Quellen ohne Events (inaktiv)
    all_sources = db.execute("SELECT DISTINCT source FROM events").fetchall()
    recent_sources = db.execute(
        "SELECT DISTINCT source FROM events WHERE DATE(ts) >= ?",
        (since,),
    ).fetchall()
    recent_set = {r["source"] for r in recent_sources}
    for r in all_sources:
        if r["source"] not in recent_set:
            insights.append(f"INAKTIV: {r['source']} (keine Events seit {since})")

    # Output
    print(f"Event-Insights (letzte {args.days} Tage)")
    print("=" * 60)
    if not insights:
        print("  Keine Anomalien erkannt.")
    else:
        for i, insight in enumerate(insights, 1):
            print(f"  {i}. {insight}")
    print(
        f"\n  Basis: {db.execute('SELECT COUNT(*) FROM events WHERE DATE(ts) >= ?', (since,)).fetchone()[0]} Events"
    )


def cmd_efficiency(args):
    """Token/Cost-Optimierung aus Event-Daten."""
    db = get_db()
    since = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")

    print(f"Effizienz-Analyse (letzte {args.days} Tage)")
    print("=" * 60)

    # 1. Source-Level-Effizienz
    sources = db.execute(
        """SELECT source,
                  COUNT(*) as total,
                  SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) as ok,
                  ROUND(AVG(latency_ms), 0) as avg_lat,
                  ROUND(AVG(value_num), 1) as avg_val,
                  SUM(value_num) as sum_val
           FROM events WHERE DATE(ts) >= ?
           GROUP BY source ORDER BY total DESC""",
        (since,),
    ).fetchall()

    if not sources:
        print("  Keine Event-Daten.")
        return

    print(f"\n  {'Source':20s} {'Events':>7s} {'OK%':>5s} {'Ø Lat':>7s} {'Ø Wert':>8s}")
    print("  " + "-" * 51)
    for s in sources:
        rate = s["ok"] / s["total"] * 100 if s["total"] else 0
        lat = f"{s['avg_lat']:.0f}ms" if s["avg_lat"] else "—"
        val = f"{s['avg_val']:.1f}" if s["avg_val"] else "—"
        print(
            f"  {s['source']:20s} {s['total']:>5d}  {rate:>4.0f}% {lat:>7s} {val:>8s}"
        )

    # 2. Langsamste Domains
    slow = db.execute(
        """SELECT domain, ROUND(AVG(latency_ms), 0) as avg_lat,
                  COUNT(*) as n, SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) as ok
           FROM events WHERE DATE(ts) >= ? AND domain IS NOT NULL AND latency_ms IS NOT NULL
           GROUP BY domain HAVING COUNT(*) >= 2
           ORDER BY avg_lat DESC LIMIT 10""",
        (since,),
    ).fetchall()

    if slow:
        print("\n  Langsamste Domains:")
        print(f"  {'Domain':30s} {'Ø Lat':>7s} {'OK%':>5s} {'n':>4s}")
        print("  " + "-" * 50)
        for r in slow:
            rate = r["ok"] / r["n"] * 100 if r["n"] else 0
            print(
                f"  {r['domain']:30s} {r['avg_lat']:>5.0f}ms {rate:>4.0f}% {r['n']:>4d}"
            )

    # 3. Event-Typ-Verteilung
    types = db.execute(
        """SELECT event_type, COUNT(*) as n,
                  ROUND(AVG(latency_ms), 0) as avg_lat
           FROM events WHERE DATE(ts) >= ?
           GROUP BY event_type ORDER BY n DESC""",
        (since,),
    ).fetchall()

    if types:
        print("\n  Event-Typen:")
        for t in types:
            lat = f"Ø{t['avg_lat']:.0f}ms" if t["avg_lat"] else ""
            print(f"    {t['event_type']:20s} {t['n']:>5d}x  {lat}")


def cmd_observe(args):
    """Kombiniertes Dashboard: Events + Trends + Insights."""
    db = get_db()
    since = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")

    total_events = db.execute(
        "SELECT COUNT(*) FROM events WHERE DATE(ts) >= ?", (since,)
    ).fetchone()[0]
    total_agg = db.execute(
        "SELECT COALESCE(SUM(count), 0) FROM daily_agg WHERE date >= ?", (since,)
    ).fetchone()[0]

    print("=" * 60)
    print("  OBSERVABILITY DASHBOARD")
    print("=" * 60)
    print(f"  Zeitraum: letzte {args.days} Tage (ab {since})")
    print(f"  Live Events: {total_events:>6d}")
    print(f"  Aggregiert:  {total_agg:>6d}")
    print()

    # Top-Sources
    sources = db.execute(
        """SELECT source, COUNT(*) as n,
                  SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) as ok,
                  ROUND(AVG(latency_ms), 0) as lat
           FROM events WHERE DATE(ts) >= ?
           GROUP BY source ORDER BY n DESC LIMIT 10""",
        (since,),
    ).fetchall()
    if sources:
        print(f"  {'Source':20s} {'Events':>7s} {'OK%':>5s} {'Ø ms':>6s}")
        print("  " + "-" * 42)
        for s in sources:
            rate = s["ok"] / s["n"] * 100 if s["n"] else 0
            lat = f"{s['lat']:.0f}" if s["lat"] else "—"
            print(f"  {s['source']:20s} {s['n']:>5d}  {rate:>4.0f}% {lat:>6s}")

    # Top-Domains
    domains = db.execute(
        """SELECT domain, COUNT(*) as n,
                  SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) as ok
           FROM events WHERE DATE(ts) >= ? AND domain IS NOT NULL
           GROUP BY domain ORDER BY n DESC LIMIT 10""",
        (since,),
    ).fetchall()
    if domains:
        print("\n  Top-Domains:")
        for d in domains:
            rate = d["ok"] / d["n"] * 100 if d["n"] else 0
            bar = "█" * min(20, d["n"])
            print(f"    {d['domain']:30s} {d['n']:>4d}x {rate:>4.0f}% {bar}")

    # Letzte 5 Fehler-Events
    errors = db.execute(
        """SELECT ts, source, event_type, domain, value_text
           FROM events WHERE DATE(ts) >= ? AND status != 'ok'
           ORDER BY ts DESC LIMIT 5""",
        (since,),
    ).fetchall()
    if errors:
        print("\n  Letzte Fehler:")
        for e in errors:
            detail = (e["value_text"] or "")[:40]
            dom = e["domain"] or ""
            print(
                f"    [{e['ts'][:16]}] {e['source']:12s} {e['event_type']:12s} {dom:20s} {detail}"
            )

    # Storage-Info
    db_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    ev_count = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    agg_count = db.execute("SELECT COUNT(*) FROM daily_agg").fetchone()[0]
    print(
        f"\n  Storage: {db_size / 1024:.1f} KB  ({ev_count} Events, {agg_count} Aggregates)"
    )
    print("=" * 60)


def cmd_export(args):
    """Daten als JSON exportieren."""
    db = get_db()
    result = {}

    runs = db.execute(
        "SELECT * FROM skill_runs ORDER BY started_at DESC LIMIT ?",
        (args.limit,),
    ).fetchall()
    result["runs"] = [dict(r) for r in runs]

    for run in result["runs"]:
        metrics = db.execute(
            "SELECT metric_name, metric_value, metric_unit FROM skill_metrics WHERE run_id = ?",
            (run["id"],),
        ).fetchall()
        run["metrics"] = {m["metric_name"]: m["metric_value"] for m in metrics}

    errors = db.execute(
        "SELECT * FROM skill_errors ORDER BY created_at DESC LIMIT ?",
        (args.limit,),
    ).fetchall()
    result["errors"] = [dict(r) for r in errors]

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()


def main():
    parser = argparse.ArgumentParser(description="Skill-Tracker CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # start
    p = sub.add_parser("start", help="Neuen Run starten")
    p.add_argument("skill_name")
    p.add_argument("--context", help="JSON-Kontext")

    # metric
    p = sub.add_parser("metric", help="Metrik loggen")
    p.add_argument("run_id", type=int)
    p.add_argument("name")
    p.add_argument("value", type=float)
    p.add_argument("--unit", default=None)

    # metrics-batch
    p = sub.add_parser("metrics-batch", help="Mehrere Metriken als JSON")
    p.add_argument("run_id", type=int)
    p.add_argument("json_data", help="JSON-String mit {name: value, ...}")

    # error
    p = sub.add_parser("error", help="Fehler loggen")
    p.add_argument("run_id", type=int)
    p.add_argument("error_type")
    p.add_argument("detail", nargs="?", default=None)
    p.add_argument("--url", default=None)

    # complete
    p = sub.add_parser("complete", help="Run abschließen")
    p.add_argument("run_id", type=int)

    # fail
    p = sub.add_parser("fail", help="Run als fehlgeschlagen markieren")
    p.add_argument("run_id", type=int)
    p.add_argument("message")

    # stats
    p = sub.add_parser("stats", help="Statistiken anzeigen")
    p.add_argument("skill_name", nargs="?", default=None)

    # errors
    p = sub.add_parser("errors", help="Fehler anzeigen")
    p.add_argument("--skill", default=None)
    p.add_argument("--type", dest="error_type", default=None)
    p.add_argument("--last", default=None, help="Zeitraum, z.B. 7d")
    p.add_argument("--limit", type=int, default=20)

    # history
    p = sub.add_parser("history", help="Letzte Runs eines Skills")
    p.add_argument("skill_name")
    p.add_argument("--limit", type=int, default=20)

    # dashboard
    sub.add_parser("dashboard", help="Kompaktes Dashboard")

    # export
    p = sub.add_parser("export", help="JSON-Export")
    p.add_argument("--limit", type=int, default=100)

    # learn (manuell)
    p = sub.add_parser("learn", help="Manuell Learning hinzufügen")
    p.add_argument("skill_name")
    p.add_argument(
        "category", help="domain_block, workaround, optimization, error_pattern"
    )
    p.add_argument("pattern", help="z.B. 'reddit.com' oder 'timeout'")
    p.add_argument("action", help="z.B. 'reddit-mcp-query.py nutzen'")

    # auto-learn
    p = sub.add_parser("auto-learn", help="Learnings aus Fehlern auto-generieren")
    p.add_argument("skill_name", nargs="?", default=None)
    p.add_argument(
        "--full",
        action="store_true",
        help="Alle Daten neu verarbeiten (ignoriert Watermarks)",
    )

    # heal (kompakter Output für Skill-Integration)
    p = sub.add_parser("heal", help="Kompakte Learnings für Skill-Pre-Check")
    p.add_argument("skill_name")

    # learnings (detaillierte Ansicht)
    p = sub.add_parser("learnings", help="Alle Learnings anzeigen")
    p.add_argument("skill_name", nargs="?", default=None)

    # event (einzelnes Event loggen)
    p = sub.add_parser("event", help="Einzelnes Event loggen")
    p.add_argument("source", help="Quelle (web-search, crawler, market, renderer)")
    p.add_argument("event_type", help="Typ (url_fetch, query, render, listing)")
    p.add_argument("--run-id", type=int, default=None)
    p.add_argument("--domain", default=None)
    p.add_argument("--status", default="ok")
    p.add_argument("--latency", type=int, default=None, help="Latenz in ms")
    p.add_argument("--value-num", type=float, default=None)
    p.add_argument("--value-text", default=None)
    p.add_argument("--meta", default=None, help="JSON-Metadaten")

    # events-batch (Batch-Insert)
    p = sub.add_parser("events-batch", help="Batch-Insert von Events (JSON)")
    p.add_argument(
        "json_data", nargs="?", default="-", help="JSON-Array oder - für stdin"
    )

    # prune
    p = sub.add_parser("prune", help="Alte Events aggregieren + löschen")
    p.add_argument("--days", type=int, default=90, help="Events älter als N Tage")
    p.add_argument("--dry-run", action="store_true", help="Nur anzeigen, nicht löschen")

    # trends
    p = sub.add_parser("trends", help="Zeitreihen-Analyse")
    p.add_argument("--days", type=int, default=30)

    # insights
    p = sub.add_parser("insights", help="Anomalie-Erkennung")
    p.add_argument("--days", type=int, default=7)

    # efficiency
    p = sub.add_parser("efficiency", help="Token/Cost-Optimierung")
    p.add_argument("--days", type=int, default=30)

    # observe
    p = sub.add_parser("observe", help="Kombiniertes Observability-Dashboard")
    p.add_argument("--days", type=int, default=7)

    # reflect (Reflexion speichern)
    p = sub.add_parser("reflect", help="Reflexion zu einem Run speichern")
    p.add_argument("run_id", type=int, nargs="?", default=None)
    p.add_argument("reflection", help="NL-Analyse: Was, Warum, Was anders")
    p.add_argument(
        "--category",
        choices=sorted(VALID_REFLECTION_CATEGORIES),
        default=None,
        help="error_analysis|quality_insight|strategy_learning|anti_pattern",
    )
    p.add_argument("--skill", dest="skill_name", default=None)
    p.add_argument("--trigger", default="manual")
    p.add_argument("--action", default=None, help="Was wurde daraufhin geändert")

    # reflections (Reflexionen anzeigen)
    p = sub.add_parser("reflections", help="Reflexionen anzeigen")
    p.add_argument("skill_name", nargs="?", default=None)
    p.add_argument("--category", default=None)
    p.add_argument("--confirmed", dest="confirmed_only", action="store_true")
    p.add_argument("--limit", type=int, default=20)

    # ratchet (Baseline-Vergleich + Update)
    p = sub.add_parser(
        "ratchet", help="Baselines prüfen und bei Verbesserung aktualisieren"
    )
    p.add_argument(
        "--update", action="store_true", help="Bessere Werte als neue Baseline setzen"
    )

    # consolidate (bestätigte Reflexionen → Zettel + Learnings)
    p = sub.add_parser("consolidate", help="Bestätigte Reflexionen konsolidieren")
    p.add_argument(
        "--threshold", type=int, default=3, help="Min. Bestätigungen (default: 3)"
    )
    p.add_argument("--dry-run", action="store_true", help="Nur anzeigen")

    args = parser.parse_args()

    commands = {
        "start": cmd_start,
        "metric": cmd_metric,
        "metrics-batch": cmd_metrics_batch,
        "error": cmd_error,
        "complete": cmd_complete,
        "fail": cmd_fail,
        "stats": cmd_stats,
        "errors": cmd_errors,
        "history": cmd_history,
        "dashboard": cmd_dashboard,
        "export": cmd_export,
        "learn": cmd_learn,
        "auto-learn": cmd_auto_learn,
        "heal": cmd_heal,
        "learnings": cmd_learnings,
        "reflect": cmd_reflect,
        "reflections": cmd_reflections,
        "consolidate": cmd_consolidate,
        "event": cmd_event,
        "events-batch": cmd_events_batch_new,
        "prune": cmd_prune,
        "trends": cmd_trends,
        "insights": cmd_insights,
        "efficiency": cmd_efficiency,
        "observe": cmd_observe,
        "ratchet": cmd_ratchet,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
