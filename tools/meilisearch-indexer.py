#!/home/maetzger/.claude/tools/.venv/bin/python
"""Pi-wide Meilisearch indexer — sessions, files, memories.

Three indexes:
  messages  — Claude Code session chat messages (1 doc per message)
  files     — Tools, skills, rules, reports, code, thesis, notes
  memories  — Zettelkasten notes from zettel.db (active only)

Usage:
    ./tools/meilisearch-indexer.py                    # Reindex all
    ./tools/meilisearch-indexer.py --delta            # Only new/changed
    ./tools/meilisearch-indexer.py --only messages    # Only sessions
    ./tools/meilisearch-indexer.py --only files       # Only files
    ./tools/meilisearch-indexer.py --stats
    ./tools/meilisearch-indexer.py --search "query"
    ./tools/meilisearch-indexer.py --search "query" --index files
    ./tools/meilisearch-indexer.py --search "query" --filter "role=user"
    ./tools/meilisearch-indexer.py --search "query" --filter "category=tool"
    ./tools/meilisearch-indexer.py --search "query" --strategy all
    ./tools/meilisearch-indexer.py --multi "query"    # Search all indexes
"""

import argparse
import hashlib
import json
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MEILI_URL = "http://127.0.0.1:7700"
MEILI_KEY = "G8CnrlKGM2Hu-XZryzsIlGZoCsafBkGC84oUTinA2jo"
HOME = Path.home()
STATE_FILE = HOME / ".claude" / ".meilisearch-state.json"

CHUNK_THRESHOLD = 10_000
CHUNK_SIZE = 8_000
CHUNK_OVERLAP = 500

# ── File sources to index ──────────────────────────────────────────
FILE_SOURCES = [
    # (base_path, glob_patterns, category, exclude_patterns)
    (HOME / ".claude/tools", ["*.py", "*.md", "*.sh"], "tool", []),
    (HOME / ".claude/skills", ["**/*.md"], "skill", []),
    (HOME / ".claude/rules", ["*.md"], "rule", []),
    (HOME / ".claude/rules-lib", ["*.md"], "rule", []),
    (HOME / ".claude/CLAUDE.md", [], "config", []),
    (HOME / "CLAUDE.md", [], "config", []),
    (HOME / "shared/reports", ["*.html", "*.json"], "report", ["*.png", "*.jpg"]),
    (HOME / "research", ["*.html"], "report", []),
    (HOME / "docs/plans", ["*.md"], "plan", []),
    (HOME / "shared/masterarbeit/reviews", ["*.md"], "review", []),
    (HOME / "shared/notizen", ["*.md", "*.txt"], "note", ["*.zip", "*.docx"]),
    # Thesis — only .tex and .bib, skip PDFs and figures
    (
        HOME / "Projects/Masterarbeit-Final/Masterarbeit",
        ["*.tex", "*.bib"],
        "thesis",
        [],
    ),
    (HOME / "Projects/Facharbeit", ["*.tex", "*.bib"], "thesis", []),
    # Project source code — key projects only
    (
        HOME / "Projects/mission-control-v3",
        ["*.py", "*.html", "*.md", "*.toml"],
        "project",
        ["__pycache__", ".venv", "node_modules"],
    ),
    (
        HOME / "Projects/master-agent",
        ["*.py", "*.md", "*.toml"],
        "project",
        ["__pycache__", ".venv"],
    ),
    (
        HOME / "Projects/rss-digest",
        ["*.py", "*.html", "*.yaml", "*.toml"],
        "project",
        ["__pycache__", ".venv"],
    ),
    (
        HOME / "Projects/pauschalreise",
        ["*.py", "*.html", "*.toml"],
        "project",
        ["__pycache__", ".venv"],
    ),
    (
        HOME / "Projects/metzger-website",
        ["*.py", "*.html", "*.md", "*.toml"],
        "project",
        ["__pycache__", ".venv"],
    ),
    (
        HOME / "Projects/jarvis-config",
        ["*.py", "*.sh", "*.md", "*.json"],
        "project",
        ["__pycache__", ".venv"],
    ),
    (HOME / "Projects/agent-mail", ["*.py"], "project", []),
    (HOME / "Projects/flight-search", ["*.py"], "project", []),
]


