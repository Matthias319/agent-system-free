#!/home/maetzger/.claude/tools/.venv/bin/python
"""Social Research Runner — parallel YouTube + Reddit evidence gathering.

Replaces 4-6 sequential LLM turns with 1 tool call:
  YouTube search + enrichment extraction + Reddit research (parallel)

Usage:
    social-research-runner.py tech "MCP best practices" [--subreddits sub1+sub2]
    social-research-runner.py urban "restaurants frankfurt" [--subreddits germany+travel]
    social-research-runner.py auto "query here"

Output: JSON evidence pack ready for LLM synthesis (1 turn).
"""

import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path.home() / ".claude" / ".env", override=True)

TOOLS_DIR = Path(__file__).parent
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Hardcaps (match youtube-intel.py and reddit-mcp-query.py constants)
MAX_YT_RESULTS = 8
MAX_YT_TRANSCRIPTS = 2
MAX_REDDIT_TOP_POSTS = 3
MAX_REDDIT_COMMENTS = 10

# Subreddit defaults per mode
SUBREDDITS = {
    "tech": "programming+webdev+ExperiencedDevs+MachineLearning+LocalLLaMA+selfhosted+sysadmin",
    "urban": "travel+solotravel+germany+europe+AskCulinary+frankfurt+berlin+de+kochen",
}

# Keywords for auto-routing
TECH_KEYWORDS = {
    "programming",
    "code",
    "developer",
    "framework",
    "library",
    "api",
    "tool",
    "ide",
    "ai",
    "llm",
    "model",
    "benchmark",
    "self-hosted",
    "open source",
    "vs",
    "alternative",
    "mcp",
    "agent",
    "tutorial",
    "charger",
    "usb",
    "server",
    "linux",
    "docker",
    "kubernetes",
    "gpu",
    "cpu",
    "ram",
}
URBAN_KEYWORDS = {
    "restaurant",
    "café",
    "bar",
    "club",
    "geheimtipp",
    "hidden gem",
    "reise",
    "urlaub",
    "aktivität",
    "food",
    "nightlife",
    "date",
}


