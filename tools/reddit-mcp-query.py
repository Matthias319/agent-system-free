#!/home/maetzger/.claude/tools/.venv/bin/python
"""Smart Reddit MCP query wrapper.

Talks to reddit-mcp-buddy via stdio JSON-RPC.
Budget-aware: tracks requests against 10/min limit.

Usage:
    python3 reddit-mcp-query.py search "claude code workflow" [--sub ClaudeAI] [--limit 10]
    python3 reddit-mcp-query.py browse ClaudeAI --sort top --time week --limit 5
    python3 reddit-mcp-query.py post POST_ID --comments 10
    python3 reddit-mcp-query.py research "query" [--subreddits sub1+sub2] [--top-posts 3] [--comments 15]
    python3 reddit-mcp-query.py pipeline "topic" --budget 8
"""

import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

MCP_CMD = ["npx", "-y", "reddit-mcp-buddy"]
RATE_FILE = Path("/tmp/reddit-mcp-rate.json")

# Hardcaps — enforced in tooling, not just prose in skill prompts
MAX_RESEARCH_TOP_POSTS = 3
MAX_RESEARCH_COMMENTS = 10
MAX_RESEARCH_LIMIT = 10


def load_rate_state():
    if RATE_FILE.exists():
        state = json.loads(RATE_FILE.read_text())
        # Reset if >60s since first request in window
        if time.time() - state.get("window_start", 0) > 60:
            return {"count": 0, "window_start": time.time()}
        return state
    return {"count": 0, "window_start": time.time()}


def save_rate_state(state):
    RATE_FILE.write_text(json.dumps(state))


def check_budget(needed=1):
    state = load_rate_state()
    remaining = 10 - state["count"]
    if remaining < needed:
        wait = 60 - (time.time() - state["window_start"])
        if wait > 0:
            print(
                f"Rate limit: {remaining} remaining, need {needed}. Wait {wait:.0f}s",
                file=sys.stderr,
            )
            return False
    return True


def _read_response(stdout, timeout=15):
    """Read a single JSON-RPC response from MCP server stdout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        ready, _, _ = select.select([stdout], [], [], 0.5)
        if ready:
            line = stdout.readline().strip()
            if line and line.startswith("{"):
                return json.loads(line)
    return None


class MCPSession:
    """Persistent MCP connection for batch operations.

    Keeps one npx process alive across multiple tool calls,
    avoiding ~1.5s startup overhead per call.
    """

    def __init__(self):
        self.proc = None
        self._next_id = 10

    def __enter__(self):
        self.proc = subprocess.Popen(
            MCP_CMD,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "NODE_NO_WARNINGS": "1"},
        )
        # Initialize handshake
        self._send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "reddit-query", "version": "2.0"},
                },
            }
        )
        init_resp = _read_response(self.proc.stdout, timeout=10)
        if not init_resp or init_resp.get("id") != 1:
            raise RuntimeError("MCP init failed")
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        time.sleep(0.2)
        return self

    def __exit__(self, *args):
        if self.proc:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def _send(self, msg):
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def call(self, name, arguments, timeout=20):
        """Call an MCP tool and return the result."""
        self._next_id += 1
        msg_id = self._next_id
        self._send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        resp = _read_response(self.proc.stdout, timeout=timeout)
        if resp and resp.get("id") == msg_id and "result" in resp:
            return resp["result"]
        if resp and "error" in resp:
            print(f"MCP Error: {resp['error']}", file=sys.stderr)
        return None


def mcp_call(method, params):
    """Send a JSON-RPC call to the MCP server via Popen."""
    state = load_rate_state()

    proc = subprocess.Popen(
        MCP_CMD,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "NODE_NO_WARNINGS": "1"},
    )

    def send(msg):
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()

    try:
        # 1. Initialize
        send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "reddit-query", "version": "1.0"},
                },
            }
        )
        init_resp = _read_response(proc.stdout, timeout=10)
        if not init_resp or init_resp.get("id") != 1:
            print("MCP init failed", file=sys.stderr)
            return None

        # 2. Initialized notification
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        time.sleep(0.2)

        # 3. Actual tool call
        send({"jsonrpc": "2.0", "id": 2, "method": method, "params": params})
        resp = _read_response(proc.stdout, timeout=20)

        if resp and resp.get("id") == 2:
            state["count"] += 1
            save_rate_state(state)
            if "result" in resp:
                return resp["result"]
            if "error" in resp:
                print(f"MCP Error: {resp['error']}", file=sys.stderr)
                return None

        print(f"No tool response (got: {resp})", file=sys.stderr)
        return None

    except Exception as e:
        print(f"MCP call failed: {e}", file=sys.stderr)
        return None
    finally:
        if proc.stdin is not None:
            proc.stdin.close()
        proc.terminate()
        proc.wait(timeout=5)


def search_reddit(
    query, subreddit=None, sort="relevance", time_filter="month", limit=10
):
    """Search Reddit for posts matching a query."""
    params = {
        "name": "search_reddit",
        "arguments": {
            "query": query,
            "sort": sort,
            "time": time_filter,
            "limit": limit,
        },
    }
    if subreddit:
        # MCP expects "subreddits" (plural) as array
        params["arguments"]["subreddits"] = [
            s.strip() for s in subreddit.replace("+", ",").split(",") if s.strip()
        ]
    return mcp_call("tools/call", params)


def browse_subreddit(subreddit, sort="hot", time_filter="week", limit=10):
    """Browse a subreddit's posts."""
    params = {
        "name": "browse_subreddit",
        "arguments": {
            "subreddit": subreddit,
            "sort": sort,
            "limit": limit,
        },
    }
    if sort == "top" and time_filter:
        params["arguments"]["time"] = time_filter
    return mcp_call("tools/call", params)


