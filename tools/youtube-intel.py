#!/home/maetzger/.claude/tools/.venv/bin/python
"""YouTube intelligence tool for social research.

Uses yt-dlp (search, metadata, comments) and youtube-transcript-api (transcripts).
No API key required. Budget-aware with rate limiting.

Usage:
    python3 youtube-intel.py search "MCP server best practices" [--max 10]
    python3 youtube-intel.py video VIDEO_ID_OR_URL
    python3 youtube-intel.py transcript VIDEO_ID_OR_URL [--lang de,en]
    python3 youtube-intel.py comments VIDEO_ID_OR_URL [--max 20]
    python3 youtube-intel.py channel CHANNEL_URL [--max 5]
    python3 youtube-intel.py pipeline "topic" [--budget 8] [--comments 15]
    python3 youtube-intel.py rate
    python3 youtube-intel.py reset
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

RATE_FILE = Path("/tmp/youtube-intel-rate.json")
YT_DLP = str(Path.home() / ".local/bin/yt-dlp")

# Hardcaps — enforced in tooling, not just prose in skill prompts
MAX_SEARCH_RESULTS = 8
MAX_PIPELINE_VIDEOS = 3
MAX_PIPELINE_COMMENTS = 15
MAX_PIPELINE_BUDGET = 8

# Ensure deno is in PATH for yt-dlp JS runtime
_deno_bin = Path.home() / ".deno/bin"
if _deno_bin.exists() and str(_deno_bin) not in os.environ.get("PATH", ""):
    os.environ["PATH"] = f"{_deno_bin}:{os.environ.get('PATH', '')}"


# --- Rate Limiting (same pattern as reddit-mcp-query.py) ---


def load_rate_state():
    if RATE_FILE.exists():
        state = json.loads(RATE_FILE.read_text())
        if time.time() - state.get("window_start", 0) > 60:
            return {"count": 0, "window_start": time.time()}
        return state
    return {"count": 0, "window_start": time.time()}


def save_rate_state(state):
    RATE_FILE.write_text(json.dumps(state))


RATE_LIMIT_PER_MINUTE = 20  # Raised from 10: yt-dlp has no API key limit


def use_budget(cost=1):
    state = load_rate_state()
    remaining = RATE_LIMIT_PER_MINUTE - state["count"]
    if remaining < cost:
        wait = 60 - (time.time() - state["window_start"])
        if wait > 0:
            print(
                f"Rate limit: {remaining} remaining, need {cost}. Wait {wait:.0f}s",
                file=sys.stderr,
            )
            return False
    state["count"] += cost
    save_rate_state(state)
    return True


# --- Helpers ---


def extract_video_id(url_or_id):
    """Extract video ID from URL or return as-is if already an ID."""
    if not url_or_id:
        return None
    # Already a plain ID (11 chars, no slashes)
    if re.match(r"^[\w-]{11}$", url_or_id):
        return url_or_id
    # youtu.be/ID
    m = re.search(r"youtu\.be/([\w-]{11})", url_or_id)
    if m:
        return m.group(1)
    # youtube.com/watch?v=ID or /shorts/ID or /embed/ID
    m = re.search(r"(?:v=|/shorts/|/embed/)([\w-]{11})", url_or_id)
    if m:
        return m.group(1)
    return url_or_id


def run_ytdlp(args, timeout=30):
    """Run yt-dlp with given args, return stdout text."""
    cmd = [YT_DLP, "--no-warnings", "--no-check-certificates"] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0 and result.stderr:
            # Filter noise
            err = "\n".join(
                line
                for line in result.stderr.strip().split("\n")
                if not line.startswith("WARNING:")
            )
            if err:
                print(f"yt-dlp error: {err}", file=sys.stderr)
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        print(f"yt-dlp timeout ({timeout}s)", file=sys.stderr)
        return ""
    except FileNotFoundError:
        print(f"yt-dlp not found at {YT_DLP}", file=sys.stderr)
        return ""


def format_number(n):
    """Format large numbers: 1234567 -> 1.2M"""
    if n is None:
        return "?"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def format_duration(seconds):
    """Format seconds to MM:SS or HH:MM:SS."""
    if not seconds:
        return "?"
    h, m, s = seconds // 3600, (seconds % 3600) // 60, seconds % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# --- Commands ---


def cmd_search(query, max_results=10):
    """Search YouTube for videos matching query."""
    max_results = min(max_results, MAX_SEARCH_RESULTS)
    if not use_budget(1):
        return
    print(f"Searching YouTube: '{query}' (max {max_results})...", file=sys.stderr)
    t0 = time.time()

    raw = run_ytdlp(
        [
            f"ytsearch{max_results}:{query}",
            "--flat-playlist",
            "--dump-json",
            "--extractor-args",
            "youtube:lang=en",
        ],
        timeout=45,
    )

    if not raw:
        print("No results.", file=sys.stderr)
        return []

    results = []
    for line in raw.split("\n"):
        if not line.strip():
            continue
        try:
            v = json.loads(line)
        except json.JSONDecodeError:
            continue
        results.append(
            {
                "id": v.get("id", ""),
                "title": v.get("title", ""),
                "url": v.get("url")
                or f"https://www.youtube.com/watch?v={v.get('id', '')}",
                "channel": v.get("channel") or v.get("uploader", ""),
                "views": v.get("view_count"),
                "duration": v.get("duration"),
                "upload_date": v.get("upload_date", ""),
                "description": (v.get("description") or "")[:300],
            }
        )

    elapsed = time.time() - t0
    print(f"Found {len(results)} videos in {elapsed:.1f}s", file=sys.stderr)
    return results


def cmd_video(video_ref):
    """Get full metadata for a single video."""
    vid = extract_video_id(video_ref)
    if not use_budget(1):
        return
    print(f"Fetching video metadata: {vid}...", file=sys.stderr)

    raw = run_ytdlp(
        [
            f"https://www.youtube.com/watch?v={vid}",
            "--dump-json",
            "--skip-download",
        ],
        timeout=30,
    )

    if not raw:
        return None

    v = json.loads(raw)
    return {
        "id": v.get("id", ""),
        "title": v.get("title", ""),
        "url": f"https://www.youtube.com/watch?v={v.get('id', '')}",
        "channel": v.get("channel") or v.get("uploader", ""),
        "channel_url": v.get("channel_url", ""),
        "views": v.get("view_count"),
        "likes": v.get("like_count"),
        "comment_count": v.get("comment_count"),
        "duration": v.get("duration"),
        "upload_date": v.get("upload_date", ""),
        "description": v.get("description", ""),
        "tags": v.get("tags", [])[:15],
        "categories": v.get("categories", []),
    }


def cmd_transcript(video_ref, languages=None):
    """Get transcript for a video via youtube-transcript-api."""
    vid = extract_video_id(video_ref)
    if not use_budget(1):
        return

    print(f"Fetching transcript: {vid}...", file=sys.stderr)
    t0 = time.time()

    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        ytt = YouTubeTranscriptApi()
        langs = languages or ["en", "de"]
        result = ytt.fetch(vid, languages=langs)

        text_parts = [snippet.text for snippet in result.snippets]
        full_text = " ".join(text_parts)
        elapsed = time.time() - t0
        chars = len(full_text)
        print(
            f"Transcript: {chars} chars, {len(result.snippets)} segments, "
            f"lang={result.language_code} in {elapsed:.1f}s",
            file=sys.stderr,
        )
        return {
            "video_id": vid,
            "language": result.language_code,
            "text": full_text,
            "chars": chars,
            "segments": len(result.snippets),
        }

    except Exception as e:
        err_msg = str(e)
        if "TranscriptsDisabled" in err_msg or "NoTranscript" in err_msg:
            print(f"No transcript available for {vid}", file=sys.stderr)
        else:
            print(f"Transcript error: {err_msg}", file=sys.stderr)
        return None


def cmd_comments(video_ref, max_comments=20):
    """Get top comments for a video via yt-dlp."""
    vid = extract_video_id(video_ref)
    if not use_budget(1):
        return

    print(f"Fetching comments: {vid} (max {max_comments})...", file=sys.stderr)
    t0 = time.time()

    raw = run_ytdlp(
        [
            f"https://www.youtube.com/watch?v={vid}",
            "--dump-json",
            "--skip-download",
            "--write-comments",
            "--extractor-args",
            f"youtube:max_comments={max_comments},comment_sort=top",
        ],
        timeout=60,
    )

    if not raw:
        return []

    v = json.loads(raw)
    comments = v.get("comments") or []
    result = []
    for c in comments[:max_comments]:
        result.append(
            {
                "author": c.get("author", ""),
                "text": c.get("text", ""),
                "likes": c.get("like_count", 0),
                "timestamp": c.get("timestamp"),
            }
        )

    elapsed = time.time() - t0
    print(f"Got {len(result)} comments in {elapsed:.1f}s", file=sys.stderr)
    return result


def cmd_channel(channel_ref, max_videos=5):
    """Get channel info and recent videos."""
    if not use_budget(1):
        return

    # Normalize URL
    if not channel_ref.startswith("http"):
        channel_ref = f"https://www.youtube.com/@{channel_ref}"

    print(f"Fetching channel: {channel_ref}...", file=sys.stderr)

    raw = run_ytdlp(
        [
            channel_ref,
            "--flat-playlist",
            "--dump-json",
            "--playlist-end",
            str(max_videos),
        ],
        timeout=30,
    )

    if not raw:
        return None

    videos = []
    for line in raw.split("\n"):
        if not line.strip():
            continue
        try:
            v = json.loads(line)
            videos.append(
                {
                    "id": v.get("id", ""),
                    "title": v.get("title", ""),
                    "url": v.get("url")
                    or f"https://www.youtube.com/watch?v={v.get('id', '')}",
                    "views": v.get("view_count"),
                    "duration": v.get("duration"),
                }
            )
        except json.JSONDecodeError:
            continue

    return {"channel_url": channel_ref, "recent_videos": videos}


def cmd_pipeline(query, budget=8, max_comments=15):
    """Full research pipeline: search → top videos → comments + transcripts.

    Returns a structured research report as JSON.
    """
    budget = min(budget, MAX_PIPELINE_BUDGET)
    max_comments = min(max_comments, MAX_PIPELINE_COMMENTS)
    print(f"Pipeline: '{query}' (budget: {budget})", file=sys.stderr)
    report = {"query": query, "videos": [], "stats": {}}
    t0 = time.time()
    spent = 0

    # Phase 1: Search (1 req)
    print("Phase 1/3: Search...", file=sys.stderr)
    results = cmd_search(query, max_results=min(10, budget * 2))
    spent += 1
    if not results:
        print("No results found.", file=sys.stderr)
        return report

    report["stats"]["search_results"] = len(results)

    # Phase 2: Get details + comments for top videos
    remaining = budget - spent
    top_n = min(len(results), remaining // 2, MAX_PIPELINE_VIDEOS)
    print(
        f"Phase 2/3: Deep-dive into top {top_n} videos...",
        file=sys.stderr,
    )

    def _process_video(iv):
        """Ein Video verarbeiten: Comments + Transcript parallel."""
        i, v = iv
        vid = v["id"]
        entry = {**v, "comments": [], "transcript_preview": ""}

        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_comments = pool.submit(cmd_comments, vid, max_comments)
            fut_transcript = pool.submit(cmd_transcript, vid)
            comments = fut_comments.result()
            transcript = fut_transcript.result()

        if comments:
            entry["comments"] = comments
        if transcript:
            entry["transcript_preview"] = transcript["text"][:1000]
            entry["transcript_chars"] = transcript["chars"]

        print(
            f"  [{i + 1}/{top_n}] {v['title'][:60]}... "
            f"({format_number(v.get('views'))} views)",
            file=sys.stderr,
        )
        return entry

    # Videos parallel verarbeiten (max 3 gleichzeitig, Rate-Limiter schützt)
    from concurrent.futures import ThreadPoolExecutor, as_completed

    video_workers = min(3, top_n)
    with ThreadPoolExecutor(max_workers=video_workers) as pool:
        futures = {
            pool.submit(_process_video, (i, v)): i
            for i, v in enumerate(results[:top_n])
        }
        entries = [None] * top_n
        for fut in as_completed(futures):
            idx = futures[fut]
            entries[idx] = fut.result()
        report["videos"] = [e for e in entries if e is not None]

    spent = 1 + top_n * 2  # search + 2 per video (comments + transcript)

    elapsed = time.time() - t0
    report["stats"]["budget_used"] = spent
    report["stats"]["budget_total"] = budget
    report["stats"]["videos_analyzed"] = len(report["videos"])
    report["stats"]["total_comments"] = sum(
        len(v.get("comments", [])) for v in report["videos"]
    )
    report["stats"]["elapsed_seconds"] = round(elapsed, 1)

    print(
        f"\nPipeline complete: {spent}/{budget} budget, "
        f"{len(report['videos'])} videos, "
        f"{report['stats']['total_comments']} comments, "
        f"{elapsed:.1f}s",
        file=sys.stderr,
    )
    return report


# --- CLI ---


def parse_int_flag(args, flag, default):
    """Extract --flag value from args list and convert to int."""
    for i, a in enumerate(args):
        if a == flag and i + 1 < len(args):
            return int(args[i + 1])
    return default


def parse_str_flag(args, flag, default=None):
    """Extract --flag string value from args list."""
    for i, a in enumerate(args):
        if a == flag and i + 1 < len(args):
            return args[i + 1]
    return default


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        state = load_rate_state()
        remaining = 10 - state["count"]
        elapsed = time.time() - state["window_start"]
        print(
            f"\nRate: {state['count']}/10 used, {remaining} remaining ({elapsed:.0f}s in window)"
        )
        return

    cmd = sys.argv[1]
    args = sys.argv[2:]

    result = None

    if cmd == "search":
        query = args[0] if args else "MCP server"
        max_r = parse_int_flag(args, "--max", 10)
        result = cmd_search(query, max_results=max_r)

    elif cmd == "video":
        if not args:
            print("Usage: youtube-intel.py video VIDEO_ID_OR_URL", file=sys.stderr)
            return
        result = cmd_video(args[0])

    elif cmd == "transcript":
        if not args:
            print(
                "Usage: youtube-intel.py transcript VIDEO_ID_OR_URL [--lang de,en]",
                file=sys.stderr,
            )
            return
        langs = parse_str_flag(args, "--lang")
        lang_list = langs.split(",") if langs else None
        result = cmd_transcript(args[0], languages=lang_list)

    elif cmd == "comments":
        if not args:
            print(
                "Usage: youtube-intel.py comments VIDEO_ID_OR_URL [--max 20]",
                file=sys.stderr,
            )
            return
        max_c = parse_int_flag(args, "--max", 20)
        result = cmd_comments(args[0], max_comments=max_c)

    elif cmd == "channel":
        if not args:
            print(
                "Usage: youtube-intel.py channel CHANNEL_URL [--max 5]", file=sys.stderr
            )
            return
        max_v = parse_int_flag(args, "--max", 5)
        result = cmd_channel(args[0], max_videos=max_v)

    elif cmd == "pipeline":
        query = args[0] if args else "MCP server best practices"
        b = parse_int_flag(args, "--budget", 8)
        c = parse_int_flag(args, "--comments", 15)
        result = cmd_pipeline(query, budget=b, max_comments=c)

    elif cmd == "rate":
        state = load_rate_state()
        remaining = 10 - state["count"]
        print(f"Used: {state['count']}/10, Remaining: {remaining}")
        return

    elif cmd == "reset":
        RATE_FILE.unlink(missing_ok=True)
        print("Rate counter reset.")
        return

    else:
        print(f"Unknown command: {cmd}")
        print(
            "Commands: search, video, transcript, comments, channel, pipeline, rate, reset"
        )
        return

    if result is not None:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
