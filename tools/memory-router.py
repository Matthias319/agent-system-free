#!/home/maetzger/.claude/tools/.venv/bin/python
"""Memory Router — search Zettelkasten notes via Meilisearch with Composite Scoring.

Combines embedding similarity, recency decay, importance and access frequency
into a single score for better memory retrieval (inspired by CrewAI's memory system).

Usage:
    uv run ./tools/memory-router.py --query "video transkribieren"
    uv run ./tools/memory-router.py --query "api key" --limit 5
    uv run ./tools/memory-router.py --query "groq" --min-importance 1.0
    uv run ./tools/memory-router.py --query "test" --debug
"""

import argparse
import json
import math
import sys
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MEILI_URL = "http://127.0.0.1:7700"
MEILI_KEY = "G8CnrlKGM2Hu-XZryzsIlGZoCsafBkGC84oUTinA2jo"

# Composite Score Gewichte
W_SIMILARITY = 0.50  # Embedding/Ranking-Similarity
W_RECENCY = 0.25  # Recency Decay
W_IMPORTANCE = 0.20  # Importance Score (normalisiert)
W_ACCESS = 0.05  # Access Frequency Bonus

RECENCY_HALF_LIFE = 30  # Tage bis Score auf 50% fällt


def _compute_recency(updated_at: str) -> float:
    """Exponentieller Recency-Decay: exp(-days * ln(2) / half_life).

    Ergebnis: 1.0 = heute, 0.5 = vor 30 Tagen, 0.25 = vor 60 Tagen.
    """
    try:
        updated = datetime.fromisoformat(updated_at)
        days = max((datetime.now() - updated).total_seconds() / 86400, 0)
        return math.exp(-days * math.log(2) / RECENCY_HALF_LIFE)
    except (ValueError, TypeError):
        return 0.5  # Fallback bei ungültigem Datum


def _normalize_importance(importance: float) -> float:
    """Importance auf 0-1 normalisieren (max erwarteter Wert: 2.0)."""
    return min(importance / 2.0, 1.0)


def _access_bonus(access_count: int) -> float:
    """Logarithmischer Access-Bonus: log2(1 + count) / log2(11).

    Sättigt bei ~10 Zugriffen nahe 1.0.
    """
    return min(math.log2(1 + access_count) / math.log2(11), 1.0)


def _composite_score(
    ranking_score: float,
    updated_at: str,
    importance: float,
    access_count: int,
) -> float:
    """Berechnet gewichteten Composite Score aus allen Faktoren.

    Formel: 0.50 * similarity + 0.25 * recency + 0.20 * importance_norm + 0.05 * access_bonus
    """
    sim = ranking_score  # bereits 0-1 von Meilisearch
    rec = _compute_recency(updated_at)
    imp = _normalize_importance(importance)
    acc = _access_bonus(access_count)

    return W_SIMILARITY * sim + W_RECENCY * rec + W_IMPORTANCE * imp + W_ACCESS * acc


def search_memories(query, limit=3, min_importance=0.0, debug=False):
    """Search the memories index with Composite Scoring.

    Holt mehr Kandidaten als angefragt (3x limit, min 10), berechnet
    Composite Score aus Similarity + Recency + Importance + Access,
    und gibt die Top-N nach Re-Ranking zurück.
    """
    # Mehr Kandidaten holen damit Re-Ranking wirkt
    fetch_limit = max(limit * 3, 10)

    body = {
        "q": query,
        "limit": fetch_limit,
        "matchingStrategy": "frequency",
        "showRankingScore": True,
    }
    if min_importance > 0:
        body["filter"] = f"importance >= {min_importance}"

    headers = {
        "Authorization": f"Bearer {MEILI_KEY}",
        "Content-Type": "application/json",
    }
    req = Request(
        f"{MEILI_URL}/indexes/memories/search",
        data=json.dumps(body).encode(),
        headers=headers,
        method="POST",
    )

    try:
        with urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read().decode())
    except (HTTPError, URLError, OSError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        print("[]")
        return

    hits = result.get("hits", [])

    # Composite Score berechnen und re-ranken
    scored_hits = []
    for hit in hits:
        ranking_score = hit.get("_rankingScore", 0.5)
        updated_at = hit.get("updated_at", "")
        importance = hit.get("importance", 1.0)
        access_count = hit.get("access_count", 0)

        score = _composite_score(ranking_score, updated_at, importance, access_count)

        if debug:
            recency = _compute_recency(updated_at)
            print(
                f"  #{hit.get('zettel_id', '?'):>3} "
                f"sim={ranking_score:.3f} rec={recency:.3f} "
                f"imp={importance:.1f} acc={access_count} "
                f"\u2192 composite={score:.4f}  {hit.get('title', '')[:50]}",
                file=sys.stderr,
            )

        scored_hits.append((score, hit))

    # Nach Composite Score absteigend sortieren
    scored_hits.sort(key=lambda x: x[0], reverse=True)

    output = []
    for score, hit in scored_hits[:limit]:
        content = hit.get("content", "")
        preview = content[:200].replace("\n", " ").strip()
        if len(content) > 200:
            preview += "..."
        output.append(
            {
                "id": hit.get("zettel_id", 0),
                "title": hit.get("title", ""),
                "importance": hit.get("importance", 0),
                "tags": hit.get("tags", []),
                "composite_score": round(score, 4),
                "preview": preview,
            }
        )

    print(json.dumps(output, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(
        description="Search Zettelkasten via Meilisearch with Composite Scoring"
    )
    parser.add_argument("--query", "-q", required=True, help="Search query")
    parser.add_argument("--limit", "-l", type=int, default=3, help="Max results")
    parser.add_argument(
        "--min-importance", type=float, default=0.0, help="Min importance filter"
    )
    parser.add_argument(
        "--debug", action="store_true", help="Zeige Score-Aufschlüsselung pro Hit"
    )
    args = parser.parse_args()

    search_memories(args.query, args.limit, args.min_importance, args.debug)


if __name__ == "__main__":
    main()