def get_post_details(post_id=None, url=None, comments_limit=10):
    """Get post details including top comments."""
    args = {"comments_limit": comments_limit}
    if url:
        args["url"] = url
    elif post_id:
        args["post_id"] = post_id
    else:
        raise ValueError("Need post_id or url")

    return mcp_call("tools/call", {"name": "get_post_details", "arguments": args})


def extract_text(result):
    """Extract text content from MCP result."""
    if not result:
        return ""
    if isinstance(result, dict) and "content" in result:
        parts = []
        for item in result["content"]:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item["text"])
        return "\n".join(parts)
    return json.dumps(result, indent=2)


def cmd_search(args):
    query = args[0] if args else "claude code"
    subreddit = None
    limit = 10
    sort = "relevance"
    time_filter = "month"
    for i, a in enumerate(args):
        if a in ("--sub", "--subreddits") and i + 1 < len(args):
            subreddit = args[i + 1]
        if a == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
        if a == "--sort" and i + 1 < len(args):
            sort = args[i + 1]
        if a == "--time" and i + 1 < len(args):
            time_filter = args[i + 1]

    if not check_budget(1):
        return
    result = search_reddit(
        query, subreddit=subreddit, sort=sort, time_filter=time_filter, limit=limit
    )
    print(extract_text(result))


def cmd_browse(args):
    subreddit = args[0] if args else "ClaudeAI"
    sort = "top"
    time_filter = "week"
    limit = 5
    for i, a in enumerate(args):
        if a == "--sort" and i + 1 < len(args):
            sort = args[i + 1]
        if a == "--time" and i + 1 < len(args):
            time_filter = args[i + 1]
        if a == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])

    if not check_budget(1):
        return
    result = browse_subreddit(
        subreddit, sort=sort, time_filter=time_filter, limit=limit
    )
    print(extract_text(result))


def cmd_post(args):
    post_id = args[0] if args else None
    comments = 10
    for i, a in enumerate(args):
        if a == "--comments" and i + 1 < len(args):
            comments = int(args[i + 1])
        if a == "--url" and i + 1 < len(args):
            post_id = None  # use url mode

    if not check_budget(1):
        return
    if post_id and post_id.startswith("http"):
        result = get_post_details(url=post_id, comments_limit=comments)
    else:
        result = get_post_details(post_id=post_id, comments_limit=comments)
    print(extract_text(result))


def cmd_pipeline(args):
    """Smart pipeline: discover → rank → deep-dive."""
    topic = args[0] if args else "claude code tips"
    budget = 8
    for i, a in enumerate(args):
        if a == "--budget" and i + 1 < len(args):
            budget = int(args[i + 1])

    print(f"Pipeline: '{topic}' (Budget: {budget} requests)", file=sys.stderr)

    # Phase 1: Search (1 request)
    print("Phase 1: Searching...", file=sys.stderr)
    search_result = search_reddit(
        topic, sort="relevance", time_filter="month", limit=10
    )
    search_text = extract_text(search_result)
    print(search_text)

    print(f"\n{'=' * 60}", file=sys.stderr)
    print(f"Remaining budget: {budget - 1} requests", file=sys.stderr)
    print("Paste post IDs to deep-dive, or 'done' to finish.", file=sys.stderr)


