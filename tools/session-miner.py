#!/home/maetzger/.claude/tools/.venv/bin/python
"""Jarvis Session Miner — Extrahiert Wissen aus Claude Code Sessions via Gemini 3 Flash.

Rate Limits (Free Tier): 10 RPM, ~1000 RPD, 250K TPM.
Strategie: 1 Request alle 8 Sekunden, max 400K chars Input (~100-150K Tokens).
"""

import json
import os
import sys
import time
import glob
import urllib.request
import urllib.error

from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/.env-agent"))

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-3-flash-preview"
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent?key={GEMINI_KEY}"
)

SESSIONS_ROOT = os.path.expanduser("./projects")
OUTPUT_DIR = os.path.expanduser("./data/mining-results")
DONE_FILE = os.path.join(OUTPUT_DIR, "mined-sessions.json")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Rate Limit: Tier 1 (~150+ RPM) -> 3 Sekunden zwischen Requests (konservativ)
RATE_LIMIT_SECONDS = 3
# Max chars pro Request (~100-150K Tokens bei ~3 chars/Token)
MAX_CHARS_PER_REQUEST = 400000

EXTRACTION_PROMPT = """Du bist ein Knowledge-Extractor für ein AI-Assistenten-System auf einem Raspberry Pi 5.

Analysiere den Chat-Verlauf zwischen Matthias (User) und Claude (Assistant).
Extrahiere ALLE verwertbaren Erkenntnisse als JSON.

Antworte NUR mit einem JSON-Objekt (kein Array, kein Markdown):

{
  "session_summary": "1-2 Sätze was in dieser Session passiert ist",
  "debugging_patterns": [
    {"problem": "...", "root_cause": "...", "solution": "...", "prevention": "..."}
  ],
  "architecture_decisions": [
    {"decision": "...", "reasoning": "...", "alternatives_rejected": "..."}
  ],
  "user_preferences": [
    {"preference": "...", "evidence": "...", "strength": "strong|moderate|weak"}
  ],
  "failed_approaches": [
    {"approach": "...", "why_failed": "...", "lesson": "..."}
  ],
  "successful_patterns": [
    {"pattern": "...", "context": "...", "reusable": true}
  ],
  "recurring_frustrations": [
    {"frustration": "...", "frequency": "...", "fix_suggestion": "..."}
  ],
  "skill_suggestions": [
    {"skill_name": "...", "description": "...", "trigger": "...", "would_help_because": "..."}
  ],
  "memory_updates": [
    {"topic": "...", "content": "...", "priority": "high|medium|low"}
  ]
}

Regeln:
- IMMER ein einzelnes JSON-Objekt zurückgeben, NIEMALS ein Array
- Nur KONKRETE, ACTIONABLE Erkenntnisse — keine Allgemeinplätze
- Spezifisch für dieses Setup (Pi 5, Python, uv, FastAPI, SQLite, etc.)
- Deutsche Zusammenfassungen, technische Begriffe auf Englisch
- Leere Arrays komplett weglassen
- Wenn keine verwertbaren Erkenntnisse: {"session_summary": "...", "empty": true}

CHAT-VERLAUF:
"""


def load_done_sessions():
    """Lade Liste bereits gemineder Session-IDs."""
    if os.path.exists(DONE_FILE):
        with open(DONE_FILE) as f:
            return set(json.load(f))
    return set()


def save_done_sessions(done):
    """Speichere Liste bereits gemineder Session-IDs."""
    with open(DONE_FILE, "w") as f:
        json.dump(sorted(done), f)


def extract_messages(jsonl_path, max_chars=MAX_CHARS_PER_REQUEST):
    """Extrahiere User/Assistant Messages aus einer JSONL Session-Datei."""
    messages = []
    total_chars = 0

    with open(jsonl_path) as f:
        for line in f:
            try:
                d = json.loads(line.strip())
            except json.JSONDecodeError:
                continue

            if d.get("type") not in ("user", "assistant"):
                continue

            msg = d.get("message", {})
            if not isinstance(msg, dict):
                continue

            content = msg.get("content", "")
            text = ""

            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        t = block.get("text", "")
                        if t.startswith(("<system-reminder>", "<task-notification>")):
                            continue
                        text += t + "\n"
            elif isinstance(content, str):
                text = content

            # Tool-Results und lange Assistant-Messages kürzen
            if d.get("type") == "assistant" and len(text) > 1500:
                text = text[:1500] + "\n[...truncated...]"

            if text.strip():
                role = "USER" if d["type"] == "user" else "ASSISTANT"
                entry = f"[{role}]: {text.strip()}\n"
                if total_chars + len(entry) > max_chars:
                    break
                messages.append(entry)
                total_chars += len(entry)

    return "\n".join(messages)


