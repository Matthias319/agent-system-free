#!/home/maetzger/.claude/tools/.venv/bin/python
"""Minimaler HTTP-Endpunkt zum Speichern von Design-Bewertungen.

Empfängt POST /save mit JSON-Body, schreibt nach /tmp/design-ratings.json.
GET /ratings liefert gespeicherte Bewertungen zurück.

Läuft auf Port 8787, CORS für alle Origins erlaubt.
"""

import json
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

RATINGS_FILE = Path("/tmp/design-ratings.json")
PORT = 8787


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self):
        if self.path != "/save":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
            # Merge: lade existierende Daten, update mit neuen (device-spezifisch)
            existing = {}
            if RATINGS_FILE.exists():
                existing = json.loads(RATINGS_FILE.read_text())
            device = data.pop("_device", "unknown")
            existing[device] = data
            RATINGS_FILE.write_text(json.dumps(existing, ensure_ascii=False, indent=2))
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "device": device}).encode())
            print(f"  Saved ratings from {device}")
        except Exception as e:
            self.send_response(400)
            self._cors()
            self.end_headers()
            self.wfile.write(str(e).encode())

    def do_GET(self):
        if self.path != "/ratings":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        if RATINGS_FILE.exists():
            self.wfile.write(RATINGS_FILE.read_bytes())
        else:
            self.wfile.write(b"{}")

    def log_message(self, fmt, *args):
        pass  # Suppress default logging


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Rating-Server auf Port {PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nGestoppt.")
        sys.exit(0)