def run_tool(cmd, timeout=60):
    """Run a tool and return stdout as string."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(TOOLS_DIR),
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return ""
    except Exception as e:
        print(f"Tool error: {e}", file=sys.stderr)
        return ""


def route_mode(query):
    """Auto-detect tech vs urban mode from query keywords."""
    words = set(query.lower().split())
    tech_score = len(words & TECH_KEYWORDS)
    urban_score = len(words & URBAN_KEYWORDS)
    return "urban" if urban_score > tech_score else "tech"


def youtube_search(query):
    """Run YouTube search and return results."""
    raw = run_tool(
        [
            str(TOOLS_DIR / "youtube-intel.py"),
            "search",
            query,
            "--max",
            str(MAX_YT_RESULTS),
        ],
        timeout=60,
    )
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def extract_enrichment_terms(videos, original_query):
    """Extract enrichment terms via Groq GPT-OSS 120B (fast LLM, ~300ms).

    Returns dict: {"entity_terms": [...], "reviewer_terms": [...]}.
    Falls back to simple regex extraction if Groq is unavailable.
    """
    if not videos:
        return {"entity_terms": [], "reviewer_terms": []}

    # Try Groq GPT-OSS 120B first (full video metadata for context depth)
    if GROQ_API_KEY:
        try:
            enrichment = _groq_enrichment(videos[:8], original_query)
            if enrichment.get("entity_terms") or enrichment.get("reviewer_terms"):
                return enrichment
        except Exception as e:
            print(
                f"Groq enrichment failed ({e}), falling back to regex", file=sys.stderr
            )

    # Fallback: simple regex on titles only (all as entity terms)
    titles = [v.get("title", "") for v in videos[:8] if v.get("title")]
    return {
        "entity_terms": _regex_enrichment(titles, original_query),
        "reviewer_terms": [],
    }


def _groq_enrichment(videos, original_query):
    """Extract entity terms + reviewer terms via Groq API (~300ms).

    Returns dict: {"entity_terms": [...], "reviewer_terms": [...]}.
    Only entity_terms are used for Reddit enrichment (channel names lower recall).
    """
    example_in = (
        'Query: "best GaN charger 200W for laptop"\n'
        "Videos:\n"
        "1. [MobileReviewsEh] Anker Prime 250W Review — The new Anker Prime 250W 6-Port is here...\n"
        "2. [TechTablets] UGREEN Nexode 140W vs Anker — Comparing the UGREEN Nexode 140W GaN..."
    )
    example_out = '{"entity_terms": ["Anker Prime 250W", "UGREEN Nexode 140W", "6-Port GaN"], "reviewer_terms": ["MobileReviewsEh", "TechTablets"]}'

    # Build rich context from video metadata
    video_lines = []
    for i, v in enumerate(videos, 1):
        title = v.get("title", "")
        channel = v.get("channel", "")
        desc = v.get("description", "")[:200]
        views = v.get("views", 0)
        line = f"{i}. [{channel}] {title}"
        if desc:
            line += f" — {desc}"
        if views:
            line += f" ({views:,} views)"
        video_lines.append(line)

    prompt = (
        f'Query: "{original_query}"\n\n'
        "Extract terms from these YouTube videos into two categories:\n"
        "- entity_terms: brand names, full product names (with model/wattage), "
        "key technical terms that would make a Reddit search more specific\n"
        "- reviewer_terms: YouTube channel names of known reviewers\n\n"
        "Return JSON: "
        '{{"entity_terms": ["product1", "tech term"], "reviewer_terms": ["channel1"]}}\n\n'
        "Videos:\n" + "\n".join(video_lines)
    )
    resp = httpx.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        json={
            "model": GROQ_MODEL,
            "messages": [
                {"role": "user", "content": example_in},
                {"role": "assistant", "content": example_out},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "max_tokens": 8000,
            "response_format": {"type": "json_object"},
        },
        timeout=10.0,
    )
    data = resp.json()
    if "error" in data:
        raise RuntimeError(data["error"].get("message", str(data["error"])))
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not content:
        return {"entity_terms": [], "reviewer_terms": []}
    parsed = json.loads(content)

    def _extract_strings(raw):
        terms = []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str) and len(item) > 2:
                    terms.append(item)
                elif isinstance(item, dict):
                    for v in item.values():
                        if isinstance(v, str) and v and len(v) > 2:
                            terms.append(v)
        return terms

    # Parse structured response, fallback to flat "terms" key
    if isinstance(parsed, dict) and "entity_terms" in parsed:
        entity = _extract_strings(parsed["entity_terms"])
        reviewer = _extract_strings(parsed.get("reviewer_terms", []))
    elif isinstance(parsed, dict) and "terms" in parsed:
        # Fallback: all terms as entity, no reviewer separation
        entity = _extract_strings(parsed["terms"])
        reviewer = []
    else:
        entity = _extract_strings(parsed if isinstance(parsed, list) else [])
        reviewer = []

    # Deduplicate each list
    def _dedup(lst):
        seen = set()
        out = []
        for t in lst:
            if t.lower() not in seen:
                seen.add(t.lower())
                out.append(t)
        return out

    entity = _dedup(entity)[:8]
    reviewer = _dedup(reviewer)[:4]
    print(
        f"  Groq enrichment: {len(entity)} entity terms {entity}, "
        f"{len(reviewer)} reviewer terms {reviewer}",
        file=sys.stderr,
    )
    return {"entity_terms": entity, "reviewer_terms": reviewer}


def _regex_enrichment(titles, original_query):
    """Fallback: extract terms by word frequency across titles."""
    query_words = set(original_query.lower().split())
    term_freq = {}
    stopwords = {
        "the",
        "and",
        "for",
        "with",
        "this",
        "that",
        "from",
        "have",
        "best",
        "new",
        "just",
        "like",
        "video",
        "watch",
        "review",
        "guide",
        "2025",
        "2026",
        "subscribe",
        "channel",
        "compared",
    }
    for title in titles:
        words = re.findall(r"\b[a-zA-Z][a-zA-Z0-9-]{2,}\b", title.lower())
        for w in words:
            if w in query_words or w in stopwords or len(w) < 4:
                continue
            term_freq[w] = term_freq.get(w, 0) + 1
    enriched = sorted(
        [(t, c) for t, c in term_freq.items() if c >= 2],
        key=lambda x: -x[1],
    )
    return [t for t, _ in enriched[:5]]


def youtube_deep_dive(videos):
    """Get transcripts + comments for top qualifying videos (all parallel)."""
    qualifying = [
        v
        for v in videos
        if v.get("views", 0)
        and v["views"] > 20000
        and not any(
            kw in v.get("title", "").lower()
            for kw in ["reaction", "vlog", "shorts", "unboxing"]
        )
    ][:4]  # Top 4 videos for deep-dive

    if not qualifying:
        return [], []

    transcripts = []
    comments = []

    def _get_transcript(v):
        raw = run_tool(
            [
                str(TOOLS_DIR / "youtube-intel.py"),
                "transcript",
                v["id"],
                "--lang",
                "en,de",
            ],
            timeout=30,
        )
        if raw:
            try:
                data = json.loads(raw)
                return {
                    "video_id": v["id"],
                    "title": v.get("title", ""),
                    "channel": v.get("channel", ""),
                    "views": v.get("views"),
                    "text_preview": data.get("text", "")[:3000],
                }
            except json.JSONDecodeError:
                pass
        return None

    def _get_comments(v):
        raw = run_tool(
            [
                str(TOOLS_DIR / "youtube-intel.py"),
                "comments",
                v["id"],
                "--max",
                "15",
            ],
            timeout=30,
        )
        if raw:
            try:
                data = json.loads(raw)
                if isinstance(data, list):
                    return {
                        "video_id": v["id"],
                        "title": v.get("title", ""),
                        "channel": v.get("channel", ""),
                        "comments": [
                            {
                                "text": c.get("text", "")[:500],
                                "likes": c.get("likes", 0),
                                "author": c.get("author", ""),
                            }
                            for c in data[:15]
                        ],
                    }
            except json.JSONDecodeError:
                pass
        return None

    # Run ALL transcript + comment fetches in parallel
    with ThreadPoolExecutor(max_workers=8) as pool:
        transcript_futures = {
            pool.submit(_get_transcript, v): ("transcript", v) for v in qualifying[:2]
        }
        comment_futures = {
            pool.submit(_get_comments, v): ("comment", v) for v in qualifying
        }

        all_futures = {**transcript_futures, **comment_futures}
        for fut in as_completed(all_futures):
            ftype, _ = all_futures[fut]
            result = fut.result()
            if result:
                if ftype == "transcript":
                    transcripts.append(result)
                else:
                    comments.append(result)

    return transcripts, comments


def reddit_research(query, subreddits):
    """Run Reddit research with enriched query."""
    raw = run_tool(
        [
            str(TOOLS_DIR / "reddit-mcp-query.py"),
            "research",
            query,
            "--subreddits",
            subreddits,
            "--top-posts",
            str(MAX_REDDIT_TOP_POSTS),
            "--comments",
            str(MAX_REDDIT_COMMENTS),
        ],
        timeout=60,
    )
    if not raw:
        return {"posts": [], "error": "no output"}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"posts": [], "raw": raw[:500]}


def run_research(mode, query, subreddits=None):
    """Main research pipeline — parallel YouTube + Reddit."""
    t0 = time.time()

    if subreddits is None:
        subreddits = SUBREDDITS.get(mode, SUBREDDITS["tech"])

    evidence = {
        "query": query,
        "mode": mode,
        "youtube": {
            "videos": [],
            "enrichment_terms": [],
            "transcripts": [],
            "comments": [],
        },
        "reddit": {"posts": []},
        "meta": {},
    }

    # Phase 1: YouTube search (must complete before Reddit for enrichment)
    print(f"[1/3] YouTube search: '{query}'", file=sys.stderr)
    videos = youtube_search(query)
    evidence["youtube"]["videos"] = videos
    yt_search_time = time.time() - t0

    # Phase 2: Extract enrichment terms via Groq (entity vs reviewer split)
    enrichment = extract_enrichment_terms(videos, query)
    entity_terms = enrichment.get("entity_terms", [])
    reviewer_terms = enrichment.get("reviewer_terms", [])
    evidence["youtube"]["enrichment_terms"] = entity_terms
    evidence["youtube"]["reviewer_terms"] = reviewer_terms
    # Only entity_terms for Reddit query — channel names lower recall
    enriched_query = f"{query} {' '.join(entity_terms[:3])}" if entity_terms else query

    # Phase 3: Parallel — Reddit + YouTube deep-dive (transcripts + comments)
    print(
        f"[2/3] Parallel: Reddit ({enriched_query[:50]}) + YouTube deep-dive",
        file=sys.stderr,
    )
    t_parallel = time.time()

    with ThreadPoolExecutor(max_workers=3) as pool:
        fut_reddit = pool.submit(reddit_research, enriched_query, subreddits)
        fut_yt_deep = pool.submit(youtube_deep_dive, videos)

        reddit_data = fut_reddit.result()
        yt_transcripts, yt_comments = fut_yt_deep.result()

    evidence["reddit"] = reddit_data
    evidence["youtube"]["transcripts"] = yt_transcripts
    evidence["youtube"]["comments"] = yt_comments
    parallel_time = time.time() - t_parallel

    # Meta
    elapsed = time.time() - t0
    evidence["meta"] = {
        "elapsed_seconds": round(elapsed, 1),
        "yt_search_seconds": round(yt_search_time, 1),
        "parallel_seconds": round(parallel_time, 1),
        "yt_videos": len(videos),
        "yt_transcripts": len(yt_transcripts),
        "yt_comments": len(yt_comments),
        "reddit_posts": len(reddit_data.get("posts", [])),
        "enrichment_terms": enrichment,
        "usable_sources": len(videos) + len(reddit_data.get("posts", [])),
    }

    print(
        f"[3/3] Done in {elapsed:.1f}s "
        f"(yt_search={yt_search_time:.1f}s, parallel={parallel_time:.1f}s, "
        f"videos={len(videos)}, transcripts={len(yt_transcripts)}, "
        f"yt_comments={len(yt_comments)}, "
        f"reddit_posts={len(reddit_data.get('posts', []))})",
        file=sys.stderr,
    )

    return evidence


def analyze_gaps(evidence, original_query):
    """Use GPT-OSS 20B to identify gaps and generate follow-up queries (~300ms)."""
    if not GROQ_API_KEY:
        return []

    # Compact summary of what we found
    found_items = []
    for v in evidence.get("youtube", {}).get("videos", []):
        found_items.append(f"YT: {v.get('title', '')[:60]}")
    for p in evidence.get("reddit", {}).get("posts", []):
        found_items.append(f"Reddit: {p.get('title', '')[:60]}")

    # Top YouTube comments by likes — real-world data points for gap detection
    top_comments = []
    for vc in evidence.get("youtube", {}).get("comments", []):
        for c in vc.get("comments", []):
            top_comments.append(c)
    top_comments.sort(key=lambda c: c.get("likes", 0), reverse=True)
    comment_snippets = []
    for c in top_comments[:3]:
        text = c.get("text", "")[:500]
        likes = c.get("likes", 0)
        comment_snippets.append(f"YT comment ({likes} likes): {text}")

    example_gap_in = (
        'Query: "best espresso machine under 500 EUR"\n'
        "Evidence: YT: Top 5 Espresso Machines 2026, Reddit: r/espresso — DeLonghi vs Breville\n"
        "What gaps remain? Generate follow-up queries."
    )
    example_gap_out = json.dumps(
        {
            "gaps": ["No price comparison data", "Missing long-term durability info"],
            "follow_up_queries": [
                "DeLonghi Dedica vs Breville Bambino price comparison 2026",
                "espresso machine reliability long term review reddit",
            ],
        }
    )

    comment_section = ""
    if comment_snippets:
        comment_section = (
            "\n\nTop YouTube comments (real-world data points):\n"
            + "\n".join(f"- {s}" for s in comment_snippets)
        )

    prompt = (
        f'Research query: "{original_query}"\n\n'
        f"Evidence collected so far:\n"
        + "\n".join(f"- {i}" for i in found_items)
        + comment_section
        + "\n\n"
        "Identify 2-3 specific gaps and for EACH gap write a concrete YouTube/Reddit "
        "search query that would fill it. Queries must be specific enough to find results.\n"
        'Return JSON: {"gaps": ["gap1"], "follow_up_queries": ["query1"]}'
    )

    try:
        resp = httpx.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "user", "content": example_gap_in},
                    {"role": "assistant", "content": example_gap_out},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.4,
                "max_tokens": 8000,
                "reasoning_effort": "medium",
                "response_format": {"type": "json_object"},
            },
            timeout=10.0,
        )
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if content:
            parsed = json.loads(content)
            queries = parsed.get("follow_up_queries", [])
            gaps = parsed.get("gaps", [])
            # If model found gaps but no queries, derive queries from gaps
            if gaps and not queries:
                queries = [f"{original_query} {gap[:40]}" for gap in gaps[:3]]
            print(
                f"  Gap analysis: {len(gaps)} gaps → {len(queries)} follow-up queries",
                file=sys.stderr,
            )
            if queries:
                for q in queries[:3]:
                    print(f"    → {q[:70]}", file=sys.stderr)
            return queries[:3]
    except Exception as e:
        import traceback

        print(f"  Gap analysis failed: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)

    return []


def run_multi_round(mode, query, subreddits=None, rounds=3):
    """Multi-round research: each round builds on gaps from the previous."""
    t0 = time.time()

    if subreddits is None:
        subreddits = SUBREDDITS.get(mode, SUBREDDITS["tech"])

    all_evidence = {
        "query": query,
        "mode": mode,
        "rounds": [],
        "youtube": {"videos": [], "enrichment_terms": [], "transcripts": []},
        "reddit": {"posts": []},
        "meta": {},
    }

    current_query = query
    seen_video_ids = set()
    seen_post_titles = set()

    for rnd in range(1, rounds + 1):
        print(f"\n{'=' * 50}", file=sys.stderr)
        print(f"ROUND {rnd}/{rounds}: '{current_query[:60]}'", file=sys.stderr)
        print(f"{'=' * 50}", file=sys.stderr)

        # Reset rate limits between rounds
        evidence = run_research(mode, current_query, subreddits)

        # Deduplicate: only add new content
        round_info = {
            "round": rnd,
            "query": current_query,
            "new_videos": 0,
            "new_posts": 0,
        }

        for v in evidence.get("youtube", {}).get("videos", []):
            vid = v.get("id", "")
            if vid and vid not in seen_video_ids:
                seen_video_ids.add(vid)
                all_evidence["youtube"]["videos"].append(v)
                round_info["new_videos"] += 1

        for p in evidence.get("reddit", {}).get("posts", []):
            title = p.get("title", "")
            if title and title not in seen_post_titles:
                seen_post_titles.add(title)
                all_evidence["reddit"]["posts"].append(p)
                round_info["new_posts"] += 1

        # Merge enrichment terms
        for term in evidence.get("youtube", {}).get("enrichment_terms", []):
            if term not in all_evidence["youtube"]["enrichment_terms"]:
                all_evidence["youtube"]["enrichment_terms"].append(term)

        # Merge transcripts + comments
        all_evidence["youtube"]["transcripts"].extend(
            evidence.get("youtube", {}).get("transcripts", [])
        )
        all_evidence["youtube"].setdefault("comments", []).extend(
            evidence.get("youtube", {}).get("comments", [])
        )

        all_evidence["rounds"].append(round_info)
        print(
            f"  Round {rnd} result: +{round_info['new_videos']} videos, +{round_info['new_posts']} posts",
            file=sys.stderr,
        )

        # After each round (except last): analyze gaps and run top-2 follow-ups parallel
        if rnd < rounds:
            follow_ups = analyze_gaps(all_evidence, query)
            if not follow_ups:
                print("  No gaps found, stopping early.", file=sys.stderr)
                break

            # Run up to 2 follow-up queries in parallel, deduplicate into all_evidence
            queries_to_run = follow_ups[:2]
            print(
                f"  Running {len(queries_to_run)} follow-up queries in parallel",
                file=sys.stderr,
            )

            with ThreadPoolExecutor(max_workers=2) as pool:
                futs = {
                    pool.submit(run_research, mode, q, subreddits): q
                    for q in queries_to_run
                }
                for fut in as_completed(futs):
                    fq = futs[fut]
                    try:
                        fe = fut.result()
                    except Exception as e:
                        print(f"  Follow-up '{fq[:40]}' failed: {e}", file=sys.stderr)
                        continue

                    new_v = new_p = 0
                    for v in fe.get("youtube", {}).get("videos", []):
                        vid = v.get("id", "")
                        if vid and vid not in seen_video_ids:
                            seen_video_ids.add(vid)
                            all_evidence["youtube"]["videos"].append(v)
                            new_v += 1
                    for p in fe.get("reddit", {}).get("posts", []):
                        title = p.get("title", "")
                        if title and title not in seen_post_titles:
                            seen_post_titles.add(title)
                            all_evidence["reddit"]["posts"].append(p)
                            new_p += 1
                    for term in fe.get("youtube", {}).get("enrichment_terms", []):
                        if term not in all_evidence["youtube"]["enrichment_terms"]:
                            all_evidence["youtube"]["enrichment_terms"].append(term)
                    all_evidence["youtube"]["transcripts"].extend(
                        fe.get("youtube", {}).get("transcripts", [])
                    )
                    all_evidence["youtube"].setdefault("comments", []).extend(
                        fe.get("youtube", {}).get("comments", [])
                    )
                    print(
                        f"  Follow-up '{fq[:40]}': +{new_v} videos, +{new_p} posts",
                        file=sys.stderr,
                    )

            # Use first follow-up as basis for next round's gap analysis context
            current_query = follow_ups[0]

    elapsed = time.time() - t0
    all_evidence["meta"] = {
        "elapsed_seconds": round(elapsed, 1),
        "total_rounds": len(all_evidence["rounds"]),
        "yt_videos": len(all_evidence["youtube"]["videos"]),
        "yt_transcripts": len(all_evidence["youtube"]["transcripts"]),
        "reddit_posts": len(all_evidence["reddit"]["posts"]),
        "enrichment_terms": all_evidence["youtube"]["enrichment_terms"][:10],
        "usable_sources": len(all_evidence["youtube"]["videos"])
        + len(all_evidence["reddit"]["posts"]),
    }

    print(
        f"\nMulti-round complete: {elapsed:.1f}s, "
        f"{len(all_evidence['rounds'])} rounds, "
        f"{all_evidence['meta']['yt_videos']} videos, "
        f"{all_evidence['meta']['reddit_posts']} reddit posts",
        file=sys.stderr,
    )

    return all_evidence


def synthesize(evidence):
    """Synthesize evidence pack into structured report via Groq GPT-OSS 120B."""
    if not GROQ_API_KEY:
        return {"error": "No GROQ_API_KEY set"}

    t0 = time.time()
    query = evidence.get("query", "")
    meta = evidence.get("meta", {})

    # Build FULL evidence context — GPT-OSS 120B has 131K context, use it
    yt_section = ""
    for v in evidence.get("youtube", {}).get("videos", []):
        yt_section += f"- [{v.get('channel', '')}] {v.get('title', '')} ({v.get('views', 0):,} views)\n"
        if v.get("description"):
            yt_section += f"  Description: {v['description']}\n"

    for t in evidence.get("youtube", {}).get("transcripts", []):
        yt_section += (
            f"\n### Transcript: {t.get('title', '')} (@{t.get('channel', '')})\n"
            f"{t.get('text_preview', '')}\n"
        )

    # YouTube Comments (the golden nuggets — user benchmarks, corrections, alternatives)
    yt_comments_section = ""
    for vc in evidence.get("youtube", {}).get("comments", []):
        yt_comments_section += (
            f"\n### Comments on: {vc.get('title', '')} (@{vc.get('channel', '')})\n"
        )
        for c in vc.get("comments", []):
            likes = c.get("likes", 0)
            like_str = f" [{likes} likes]" if likes else ""
            yt_comments_section += (
                f"- {c.get('author', '')}{like_str}: {c.get('text', '')}\n"
            )

    reddit_section = ""
    for p in evidence.get("reddit", {}).get("posts", []):
        reddit_section += f"\n### [{p.get('score', 0)} pts] r/{p.get('subreddit', '')} — {p.get('title', '')}\n"
        if p.get("content"):
            reddit_section += f"Post body: {p['content']}\n"
        comments = p.get("comments", "")
        if isinstance(comments, list):
            # Structured comments: list of dicts with text/score/author
            for c in comments:
                if isinstance(c, dict):
                    score = c.get("score", c.get("likes", 0))
                    author = c.get("author", "anon")
                    text = c.get("text", c.get("body", ""))[:500]
                    reddit_section += f"- [{score} pts] u/{author}: {text}\n"
                else:
                    reddit_section += f"- {str(c)[:500]}\n"
        elif comments:
            reddit_section += f"Comments:\n{comments}\n"

    # Round info if multi-round
    rounds_section = ""
    for r in evidence.get("rounds", []):
        rounds_section += (
            f'Round {r["round"]}: query="{r["query"][:60]}" '
            f"→ +{r['new_videos']} videos, +{r['new_posts']} posts\n"
        )

    prompt = f"""Research query: "{query}"
{f"Research rounds:{chr(10)}{rounds_section}" if rounds_section else ""}
## YouTube Evidence ({len(evidence.get("youtube", {}).get("videos", []))} videos)
{yt_section or "(no relevant videos)"}

