#!/usr/bin/env -S uv run --with httpx --with trafilatura --quiet
"""Surface Pro Panther Lake Monitor.

Prüft alle 5 Tage ob ein neues Surface Pro mit Intel Panther Lake
(nicht ARM/Snapdragon) in Deutschland verfügbar oder angekündigt ist.
Benachrichtigt per Datei + MCB Dispatcher-Callback.
"""

import json
import hashlib
import sys
from datetime import datetime
from pathlib import Path

import httpx
import trafilatura

# --- Config ---
STATE_FILE = Path.home() / ".claude" / "data" / "surface-monitor-state.json"
NOTIFY_FILE = Path.home() / ".claude" / "data" / "surface-monitor-alert.txt"
LOG_FILE = Path.home() / ".claude" / "data" / "surface-monitor.log"
MCB_CALLBACK_URL = "https://127.0.0.1:8205/api/callback"

# Suchbegriffe die auf Panther Lake Surface hindeuten
POSITIVE_KEYWORDS = [
    "panther lake",
    "core ultra 3",  # Series 3 = Panther Lake
    "core ultra 300",
    "356h",
    "358h",
    "388h",
    "386h",  # Panther Lake SKUs
]

# Muss auch Surface-bezogen sein
SURFACE_KEYWORDS = ["surface pro", "surface laptop"]

# Ausschluss: ARM/Snapdragon-only News
ARM_ONLY_INDICATORS = ["snapdragon x2", "snapdragon x plus", "qualcomm"]

# URLs zum Prüfen
CHECK_URLS = [
    # Microsoft Store DE - Surface Pro Intel
    "https://www.microsoft.com/de-de/store/b/surface-pro",
    "https://www.microsoft.com/de-de/store/b/surface-laptop",
    # Tech-News DE
    "https://winfuture.de/news,133488.html",  # WinFuture Surface News
    "https://www.notebookcheck.com/Microsoft-Surface.396015.0.html",
    # Microsoft Surface Blog
    "https://blogs.windows.com/devices/",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
}


def log(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    line = f"[{timestamp}] {msg}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_check": None, "content_hash": None, "found": False, "findings": []}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def fetch_page(url: str) -> str | None:
    try:
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=20) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                text = trafilatura.extract(resp.text) or ""
                return text.lower()
    except Exception as e:
        log(f"  Fehler bei {url}: {e}")
    return None


def check_for_panther_lake(text: str) -> list[str]:
    """Prüft ob Text Hinweise auf Surface + Panther Lake enthält."""
    hits = []

    has_surface = any(kw in text for kw in SURFACE_KEYWORDS)
    if not has_surface:
        return []

    for kw in POSITIVE_KEYWORDS:
        if kw in text:
            # Kontext extrahieren (50 Zeichen drumherum)
            idx = text.index(kw)
            start = max(0, idx - 80)
            end = min(len(text), idx + len(kw) + 80)
            context = text[start:end].replace("\n", " ").strip()
            hits.append(f"'{kw}' gefunden: ...{context}...")

    return hits


def notify_dispatcher(findings: list[str]):
    """Sendet Callback an MCB Dispatcher-Terminal."""
    summary = "Surface Panther Lake Monitor: Neue Treffer!\n\n"
    for f in findings[:5]:  # Max 5 Treffer im Callback
        summary += f"- {f}\n"
    summary += "\nDetails: ./data/surface-monitor-alert.txt"

    try:
        with httpx.Client(timeout=10, verify=False) as client:
            resp = client.post(
                MCB_CALLBACK_URL,
                json={
                    "kind": "done",
                    "message": summary,
                    "session_name": "Surface-Monitor",
                },
            )
            if resp.status_code == 200:
                log("  MCB Dispatcher benachrichtigt!")
            else:
                log(f"  MCB Callback fehlgeschlagen: {resp.status_code}")
    except Exception as e:
        log(f"  MCB Callback nicht erreichbar: {e}")


def main():
    log("=== Surface Panther Lake Monitor gestartet ===")
    state = load_state()

    all_findings = []
    all_texts = []

    for url in CHECK_URLS:
        log(f"  Prüfe: {url}")
        text = fetch_page(url)
        if not text:
            continue

        all_texts.append(text)
        hits = check_for_panther_lake(text)
        if hits:
            for h in hits:
                finding = f"[{url}] {h}"
                all_findings.append(finding)
                log(f"  TREFFER: {finding}")

    # Content-Hash für Änderungserkennung
    combined = "\n".join(all_texts)
    content_hash = hashlib.md5(combined.encode()).hexdigest()[:16]

    now = datetime.now().isoformat()
    state["last_check"] = now

    if all_findings:
        # Neue Findings?
        new_findings = [f for f in all_findings if f not in state.get("findings", [])]

        if new_findings:
            state["found"] = True
            state["findings"] = all_findings
            state["content_hash"] = content_hash
            save_state(state)

            # Alert-Datei schreiben
            alert = (
                f"SURFACE PANTHER LAKE UPDATE ({now})\n"
                f"{'=' * 50}\n\n"
                f"Neue Hinweise auf Surface Pro mit Intel Panther Lake gefunden!\n\n"
            )
            for f in all_findings:
                alert += f"  - {f}\n"
            alert += (
                "\nNächste Schritte:\n"
                "  - Microsoft Store DE prüfen\n"
                "  - Preise und Verfügbarkeit checken\n"
            )
            NOTIFY_FILE.write_text(alert)
            log(f"  ALERT geschrieben: {NOTIFY_FILE}")
            log(f"  {len(new_findings)} neue Treffer!")

            # MCB Dispatcher benachrichtigen
            notify_dispatcher(all_findings)
        else:
            log("  Keine neuen Treffer (bekannte Findings).")
            state["content_hash"] = content_hash
            save_state(state)
    else:
        log("  Kein Treffer. Surface Panther Lake noch nicht gefunden.")
        state["content_hash"] = content_hash
        state["findings"] = []
        save_state(state)

    # Alert-Datei entfernen wenn nichts mehr gefunden
    if not all_findings and NOTIFY_FILE.exists():
        NOTIFY_FILE.unlink()

    log("=== Monitor beendet ===\n")
    return 0 if not all_findings else 1


if __name__ == "__main__":
    sys.exit(main())
