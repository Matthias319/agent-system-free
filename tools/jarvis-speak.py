#!/home/maetzger/.claude/tools/.venv/bin/python
"""JARVIS TTS — Low-latency streaming text-to-speech via ElevenLabs.

Two playback modes:
- Server mode (default): Saves MP3, notifies jarvis-audio-server for browser playback
- Local mode (--local): Streams directly to ffplay for HDMI output
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

ENV_PATH = Path.home() / ".env-jarvis"
load_dotenv(ENV_PATH)

API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "")
MODEL_ID = os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")
AUDIO_DIR = Path(
    os.getenv("JARVIS_AUDIO_DIR", str(Path.home() / ".claude/data/jarvis-audio"))
)
SERVER_PORT = int(os.getenv("JARVIS_SERVER_PORT", "8095"))
MAX_CHARS = int(os.getenv("JARVIS_MAX_CHARS", "500"))

AUDIO_DIR.mkdir(parents=True, exist_ok=True)

API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
HEADERS = {"Content-Type": "application/json"}


def speak(text: str, local: bool = False) -> dict:
    """Generate TTS audio and deliver to browser (server) or ffplay (local)."""
    text = text.strip()
    if not text:
        print("Fehler: Leerer Text", file=sys.stderr)
        return {"ok": False, "error": "empty text"}

    if len(text) > MAX_CHARS:
        print(f"WARN: Text gekürzt auf {MAX_CHARS} Zeichen", file=sys.stderr)
        text = text[:MAX_CHARS]

    url = API_URL.format(voice_id=VOICE_ID)
    headers = {**HEADERS, "xi-api-key": API_KEY}
    payload = {
        "text": text,
        "model_id": MODEL_ID,
        "voice_settings": {"stability": 0.6, "similarity_boost": 0.85},
    }
    params = {"output_format": "mp3_44100_128"}

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"jarvis_{timestamp}.mp3"
    filepath = AUDIO_DIR / filename

    # For local mode: start ffplay
    player = None
    if local:
        player = subprocess.Popen(
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-i", "pipe:0"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    t0 = time.time()
    first_chunk_time = None
    total_bytes = 0

    try:
        with httpx.Client(timeout=30) as client:
            with client.stream(
                "POST", url, json=payload, headers=headers, params=params
            ) as resp:
                if resp.status_code != 200:
                    error = resp.read().decode()
                    print(f"API Error {resp.status_code}: {error}", file=sys.stderr)
                    if player:
                        player.stdin.close()
                        player.wait()
                    return {"ok": False, "error": error}

                with open(filepath, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=4096):
                        if first_chunk_time is None:
                            first_chunk_time = time.time() - t0
                        f.write(chunk)
                        if player:
                            player.stdin.write(chunk)
                        total_bytes += len(chunk)
    except Exception as e:
        print(f"Fehler: {e}", file=sys.stderr)
        return {"ok": False, "error": str(e)}
    finally:
        if player:
            try:
                player.stdin.close()
            except BrokenPipeError:
                pass

    api_time = time.time() - t0

    # Notify audio server for browser playback
    if not local:
        try:
            httpx.post(
                "http://localhost:8084/jarvis/notify",
                json={"file": filename, "text": text},
                timeout=2,
            )
        except Exception:
            pass

    # Wait for ffplay if local mode
    if player:
        player.wait()

    total_time = time.time() - t0

    result = {
        "ok": True,
        "chars": len(text),
        "bytes": total_bytes,
        "first_chunk_s": round(first_chunk_time or 0, 2),
        "api_s": round(api_time, 2),
        "total_s": round(total_time, 2),
        "file": filename,
        "mode": "local" if local else "server",
    }
    print(json.dumps(result))
    return result


def main():
    parser = argparse.ArgumentParser(description="JARVIS TTS")
    parser.add_argument("text", nargs="?", help="Text to speak")
    parser.add_argument("--file", help="Read text from file")
    parser.add_argument("--local", action="store_true", help="Play via ffplay (HDMI)")
    args = parser.parse_args()

    if args.file:
        text = Path(args.file).read_text().strip()
    elif args.text:
        text = args.text
    elif not sys.stdin.isatty():
        text = sys.stdin.read().strip()
    else:
        parser.print_help()
        sys.exit(1)

    if not API_KEY or API_KEY == "your_api_key_here":
        print("Fehler: ELEVENLABS_API_KEY in ~/.env-jarvis setzen!", file=sys.stderr)
        sys.exit(1)

    if not VOICE_ID or VOICE_ID == "your_voice_id_here":
        print("Fehler: ELEVENLABS_VOICE_ID in ~/.env-jarvis setzen!", file=sys.stderr)
        sys.exit(1)

    speak(text, local=args.local)


if __name__ == "__main__":
    main()