## YouTube Comments (user benchmarks, corrections, real-world experiences)
{yt_comments_section or "(no comments collected)"}

## Reddit Evidence ({len(evidence.get("reddit", {}).get("posts", []))} posts)
{reddit_section or "(no relevant posts)"}

## Enrichment terms: {meta.get("enrichment_terms", [])}

---

Synthesize ALL evidence in two phases. Read every transcript, every YouTube comment, every Reddit comment. YouTube comments are especially valuable — real-world benchmarks, corrections, alternatives.

PHASE 1 — Structured extraction (fill these fields first):
- tiers: group products/tools into budget, mid-range, premium with name, specs, price (extract exact numbers from comments)
- hardware_requirements: ONLY concrete hardware specs (VRAM, CPU cores, RAM amount, storage size). Do NOT list subjective preferences.
- pricing: all price points mentioned, with source and currency. Mark prices with ~ prefix if estimated/inferred rather than directly quoted.
- controversies: specific disagreements between sources (quote both sides)

IMPORTANT accuracy rules:
- Verify product specs against evidence (e.g., keyboard layout sizes, model numbers). Do not guess specs.
- Only include prices that appear in the evidence. Mark inferred prices with "~" prefix.
- For product tiers: budget = below average price, mid = average, premium = above average. Do not mislabel a $130 product as premium if most products cost $150+.