def cmd_research(args):
    """Combined search + top-post deep-dive in one MCP session.

    Single tool call replaces: search → (post × N) = N+1 calls.
    Keeps one npx process alive, auto-selects top posts by score.
    """
    query = args[0] if args else ""
    subreddits = None
    limit = MAX_RESEARCH_LIMIT
    top_posts = MAX_RESEARCH_TOP_POSTS
    comments_limit = MAX_RESEARCH_COMMENTS
    sort = "relevance"
    time_filter = "month"

    for i, a in enumerate(args):
        if a in ("--subreddits", "--sub") and i + 1 < len(args):
            subreddits = args[i + 1]
        if a == "--limit" and i + 1 < len(args):
            limit = min(int(args[i + 1]), MAX_RESEARCH_LIMIT)
        if a == "--top-posts" and i + 1 < len(args):
            top_posts = min(int(args[i + 1]), MAX_RESEARCH_TOP_POSTS)
        if a == "--comments" and i + 1 < len(args):
            comments_limit = min(int(args[i + 1]), MAX_RESEARCH_COMMENTS)
        if a == "--sort" and i + 1 < len(args):
            sort = args[i + 1]
        if a == "--time" and i + 1 < len(args):
            time_filter = args[i + 1]

    needed = 1 + top_posts
    if not check_budget(needed):
        return

    t0 = time.time()
    print(
        f"Research: '{query}' (top {top_posts} posts, {comments_limit} comments each)",
        file=sys.stderr,
    )

    try:
        with MCPSession() as session:
            # Step 1: Search
            search_args = {
                "query": query,
                "sort": sort,
                "time": time_filter,
                "limit": limit,
            }
            if subreddits:
                # MCP expects "subreddits" (plural) as array
                search_args["subreddits"] = [
                    s.strip()
                    for s in subreddits.replace("+", ",").split(",")
                    if s.strip()
                ]

            search_result = session.call("search_reddit", search_args)
            search_text = extract_text(search_result)

            # Parse structured results
            try:
                search_data = json.loads(search_text)
                posts = search_data.get("results", [])
            except (json.JSONDecodeError, TypeError):
                posts = []
                print("Could not parse search results", file=sys.stderr)

            if not posts:
                print("No posts found.", file=sys.stderr)
                elapsed = time.time() - t0
                print(
                    json.dumps(
                        {
                            "query": query,
                            "search_results": 0,
                            "posts": [],
                            "elapsed_seconds": round(elapsed, 1),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return

            # Step 2: Select top posts by score
            posts.sort(key=lambda p: p.get("score", 0), reverse=True)
            selected = posts[:top_posts]
            print(
                f"Found {len(posts)} posts, analyzing top {len(selected)}...",
                file=sys.stderr,
            )

            # Step 3: Fetch details for each selected post
            detailed = []
            for j, post in enumerate(selected):
                url = post.get("permalink") or post.get("url", "")
                if not url or not url.startswith("http"):
                    url = f"https://reddit.com{post.get('permalink', '')}"

                print(
                    f"  [{j + 1}/{len(selected)}] {post.get('title', '')[:60]}... "
                    f"(score: {post.get('score', 0)})",
                    file=sys.stderr,
                )
                detail_result = session.call(
                    "get_post_details",
                    {"url": url, "comments_limit": comments_limit},
                )
                detail_text = extract_text(detail_result)
                detailed.append(
                    {
                        "title": post.get("title", ""),
                        "score": post.get("score", 0),
                        "subreddit": post.get("subreddit", ""),
                        "url": url,
                        "num_comments": post.get("num_comments", 0),
                        "content": post.get("content", ""),
                        "comments": detail_text,
                    }
                )

        # Update rate state
        state = load_rate_state()
        state["count"] += needed
        save_rate_state(state)

        elapsed = time.time() - t0
        output = {
            "query": query,
            "subreddits": subreddits,
            "search_results": len(posts),
            "posts_analyzed": len(detailed),
            "elapsed_seconds": round(elapsed, 1),
            "posts": detailed,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        print(f"Research complete in {elapsed:.1f}s", file=sys.stderr)

    except Exception as e:
        print(f"Research failed: {e}", file=sys.stderr)
        elapsed = time.time() - t0
        print(
            json.dumps(
                {"query": query, "error": str(e), "elapsed_seconds": round(elapsed, 1)},
                ensure_ascii=False,
                indent=2,
            )
        )


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

    if cmd == "search":
        cmd_search(args)
    elif cmd == "browse":
        cmd_browse(args)
    elif cmd == "post":
        cmd_post(args)
    elif cmd == "pipeline":
        cmd_pipeline(args)
    elif cmd == "research":
        cmd_research(args)
    elif cmd == "rate":
        state = load_rate_state()
        remaining = 10 - state["count"]
        print(f"Used: {state['count']}/10, Remaining: {remaining}")
    elif cmd == "reset":
        RATE_FILE.unlink(missing_ok=True)
        print("Rate counter reset.")
    else:
        print(f"Unknown command: {cmd}")
        print("Commands: search, browse, post, research, pipeline, rate, reset")


if __name__ == "__main__":
    main()
