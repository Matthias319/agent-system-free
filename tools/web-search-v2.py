#!/home/maetzger/.claude/tools/.venv/bin/python
"""
Web-Search v2: Autonome Research-Pipeline in einem einzigen Aufruf.

Eliminiert LLM-Inferenz-Roundtrips durch Groq-API für Query-Gen + Synthese.
Importiert fast-search.py und research-crawler.py als Module (kein Subprocess).

Verwendung:
    # Standard (auto-detects mode)
    web-search-v2.py "Was kostet ein Framework Laptop 13?"

    # Expliziter Modus
    web-search-v2.py --mode quick "Höhe Eiffelturm"
    web-search-v2.py --mode deep "Framework Laptop vs ThinkPad X1 Carbon 2026"

    # Ohne Report (nur JSON)
    web-search-v2.py --no-report "query"

    # Ohne Synthese (nur Rohdaten)
    web-search-v2.py --no-synthesis "query"

Output (stdout): JSON mit synthesis, report_path, sources, meta
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Konfiguration ──────────────────────────────────────────────────────────────

TOOLS_DIR = Path(__file__).parent
GROQ_MODEL_FAST = "openai/gpt-oss-120b"  # Query-Gen, Gap-Analyse
GROQ_MODEL_SYNTH = "openai/gpt-oss-120b"  # Synthese
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# Modus-Konfiguration
MODE_CONFIG = {
    "quick": {
        "max_queries": 1,
        "depth": "quick",
        "max_chars": 6000,
        "expansion": False,
        "report": False,
        "freshness_weight": 1.0,
    },
    "standard": {
        "max_queries": 3,
        "depth": "standard",
        "max_chars": 18000,
        "expansion": True,
        "report": True,
        "freshness_weight": 1.5,
    },
    "deep": {
        "max_queries": 5,
        "depth": "deep",
        "max_chars": 18000,
        "expansion": True,
        "report": True,
        "freshness_weight": 1.5,
    },
}


# ── Modul-Loader ───────────────────────────────────────────────────────────────


def _load_module(filename: str, module_name: str):
    """Python-Datei mit Bindestrich als Modul laden."""
    path = TOOLS_DIR / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Lazy-Load (erst bei Bedarf)
_fast_search = None
_research_crawler = None
_report_renderer = None


def get_fast_search():
    global _fast_search
    if _fast_search is None:
        _fast_search = _load_module("fast-search.py", "fast_search")
    return _fast_search


def get_research_crawler():
    global _research_crawler
    if _research_crawler is None:
        _research_crawler = _load_module("research-crawler.py", "research_crawler")
    return _research_crawler


def get_report_renderer():
    global _report_renderer
    if _report_renderer is None:
        _report_renderer = _load_module("report-renderer.py", "report_renderer")
    return _report_renderer


# ── Helpers ─────────────────────────────────────────────────────────────────────

import re as _re


def _extract_json(raw: str, fallback: dict) -> dict:
    """Robuste JSON-Extraktion aus LLM-Output (Markdown-Fencing, leerer Content)."""
    raw = raw.strip()
    if not raw:
        return fallback
    # Markdown-Fencing entfernen
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        raw = raw.rsplit("```", 1)[0]
    raw = raw.strip()
    # Versuche direktes JSON-Parsing
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Versuche JSON-Objekt aus dem Text zu extrahieren
    match = _re.search(r"\{[\s\S]*\}", raw)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return fallback


# ── Groq API ───────────────────────────────────────────────────────────────────


def _get_groq_key() -> str:
    """Groq API-Key aus .env laden (kanonische Quelle), Env-Var als Fallback."""
    env_file = Path.home() / ".claude" / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("GROQ_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("GROQ_API_KEY", "")


def groq_chat(
    messages: list[dict],
    model: str = GROQ_MODEL_FAST,
    max_tokens: int = 800,
    temperature: float = 0.3,
) -> str:
    """Synchroner Groq-API-Call. Gibt Content zurück."""
    import httpx

    key = _get_groq_key()
    if not key:
        raise RuntimeError("GROQ_API_KEY nicht gefunden")

    r = httpx.post(
        GROQ_API_URL,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    content = data["choices"][0]["message"].get("content", "")
    usage = data.get("usage", {})
    sys.stderr.write(
        f"  [Groq {model.split('/')[-1]}] "
        f"{usage.get('prompt_tokens', 0)} in / {usage.get('completion_tokens', 0)} out / "
        f"{usage.get('completion_time', 0):.2f}s\n"
    )
    return content


# ── Step 1: Query-Generierung + Mode-Routing ──────────────────────────────────

QUERY_GEN_SYSTEM = """You are a search query optimizer for web research. Given a user's question:

1. Determine the search mode:
   - "quick": Trivial single facts (height of Eiffel Tower, capital of X)
   - "standard": Default for most questions (product info, how-to, comparison of 2 things)
   - "deep": Complex comparisons, research, buying decisions, multi-aspect topics

2. Generate optimized search queries:
   - Quick: 1 query
   - Standard: 2-3 queries (main + synonym/translation)
   - Deep: 3-5 queries (main + synonym + specific + counter-position)
   - Always append year "2026" for freshness-sensitive topics
   - Mix languages: EN for tech/international, DE for local/prices, both for comparisons
   - For fact-checks: include a counter-position query

3. Determine freshness_weight:
   - 2.0 for AI/tech/news (changes weekly)
   - 1.5 for products/prices (monthly cycles)
   - 1.0 for how-to/tutorials (stable)
   - 0.5 for academic/research (slow peer-review)

4. Determine query_type for report formatting:
   - "factcheck": Verifying a claim
   - "comparison": A vs B
   - "decision": Buying advice, "should I..."
   - "research": General information gathering
   - "price": Price inquiry

Output ONLY valid JSON:
{
  "mode": "quick|standard|deep",
  "queries": ["query1", "query2", ...],
  "freshness_weight": 1.5,
  "query_type": "research",
  "language": "mixed|en|de"
}"""


def generate_queries(user_intent: str, force_mode: str | None = None) -> dict:
    """Generiere Suchqueries und bestimme Modus via Groq."""
    t0 = time.monotonic()
    try:
        raw = groq_chat(
            messages=[
                {"role": "system", "content": QUERY_GEN_SYSTEM},
                {"role": "user", "content": user_intent},
            ],
            model=GROQ_MODEL_FAST,
            max_tokens=500,
            temperature=0.3,
        )
        fallback = {
            "mode": "standard",
            "queries": [user_intent, f"{user_intent} 2026"],
            "freshness_weight": 1.5,
            "query_type": "research",
            "language": "mixed",
        }
        result = _extract_json(raw, fallback)
        # Pflichtfelder sicherstellen
        if "queries" not in result or not result["queries"]:
            result = fallback
    except Exception as e:
        sys.stderr.write(f"  [Query-Gen FALLBACK] Groq fehlgeschlagen: {e}\n")
        result = {
            "mode": "standard",
            "queries": [user_intent, f"{user_intent} 2026"],
            "freshness_weight": 1.5,
            "query_type": "research",
            "language": "mixed",
        }

    if force_mode:
        result["mode"] = force_mode

    dt = time.monotonic() - t0
    sys.stderr.write(
        f"  Step 1 (Query-Gen): {dt:.2f}s → {len(result['queries'])} queries, mode={result['mode']}\n"
    )
    return result


# ── Step 2+3: Search + Crawl ──────────────────────────────────────────────────


def search_and_crawl(
    queries: list[str],
    depth: str = "standard",
    max_chars: int = 18000,
    freshness_weight: float = 1.5,
) -> list[dict]:
    """Search via Startpage + Crawl via research-crawler, alles in-process."""
    t0 = time.monotonic()

    # Step 2: Search
    fs = get_fast_search()
    all_results = []
    for q in queries:
        try:
            results = fs.search_startpage(
                q,
                max_results=MODE_CONFIG.get(depth, MODE_CONFIG["standard"]).get(
                    "max_queries", 10
                )
                * 3,
            )
            all_results.extend(results)
        except Exception as e:
            sys.stderr.write(f"  Search-Fehler für '{q[:50]}': {e}\n")

    # Deduplizieren nach URL
    seen = set()
    unique = []
    for r in all_results:
        if r["url"] not in seen:
            seen.add(r["url"])
            unique.append(r)

    # Depth-basiertes Limit
    depth_limits = {"quick": 8, "standard": 15, "deep": 25}
    limit = depth_limits.get(depth, 15)
    unique = unique[:limit]

    dt_search = time.monotonic() - t0
    sys.stderr.write(f"  Step 2 (Search): {dt_search:.2f}s → {len(unique)} URLs\n")

    if not unique:
        return []

    # Step 3: Crawl
    t1 = time.monotonic()
    crawler = get_research_crawler()
    crawler.MAX_CHARS_PER_URL = max_chars
    crawler.FRESHNESS_WEIGHT = freshness_weight

    urls = [r["url"] for r in unique]
    try:
        raw_results = asyncio.run(crawler.crawl(urls))
    except Exception as e:
        sys.stderr.write(f"  Crawl-Fehler: {e}\n")
        return []

    # Ergebnisse aufbereiten
    results = []
    for r in raw_results:
        entry = {
            "url": r["url"],
            "title": r.get("title", ""),
            "content": r.get("content", ""),
            "chars": r.get("chars", 0),
            "quality": r.get("quality", 0),
            "domain_tier": r.get("domain_tier", "standard"),
            "source_type": r.get("source_type", "general"),
            "pub_date": r.get("pub_date"),
            "freshness_bonus": r.get("freshness_bonus", 0),
        }
        if r.get("error"):
            entry["error"] = r["error"]
        if r.get("is_boilerplate"):
            entry["boilerplate"] = True
        results.append(entry)

    ok = [r for r in results if not r.get("error") and not r.get("boilerplate")]
    dt_crawl = time.monotonic() - t1
    sys.stderr.write(
        f"  Step 3 (Crawl): {dt_crawl:.2f}s → {len(ok)}/{len(results)} usable\n"
    )
    return results


# ── Step 4: Gap-Analyse + Query-Expansion ──────────────────────────────────────

GAP_ANALYSIS_SYSTEM = """Analyze web research results and identify coverage gaps. You receive:
- The original user question
- A summary of crawled sources (title, quality, source_type, domain)