def call_gemini(prompt, retries=3):
    """Sende Prompt an Gemini 3 Flash mit Retry-Logik."""
    payload = json.dumps(
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 8192,
                "responseMimeType": "application/json",
            },
        }
    ).encode()

    req = urllib.request.Request(
        GEMINI_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read())
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                result = json.loads(text)

                # Normalize: wenn Array kommt, erstes Element nehmen
                if isinstance(result, list):
                    if len(result) >= 1 and isinstance(result[0], dict):
                        result = result[0]
                    else:
                        return {
                            "error": "unexpected array format",
                            "raw": str(result)[:500],
                        }

                if not isinstance(result, dict):
                    return {"error": f"unexpected type: {type(result).__name__}"}

                return result

        except urllib.error.HTTPError as e:
            body = e.read().decode()[:500] if hasattr(e, "read") else ""
            print(f"  HTTP {e.code} (attempt {attempt + 1}): {body}")
            if e.code == 429:
                wait = 30 * (attempt + 1)
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
            elif e.code == 500 or e.code == 503:
                time.sleep(10 * (attempt + 1))
            else:
                time.sleep(5)
        except urllib.error.URLError as e:
            print(f"  Network error (attempt {attempt + 1}): {e}")
            time.sleep(10)
        except json.JSONDecodeError as e:
            print(f"  JSON parse error (attempt {attempt + 1}): {e}")
            try:
                return {"raw_text": text[:2000], "parse_error": str(e)}
            except NameError:
                pass
            time.sleep(5)
        except (KeyError, IndexError) as e:
            print(f"  Response structure error (attempt {attempt + 1}): {e}")
            time.sleep(5)

    return {"error": "all retries failed"}


def find_sessions(min_size_kb=50):
    """Finde alle Sessions sortiert nach Größe."""
    sessions = []
    for jsonl in glob.glob(f"{SESSIONS_ROOT}/**/*.jsonl", recursive=True):
        size = os.path.getsize(jsonl)
        if size < min_size_kb * 1024:
            continue
        project = os.path.basename(os.path.dirname(jsonl))
        session_id = os.path.basename(jsonl).replace(".jsonl", "")
        sessions.append(
            {
                "path": jsonl,
                "project": project,
                "size_kb": size // 1024,
                "id": session_id,
            }
        )
    return sorted(sessions, key=lambda s: -s["size_kb"])


def count_insights(result):
    """Zähle extrahierte Erkenntnisse in einem Result."""
    keys = [
        "debugging_patterns",
        "architecture_decisions",
        "user_preferences",
        "failed_approaches",
        "successful_patterns",
        "recurring_frustrations",
        "skill_suggestions",
        "memory_updates",
    ]
    return sum(len(result.get(k, [])) for k in keys)


def main():
    sessions = find_sessions(min_size_kb=50)
    done = load_done_sessions()

    # Bereits geminte Sessions überspringen
    pending = [s for s in sessions if s["id"] not in done]
    print(f"Sessions gesamt: {len(sessions)} (>= 50KB)")
    print(f"Bereits gemined: {len(done)}")
    print(f"Noch zu minen: {len(pending)}")

    if not pending:
        print("Alles gemined!")
        return

    # Limit pro Durchlauf (Rate Limits beachten)
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    batch = pending[:limit]
    print(f"Dieses Batch: {len(batch)} Sessions")
    print(f"Geschätzte Dauer: ~{len(batch) * RATE_LIMIT_SECONDS // 60 + 1} Minuten")
    print()

    all_results = []
    errors = 0

    for i, s in enumerate(batch):
        print(
            f"[{i + 1}/{len(batch)}] {s['project']}/{s['id'][:12]}... ({s['size_kb']}KB)"
        )

        messages = extract_messages(s["path"])
        if len(messages) < 500:
            print("  -> Zu wenig Content, überspringe")
            done.add(s["id"])
            continue

        prompt = EXTRACTION_PROMPT + messages
        token_estimate = len(prompt) // 3
        print(f"  -> {len(prompt) // 1000}K chars (~{token_estimate // 1000}K tokens)")

        result = call_gemini(prompt)

        if result.get("error"):
            print(f"  -> ERROR: {result['error']}")
            errors += 1
            if errors >= 5:
                print("Zu viele Fehler, breche ab.")
                break
            continue

        n = count_insights(result)
        summary = result.get("session_summary", "?")[:80]
        print(f"  -> {n} Erkenntnisse: {summary}")

        if not result.get("empty"):
            result["_meta"] = {
                "session_id": s["id"],
                "project": s["project"],
                "size_kb": s["size_kb"],
                "mined_at": time.strftime("%Y-%m-%d %H:%M"),
            }
            all_results.append(result)

            with open(os.path.join(OUTPUT_DIR, f"{s['id'][:12]}.json"), "w") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)

        done.add(s["id"])
        save_done_sessions(done)

        # Rate limiting
        time.sleep(RATE_LIMIT_SECONDS)

    # Gesamtergebnis an combined.json anhängen
    combined_path = os.path.join(OUTPUT_DIR, "combined.json")
    existing = []
    if os.path.exists(combined_path):
        with open(combined_path) as f:
            try:
                existing = json.load(f)
            except json.JSONDecodeError:
                existing = []

    existing.extend(all_results)
    with open(combined_path, "w") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    # Statistik
    print(f"\n{'=' * 50}")
    print(f"Batch fertig: {len(all_results)} erfolgreich, {errors} Fehler")
    print(f"Gesamt gemined: {len(done)}/{len(sessions)}")
    print(f"Noch offen: {len(sessions) - len(done)}")

    total_insights = sum(count_insights(r) for r in all_results)
    print(f"Neue Erkenntnisse: {total_insights}")
    print(f"Ergebnisse: {combined_path}")


if __name__ == "__main__":
    main()
