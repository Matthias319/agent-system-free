#!/usr/bin/env python3
"""Dispatch Helper — zuverlässige Session-Verwaltung für den Dispatcher.

Usage:
    dispatch-helper.py status          — Alle Sessions mit Status (permission/working/idle)
    dispatch-helper.py ping            — Nur Sessions die Handlungsbedarf haben
    dispatch-helper.py accept <tmux>   — Permission akzeptieren + verifizieren
    dispatch-helper.py send <name> <msg> — Nachricht an Session (by name, nicht ID)
    dispatch-helper.py sessions        — Session-Liste als JSON (name → id mapping)
"""

import json
import subprocess
import sys
import time
import re


API = "https://127.0.0.1:8205/api"
AUTH = "Authorization: Bearer admin"


def curl(endpoint, method="GET", data=None):
    cmd = ["curl", "-sk", f"{API}/{endpoint}", "-H", AUTH]
    if method == "POST":
        cmd += ["-X", "POST", "-H", "Content-Type: application/json"]
        if data:
            cmd += ["-d", json.dumps(data)]
    elif method == "DELETE":
        cmd += ["-X", "DELETE"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return json.loads(r.stdout) if r.stdout.strip() else {}
    except Exception:
        return {}


def get_sessions():
    """Alle Sessions als dict {tmux_name: {id, name, tmux_name}}."""
    raw = curl("sessions")
    if not isinstance(raw, list):
        return {}
    result = {}
    for s in raw:
        if not isinstance(s, dict):
            continue
        tmux = s.get("tmux_name")
        if not tmux or "id" not in s:
            continue
        result[tmux] = s
    return result


def capture_pane(tmux_name, lines=15):
    """tmux capture-pane mit korrekten Flags."""
    try:
        r = subprocess.run(
            [
                "tmux",
                "capture-pane",
                "-t",
                f"{tmux_name}:0.0",
                "-p",
                "-e",
                "-S",
                "-200",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = r.stdout
        # Strip ANSI für Pattern-Matching, behalte Original für Display
        clean = re.sub(r"\x1b\[[0-9;]*m", "", output)
        tail = output.strip().split("\n")[-lines:] if output.strip() else []
        return {
            "raw": "\n".join(tail),
            "clean": re.sub(r"\x1b\[[0-9;]*m", "", "\n".join(tail)),
            "full_clean": clean,
        }
    except Exception:
        return {"raw": "", "clean": "", "full_clean": ""}


def detect_status(pane):
    """Erkennt Session-Status aus Pane-Inhalt."""
    clean = pane["clean"]
    if "Esc to cancel" in clean or "Do you want to" in clean:
        return "PERMISSION"
    if "Error" in clean and "error" in clean.lower():
        # Nur echte Errors, nicht "error connecting"
        if any(x in clean for x in ["stack trace", "Traceback", "FAILED"]):
            return "ERROR"
    if any(
        x in clean
        for x in [
            "thinking",
            "Spinning",
            "Evaporating",
            "Wandering",
            "Shimmying",
            "Puttering",
            "Fluttering",
            "Ebbing",
            "Lollygagging",
            "Twisting",
            "Running",
        ]
    ):
        return "WORKING"
    if "❯" in clean and clean.strip().endswith(("to", "on", "")):
        return "IDLE"
    return "UNKNOWN"


def cmd_status():
    """Zeige Status aller Sessions."""
    sessions = get_sessions()
    if not sessions:
        print("Keine Sessions gefunden")
        return

    # Eigene Session rausfiltern
    try:
        own = subprocess.run(
            ["tmux", "display-message", "-p", "#{session_name}"],
            capture_output=True,
            text=True,
            timeout=3,
        ).stdout.strip()
    except Exception:
        own = ""

    results = []
    for tmux_name, info in sorted(sessions.items()):
        if tmux_name == own:
            continue
        pane = capture_pane(tmux_name)
        status = detect_status(pane)
        marker = {
            "PERMISSION": "⚠️",
            "ERROR": "❌",
            "WORKING": "⏳",
            "IDLE": "💤",
            "UNKNOWN": "❓",
        }
        results.append(
            {
                "tmux": tmux_name,
                "name": info.get("name", "—"),
                "id": info["id"],
                "status": status,
                "marker": marker.get(status, "?"),
            }
        )

    # Sortiere: PERMISSION zuerst, dann ERROR, dann WORKING, dann rest
    priority = {"PERMISSION": 0, "ERROR": 1, "WORKING": 2, "UNKNOWN": 3, "IDLE": 4}
    results.sort(key=lambda x: priority.get(x["status"], 5))

    for r in results:
        print(f"{r['marker']}  {r['name']:25s} ({r['tmux']})  [{r['status']}]")

    # Zusammenfassung
    needs_action = [r for r in results if r["status"] in ("PERMISSION", "ERROR")]
    if needs_action:
        print(f"\n⚠️  {len(needs_action)} Session(s) brauchen Eingriff!")
    else:
        print("\n✅ Kein Handlungsbedarf")


def cmd_ping():
    """Zeige nur Sessions die Handlungsbedarf haben."""
    sessions = get_sessions()
    try:
        own = subprocess.run(
            ["tmux", "display-message", "-p", "#{session_name}"],
            capture_output=True,
            text=True,
            timeout=3,
        ).stdout.strip()
    except Exception:
        own = ""

    found = False
    for tmux_name, info in sessions.items():
        if tmux_name == own:
            continue
        pane = capture_pane(tmux_name)
        status = detect_status(pane)
        if status in ("PERMISSION", "ERROR"):
            found = True
            print(f"⚠️  {info.get('name', tmux_name)} ({tmux_name}) — {status}")
            # Bei Permission: zeige was gefragt wird
            if status == "PERMISSION":
                for line in pane["clean"].split("\n"):
                    if "Do you want" in line or "create" in line or "edit" in line:
                        print(f"    → {line.strip()}")

    if not found:
        print("✅ Kein Handlungsbedarf")


def cmd_accept(tmux_name):
    """Permission akzeptieren + verifizieren."""
    if not tmux_name or not tmux_name.strip():
        print("❌ tmux-Name darf nicht leer sein")
        return

    # Verify tmux session exists
    check = subprocess.run(
        ["tmux", "has-session", "-t", tmux_name],
        capture_output=True,
        timeout=3,
    )
    if check.returncode != 0:
        print(f"❌ tmux-Session '{tmux_name}' existiert nicht")
        return

    # Accept (Enter)
    subprocess.run(
        ["tmux", "send-keys", "-t", f"{tmux_name}:0.0", "Enter"],
        capture_output=True,
        timeout=3,
    )
    time.sleep(3)

    # Verify
    pane = capture_pane(tmux_name)
    status = detect_status(pane)
    if status == "PERMISSION":
        print("⚠️  NOCH PERMISSION — versuche Option 2 (Down+Enter)")
        subprocess.run(
            ["tmux", "send-keys", "-t", f"{tmux_name}:0.0", "Down"],
            capture_output=True,
            timeout=3,
        )
        time.sleep(0.3)
        subprocess.run(
            ["tmux", "send-keys", "-t", f"{tmux_name}:0.0", "Enter"],
            capture_output=True,
            timeout=3,
        )
        time.sleep(3)
        pane = capture_pane(tmux_name)
        status = detect_status(pane)
        if status == "PERMISSION":
            print("❌ Permission IMMER NOCH da — manueller Eingriff nötig")
        else:
            print(f"✅ Permission akzeptiert (Option 2), Status: {status}")
    else:
        print(f"✅ Permission akzeptiert, Status: {status}")


def cmd_send(session_name, message):
    """Nachricht an Session senden (by name)."""
    if not session_name or not session_name.strip():
        print("❌ Session-Name darf nicht leer sein")
        return
    if not message or not message.strip():
        print("❌ Nachricht darf nicht leer sein")
        return

    sessions = get_sessions()
    # Suche by name (case-insensitive partial match)
    target = None
    for tmux_name, info in sessions.items():
        if session_name.lower() in info.get("name", "").lower():
            target = info
            break
        if session_name.lower() in tmux_name.lower():
            target = info
            break

    if not target:
        print(f"❌ Session '{session_name}' nicht gefunden")
        print("Verfügbar:", ", ".join(s.get("name", t) for t, s in sessions.items()))
        return

    result = curl(
        "terminal/send",
        method="POST",
        data={"session_id": target["id"], "text": message, "submit": True},
    )

    if result.get("ok"):
        print(f"✅ Gesendet an '{target.get('name', '')}' ({target['id'][:8]})")
    else:
        print(f"❌ Fehler: {result}")


def cmd_sessions():
    """Session-Liste als kompaktes JSON."""
    sessions = get_sessions()
    mapping = {info.get("name", tmux): info["id"] for tmux, info in sessions.items()}
    print(json.dumps(mapping, indent=2))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "status":
        cmd_status()
    elif cmd == "ping":
        cmd_ping()
    elif cmd == "accept" and len(sys.argv) >= 3:
        cmd_accept(sys.argv[2])
    elif cmd == "send" and len(sys.argv) >= 4:
        cmd_send(sys.argv[2], " ".join(sys.argv[3:]))
    elif cmd == "sessions":
        cmd_sessions()
    else:
        print(__doc__)
