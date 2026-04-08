#!/home/maetzger/.claude/tools/.venv/bin/python
"""Reddit Digest — fetcht Top-Posts aus relevanten Subreddits für den Nachtschicht-Agent.

Wird als Pre-Step in auto-agent.sh ausgeführt (VOR dem Agent, damit Daten lokal vorliegen).
Output: /tmp/reddit-digest.json

Subreddits:
  - r/ClaudeCode (primär): Claude Code Workflows, Skills, Hooks, MCP
  - r/ChatGPTCoding (sekundär): AI-Coding-Agents allgemein

Rate-Budget: 5 von 10 Requests/Minute (browse x2 + post-details x3)
"""

import json
import subprocess
import sys
import time
from pathlib import Path

TOOL = Path(__file__).parent / "reddit-mcp-query.py"
OUTPUT = Path("/tmp/reddit-digest.json")

SUBREDDITS = [
    {"name": "ClaudeCode", "limit": 3, "fetch_details": True},
    {"name": "ChatGPTCoding", "limit": 3, "fetch_details": False},
]


def run_reddit_cmd(*args: str, timeout: int = 30) -> str:
    """Run reddit-mcp-query.py and return stdout."""
    cmd = ["python3", str(TOOL), *args]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            print(
                f"  WARN: {' '.join(args[:2])}: {result.stderr.strip()}",
                file=sys.stderr,
            )
            return ""
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        print(f"  WARN: Timeout bei {' '.join(args[:2])}", file=sys.stderr)
        return ""
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        return ""


def parse_browse_posts(text: str) -> list[dict]:
    """Parse browse output (JSON) into structured post list."""
    if not text:
        return []
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "posts" in data:
            return data["posts"]
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _fetch_subreddit(sub: dict) -> tuple[str, dict]:
    """Ein Subreddit komplett verarbeiten (browse + details). Thread-safe."""
    name = sub["name"]
    limit = sub["limit"]
    print(f"  Browse r/{name} (top/day, limit {limit})...", file=sys.stderr)

    browse_text = run_reddit_cmd(
        "browse", name, "--sort", "top", "--time", "day", "--limit", str(limit)
    )

    posts = parse_browse_posts(browse_text)
    print(f"    → {len(posts)} Posts gefunden", file=sys.stderr)

    # Optionally fetch details (comments) for top posts
    if sub.get("fetch_details") and posts:
        for i, post in enumerate(posts[:3]):
            post_url = post.get("url", "")
            post_id = post.get("id", "")
            if not post_url and not post_id:
                continue

            print(
                f"    Details für Post {i + 1}: {post.get('title', '?')[:50]}...",
                file=sys.stderr,
            )
            time.sleep(1)  # Rate-Limit-Schonung

            permalink = post.get("permalink", "")
            if permalink:
                url = (
                    permalink
                    if permalink.startswith("http")
                    else f"https://reddit.com{permalink}"
                )
                detail_text = run_reddit_cmd("post", url, "--comments", "5")
            elif post_id:
                detail_text = run_reddit_cmd("post", post_id, "--comments", "5")
            else:
                detail_text = ""

            if detail_text:
                try:
                    post["detail"] = json.loads(detail_text)
                except (json.JSONDecodeError, TypeError):
                    post["detail"] = detail_text
            else:
                post["detail"] = None

    return name, {"posts": posts, "raw": browse_text if not posts else None}


def main():
    print("=== Reddit Digest Start ===", file=sys.stderr)
    digest = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "subreddits": {},
    }

    # Subreddits parallel fetchen (jedes Subreddit = eigener Thread)
    if len(SUBREDDITS) > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=len(SUBREDDITS)) as pool:
            futures = {pool.submit(_fetch_subreddit, sub): sub for sub in SUBREDDITS}
            for fut in as_completed(futures):
                name, result = fut.result()
                digest["subreddits"][name] = result
    else:
        for sub in SUBREDDITS:
            name, result = _fetch_subreddit(sub)
            digest["subreddits"][name] = result

    # Save
    OUTPUT.write_text(json.dumps(digest, indent=2, ensure_ascii=False))
    post_count = sum(len(s["posts"]) for s in digest["subreddits"].values())
    print(f"  → {post_count} Posts gespeichert nach {OUTPUT}", file=sys.stderr)
    print("=== Reddit Digest Done ===", file=sys.stderr)


if __name__ == "__main__":
    main()
