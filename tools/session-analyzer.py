#!/home/maetzger/.claude/tools/.venv/bin/python
"""Session Analyzer — Systematische Analyse aller Claude Code Sessions.

Parst JSONL-Dateien, extrahiert Tool-Calls + Errors, erkennt Anti-Patterns,
analysiert Workflows und generiert einen Report.

Usage:
    ./tools/session-analyzer.py                  # Full analysis
    ./tools/session-analyzer.py --json /tmp/x.json  # JSON output for report-renderer
    ./tools/session-analyzer.py --quick          # Skip JSONL parsing, use cached DB
    ./tools/session-analyzer.py --since 7        # Only last N days
"""

import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta

DB_PATH = os.path.expanduser("./data/session-analysis.db")
PROJECTS_DIR = os.path.expanduser("./projects")

# Tools that should NOT be called via Bash
ANTI_PATTERN_MAP = {
    "cat": "Read",
    "head": "Read",
    "tail": "Read",
    "grep": "Grep",
    "rg": "Grep",
    "find": "Glob",
    "sed": "Edit",
    "awk": "Edit",
}


# Known Playwright tool name shortener
def shorten_tool(name: str) -> str:
    if "playwright" in name:
        return "PW:" + name.split("__")[-1]
    if name.startswith("mcp__"):
        parts = name.split("__")
        return f"MCP:{parts[-1]}" if len(parts) > 2 else name
    return name


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tool_calls (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            project TEXT,
            timestamp TEXT,
            tool_name TEXT,
            tool_name_short TEXT,
            is_error INTEGER DEFAULT 0,
            error_type TEXT,
            error_detail TEXT,
            is_anti_pattern INTEGER DEFAULT 0,
            anti_pattern_type TEXT,
            bash_command TEXT,
            seq_position INTEGER
        );
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            project TEXT,
            file_path TEXT,
            first_ts TEXT,
            last_ts TEXT,
            tool_count INTEGER,
            error_count INTEGER,
            anti_pattern_count INTEGER
        );
        CREATE TABLE IF NOT EXISTS parse_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_tc_tool ON tool_calls(tool_name);
        CREATE INDEX IF NOT EXISTS idx_tc_session ON tool_calls(session_id);
        CREATE INDEX IF NOT EXISTS idx_tc_error ON tool_calls(is_error);
        CREATE INDEX IF NOT EXISTS idx_tc_ts ON tool_calls(timestamp);
        CREATE INDEX IF NOT EXISTS idx_tc_anti ON tool_calls(is_anti_pattern);
    """)
    return conn


def classify_error(tool_name: str, error_text: str) -> str:
    """Classify error into a category."""
    err = error_text.lower()
    if "not been read" in err:
        return "file_not_read_first"
    if "not found" in err or "enoent" in err or "no such file" in err:
        return "file_not_found"
    if "not unique" in err or "found 2 matches" in err or "found 3 matches" in err:
        return "edit_not_unique"
    if "sibling" in err:
        return "sibling_error"
    if "cancelled" in err:
        return "cancelled"
    if "timeout" in err:
        return "timeout"
    if "permission" in err or "eacces" in err:
        return "permission_denied"
    if "exceeds maximum" in err:
        return "file_too_large"
    if "exit code" in err:
        # Extract code
        parts = error_text.split("Exit code")
        if len(parts) > 1:
            code = parts[1].strip().split()[0].strip()
            return f"exit_code_{code}"
        return "exit_code_unknown"
    if "browser is already in use" in err:
        return "browser_busy"
    if "file:" in err and "blocked" in err:
        return "file_url_blocked"
    if "net::" in err or "err_" in err:
        return "network_error"
    if "user doesn't want" in err or "rejected" in err:
        return "user_rejected"
    if "unknown skill" in err:
        return "unknown_skill"
    return "other"


def detect_anti_pattern(cmd: str) -> tuple[bool, str]:
    """Check if a Bash command is an anti-pattern."""
    stripped = cmd.strip()
    if not stripped:
        return False, ""
    first_word = stripped.split()[0]
    # Handle pipes: cat file | ... is still anti-pattern
    if first_word in ANTI_PATTERN_MAP:
        return True, f"bash_{first_word}_instead_of_{ANTI_PATTERN_MAP[first_word]}"
    return False, ""


def parse_sessions(conn, since_days=None):
    """Parse all JSONL files and populate DB."""
    conn.execute("DELETE FROM tool_calls")
    conn.execute("DELETE FROM sessions")

    cutoff = None
    if since_days:
        cutoff = (datetime.now() - timedelta(days=since_days)).isoformat()

    files_parsed = 0
    total_tools = 0

    for root, dirs, files in os.walk(PROJECTS_DIR):
        if "subagents" in root:
            continue
        for fname in files:
            if not fname.endswith(".jsonl"):
                continue
            fpath = os.path.join(root, fname)
            session_id = fname.replace(".jsonl", "")

            # Derive project from path
            parts = root.replace(PROJECTS_DIR, "").strip("/").split("/")
            project = parts[0] if parts else "unknown"

            try:
                prev_tools = {}  # id -> tool_use block
                session_tools = []
                first_ts = None
                last_ts = None
                error_count = 0
                ap_count = 0

                for line in open(fpath):
                    obj = json.loads(line)
                    msg_type = obj.get("type")
                    ts = obj.get("timestamp", "")

                    if cutoff and ts and ts < cutoff:
                        continue

                    if not first_ts and ts:
                        first_ts = ts
                    if ts:
                        last_ts = ts

                    if msg_type == "assistant":
                        for block in obj.get("message", {}).get("content", []):
                            if not isinstance(block, dict):
                                continue
                            if block.get("type") == "tool_use":
                                tool_name = block["name"]
                                tool_id = block["id"]
                                prev_tools[tool_id] = block

                                cmd = ""
                                is_ap = False
                                ap_type = ""
                                if tool_name == "Bash":
                                    cmd = block.get("input", {}).get("command", "")
                                    is_ap, ap_type = detect_anti_pattern(cmd)
                                    if is_ap:
                                        ap_count += 1

                                session_tools.append(
                                    {
                                        "tool_name": tool_name,
                                        "tool_name_short": shorten_tool(tool_name),
                                        "ts": ts,
                                        "bash_command": cmd[:500] if cmd else "",
                                        "is_anti_pattern": is_ap,
                                        "anti_pattern_type": ap_type,
                                    }
                                )

                    elif msg_type == "user":
                        for block in obj.get("message", {}).get("content", []):
                            if not isinstance(block, dict):
                                continue
                            if block.get("type") == "tool_result" and block.get(
                                "is_error"
                            ):
                                tid = block.get("tool_use_id", "")
                                tool = prev_tools.get(tid)
                                if not tool:
                                    continue

                                content = block.get("content", "")
                                if isinstance(content, list):
                                    err_text = " ".join(
                                        c.get("text", "")[:300]
                                        for c in content
                                        if isinstance(c, dict)
                                    )
                                else:
                                    err_text = str(content)[:300]

                                tool_name = tool["name"]
                                err_type = classify_error(tool_name, err_text)

                                # Find and update the matching tool entry
                                for st in reversed(session_tools):
                                    if st["tool_name"] == tool_name and not st.get(
                                        "_matched"
                                    ):
                                        st["is_error"] = True
                                        st["error_type"] = err_type
                                        st["error_detail"] = err_text[:200]
                                        st["_matched"] = True
                                        error_count += 1
                                        break

                # Insert into DB
                for i, st in enumerate(session_tools):
                    conn.execute(
                        """INSERT INTO tool_calls
                        (session_id, project, timestamp, tool_name, tool_name_short,
                         is_error, error_type, error_detail, is_anti_pattern,
                         anti_pattern_type, bash_command, seq_position)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            session_id,
                            project,
                            st["ts"],
                            st["tool_name"],
                            st["tool_name_short"],
                            1 if st.get("is_error") else 0,
                            st.get("error_type", ""),
                            st.get("error_detail", ""),
                            1 if st["is_anti_pattern"] else 0,
                            st["anti_pattern_type"],
                            st["bash_command"],
                            i,
                        ),
                    )
                    total_tools += 1

                conn.execute(
                    """INSERT OR REPLACE INTO sessions
                    (session_id, project, file_path, first_ts, last_ts,
                     tool_count, error_count, anti_pattern_count)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        session_id,
                        project,
                        fpath,
                        first_ts,
                        last_ts,
                        len(session_tools),
                        error_count,
                        ap_count,
                    ),
                )

                files_parsed += 1

            except Exception as e:
                print(f"  SKIP {fname}: {e}", file=sys.stderr)

    conn.execute(
        "INSERT OR REPLACE INTO parse_meta VALUES (?, ?)",
        ("last_parse", datetime.now().isoformat()),
    )
    conn.execute(
        "INSERT OR REPLACE INTO parse_meta VALUES (?, ?)",
        ("files_parsed", str(files_parsed)),
    )
    conn.commit()
    return files_parsed, total_tools


def run_analysis(conn, since_days=None):
    """Run all analysis queries and return results dict."""
    results = {}
    where = ""
    if since_days:
        cutoff = (datetime.now() - timedelta(days=since_days)).isoformat()
        where = f"WHERE timestamp > '{cutoff}'"
        where_and = f"AND timestamp > '{cutoff}'"
    else:
        where_and = ""

    # --- 1. Tool Usage ---
    rows = conn.execute(f"""
        SELECT tool_name_short, COUNT(*) as total,
               SUM(is_error) as errors,
               ROUND(SUM(is_error)*100.0/COUNT(*), 1) as error_rate
        FROM tool_calls {where}
        GROUP BY tool_name_short
        ORDER BY total DESC
        LIMIT 25
    """).fetchall()
    results["tool_usage"] = [
        {"tool": r[0], "total": r[1], "errors": r[2], "error_rate": r[3]} for r in rows
    ]

    # --- 2. Error Patterns ---
    rows = conn.execute(f"""
        SELECT tool_name_short, error_type, COUNT(*) as n
        FROM tool_calls
        WHERE is_error=1 {where_and}
        GROUP BY tool_name_short, error_type
        ORDER BY n DESC
        LIMIT 30
    """).fetchall()
    results["error_patterns"] = [
        {"tool": r[0], "error_type": r[1], "count": r[2]} for r in rows
    ]

    # --- 3. Anti-Patterns ---
    rows = conn.execute(f"""
        SELECT anti_pattern_type, COUNT(*) as n
        FROM tool_calls
        WHERE is_anti_pattern=1 {where_and}
        GROUP BY anti_pattern_type
        ORDER BY n DESC
    """).fetchall()
    total_bash = conn.execute(f"""
        SELECT COUNT(*) FROM tool_calls
        WHERE tool_name='Bash' {where_and}
    """).fetchone()[0]
    results["anti_patterns"] = {
        "total_bash": total_bash,
        "violations": [{"type": r[0], "count": r[1]} for r in rows],
        "total_violations": sum(r[1] for r in rows),
    }

    # --- 4. Tool Sequences (pairs) ---
    rows = conn.execute(f"""
        SELECT a.tool_name_short, b.tool_name_short, COUNT(*) as n
        FROM tool_calls a
        JOIN tool_calls b ON a.session_id = b.session_id
            AND a.seq_position + 1 = b.seq_position
        {"WHERE a." + where[6:] if where else ""}
        GROUP BY a.tool_name_short, b.tool_name_short
        ORDER BY n DESC
        LIMIT 20
    """).fetchall()
    results["sequences"] = [{"from": r[0], "to": r[1], "count": r[2]} for r in rows]

    # --- 5. Sessions with most errors ---
    rows = conn.execute(f"""
        SELECT s.session_id, s.project, s.first_ts, s.tool_count,
               s.error_count, s.anti_pattern_count,
               ROUND(s.error_count*100.0/MAX(s.tool_count,1), 1) as err_rate
        FROM sessions s
        {"WHERE s.first_ts > " + repr((datetime.now() - timedelta(days=since_days)).isoformat()) if since_days else ""}
        ORDER BY s.error_count DESC
        LIMIT 10
    """).fetchall()
    results["worst_sessions"] = [
        {
            "session": r[0][:12] + "…",
            "project": r[1],
            "date": (r[2] or "")[:10],
            "tools": r[3],
            "errors": r[4],
            "anti_patterns": r[5],
            "error_rate": r[6],
        }
        for r in rows
    ]

    # --- 6. Summary Stats ---
    total = conn.execute(f"SELECT COUNT(*) FROM tool_calls {where}").fetchone()[0]
    errors = conn.execute(
        f"SELECT COUNT(*) FROM tool_calls WHERE is_error=1 {where_and}"
    ).fetchone()[0]
    aps = conn.execute(
        f"SELECT COUNT(*) FROM tool_calls WHERE is_anti_pattern=1 {where_and}"
    ).fetchone()[0]
    sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    results["summary"] = {
        "total_tool_calls": total,
        "total_errors": errors,
        "error_rate": round(errors / max(total, 1) * 100, 1),
        "total_anti_patterns": aps,
        "anti_pattern_rate": round(aps / max(total, 1) * 100, 1),
        "sessions_analyzed": sessions,
    }

    # --- 7. Error rate trend (by week) ---
    rows = conn.execute(f"""
        SELECT strftime('%Y-W%W', timestamp) as week,
               COUNT(*) as total,
               SUM(is_error) as errors,
               ROUND(SUM(is_error)*100.0/COUNT(*), 1) as rate
        FROM tool_calls
        WHERE timestamp != '' {where_and}
        GROUP BY week
        ORDER BY week DESC
        LIMIT 8
    """).fetchall()
    results["trend"] = [
        {"week": r[0], "total": r[1], "errors": r[2], "rate": r[3]} for r in rows
    ]

    # --- 8. Repeat errors (same tool+error_type combo) ---
    rows = conn.execute(f"""
        SELECT tool_name_short, error_type, COUNT(*) as n,
               COUNT(DISTINCT session_id) as sessions
        FROM tool_calls
        WHERE is_error=1 AND error_type != '' {where_and}
        GROUP BY tool_name_short, error_type
        HAVING n >= 3
        ORDER BY n DESC
        LIMIT 15
    """).fetchall()
    results["systematic_errors"] = [
        {"tool": r[0], "error": r[1], "count": r[2], "sessions": r[3]} for r in rows
    ]

    return results


def print_report(results):
    """Print human-readable report to stdout."""
    s = results["summary"]
    print("=" * 60)
    print("  SESSION ANALYZER — Agent System Audit")
    print("=" * 60)
    print(f"  Sessions:       {s['sessions_analyzed']}")
    print(f"  Tool Calls:     {s['total_tool_calls']:,}")
    print(f"  Errors:         {s['total_errors']:,} ({s['error_rate']}%)")
    print(f"  Anti-Patterns:  {s['total_anti_patterns']:,} ({s['anti_pattern_rate']}%)")
    print()

    # Tool Usage
    print("─" * 60)
    print("  TOP TOOLS")
    print("─" * 60)
    for t in results["tool_usage"][:15]:
        bar = "█" * min(int(t["total"] / 200), 30)
        err = f"  ⚠ {t['errors']} err ({t['error_rate']}%)" if t["errors"] else ""
        print(f"  {t['total']:5d}  {t['tool']:<28s} {bar}{err}")
    print()

    # Systematic Errors
    print("─" * 60)
    print("  SYSTEMATISCHE FEHLER (≥3x, gleicher Typ)")
    print("─" * 60)
    for e in results["systematic_errors"]:
        print(
            f"  {e['count']:4d}x  {e['tool']:<20s}  {e['error']:<25s}  ({e['sessions']} Sessions)"
        )
    print()

    # Anti-Patterns
    ap = results["anti_patterns"]
    print("─" * 60)
    print(
        f"  ANTI-PATTERNS ({ap['total_violations']}/{ap['total_bash']} Bash = "
        f"{ap['total_violations'] / max(ap['total_bash'], 1) * 100:.1f}%)"
    )
    print("─" * 60)
    for v in ap["violations"]:
        print(f"  {v['count']:5d}  {v['type']}")
    print()

    # Trend
    print("─" * 60)
    print("  ERROR-TREND (wöchentlich)")
    print("─" * 60)
    for t in results["trend"]:
        bar = "█" * min(int(t["rate"]), 30)
        print(
            f"  {t['week']}  {t['total']:5d} calls  {t['errors']:3d} err  {t['rate']:5.1f}% {bar}"
        )
    print()

    # Worst sessions
    print("─" * 60)
    print("  SESSIONS MIT MEISTEN FEHLERN")
    print("─" * 60)
    for ws in results["worst_sessions"][:7]:
        print(
            f"  {ws['date']}  {ws['session']:<15s}  {ws['tools']:3d} tools  "
            f"{ws['errors']:2d} err  {ws['anti_patterns']:2d} AP  ({ws['error_rate']}%)"
        )
    print()


def generate_report_json(results, output_path):
    """Generate JSON for report-renderer.py."""
    s = results["summary"]

    # Build sections
    sections = []

    # Part 1: Overview
    sections.append({"heading": "Übersicht", "level": "part", "body": ""})

    # Tool Usage bars
    tool_bars = []
    for t in results["tool_usage"][:12]:
        max_val = results["tool_usage"][0]["total"]
        tool_bars.append(
            {
                "label": t["tool"],
                "value": t["total"],
                "max": max_val,
                "note": f"{t['errors']} Fehler ({t['error_rate']}%)"
                if t["errors"]
                else "fehlerfrei",
            }
        )
    sections.append(
        {
            "heading": "Tool-Nutzung",
            "body": f"{s['total_tool_calls']:,} Tool-Calls in {s['sessions_analyzed']} Sessions analysiert.",
            "bars": tool_bars,
        }
    )

    # Part 2: Errors
    sections.append({"heading": "Fehler-Analyse", "level": "part", "body": ""})

    # Systematic errors table
    if results["systematic_errors"]:
        sys_rows = []
        for e in results["systematic_errors"]:
            sys_rows.append(
                [e["tool"], e["error"], str(e["count"]), str(e["sessions"])]
            )
        sections.append(
            {
                "heading": "Systematische Fehler",
                "body": "Fehler die ≥3x mit dem gleichen Tool und Fehlertyp auftreten — das sind keine Einzelfälle sondern strukturelle Probleme.",
                "table": {
                    "headers": ["Tool", "Fehlertyp", "Anzahl", "Sessions"],
                    "rows": sys_rows,
                },
            }
        )

    # Error trend
    trend_bars = []
    for t in reversed(results["trend"]):
        trend_bars.append(
            {
                "label": t["week"],
                "value": round(t["rate"], 1),
                "max": max(tt["rate"] for tt in results["trend"])
                if results["trend"]
                else 10,
                "note": f"{t['errors']}/{t['total']}",
            }
        )
    sections.append(
        {
            "heading": "Fehler-Trend (wöchentlich)",
            "body": "Error-Rate über die letzten Wochen.",
            "bars": trend_bars,
        }
    )

    # Part 3: Anti-Patterns
    sections.append({"heading": "Anti-Patterns", "level": "part", "body": ""})
    ap = results["anti_patterns"]
    ap_items = [f"**{v['type']}**: {v['count']}x" for v in ap["violations"]]
    ap_pct = round(ap["total_violations"] / max(ap["total_bash"], 1) * 100, 1)
    sections.append(
        {
            "heading": f"Bash Anti-Patterns ({ap_pct}%)",
            "body": f"{ap['total_violations']} von {ap['total_bash']} Bash-Calls verwenden Bash für Aufgaben, die ein dediziertes Tool besser kann.",
            "callout": "warn",
            "items": ap_items,
        }
    )

    # Part 4: Sequences
    sections.append({"heading": "Workflow-Muster", "level": "part", "body": ""})
    seq_items = [
        f"**{sq['from']}** → **{sq['to']}**: {sq['count']}x"
        for sq in results["sequences"][:12]
    ]
    sections.append(
        {
            "heading": "Häufigste Tool-Sequenzen",
            "body": "Die häufigsten Zwei-Schritt-Abfolgen. Lange Ketten gleicher Tools deuten auf iteratives Vorgehen hin.",
            "items": seq_items,
        }
    )

    # Part 5: Worst Sessions
    sections.append({"heading": "Problemsessions", "level": "part", "body": ""})
    ws_rows = []
    for ws in results["worst_sessions"][:8]:
        ws_rows.append(
            [
                ws["date"],
                ws["session"],
                str(ws["tools"]),
                str(ws["errors"]),
                str(ws["anti_patterns"]),
                f"{ws['error_rate']}%",
            ]
        )
    sections.append(
        {
            "heading": "Sessions mit den meisten Fehlern",
            "body": "Diese Sessions hatten überdurchschnittlich viele Fehler.",
            "table": {
                "headers": ["Datum", "Session", "Tools", "Fehler", "Anti-Pat.", "Rate"],
                "rows": ws_rows,
            },
            "collapsed": True,
        }
    )

    # Assemble report
    report = {
        "type": "deep-research",
        "title": "Agent System Audit",
        "subtitle": f"{datetime.now().strftime('%d.%m.%Y, %H:%M')} — {s['sessions_analyzed']} Sessions, {s['total_tool_calls']:,} Tool-Calls",
        "highlights": [
            f"{s['total_tool_calls']:,} Tool-Calls analysiert — {s['error_rate']}% Fehlerrate gesamt",
            f"{s['total_anti_patterns']} Anti-Pattern-Verstöße ({s['anti_pattern_rate']}% aller Bash-Calls)",
            f"Top-Fehler: {results['systematic_errors'][0]['tool']} {results['systematic_errors'][0]['error']} ({results['systematic_errors'][0]['count']}x)"
            if results["systematic_errors"]
            else "Keine systematischen Fehler gefunden",
        ],
        "kpis": [
            {
                "label": "Sessions",
                "value": str(s["sessions_analyzed"]),
                "note": "analysiert",
            },
            {
                "label": "Tool-Calls",
                "value": f"{s['total_tool_calls']:,}",
                "note": "gesamt",
            },
            {
                "label": "Error Rate",
                "value": f"{s['error_rate']}%",
                "note": f"{s['total_errors']} Fehler",
            },
            {
                "label": "Anti-Patterns",
                "value": str(s["total_anti_patterns"]),
                "note": f"{s['anti_pattern_rate']}% der Bash-Calls",
            },
        ],
        "sections": sections,
        "metrics": {
            "Sessions": str(s["sessions_analyzed"]),
            "Tool-Calls": f"{s['total_tool_calls']:,}",
            "Error-Rate": f"{s['error_rate']}%",
            "Anti-Pattern-Rate": f"{s['anti_pattern_rate']}%",
        },
    }

    with open(output_path, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"Report JSON: {output_path}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Session Analyzer")
    parser.add_argument("--json", help="Output JSON for report-renderer.py")
    parser.add_argument(
        "--quick", action="store_true", help="Skip parsing, use cached DB"
    )
    parser.add_argument("--since", type=int, help="Only analyze last N days")
    args = parser.parse_args()

    conn = init_db()

    if not args.quick:
        print("Parsing JSONL files...", file=sys.stderr)
        t0 = time.time()
        files, tools = parse_sessions(conn, since_days=args.since)
        elapsed = time.time() - t0
        print(
            f"Parsed {files} sessions, {tools:,} tool calls in {elapsed:.1f}s",
            file=sys.stderr,
        )

    results = run_analysis(conn, since_days=args.since)
    print_report(results)

    if args.json:
        generate_report_json(results, args.json)

    conn.close()


if __name__ == "__main__":
    main()