Determine if follow-up queries are needed:
- Missing perspectives (only pro, no contra?)
- Missing source types (no reviews? no academic?)
- Missing languages (only EN, needs DE?)
- All sources too old?
- Key aspects of the question not covered?

If gaps exist, generate 1-3 targeted follow-up queries.
If coverage is sufficient, return empty expansion list.

Output ONLY valid JSON:
{
  "coverage_sufficient": true/false,
  "gaps": ["gap description 1", ...],
  "expansion_queries": ["follow-up query 1", ...]
}"""


def analyze_gaps(user_intent: str, results: list[dict]) -> dict:
    """Analysiere Ergebnis-Coverage und generiere ggf. Folge-Queries."""
    ok = [r for r in results if not r.get("error") and not r.get("boilerplate")]
    if not ok:
        return {
            "coverage_sufficient": False,
            "gaps": ["No results"],
            "expansion_queries": [f"{user_intent} 2026"],
        }

    # Kompakte Zusammenfassung der Ergebnisse für Groq
    source_summary = []
    for r in ok[:15]:
        domain = r["url"].split("/")[2] if "/" in r["url"] else ""
        source_summary.append(
            f"- {r.get('title', 'N/A')[:80]} | Q={r.get('quality', 0)} | "
            f"{r.get('source_type', 'general')} | {domain}"
        )

    t0 = time.monotonic()
    try:
        raw = groq_chat(
            messages=[
                {"role": "system", "content": GAP_ANALYSIS_SYSTEM},
                {
                    "role": "user",
                    "content": f"User question: {user_intent}\n\nSources ({len(ok)} usable):\n"
                    + "\n".join(source_summary),
                },
            ],
            model=GROQ_MODEL_FAST,
            max_tokens=700,
            temperature=0.3,
        )
        result = _extract_json(
            raw, {"coverage_sufficient": True, "gaps": [], "expansion_queries": []}
        )
    except Exception as e:
        sys.stderr.write(f"  [Gap-Analysis FALLBACK] {e}\n")
        result = {"coverage_sufficient": True, "gaps": [], "expansion_queries": []}

    dt = time.monotonic() - t0
    exp = result.get("expansion_queries", [])
    status = (
        "sufficient"
        if result.get("coverage_sufficient")
        else f"{len(exp)} expansion queries"
    )
    sys.stderr.write(f"  Step 4 (Gap-Analysis): {dt:.2f}s → {status}\n")
    return result


# ── Step 6: Synthese ───────────────────────────────────────────────────────────

SYNTHESIS_SYSTEM = """You are a research synthesizer. Analyze crawled web sources and produce a structured summary.

Rules:
- Cite sources as [Q1], [Q2], etc.
- Mark your own inferences as [Own inference]
- If sources contradict, present both positions with source IDs
- For product/tech: distinguish manufacturer claims from independent tests
- Use UTF-8 German umlauts (ä, ö, ü, ß) for German text
- Be concise but comprehensive