# ── HTML text extraction ───────────────────────────────────────────
class HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._text = []
        self._skip = False
        self._skip_tags = {"script", "style", "svg", "noscript"}

    def handle_starttag(self, tag, attrs):
        if tag in self._skip_tags:
            self._skip = True

    def handle_endtag(self, tag):
        if tag in self._skip_tags:
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            stripped = data.strip()
            if stripped:
                self._text.append(stripped)

    def get_text(self):
        return "\n".join(self._text)


def strip_html(html_content):
    """Extract readable text from HTML."""
    extractor = HTMLTextExtractor()
    try:
        extractor.feed(html_content)
        return extractor.get_text()
    except Exception:
        # Fallback: regex strip
        text = re.sub(r"<[^>]+>", " ", html_content)
        return re.sub(r"\s+", " ", text).strip()


# ── Meilisearch API ────────────────────────────────────────────────
def meili(method, path, data=None, timeout=30):
    """Make a request to Meilisearch API."""
    url = f"{MEILI_URL}{path}"
    headers = {
        "Authorization": f"Bearer {MEILI_KEY}",
        "Content-Type": "application/json",
    }
    body = json.dumps(data).encode() if data else None
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        err = e.read().decode() if e.fp else ""
        print(f"  HTTP {e.code}: {err[:300]}", file=sys.stderr)
        return None
    except URLError as e:
        print(f"  Connection error: {e}", file=sys.stderr)
        return None


def wait_idle(index_name, max_wait=120):
    """Wait for indexing to finish."""
    for _ in range(max_wait):
        stats = meili("GET", f"/indexes/{index_name}/stats")
        if stats and not stats.get("isIndexing"):
            return True
        time.sleep(1)
    return False


