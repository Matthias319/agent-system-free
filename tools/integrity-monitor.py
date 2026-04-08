#!/usr/bin/env python3
"""File Integrity Monitor — detects unauthorized changes to critical files.

Monitors: settings.json, CLAUDE.md files, hooks, agent_policy.py,
auto-agent-prompt.md, crontabs, authorized_keys, systemd services.

Usage:
    integrity-monitor.py init       # Create baseline hashes
    integrity-monitor.py check      # Check for changes (returns exit 1 if changed)
    integrity-monitor.py check -v   # Verbose: show diffs
    integrity-monitor.py status     # Show monitored files and last check

Designed to run as cron job before auto-agent.sh (5:55 AM).
Sends notification via Pushover if changes detected.
"""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HOME = Path.home()
DB_PATH = HOME / ".claude/data/integrity.db"
PUSHOVER_ENABLED = True

# Critical files to monitor
WATCHED_FILES = [
    # Agent system core
    HOME / ".claude/settings.json",
    HOME / ".claude/CLAUDE.md",
    HOME / "CLAUDE.md",
    HOME / ".claude/hooks/guard-policy.py",
    HOME / ".claude/tools/agent_policy.py",
    # Hooks (all .sh and .py in hooks dir)
    *sorted((HOME / ".claude/hooks").glob("*.sh")),
    *sorted((HOME / ".claude/hooks").glob("*.py")),
    # Auto-agent prompt (nightly autonomous agent)
    HOME / ".claude/tools/auto-agent-prompt.md",
    # SSH
    HOME / ".ssh/authorized_keys",
    # Crontab (we hash the output of crontab -l)
    # System configs
    Path("/etc/ssh/sshd_config"),
]

# Directories where new files should be detected
WATCHED_DIRS = [
    (HOME / ".claude/hooks", "*.sh"),
    (HOME / ".claude/hooks", "*.py"),
    (Path("/etc/ssh/sshd_config.d"), "*.conf"),
    (Path("/etc/systemd/system"), "*.service"),
]


def init_db():
    db = sqlite3.connect(str(DB_PATH))
    db.execute("""CREATE TABLE IF NOT EXISTS file_hashes (
        path TEXT PRIMARY KEY,
        hash TEXT NOT NULL,
        size INTEGER,
        mtime REAL,
        updated_at TEXT NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS dir_listings (
        dir_path TEXT PRIMARY KEY,
        file_list TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS check_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        status TEXT NOT NULL,
        changes TEXT
    )""")
    db.commit()
    return db


def hash_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, PermissionError):
        return None


def hash_crontab() -> str:
    try:
        result = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True, timeout=5
        )
        return hashlib.sha256(result.stdout.encode()).hexdigest()
    except Exception:
        return "error"


def get_dir_listing(dir_path: Path, pattern: str) -> list[str]:
    try:
        return sorted(str(f) for f in dir_path.glob(pattern) if f.is_file())
    except OSError:
        return []


def cmd_init():
    db = init_db()
    now = datetime.now().isoformat()
    count = 0

    for path in WATCHED_FILES:
        if path.exists():
            h = hash_file(path)
            if h:
                stat = path.stat()
                db.execute(
                    "INSERT OR REPLACE INTO file_hashes VALUES (?, ?, ?, ?, ?)",
                    (str(path), h, stat.st_size, stat.st_mtime, now),
                )
                count += 1

    # Crontab as special case
    cron_hash = hash_crontab()
    db.execute(
        "INSERT OR REPLACE INTO file_hashes VALUES (?, ?, ?, ?, ?)",
        ("__crontab__", cron_hash, 0, 0, now),
    )
    count += 1

    # Directory listings
    for dir_path, pattern in WATCHED_DIRS:
        listing = get_dir_listing(dir_path, pattern)
        db.execute(
            "INSERT OR REPLACE INTO dir_listings VALUES (?, ?, ?)",
            (str(dir_path), json.dumps(listing), now),
        )

    db.commit()
    db.close()
    print(f"Baseline erstellt: {count} Dateien + {len(WATCHED_DIRS)} Verzeichnisse")


