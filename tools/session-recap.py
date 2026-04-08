#!/home/maetzger/.claude/tools/.venv/bin/python
"""Session-Recap: Extrahiert Metriken aus Claude Code JSONL-Session-Dateien.

Findet die neueste Session-JSONL oder akzeptiert einen Pfad als Argument.
Gibt strukturierte Metriken als JSON auf stdout aus.
"""

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


def find_newest_session() -> Path | None:
    """Findet die neueste JSONL-Session-Datei über alle Projekte."""
    base = Path.home() / ".claude" / "projects"
    if not base.exists():
        return None

    # Nur Top-Level JSONL-Dateien (keine Subagent-Dateien)
    sessions = []
    for project_dir in base.iterdir():
        if not project_dir.is_dir():
            continue
        for f in project_dir.glob("*.jsonl"):
            sessions.append(f)

    if not sessions:
        return None

    return max(sessions, key=lambda p: p.stat().st_mtime)


def parse_session(path: Path) -> dict:
    """Parsed eine JSONL-Session und extrahiert alle relevanten Metriken."""
    tool_usage: Counter = Counter()
    files_read: Counter = Counter()
    files_edited: Counter = Counter()
    files_written: Counter = Counter()
    files_globbed: list[str] = []
    errors: list[dict] = []
    timestamps: list[str] = []
    user_messages = 0
    assistant_messages = 0
    total_assistant_chars = 0
    total_user_chars = 0
    tool_details: dict[str, list] = defaultdict(list)

    with open(path) as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            entry_type = entry.get("type", "")
            ts = entry.get("timestamp", "")
            if ts:
                timestamps.append(ts)

            # User-Messages zählen
            if entry_type == "user":
                msg = entry.get("message", {})
                if msg.get("role") == "user":
                    content = msg.get("content", "")

                    # Prüfe ob es ein echtes User-Message ist (kein Meta/Command)
                    is_meta = entry.get("isMeta", False)
                    if (
                        not is_meta
                        and isinstance(content, str)
                        and not content.startswith("<")
                    ):
                        user_messages += 1
                        total_user_chars += len(content)

                    # Tool-Results auswerten (Fehler finden)
                    if isinstance(content, list):
                        for block in content:
                            if not isinstance(block, dict):
                                continue
                            if block.get("type") == "tool_result" and block.get(
                                "is_error"
                            ):
                                error_content = block.get("content", "")
                                if isinstance(error_content, list):
                                    error_text = " ".join(
                                        sub.get("text", "")
                                        for sub in error_content
                                        if isinstance(sub, dict)
                                    )
                                elif isinstance(error_content, str):
                                    error_text = error_content
                                else:
                                    error_text = str(error_content)
                                errors.append(
                                    {
                                        "tool_use_id": block.get("tool_use_id", "")[
                                            :20
                                        ],
                                        "error": error_text[:300],
                                    }
                                )

            # Assistant-Messages und Tool-Calls
            elif entry_type == "assistant":
                assistant_messages += 1
                msg = entry.get("message", {})
                content = msg.get("content", [])

                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue

                        btype = block.get("type", "")

                        if btype == "text":
                            total_assistant_chars += len(block.get("text", ""))

                        elif btype == "tool_use":
                            tool_name = block.get("name", "unknown")
                            tool_input = block.get("input", {})
                            tool_usage[tool_name] += 1

                            # Datei-Tracking
                            if tool_name == "Read":
                                fp = tool_input.get("file_path", "")
                                if fp:
                                    files_read[fp] += 1

                            elif tool_name == "Edit":
                                fp = tool_input.get("file_path", "")
                                if fp:
                                    files_edited[fp] += 1

                            elif tool_name == "Write":
                                fp = tool_input.get("file_path", "")
                                if fp:
                                    files_written[fp] += 1

                            elif tool_name == "Glob":
                                pat = tool_input.get("pattern", "")
                                if pat:
                                    files_globbed.append(pat)

                            elif tool_name == "Bash":
                                cmd = tool_input.get("command", "")
                                # Kurzbeschreibung speichern
                                desc = tool_input.get("description", cmd[:80])
                                tool_details["Bash"].append(desc[:100])

                            elif tool_name == "Grep":
                                pat = tool_input.get("pattern", "")
                                tool_details["Grep"].append(pat[:80])

    # Zeitberechnung
    duration_str = "unbekannt"
    start_time = None
    end_time = None
    if timestamps:
        try:
            parsed_ts = []
            for ts in timestamps:
                # ISO-Format parsen
                t = ts.replace("Z", "+00:00")
                parsed_ts.append(datetime.fromisoformat(t))
            parsed_ts.sort()
            start_time = parsed_ts[0]
            end_time = parsed_ts[-1]
            delta = end_time - start_time
            hours, remainder = divmod(int(delta.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)
            if hours > 0:
                duration_str = f"{hours}h {minutes}m"
            elif minutes > 0:
                duration_str = f"{minutes}m {seconds}s"
            else:
                duration_str = f"{seconds}s"
        except (ValueError, IndexError):
            pass

    # Alle bearbeiteten Dateien zusammenführen (mit Typ)
    all_files = {}
    for fp, count in files_read.items():
        all_files.setdefault(fp, {"read": 0, "edit": 0, "write": 0})
        all_files[fp]["read"] = count
    for fp, count in files_edited.items():
        all_files.setdefault(fp, {"read": 0, "edit": 0, "write": 0})
        all_files[fp]["edit"] = count
    for fp, count in files_written.items():
        all_files.setdefault(fp, {"read": 0, "edit": 0, "write": 0})
        all_files[fp]["write"] = count

    # Top-Dateien nach Gesamtinteraktionen sortieren
    top_files = sorted(
        all_files.items(),
        key=lambda x: x[1]["read"] + x[1]["edit"] + x[1]["write"],
        reverse=True,
    )[:20]

    # Token-Schätzung (chars / 3.5)
    estimated_tokens_assistant = int(total_assistant_chars / 3.5)
    estimated_tokens_user = int(total_user_chars / 3.5)

    # Projekt aus Pfad ableiten
    project = path.parent.name.replace("-home-maetzger-", "~/").replace("-", "/")
    if project.startswith("/home/maetzger"):
        project = project.replace("/home/maetzger", "~")

    return {
        "session_id": path.stem,
        "project": project,
        "file_path": str(path),
        "file_size_kb": round(path.stat().st_size / 1024, 1),
        "duration": duration_str,
        "start_time": start_time.isoformat() if start_time else None,
        "end_time": end_time.isoformat() if end_time else None,
        "messages": {
            "user": user_messages,
            "assistant": assistant_messages,
            "total": user_messages + assistant_messages,
        },
        "tokens_estimated": {
            "assistant": estimated_tokens_assistant,
            "user": estimated_tokens_user,
            "total": estimated_tokens_assistant + estimated_tokens_user,
        },
        "tools": dict(tool_usage.most_common()),
        "tools_total": sum(tool_usage.values()),
        "files": {
            "top": [
                {
                    "path": fp,
                    "read": ops["read"],
                    "edit": ops["edit"],
                    "write": ops["write"],
                }
                for fp, ops in top_files
            ],
            "unique_read": len(files_read),
            "unique_edited": len(files_edited),
            "unique_written": len(files_written),
        },
        "errors": errors[:20],
        "error_count": len(errors),
        "bash_commands": tool_details.get("Bash", [])[:15],
        "grep_patterns": tool_details.get("Grep", [])[:10],
    }


def main():
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        if not path.exists():
            print(json.dumps({"error": f"Datei nicht gefunden: {path}"}))
            sys.exit(1)
    else:
        path = find_newest_session()
        if path is None:
            print(json.dumps({"error": "Keine Session-Dateien gefunden"}))
            sys.exit(1)

    result = parse_session(path)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