PHASE 2 — Narrative synthesis (build on Phase 1 data):
1. **Key findings** (5-8 bullet points with source attribution: "YouTube: @channel" or "Reddit: r/sub, X pts" or "YT comment by @user, N likes")
2. **Product/tool recommendations** as tiered list from Phase 1, each with: name, key specs, price range, why, source
3. **Community consensus** — agreements AND controversies from Phase 1
4. **Gaps** — what questions remain unanswered?
5. **Summary** — 3-4 sentence executive summary with "best for most people" recommendation

Return JSON: {{"tiers": {{"budget": [...], "mid": [...], "premium": [...]}}, "hardware_requirements": [...], "pricing": [...], "controversies": [...], "key_findings": [...], "recommendations": [{{"name": "...", "tier": "budget|mid|premium", "specs": "...", "price": "...", "why": "...", "source": "..."}}], "consensus": "...", "gaps": [...], "summary": "..."}}"""

    print("[4/4] Synthesizing via GPT-OSS 120B...", file=sys.stderr)

    resp = httpx.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        json={
            "model": "openai/gpt-oss-120b",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.4,
            "max_tokens": 32000,
            "reasoning_effort": "high",
            "response_format": {"type": "json_object"},
        },
        timeout=120.0,
    )

    data = resp.json()
    if "error" in data:
        raise RuntimeError(data["error"].get("message", str(data["error"])))

    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    usage = data.get("usage", {})
    elapsed = time.time() - t0

    print(
        f"  Synthesis done in {elapsed:.1f}s "
        f"({usage.get('completion_tokens', 0)} tokens, "
        f"reasoning: {usage.get('completion_tokens_details', {}).get('reasoning_tokens', 0)})",
        file=sys.stderr,
    )

    try:
        synthesis = json.loads(content) if content else {}
    except json.JSONDecodeError:
        synthesis = {"raw": content}

    synthesis["_meta"] = {
        "model": "openai/gpt-oss-120b",
        "synthesis_seconds": round(elapsed, 1),
        "tokens": usage.get("completion_tokens", 0),
    }
    return synthesis


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    mode = sys.argv[1]
    query = sys.argv[2]
    subreddits = None
    do_synthesize = "--synthesize" in sys.argv
    num_rounds = 1

    # Parse optional args
    for i, a in enumerate(sys.argv):
        if a in ("--subreddits", "--sub") and i + 1 < len(sys.argv):
            subreddits = sys.argv[i + 1]
        if a == "--rounds" and i + 1 < len(sys.argv):
            num_rounds = int(sys.argv[i + 1])

    if mode == "auto":
        mode = route_mode(query)
        print(f"Auto-routed to: {mode}", file=sys.stderr)

    if num_rounds > 1:
        evidence = run_multi_round(mode, query, subreddits, rounds=num_rounds)
    else:
        evidence = run_research(mode, query, subreddits)

    if do_synthesize:
        synthesis = synthesize(evidence)
        evidence["synthesis"] = synthesis

    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