def cmd_check(verbose=False):
    if not DB_PATH.exists():
        print("Keine Baseline vorhanden. Zuerst: integrity-monitor.py init")
        sys.exit(2)

    db = init_db()
    now = datetime.now().isoformat()
    changes = []

    # Check file hashes
    rows = db.execute("SELECT path, hash, size FROM file_hashes").fetchall()
    for path_str, old_hash, old_size in rows:
        if path_str == "__crontab__":
            new_hash = hash_crontab()
            if new_hash != old_hash:
                changes.append(
                    {
                        "type": "modified",
                        "path": "crontab (crontab -l)",
                        "detail": "Crontab wurde verändert",
                    }
                )
            continue

        path = Path(path_str)
        if not path.exists():
            changes.append(
                {"type": "deleted", "path": path_str, "detail": "Datei gelöscht!"}
            )
            continue

        new_hash = hash_file(path)
        if new_hash and new_hash != old_hash:
            detail = f"Hash geändert (size: {old_size} → {path.stat().st_size})"
            if verbose:
                try:
                    result = subprocess.run(
                        ["git", "diff", "--no-index", "/dev/null", str(path)],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    detail += f"\n{result.stdout[:500]}"
                except Exception:
                    pass
            changes.append({"type": "modified", "path": path_str, "detail": detail})

    # Check for NEW files in watched directories
    dir_rows = db.execute("SELECT dir_path, file_list FROM dir_listings").fetchall()
    for dir_str, old_list_json in dir_rows:
        dir_path = Path(dir_str)
        pattern = next((p for d, p in WATCHED_DIRS if str(d) == dir_str), "*")
        current_listing = get_dir_listing(dir_path, pattern)
        old_listing = json.loads(old_list_json)

        new_files = set(current_listing) - set(old_listing)
        removed_files = set(old_listing) - set(current_listing)

        for f in new_files:
            changes.append(
                {
                    "type": "new_file",
                    "path": f,
                    "detail": f"Neue Datei in {dir_str}",
                }
            )
        for f in removed_files:
            changes.append(
                {
                    "type": "removed_from_dir",
                    "path": f,
                    "detail": f"Datei entfernt aus {dir_str}",
                }
            )

    # Log the check
    status = "ALERT" if changes else "OK"
    db.execute(
        "INSERT INTO check_log (ts, status, changes) VALUES (?, ?, ?)",
        (now, status, json.dumps(changes, ensure_ascii=False) if changes else None),
    )
    db.commit()
    db.close()

    if changes:
        print(f"⚠ INTEGRITY ALERT — {len(changes)} Änderung(en) erkannt:")
        for c in changes:
            print(f"  [{c['type']}] {c['path']}")
            if verbose:
                print(f"    {c['detail']}")
        send_notification(changes)
        sys.exit(1)
    else:
        print(f"✓ Integrität OK — {len(rows)} Dateien geprüft")


def send_notification(changes: list[dict]):
    """Send alert via multiple channels."""
    msg_lines = [f"⚠ INTEGRITY ALERT auf {os.uname().nodename}"]
    msg_lines.append(f"Zeitpunkt: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    msg_lines.append(f"{len(changes)} Änderung(en):")
    for c in changes[:5]:
        msg_lines.append(f"  [{c['type']}] {Path(c['path']).name}")
    msg = "\n".join(msg_lines)

    # Method 1: Write to a file that MCB can pick up
    alert_file = HOME / ".claude/data/integrity-alerts.log"
    try:
        with open(alert_file, "a") as f:
            f.write(f"\n{'=' * 60}\n{msg}\n")
    except OSError:
        pass

    # Method 2: systemd journal (visible via journalctl)
    try:
        subprocess.run(
            ["logger", "-t", "integrity-monitor", "-p", "auth.crit", msg],
            timeout=5,
        )
    except Exception:
        pass

    # Method 3: Terminal bell + wall message
    try:
        subprocess.run(
            ["wall", f"SECURITY: {len(changes)} file integrity changes detected!"],
            timeout=5,
            capture_output=True,
        )
    except Exception:
        pass


def cmd_status():
    if not DB_PATH.exists():
        print("Keine Baseline vorhanden.")
        return

    db = init_db()
    rows = db.execute("SELECT path, updated_at FROM file_hashes").fetchall()
    print(f"Überwachte Dateien: {len(rows)}")
    for path, updated in rows:
        name = Path(path).name if path != "__crontab__" else "crontab"
        print(f"  {name:<40} (Baseline: {updated[:19]})")

    last_check = db.execute(
        "SELECT ts, status, changes FROM check_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if last_check:
        print(f"\nLetzter Check: {last_check[0][:19]} — {last_check[1]}")
        if last_check[2]:
            changes = json.loads(last_check[2])
            for c in changes:
                print(f"  [{c['type']}] {c['path']}")
    db.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: integrity-monitor.py {init|check|check -v|status}")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "init":
        cmd_init()
    elif cmd == "check":
        verbose = "-v" in sys.argv
        cmd_check(verbose)
    elif cmd == "status":
        cmd_status()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