# ── Chunking ───────────────────────────────────────────────────────
def chunk_text(text):
    """Split long text into overlapping chunks at natural boundaries."""
    if len(text) <= CHUNK_THRESHOLD:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        if end < len(text):
            para = text.rfind("\n\n", start + CHUNK_SIZE // 2, end)
            if para > start:
                end = para + 2
            else:
                for sep in (". ", ".\n", "! ", "? "):
                    sent = text.rfind(sep, start + CHUNK_SIZE // 2, end)
                    if sent > start:
                        end = sent + len(sep)
                        break
        chunks.append(text[start:end])
        start = end - CHUNK_OVERLAP
    return chunks


# ── Messages index (session JSONL files) ───────────────────────────
def configure_messages():
    """Create and configure the messages index."""
    meili("POST", "/indexes", {"uid": "messages", "primaryKey": "id"})
    meili(
        "PATCH",
        "/indexes/messages/settings",
        {
            "searchableAttributes": ["text", "tools_used", "session_id", "project"],
            "filterableAttributes": [
                "role",
                "project",
                "date",
                "session_id",
                "has_tools",
                "chunk",
            ],
            "sortableAttributes": ["date", "timestamp", "turn"],
            "rankingRules": [
                "words",
                "typo",
                "proximity",
                "attribute",
                "sort",
                "exactness",
                "timestamp:desc",
            ],
            "typoTolerance": {
                "enabled": True,
                "minWordSizeForTypos": {"oneTypo": 4, "twoTypos": 8},
            },
            "proximityPrecision": "byAttribute",
            "pagination": {"maxTotalHits": 5000},
            "faceting": {"maxValuesPerFacet": 200},
            "searchCutoffMs": 300,
        },
    )


def extract_msg_text(msg_data):
    if isinstance(msg_data, str):
        return msg_data
    if isinstance(msg_data, dict):
        content = msg_data.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            )
    return ""


def extract_tools(msg_data):
    tools = []
    if not isinstance(msg_data, dict):
        return tools
    content = msg_data.get("content", [])
    if not isinstance(content, list):
        return tools
    for item in content:
        if isinstance(item, dict) and item.get("type") == "tool_use":
            name = item.get("name", "")
            if name and name not in tools:
                tools.append(name)
    return tools


def parse_session(filepath):
    """Parse a JSONL session file into message documents."""
    docs = []
    session_id = None
    project = filepath.parent.name
    turn = 0

    try:
        with open(filepath, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if not session_id and entry.get("sessionId"):
                    session_id = entry["sessionId"]

                msg_type = entry.get("type")
                if msg_type not in ("user", "assistant"):
                    continue

                text = extract_msg_text(entry.get("message", ""))
                if not text or len(text) < 10:
                    continue

                turn += 1
                ts = entry.get("timestamp", "")
                date = ts[:10] if ts else ""
                tools = (
                    extract_tools(entry.get("message", {}))
                    if msg_type == "assistant"
                    else []
                )

                base = {
                    "session_id": session_id or filepath.stem,
                    "project": project,
                    "file": str(filepath),
                    "role": "user" if msg_type == "user" else "assistant",
                    "date": date,
                    "timestamp": ts,
                    "turn": turn,
                    "has_tools": bool(tools),
                    "tools_used": " ".join(tools) if tools else "",
                }

                chunks = chunk_text(text)
                for ci, chunk in enumerate(chunks):
                    doc_id = hashlib.md5(
                        f"{filepath}:{turn}:{ci}".encode()
                    ).hexdigest()[:16]
                    docs.append(
                        {
                            "id": doc_id,
                            "text": chunk,
                            "chunk": ci if len(chunks) > 1 else -1,
                            **base,
                        }
                    )
    except (OSError, UnicodeDecodeError) as e:
        print(f"  Skip {filepath.name}: {e}", file=sys.stderr)
    return docs


def index_messages(state, delta_only):
    """Index all session JSONL files."""
    configure_messages()
    time.sleep(0.5)

    sessions_dir = HOME / ".claude" / "projects"
    all_files = sorted(sessions_dir.rglob("*.jsonl"))
    print(f"[messages] Found {len(all_files)} JSONL files.")

    if delta_only:
        files = [
            f
            for f in all_files
            if str(f) not in state or state[str(f)] < f.stat().st_mtime
        ]
        print(f"[messages] Delta: {len(files)} new/modified.")
    else:
        files = all_files

    if not files:
        print("[messages] Nothing to index.")
        return state

    total = 0
    batch = []
    bnum = 0
    t0 = time.time()

    for i, fp in enumerate(files, 1):
        if i % 200 == 0:
            print(f"  Parsing {i}/{len(files)}...")
        docs = parse_session(fp)
        total += len(docs)
        batch.extend(docs)
        state[str(fp)] = fp.stat().st_mtime

        while len(batch) >= 5000:
            bnum += 1
            meili("POST", "/indexes/messages/documents", batch[:5000], timeout=60)
            print(f"  Batch {bnum}: {min(5000, len(batch))} docs")
            batch = batch[5000:]

    if batch:
        bnum += 1
        meili("POST", "/indexes/messages/documents", batch, timeout=60)
        print(f"  Batch {bnum}: {len(batch)} docs")

    print(f"[messages] {total} docs from {len(files)} files in {time.time() - t0:.1f}s")
    wait_idle("messages")
    return state


# ── Files index (tools, skills, code, reports, etc.) ───────────────
def configure_files():
    """Create and configure the files index."""
    meili("POST", "/indexes", {"uid": "files", "primaryKey": "id"})
    meili(
        "PATCH",
        "/indexes/files/settings",
        {
            "searchableAttributes": ["text", "filename", "path", "category"],
            "filterableAttributes": [
                "category",
                "language",
                "date",
                "project",
                "chunk",
            ],
            "sortableAttributes": ["date", "size"],
            "rankingRules": [
                "words",
                "typo",
                "proximity",
                "attribute",
                "sort",
                "exactness",
            ],
            "typoTolerance": {
                "enabled": True,
                "minWordSizeForTypos": {"oneTypo": 5, "twoTypos": 9},
                "disableOnAttributes": ["path", "filename"],
            },
            "proximityPrecision": "byAttribute",
            "pagination": {"maxTotalHits": 2000},
            "searchCutoffMs": 300,
        },
    )


# ── Memories index (Zettelkasten notes) ───────────────────────────
ZETTEL_DB = HOME / ".claude" / "data" / "zettel.db"


def configure_memories():
    """Create and configure the memories index."""
    meili("POST", "/indexes", {"uid": "memories", "primaryKey": "id"})
    meili(
        "PATCH",
        "/indexes/memories/settings",
        {
            "searchableAttributes": ["title", "content", "tags", "keywords"],
            "filterableAttributes": ["importance", "tags"],
            "sortableAttributes": ["importance", "updated_at"],
            "rankingRules": [
                "words",
                "typo",
                "proximity",
                "attribute",
                "sort",
                "exactness",
                "importance:desc",
            ],
            "typoTolerance": {
                "enabled": True,
                "minWordSizeForTypos": {"oneTypo": 4, "twoTypos": 8},
            },
            "pagination": {"maxTotalHits": 200},
            "searchCutoffMs": 100,
        },
    )


def index_memories(state, delta_only):
    """Index active Zettelkasten notes from zettel.db."""
    import sqlite3

    configure_memories()
    time.sleep(0.3)

    if not ZETTEL_DB.exists():
        print("[memories] zettel.db not found, skipping.")
        return state

    conn = sqlite3.connect(str(ZETTEL_DB))
    conn.row_factory = sqlite3.Row

    if delta_only:
        last_ts = state.get("_memories_last_ts", "2000-01-01T00:00:00")
        rows = conn.execute(
            "SELECT * FROM notes WHERE archived=0 AND updated_at > ? "
            "ORDER BY importance DESC",
            (last_ts,),
        ).fetchall()
        print(f"[memories] Delta: {len(rows)} new/modified notes.")
    else:
        rows = conn.execute(
            "SELECT * FROM notes WHERE archived=0 ORDER BY importance DESC"
        ).fetchall()
        print(f"[memories] Found {len(rows)} active notes.")

    if not rows:
        print("[memories] Nothing to index.")
        conn.close()
        return state

    docs = []
    max_ts = state.get("_memories_last_ts", "2000-01-01T00:00:00")
    for r in rows:
        try:
            tags = json.loads(r["tags"]) if r["tags"] else []
        except (json.JSONDecodeError, TypeError):
            tags = []
        try:
            keywords = json.loads(r["keywords"]) if r["keywords"] else []
        except (json.JSONDecodeError, TypeError):
            keywords = []
        docs.append(
            {
                "id": f"zettel-{r['id']}",
                "zettel_id": r["id"],
                "title": r["title"],
                "content": r["content"],
                "tags": tags,
                "keywords": keywords,
                "importance": r["importance"],
                "updated_at": r["updated_at"],
            }
        )
        if r["updated_at"] > max_ts:
            max_ts = r["updated_at"]

    if docs:
        meili("POST", "/indexes/memories/documents", docs, timeout=30)

    state["_memories_last_ts"] = max_ts
    conn.close()

    print(f"[memories] {len(docs)} docs indexed.")
    wait_idle("memories")
    return state


def detect_language(path):
    """Detect file language from extension."""
    ext_map = {
        ".py": "python",
        ".md": "markdown",
        ".html": "html",
        ".tex": "latex",
        ".bib": "bibtex",
        ".sh": "shell",
        ".toml": "toml",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".json": "json",
        ".txt": "text",
        ".css": "css",
        ".js": "javascript",
    }
    return ext_map.get(path.suffix.lower(), "text")


def collect_files():
    """Collect all files to index from FILE_SOURCES."""
    collected = []
    seen = set()

    for entry in FILE_SOURCES:
        base_path = entry[0]
        globs = entry[1]
        category = entry[2]
        excludes = entry[3] if len(entry) > 3 else []

        if not base_path.exists():
            continue

        # Single file (e.g. CLAUDE.md)
        if base_path.is_file() and not globs:
            if str(base_path) not in seen:
                seen.add(str(base_path))
                collected.append((base_path, category))
            continue

        if not base_path.is_dir():
            continue

        for pattern in globs:
            for fp in sorted(base_path.glob(pattern)):
                if not fp.is_file():
                    continue
                fstr = str(fp)
                if fstr in seen:
                    continue
                # Check excludes
                skip = False
                for exc in excludes:
                    if exc.startswith("*"):
                        if fp.suffix == exc[1:]:
                            skip = True
                    elif exc in fstr:
                        skip = True
                if skip:
                    continue
                # Skip venvs and caches
                if any(
                    p in fstr
                    for p in ["/.venv/", "/__pycache__/", "/node_modules/", "/.git/"]
                ):
                    continue
                seen.add(fstr)
                collected.append((fp, category))

    return collected


def read_file_text(filepath):
    """Read file and extract searchable text."""
    try:
        raw = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""

    if filepath.suffix.lower() == ".html":
        return strip_html(raw)

    return raw


def index_files(state, delta_only):
    """Index all non-session files."""
    configure_files()
    time.sleep(0.5)

    all_files = collect_files()
    print(f"[files] Found {len(all_files)} files.")

    if delta_only:
        files = [
            (fp, cat)
            for fp, cat in all_files
            if str(fp) not in state or state[str(fp)] < fp.stat().st_mtime
        ]
        print(f"[files] Delta: {len(files)} new/modified.")
    else:
        files = all_files

    if not files:
        print("[files] Nothing to index.")
        return state

    docs = []
    t0 = time.time()

    for fp, category in files:
        text = read_file_text(fp)
        if not text or len(text) < 20:
            continue

        lang = detect_language(fp)
        mtime = fp.stat().st_mtime
        date = time.strftime("%Y-%m-%d", time.localtime(mtime))
        # Derive project name from path
        project = ""
        if "Projects/" in str(fp):
            parts = str(fp).split("Projects/")
            if len(parts) > 1:
                project = parts[1].split("/")[0]

        base = {
            "filename": fp.name,
            "path": str(fp),
            "category": category,
            "language": lang,
            "date": date,
            "size": fp.stat().st_size,
            "project": project,
        }

        chunks = chunk_text(text)
        for ci, chunk in enumerate(chunks):
            doc_id = hashlib.md5(f"{fp}:{ci}".encode()).hexdigest()[:16]
            docs.append(
                {
                    "id": doc_id,
                    "text": chunk,
                    "chunk": ci if len(chunks) > 1 else -1,
                    **base,
                }
            )

        state[str(fp)] = mtime

    if docs:
        # Upload in batches
        for i in range(0, len(docs), 2000):
            batch = docs[i : i + 2000]
            meili("POST", "/indexes/files/documents", batch, timeout=60)
            print(f"  Batch: {len(batch)} docs")

    print(f"[files] {len(docs)} docs in {time.time() - t0:.1f}s")
    wait_idle("files")
    return state


# ── Search ─────────────────────────────────────────────────────────
def parse_filter(filter_str):
    """Translate simple filter syntax to Meilisearch filter expressions."""
    if not filter_str:
        return None
    parts = []
    for f in filter_str.split(","):
        f = f.strip()
        for op in (">=", "<=", "!=", ">", "<", "="):
            if op in f:
                key, val = f.split(op, 1)
                parts.append(f"{key.strip()} {op.replace('=', ' =')} '{val.strip()}'")
                break
    return " AND ".join(parts) if parts else None


def search_index(
    index_name, query, limit=10, context=200, filter_str=None, strategy="frequency"
):
    """Search a single index."""
    # memories index uses 'content' instead of 'text'
    highlight_attr = "content" if index_name == "memories" else "text"
    body = {
        "q": query,
        "limit": limit,
        "matchingStrategy": strategy,
        "attributesToHighlight": [highlight_attr],
        "highlightPreTag": "\033[1;33m",
        "highlightPostTag": "\033[0m",
        "attributesToCrop": [highlight_attr],
        "cropLength": max(context // 4, 10),
        "cropMarker": "…",
        "showRankingScore": True,
    }
    filt = parse_filter(filter_str)
    if filt:
        body["filter"] = filt

    result = meili("POST", f"/indexes/{index_name}/search", body)
    if not result:
        return None
    return result


def format_messages_hit(hit, context):
    """Format a hit from the messages index."""
    date = hit.get("date", "?")
    role = "U" if hit.get("role") == "user" else "A"
    project = hit.get("project", "?")[:20]
    sid = hit.get("session_id", "")[:8]
    turn = hit.get("turn", 0)
    score = hit.get("_rankingScore", 0)
    tools = hit.get("tools_used", "")
    chunk = hit.get("chunk", -1)
    chunk_info = f" [c{chunk}]" if chunk >= 0 else ""

    print(
        f"\033[1m[{date}] {role}#{turn}{chunk_info}  {project}  {sid}  ({score:.3f})\033[0m"
    )
    if tools:
        print(f"  Tools: {tools}")

    fmt = hit.get("_formatted", {})
    snippet = fmt.get("text", "")
    if snippet:
        lines = [l.strip() for l in snippet.split("\n") if l.strip()]
        show = 2 if context <= 200 else min(6, len(lines))
        for line in lines[:show]:
            print(f"  {line}")
    print()


def format_files_hit(hit, context):
    """Format a hit from the files index."""
    cat = hit.get("category", "?")
    fname = hit.get("filename", "?")
    lang = hit.get("language", "")
    path = hit.get("path", "")
    score = hit.get("_rankingScore", 0)
    chunk = hit.get("chunk", -1)
    chunk_info = f" [c{chunk}]" if chunk >= 0 else ""

    # Shorten path for display
    short_path = path.replace(str(HOME), "~") if path else ""

    print(f"\033[1m[{cat}] {fname}{chunk_info}  {lang}  ({score:.3f})\033[0m")
    print(f"  {short_path}")

    fmt = hit.get("_formatted", {})
    snippet = fmt.get("text", "")
    if snippet:
        lines = [l.strip() for l in snippet.split("\n") if l.strip()]
        show = 2 if context <= 200 else min(6, len(lines))
        for line in lines[:show]:
            print(f"  {line}")
    print()


def format_memories_hit(hit, context):
    """Format a hit from the memories index."""
    title = hit.get("title", "?")
    imp = hit.get("importance", 0)
    tags = hit.get("tags", [])
    zettel_id = hit.get("zettel_id", "?")
    score = hit.get("_rankingScore", 0)

    tag_str = ", ".join(tags) if tags else ""
    print(f"\033[1m[#{zettel_id}] {title}  I={imp:.1f}  ({score:.3f})\033[0m")
    if tag_str:
        print(f"  Tags: {tag_str}")

    fmt = hit.get("_formatted", {})
    snippet = fmt.get("content", "")
    if snippet:
        lines = [l.strip() for l in snippet.split("\n") if l.strip()]
        show = 2 if context <= 200 else min(6, len(lines))
        for line in lines[:show]:
            print(f"  {line}")
    print()


def search(
    query, index="all", limit=10, context=200, filter_str=None, strategy="frequency"
):
    """Search one or all indexes."""
    if index == "all":
        # Multi-search across all indexes
        query_base = {
            "q": query,
            "limit": limit,
            "matchingStrategy": strategy,
            "attributesToHighlight": ["text"],
            "highlightPreTag": "\033[1;33m",
            "highlightPostTag": "\033[0m",
            "attributesToCrop": ["text"],
            "cropLength": max(context // 4, 10),
            "cropMarker": "…",
            "showRankingScore": True,
        }
        body = {
            "queries": [
                {"indexUid": "messages", **query_base},
                {"indexUid": "files", **query_base},
                {
                    "indexUid": "memories",
                    "q": query,
                    "limit": limit,
                    "matchingStrategy": strategy,
                    "attributesToHighlight": ["content"],
                    "highlightPreTag": "\033[1;33m",
                    "highlightPostTag": "\033[0m",
                    "attributesToCrop": ["content"],
                    "cropLength": max(context // 4, 10),
                    "cropMarker": "…",
                    "showRankingScore": True,
                },
            ]
        }
        if filter_str:
            filt = parse_filter(filter_str)
            if filt:
                for q in body["queries"]:
                    q["filter"] = filt

        result = meili("POST", "/multi-search", body)
        if not result:
            print("Search failed.")
            return

        for res in result.get("results", []):
            idx = res.get("indexUid", "?")
            total = res.get("estimatedTotalHits", 0)
            ms = res.get("processingTimeMs", 0)
            hits = res.get("hits", [])

            print(f"\033[1;36m── {idx} ── {total} results ({ms}ms)\033[0m\n")

            if idx == "messages":
                formatter = format_messages_hit
            elif idx == "memories":
                formatter = format_memories_hit
            else:
                formatter = format_files_hit
            for hit in hits:
                formatter(hit, context)

    else:
        result = search_index(index, query, limit, context, filter_str, strategy)
        if not result:
            print("Search failed.")
            return

        total = result.get("estimatedTotalHits", 0)
        ms = result.get("processingTimeMs", 0)
        print(f"  {total} results in {ms}ms\n")

        if index == "messages":
            formatter = format_messages_hit
        elif index == "memories":
            formatter = format_memories_hit
        else:
            formatter = format_files_hit
        for hit in result.get("hits", []):
            formatter(hit, context)


# ── Stats ──────────────────────────────────────────────────────────
def show_stats():
    for idx in ("messages", "files", "memories"):
        stats = meili("GET", f"/indexes/{idx}/stats")
        if stats:
            n = stats.get("numberOfDocuments", 0)
            indexing = "indexing" if stats.get("isIndexing") else "idle"
            print(f"  {idx}: {n:,} docs ({indexing})")
        else:
            print(f"  {idx}: not found")


# ── Main ───────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Pi-wide Meilisearch indexer")
    parser.add_argument("--delta", action="store_true", help="Only new/modified")
    parser.add_argument(
        "--only", choices=["messages", "files", "memories"], help="Index only one type"
    )
    parser.add_argument("--stats", action="store_true", help="Show index stats")
    parser.add_argument("--search", type=str, help="Search query")
    parser.add_argument("--multi", type=str, help="Multi-search across all indexes")
    parser.add_argument(
        "--index", default="all", help="Which index: messages, files, all"
    )
    parser.add_argument("--limit", type=int, default=10, help="Max results")
    parser.add_argument("--context", type=int, default=200, help="Context around match")
    parser.add_argument("--filter", type=str, help="Filter expression")
    parser.add_argument(
        "--strategy",
        default="frequency",
        choices=["last", "all", "frequency"],
        help="Matching strategy",
    )
    args = parser.parse_args()

    if args.stats:
        show_stats()
        return

    if args.search or args.multi:
        query = args.search or args.multi
        idx = "all" if args.multi else args.index
        search(
            query,
            index=idx,
            limit=args.limit,
            context=args.context,
            filter_str=args.filter,
            strategy=args.strategy,
        )
        return

    # Indexing
    state = load_state() if args.delta else {}

    if not args.delta:
        drop_list = [args.only] if args.only else ["messages", "files", "memories"]
        for idx in drop_list:
            print(f"Dropping {idx}...")
            meili("DELETE", f"/indexes/{idx}")
        time.sleep(1)

    if not args.only or args.only == "messages":
        state = index_messages(state, args.delta)

    if not args.only or args.only == "files":
        state = index_files(state, args.delta)

    if not args.only or args.only == "memories":
        state = index_memories(state, args.delta)

    save_state(state)
    print("\nFinal stats:")
    show_stats()


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state))


if __name__ == "__main__":
    main()
