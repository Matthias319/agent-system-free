#!/usr/bin/env python3
"""Structured log analysis for systemd journal and application logs.

Usage:
    log-analyse.py recent [--since <timespec>] [--unit <service>] [--priority <level>]
    log-analyse.py errors [--since <timespec>] [--unit <service>]
    log-analyse.py timeline [--since <timespec>] [--unit <service>]
    log-analyse.py services
    log-analyse.py boots
"""

import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime


def run(cmd: list[str], timeout: int = 30) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.stdout


def parse_journal_json(output: str) -> list[dict]:
    """Parse journalctl JSON output (one JSON object per line)."""
    entries = []
    for line in output.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            entries.append(entry)
        except json.JSONDecodeError:
            continue
    return entries


def safe_msg(entry: dict) -> str:
    """Extract MESSAGE as string (journalctl sometimes returns a list)."""
    msg = entry.get("MESSAGE", "")
    if isinstance(msg, list):
        msg = " ".join(str(m) for m in msg)
    return str(msg)


def get_recent(since: str = "1h", unit: str = "", priority: str = "") -> dict:
    """Get recent log entries with optional filters."""
    cmd = ["journalctl", f"--since=-{since}", "--no-pager", "-o", "json"]
    if unit:
        cmd.extend(["-u", unit])
    if priority:
        cmd.extend(["-p", priority])

    output = run(cmd, timeout=60)
    entries = parse_journal_json(output)

    formatted = []
    for e in entries[-200:]:
        ts = e.get("__REALTIME_TIMESTAMP", "")
        if ts:
            try:
                dt = datetime.fromtimestamp(int(ts) / 1_000_000)
                ts = dt.strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, OSError):
                pass
        formatted.append(
            {
                "timestamp": ts,
                "unit": e.get("_SYSTEMD_UNIT", e.get("SYSLOG_IDENTIFIER", "?")),
                "priority": int(e.get("PRIORITY", 6)),
                "message": safe_msg(e)[:500],
            }
        )

    return {
        "total_entries": len(entries),
        "shown": len(formatted),
        "since": since,
        "unit_filter": unit or "all",
        "priority_filter": priority or "all",
        "entries": formatted,
    }


def get_errors(since: str = "1h", unit: str = "") -> dict:
    """Get error/warning entries with pattern clustering."""
    cmd = [
        "journalctl",
        f"--since=-{since}",
        "--no-pager",
        "-o",
        "json",
        "-p",
        "warning",
    ]
    if unit:
        cmd.extend(["-u", unit])

    output = run(cmd, timeout=60)
    entries = parse_journal_json(output)

    by_unit = defaultdict(list)
    patterns = Counter()

    for e in entries:
        unit_name = e.get("_SYSTEMD_UNIT", e.get("SYSLOG_IDENTIFIER", "unknown"))
        msg = safe_msg(e)
        by_unit[unit_name].append(msg[:300])

        # Normalize message for pattern detection
        normalized = re.sub(r"\d+", "N", msg[:200])
        normalized = re.sub(r"0x[0-9a-fA-F]+", "0xHEX", normalized)
        normalized = re.sub(r"[0-9a-f]{8,}", "HASH", normalized)
        patterns[normalized] += 1

    top_patterns = [{"pattern": p, "count": c} for p, c in patterns.most_common(10)]

    unit_summary = []
    for u, msgs in sorted(by_unit.items(), key=lambda x: -len(x[1])):
        unit_summary.append(
            {
                "unit": u,
                "error_count": len(msgs),
                "sample_messages": msgs[:3],
            }
        )

    return {
        "total_errors": len(entries),
        "since": since,
        "unit_filter": unit or "all",
        "by_unit": unit_summary[:15],
        "top_patterns": top_patterns,
    }


