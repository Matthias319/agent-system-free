#!/home/maetzger/.claude/tools/.venv/bin/python
"""JARVIS Audio Server — serves TTS audio files and SSE events to browser."""

import asyncio
import json
import os
from collections import deque
from datetime import datetime
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request  # noqa: F401
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse

ENV_PATH = Path.home() / ".env-jarvis"
load_dotenv(ENV_PATH)

AUDIO_DIR = Path(
    os.getenv("JARVIS_AUDIO_DIR", str(Path.home() / ".claude/data/jarvis-audio"))
)
PORT = int(os.getenv("JARVIS_SERVER_PORT", "8095"))

app = FastAPI(title="JARVIS Audio Server")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Broadcast to multiple SSE clients — each client gets its own queue
client_queues: set[asyncio.Queue] = set()
event_history: deque = deque(maxlen=50)

PLAYER_HTML_PATH = Path(__file__).parent / "jarvis-player.html"


@app.get("/", response_class=HTMLResponse)
async def player():
    if PLAYER_HTML_PATH.exists():
        return HTMLResponse(PLAYER_HTML_PATH.read_text())
    return HTMLResponse(
        "<h1>JARVIS Player not found</h1><p>jarvis-player.html missing</p>"
    )


@app.get("/audio/{filename}")
async def serve_audio(filename: str):
    filepath = (AUDIO_DIR / filename).resolve()
    if not filepath.is_relative_to(AUDIO_DIR.resolve()):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    if not filepath.exists() or filepath.suffix != ".mp3":
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(filepath, media_type="audio/mpeg")


@app.post("/notify")
async def notify(data: dict, request: Request):
    # Only allow notify from localhost (jarvis-speak.py runs locally)
    client_ip = request.client.host if request.client else ""
    if client_ip not in ("127.0.0.1", "::1", "localhost"):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    event = {
        "file": data.get("file", ""),
        "text": data.get("text", ""),
        "timestamp": datetime.now().isoformat(),
    }
    event_history.append(event)
    # Broadcast to all connected clients
    dead_queues = set()
    for q in client_queues:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            dead_queues.add(q)
    client_queues.difference_update(dead_queues)
    return {"ok": True, "clients": len(client_queues)}


@app.get("/events")
async def sse_events():
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    client_queues.add(queue)

    async def event_generator():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield {"event": "new_audio", "data": json.dumps(event)}
                except asyncio.TimeoutError:
                    yield {"event": "keepalive", "data": "ping"}
        finally:
            client_queues.discard(queue)

    return EventSourceResponse(event_generator())


@app.get("/history")
async def history():
    return list(event_history)


@app.get("/health")
async def health():
    audio_count = len(list(AUDIO_DIR.glob("*.mp3")))
    return {
        "status": "ok",
        "audio_files": audio_count,
        "port": PORT,
        "clients": len(client_queues),
    }


if __name__ == "__main__":
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    print(f"JARVIS Audio Server starting on port {PORT}")
    print(f"Audio dir: {AUDIO_DIR}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