Output valid JSON:
{
  "title": "Research title",
  "subtitle": "One-line summary",
  "tldr": "2-3 sentence executive summary",
  "sections": [
    {
      "title": "Section title",
      "highlights": ["Key finding 1 [Q1]", "Key finding 2 [Q2, Q3]"],
      "body": "Detailed analysis text with [Q1] citations..."
    }
  ],
  "sources": [
    {"id": "Q1", "title": "Source title", "url": "https://...", "domain": "example.com", "quality": 8.0, "type": "review"}
  ],
  "confidence": "high|medium|low",
  "confidence_reason": "Why this confidence level"
}"""


def _make_synth_fallback(user_intent: str, ok: list[dict], reason: str) -> dict:
    """Minimale Synthese ohne LLM."""
    return {
        "title": user_intent[:80],
        "subtitle": f"Recherche mit {len(ok)} Quellen",
        "tldr": f"Es wurden {len(ok)} Quellen gefunden. {reason}",
        "sections": [
            {
                "title": "Quellen-Übersicht",
                "highlights": [
                    f"{r.get('title', 'N/A')[:60]} (Q={r.get('quality', 0)})"
                    for r in ok[:5]
                ],
                "body": "Automatische Synthese nicht verfügbar. Rohdaten stehen zur Verfügung.",
            }
        ],
        "sources": [
            {
                "id": f"Q{i + 1}",
                "title": r.get("title", ""),
                "url": r["url"],
                "quality": r.get("quality", 0),
                "type": r.get("source_type", "general"),
            }
            for i, r in enumerate(ok[:10])
        ],
        "confidence": "low",
    }


def synthesize(
    user_intent: str, results: list[dict], query_type: str = "research"
) -> dict:
    """Synthetisiere Crawl-Ergebnisse via Groq gpt-oss-120b."""
    ok = sorted(
        [r for r in results if not r.get("error") and not r.get("boilerplate")],
        key=lambda x: x.get("quality", 0),
        reverse=True,
    )
    if not ok:
        return {
            "title": "Keine Ergebnisse",
            "tldr": "Die Recherche hat keine verwertbaren Quellen ergeben.",
            "sections": [],
            "sources": [],
            "confidence": "low",
        }

    # Quellen für Groq aufbereiten (max ~100K Zeichen, Top-Quellen bevorzugt)
    source_texts = []
    total_chars = 0
    char_limit = 80000  # ~27K Tokens — Groq 120b hat 131K Context
    for i, r in enumerate(ok):
        content = r.get("content", "")[:8000]  # Max 8K pro Quelle
        domain = r["url"].split("/")[2] if "/" in r["url"] else ""
        block = (
            f"[Q{i + 1}] {r.get('title', 'N/A')}\n"
            f"URL: {r['url']}\n"
            f"Domain: {domain} | Quality: {r.get('quality', 0)} | Type: {r.get('source_type', 'general')}\n"
            f"Content:\n{content}\n"
        )
        if total_chars + len(block) > char_limit:
            break
        source_texts.append(block)
        total_chars += len(block)

    t0 = time.monotonic()
    try:
        raw = groq_chat(
            messages=[
                {"role": "system", "content": SYNTHESIS_SYSTEM},
                {
                    "role": "user",
                    "content": f"User question: {user_intent}\n"
                    f"Query type: {query_type}\n\n"
                    f"Sources ({len(source_texts)} of {len(ok)} usable):\n\n"
                    + "\n---\n".join(source_texts),
                },
            ],
            model=GROQ_MODEL_SYNTH,
            max_tokens=8000,
            temperature=0.3,
        )
        synth_fallback = _make_synth_fallback(user_intent, ok, "Groq returned empty")
        result = _extract_json(raw, synth_fallback)
        if "title" not in result:
            result = synth_fallback
    except Exception as e:
        sys.stderr.write(f"  [Synthesis FALLBACK] {e}\n")
        result = _make_synth_fallback(
            user_intent, ok, f"Groq-Synthese fehlgeschlagen: {e}"
        )

    dt = time.monotonic() - t0
    sys.stderr.write(f"  Step 6 (Synthesis): {dt:.2f}s\n")
    return result


# ── Step 7: Report-Rendering ──────────────────────────────────────────────────


def render_report(synthesis: dict, output_dir: str | None = None) -> str | None:
    """Render HTML-Report aus Synthese-JSON."""
    t0 = time.monotonic()

    if output_dir is None:
        output_dir = str(Path.home() / "shared" / "reports")
    os.makedirs(output_dir, exist_ok=True)

    # Titel für Dateinamen bereinigen
    title_slug = synthesis.get("title", "research")[:40]
    title_slug = (
        "".join(c if c.isalnum() or c in "-_ " else "" for c in title_slug)
        .strip()
        .replace(" ", "-")
        .lower()
    )
    date_str = datetime.now().strftime("%Y-%m-%d")
    output_path = os.path.join(output_dir, f"{title_slug}-{date_str}.html")

    # Report-Daten für Renderer aufbereiten
    report_data = {
        "t": synthesis.get("title", "Research"),
        "s": synthesis.get("subtitle", ""),
        "sections": [],
        "sources": [],
    }

    # TL;DR als erste Section
    if synthesis.get("tldr"):
        report_data["sections"].append(
            {
                "t": "TL;DR",
                "body": synthesis["tldr"],
            }
        )

    # Sections übernehmen
    for sec in synthesis.get("sections", []):
        section = {"t": sec.get("title", "")}
        if sec.get("highlights"):
            section["hl"] = sec["highlights"]
        if sec.get("body"):
            section["body"] = sec["body"]
        report_data["sections"].append(section)

    # Quellen
    for src in synthesis.get("sources", []):
        report_data["sources"].append(
            {
                "t": src.get("title", ""),
                "url": src.get("url", ""),
                "trust_level": "high"
                if src.get("quality", 0) >= 7
                else "medium"
                if src.get("quality", 0) >= 5
                else "low",
                "type": src.get("type", "general"),
            }
        )

    try:
        renderer = get_report_renderer()
        result_path = renderer.render("auto", report_data, output_path)
        dt = time.monotonic() - t0
        sys.stderr.write(f"  Step 7 (Report): {dt:.2f}s → {result_path}\n")
        return result_path
    except Exception as e:
        sys.stderr.write(f"  [Report FALLBACK] {e}\n")
        # Fallback: JSON-Datei statt HTML
        fallback_path = output_path.replace(".html", ".json")
        Path(fallback_path).write_text(
            json.dumps(report_data, indent=2, ensure_ascii=False)
        )
        return fallback_path


# ── Main Pipeline ──────────────────────────────────────────────────────────────


def run_pipeline(
    user_intent: str,
    force_mode: str | None = None,
    no_report: bool = False,
    no_synthesis: bool = False,
) -> dict:
    """Führe die gesamte Research-Pipeline autonom durch."""
    pipeline_start = time.monotonic()
    timings = {}

    # Step 1: Query-Generierung
    t0 = time.monotonic()
    query_plan = generate_queries(user_intent, force_mode)
    timings["query_gen"] = time.monotonic() - t0

    mode = query_plan["mode"]
    config = MODE_CONFIG.get(mode, MODE_CONFIG["standard"])
    queries = query_plan["queries"][: config["max_queries"]]
    freshness_weight = query_plan.get("freshness_weight", config["freshness_weight"])

    sys.stderr.write(f"\n{'=' * 60}\n")
    sys.stderr.write(
        f"  Mode: {mode} | Queries: {len(queries)} | FW: {freshness_weight}\n"
    )
    sys.stderr.write(f"{'=' * 60}\n\n")

    # Steps 2+3: Search + Crawl (Runde 1)
    t0 = time.monotonic()
    results_r1 = search_and_crawl(
        queries,
        depth=config["depth"],
        max_chars=config["max_chars"],
        freshness_weight=freshness_weight,
    )
    timings["search_crawl_r1"] = time.monotonic() - t0

    all_results = list(results_r1)

    # Step 4+5: Gap-Analysis + Expansion (nicht bei Quick)
    if config["expansion"] and results_r1:
        t0 = time.monotonic()
        gaps = analyze_gaps(user_intent, results_r1)
        timings["gap_analysis"] = time.monotonic() - t0

        expansion_queries = gaps.get("expansion_queries", [])
        if expansion_queries and not gaps.get("coverage_sufficient", True):
            sys.stderr.write(
                f"  Expansion: {len(expansion_queries)} follow-up queries\n"
            )
            t0 = time.monotonic()
            results_r2 = search_and_crawl(
                expansion_queries,
                depth=config["depth"],
                max_chars=config["max_chars"],
                freshness_weight=freshness_weight,
            )
            timings["search_crawl_r2"] = time.monotonic() - t0

            # Merge (dedup by URL)
            seen_urls = {r["url"] for r in all_results}
            for r in results_r2:
                if r["url"] not in seen_urls:
                    all_results.append(r)
                    seen_urls.add(r["url"])

    # Step 6: Synthese
    synthesis = None
    if not no_synthesis:
        t0 = time.monotonic()
        synthesis = synthesize(
            user_intent, all_results, query_plan.get("query_type", "research")
        )
        timings["synthesis"] = time.monotonic() - t0

    # Step 7: Report
    report_path = None
    if not no_report and config.get("report", True) and synthesis:
        t0 = time.monotonic()
        report_path = render_report(synthesis)
        timings["report"] = time.monotonic() - t0

    # Ergebnis zusammenbauen
    pipeline_total = time.monotonic() - pipeline_start
    timings["total"] = pipeline_total

    ok_results = [
        r for r in all_results if not r.get("error") and not r.get("boilerplate")
    ]

    output = {
        "synthesis": synthesis,
        "report_path": report_path,
        "sources_count": len(ok_results),
        "sources_total": len(all_results),
        "meta": {
            "mode": mode,
            "queries": queries,
            "query_type": query_plan.get("query_type", "research"),
            "freshness_weight": freshness_weight,
            "timings": {k: round(v, 2) for k, v in timings.items()},
            "pipeline_version": "v2",
        },
    }

    # Evidence Pack: strukturierte Rohdaten für Claude (falls eigene Synthese gewünscht)
    output["evidence_pack"] = {
        "top_sources": [
            {
                "url": r["url"],
                "title": r.get("title", "")[:100],
                "quality": r.get("quality", 0),
                "domain_tier": r.get("domain_tier", "standard"),
                "source_type": r.get("source_type", "general"),
                "content_preview": r.get("content", "")[:500],
            }
            for r in sorted(
                ok_results, key=lambda x: x.get("quality", 0), reverse=True
            )[:10]
        ],
        "quality_stats": {
            "avg": round(
                sum(r.get("quality", 0) for r in ok_results) / max(len(ok_results), 1),
                1,
            ),
            "max": max((r.get("quality", 0) for r in ok_results), default=0),
            "min": min((r.get("quality", 0) for r in ok_results), default=0),
        },
        "source_types": list({r.get("source_type", "general") for r in ok_results}),
        "domains": list(
            {r["url"].split("/")[2] for r in ok_results if "/" in r["url"]}
        ),
    }

    # Quellen-URLs für Claude (kompakt)
    output["source_urls"] = [
        {
            "url": r["url"],
            "title": r.get("title", "")[:80],
            "quality": r.get("quality", 0),
        }
        for r in ok_results[:20]
    ]

    sys.stderr.write(f"\n{'=' * 60}\n")
    sys.stderr.write(
        f"  DONE in {pipeline_total:.1f}s | {len(ok_results)} sources | mode={mode}\n"
    )
    for step, dt in timings.items():
        if step != "total":
            sys.stderr.write(f"    {step}: {dt:.2f}s\n")
    sys.stderr.write(f"{'=' * 60}\n")

    return output


# ── CLI ────────────────────────────────────────────────────────────────────────


def main():
    args = sys.argv[1:]
    force_mode = None
    no_report = False
    no_synthesis = False
    intent_parts = []

    i = 0
    while i < len(args):
        if args[i] == "--mode" and i + 1 < len(args):
            force_mode = args[i + 1]
            i += 2
        elif args[i] == "--no-report":
            no_report = True
            i += 1
        elif args[i] == "--no-synthesis":
            no_synthesis = True
            i += 1
        elif args[i] in ("--help", "-h"):
            print(__doc__)
            sys.exit(0)
        elif not args[i].startswith("--"):
            intent_parts.append(args[i])
            i += 1
        else:
            sys.stderr.write(f"  WARNUNG: Unbekanntes Flag '{args[i]}' ignoriert\n")
            i += 1

    if not intent_parts:
        sys.stderr.write(
            'Verwendung: web-search-v2.py [--mode quick|standard|deep] [--no-report] [--no-synthesis] "User-Intent"\n'
        )
        sys.exit(1)

    user_intent = " ".join(intent_parts)
    result = run_pipeline(user_intent, force_mode, no_report, no_synthesis)
    json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    import signal

    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    try:
        main()
    except KeyboardInterrupt:
        sys.stderr.write("\nAbgebrochen.\n")
        sys.exit(130)
    except BrokenPipeError:
        sys.stderr.close()
        sys.exit(1)