def get_timeline(since: str = "1h", unit: str = "") -> dict:
    """Build a timeline of significant events."""
    cmd = ["journalctl", f"--since=-{since}", "--no-pager", "-o", "json"]
    if unit:
        cmd.extend(["-u", unit])

    output = run(cmd, timeout=60)
    entries = parse_journal_json(output)

    # Track service state changes and errors
    events = []
    for e in entries:
        msg = safe_msg(e)
        priority = int(e.get("PRIORITY", 6))
        unit_name = e.get("_SYSTEMD_UNIT", e.get("SYSLOG_IDENTIFIER", "?"))

        is_significant = (
            priority <= 3  # error or worse
            or "Started " in msg
            or "Stopped " in msg
            or "Failed " in msg
            or "Reloading " in msg
            or "segfault" in msg.lower()
            or "oom" in msg.lower()
            or "killed" in msg.lower()
        )

        if is_significant:
            ts = e.get("__REALTIME_TIMESTAMP", "")
            if ts:
                try:
                    dt = datetime.fromtimestamp(int(ts) / 1_000_000)
                    ts = dt.strftime("%Y-%m-%d %H:%M:%S")
                except (ValueError, OSError):
                    pass

            event_type = "error"
            if priority <= 2:
                event_type = "critical"
            elif priority == 3:
                event_type = "error"
            elif "Started" in msg:
                event_type = "start"
            elif "Stopped" in msg:
                event_type = "stop"
            elif "Failed" in msg:
                event_type = "failure"

            events.append(
                {
                    "timestamp": ts,
                    "unit": unit_name,
                    "type": event_type,
                    "priority": priority,
                    "message": msg[:300],
                }
            )

    return {
        "total_entries": len(entries),
        "significant_events": len(events),
        "since": since,
        "unit_filter": unit or "all",
        "events": events[-100:],
    }


def get_services() -> dict:
    """List all services with their status."""
    output = run(
        [
            "systemctl",
            "list-units",
            "--type=service",
            "--all",
            "--no-pager",
            "--no-legend",
        ]
    )

    services = []
    for line in output.strip().splitlines():
        parts = line.split(None, 4)
        if len(parts) >= 4:
            services.append(
                {
                    "unit": parts[0],
                    "load": parts[1],
                    "active": parts[2],
                    "sub": parts[3],
                    "description": parts[4] if len(parts) > 4 else "",
                }
            )

    failed = [s for s in services if s["active"] == "failed"]
    active = [s for s in services if s["sub"] == "running"]

    return {
        "total": len(services),
        "running": len(active),
        "failed": len(failed),
        "failed_services": failed,
        "running_services": active,
    }


def get_boots() -> dict:
    """List recent boot entries."""
    output = run(["journalctl", "--list-boots", "--no-pager"])

    boots = []
    for line in output.strip().splitlines():
        parts = line.split(None, 2)
        if len(parts) >= 3:
            boots.append(line.strip())

    return {"boots": boots[-10:], "total": len(boots)}


def main():
    if len(sys.argv) < 2:
        print(
            json.dumps(
                {
                    "error": "Usage: log-analyse.py <recent|errors|timeline|services|boots> [options]"
                }
            )
        )
        sys.exit(1)

    cmd = sys.argv[1]

    # Parse common args
    since = "1h"
    unit = ""
    priority = ""

    for i, arg in enumerate(sys.argv):
        if arg == "--since" and i + 1 < len(sys.argv):
            since = sys.argv[i + 1]
        elif arg == "--unit" and i + 1 < len(sys.argv):
            unit = sys.argv[i + 1]
        elif arg == "--priority" and i + 1 < len(sys.argv):
            priority = sys.argv[i + 1]

    if cmd == "recent":
        result = get_recent(since, unit, priority)
    elif cmd == "errors":
        result = get_errors(since, unit)
    elif cmd == "timeline":
        result = get_timeline(since, unit)
    elif cmd == "services":
        result = get_services()
    elif cmd == "boots":
        result = get_boots()
    else:
        result = {
            "error": f"Unknown command '{cmd}'. Use: recent, errors, timeline, services, boots"
        }

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
