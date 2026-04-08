#!/home/maetzger/.claude/tools/.venv/bin/python
"""Fast Search: Startpage-basierte URL-Discovery für den Research-Funnel.

Sucht via Startpage (Google-Proxy), gibt deduplizierte URLs als JSON aus.
Designed für Piping zu research-crawler.py. Ersetzt natives WebSearch komplett.

Verwendung:
    # Einfache Suche
    python3 fast-search.py "Claude Code MCP architecture 2026"

    # Mehrere Queries (dedupliziert)
    python3 fast-search.py "query1" "query2" "query3"

    # Pipe zu Crawler (Funnel Stage 1)
    python3 fast-search.py "q1" "q2" | python3 research-crawler.py --max-chars 500

    # Mit Snippets (für site:-Queries, Preise, TikTok-Daten)
    python3 fast-search.py --with-snippets "site:geizhals.de Apple Watch Ultra 2"

    # Geizhals Preisabfrage (Bestpreis + Top-Händler, 1 Call)
    python3 fast-search.py --geizhals "Apple Watch Ultra 2"

    # Max URLs pro Query (default: 10)
    python3 fast-search.py --max 5 "query"

    # Depth-Presets (setzt domain_cap + diversity_target + max/query automatisch)
    python3 fast-search.py --depth deep "q1" "q2" "q3"      # 15/query, 4/host, 25 target
    python3 fast-search.py --depth ultra "q1" "q2" "q3" "q4" # 20/query, 5/host, 50 target

    # Manuell: Individuelle Werte überschreiben (alternativ zu --depth)
    python3 fast-search.py --max 15 --diversity-target 25 --domain-cap 4 "q1" "q2" "q3"

    # Gesamt-URL-Limit (nach Dedup + Filterung, vor Ausgabe)
    python3 fast-search.py --max-urls 40 --depth ultra "q1" "q2" "q3"

    # DuckDuckGo als Engine (hat Snippets, aber Rate-Limits)
    python3 fast-search.py --engine ddg "query"

    # Funnel-Modus: Search + mehrstufiges Crawling in einem Call
    python3 fast-search.py --funnel 500,1500,6000 --quality-threshold 4,6 "q1" "q2"
"""

from __future__ import annotations

import json
import re  # noqa: F811 — used in _SOURCE_TYPE_RULES below
import sys
import time
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from selectolax.lexbor import LexborHTMLParser

# ProDesk 600 G3: i7-6700 (4C/8T, 32GB) — 6 Workers für parallele Queries
MAX_SEARCH_WORKERS = 6

# curl_cffi für TLS-Fingerprint-Impersonation (umgeht Bot-Detection)
try:
    from curl_cffi.requests import Session as CurlSession

    HAS_CURL_CFFI = True
except ImportError:
    CurlSession = None  # type: ignore[assignment,misc]
    HAS_CURL_CFFI = False

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
}

# Modul-weiter HTTP-Client (Connection-Reuse statt 3× neu aufbauen)
_http_client = None  # httpx.Client oder CurlSession


def _get_client():
    global _http_client
    if _http_client is None:
        if HAS_CURL_CFFI:
            _http_client = CurlSession(impersonate="chrome")
            sys.stderr.write("  [curl_cffi] Chrome-TLS aktiv\n")
        else:
            _http_client = httpx.Client(
                timeout=15, follow_redirects=True, headers=HEADERS
            )
            sys.stderr.write("  [httpx] Kein curl_cffi verfügbar\n")
    return _http_client


def _close_client():
    global _http_client
    if _http_client is not None:
        _http_client.close()
        _http_client = None


# Domains die nie nützlich sind
BLOCK_DOMAINS = {
    "youtube.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "pinterest.com",
    "tiktok.com",
    "reddit.com",  # Braucht MCP, kein HTTP
    "quora.com",
    # Datenbasiert: Noch blocked trotz curl_cffi (verifiziert 2026-03-15)
    "dl.acm.org",  # 403 auch mit curl_cffi
    "researchgate.net",  # 403 auch mit curl_cffi
    "psycnet.apa.org",  # 3/3 fail
    "open.spotify.com",  # 4/4 fail
    "opentable.de",  # 3/3 fail, timeout
    "tripadvisor.de",  # 403 auch mit curl_cffi
    "journals.sagepub.com",  # 3/3 fail, 403
    "aimgame.de",  # 3/3 fail, timeout
    "forums.raspberrypi.com",  # 403 auch mit curl_cffi
    "pubs.acs.org",  # Paywall
    "forums.linuxmint.com",  # 307 redirect loop
    # curl_cffi recovered (von Blocklist entfernt 2026-03-15):
    # alza.de, galaxus.de, idealo.de, mdpi.com, pcmag.com,
    # studocu.com, telegraph.co.uk, medium.com (+Subdomains), ebay.de
}

# Domains die per Suffix geblockt werden
# Medium-Subdomains: mit curl_cffi wieder erreichbar (2026-03-15)
BLOCK_DOMAIN_SUFFIXES = (
    # leer — Medium + Subdomains funktionieren jetzt mit curl_cffi
)


def _load_dynamic_blocklist() -> set[str]:
    """Domain-Blocklist aus skill_learnings laden (automatisch gelernt)."""
    try:
        import sqlite3
        from pathlib import Path

        db_path = Path(__file__).parent / "skill-tracker.db"
        if not db_path.exists():
            return set()
        db = sqlite3.connect(str(db_path))
        rows = db.execute(
            "SELECT pattern FROM skill_learnings "
            "WHERE category = 'domain_block' AND confidence >= 0.6"
        ).fetchall()
        db.close()
        return {r[0] for r in rows}
    except Exception:
        return set()


# Dynamische Blocklist beim Import laden (einmalig pro Prozess)
_DYNAMIC_BLOCKS = _load_dynamic_blocklist()


def _is_blocked(domain: str) -> bool:
    """Prüfe ob eine Domain geblockt ist (statisch + dynamisch + Suffix-Match)."""
    return (
        domain in BLOCK_DOMAINS
        or domain in _DYNAMIC_BLOCKS
        or domain.endswith(BLOCK_DOMAIN_SUFFIXES)
    )


def search_startpage(query: str, max_results: int = 10) -> list[dict]:
    """Suche via Startpage (Google-Proxy). Gibt URL + Titel + Snippet zurück."""
    try:
        client = _get_client()
        r = client.post(
            "https://www.startpage.com/sp/search",
            data={"query": query},
        )
        tree = LexborHTMLParser(r.text)
        results = []
        for el in tree.css(".result")[:max_results]:
            link = el.css_first("a.result-title")
            if not link:
                continue
            href = link.attrs.get("href", "")
            title = link.text(strip=True)
            # CSS-Bug fix: manchmal enthält der erste Titel CSS statt Text
            if title.startswith(".css-") or title.startswith("{"):
                title = ""
            # Snippet extrahieren
            desc = el.css_first(".description")
            snippet = desc.text(strip=True)[:300] if desc else ""
            if href.startswith("http"):
                domain = urlparse(href).netloc.removeprefix("www.")
                if not _is_blocked(domain):
                    results.append(
                        {
                            "url": href,
                            "title": title,
                            "domain": domain,
                            "snippet": snippet,
                        }
                    )
        return results
    except Exception as e:
        sys.stderr.write(f"  Startpage error: {e}\n")
        return []


def search_ddg(query: str, max_results: int = 10) -> list[dict]:
    """Suche via DuckDuckGo HTML endpoint. Hat Snippets, aber Rate-Limits."""
    try:
        client = _get_client()
        r = client.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
        )
        tree = LexborHTMLParser(r.text)
        results = []
        for el in tree.css(".result")[:max_results]:
            link = el.css_first(".result__a")
            snippet_el = el.css_first(".result__snippet")
            if link:
                href = link.attrs.get("href", "")
                if "uddg=" in href:
                    href = unquote(parse_qs(urlparse(href).query).get("uddg", [""])[0])
                title = link.text(strip=True)
                snippet = snippet_el.text(strip=True)[:200] if snippet_el else ""
                if href.startswith("http"):
                    domain = urlparse(href).netloc.removeprefix("www.")
                    if not _is_blocked(domain):
                        results.append(
                            {
                                "url": href,
                                "title": title,
                                "domain": domain,
                                "snippet": snippet,
                            }
                        )
        return results
    except Exception as e:
        sys.stderr.write(f"  DDG error: {e}\n")
        return []


def extract_geizhals_price(url: str) -> dict:
    """Extrahiere Bestpreis + Produktinfo von einer Geizhals-URL via og:-Meta-Tags."""
    try:
        client = _get_client()
        tree = LexborHTMLParser(client.get(url).text)
        price_el = tree.css_first('meta[property="og:price:amount"]')
        currency_el = tree.css_first('meta[property="og:price:currency"]')
        title_el = tree.css_first('meta[property="og:title"]')
        return {
            "url": url,
            "price": float(price_el.attrs["content"]) if price_el else None,
            "currency": currency_el.attrs.get("content", "EUR")
            if currency_el
            else "EUR",
            "title": title_el.attrs.get("content", "") if title_el else "",
        }
    except Exception as e:
        return {"url": url, "price": None, "error": str(e)}


# Tracking-Parameter die vor Dedup entfernt werden
_TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "utm_source_platform",
        "utm_creative_format",
        "fbclid",
        "gclid",
        "gclsrc",
        "dclid",
        "msclkid",
        "twclid",
        "mc_cid",
        "mc_eid",  # Mailchimp
        "ref",
        "ref_",
        "referer",
        "_ga",
        "_gl",
        "_hsenc",
        "_hsmi",  # Google Analytics / HubSpot
        "spm",
        "scm",  # Alibaba/Taobao
        "yclid",  # Yandex
    }
)


def canonicalize_url(url: str) -> str:
    """Entferne Tracking-Parameter und Fragment für saubere Dedup."""
    from urllib.parse import urlencode, urlparse, urlunparse

    parsed = urlparse(url)
    # Query-Parameter filtern
    params = parse_qs(parsed.query, keep_blank_values=False)
    clean_params = {
        k: v for k, v in params.items() if k.lower() not in _TRACKING_PARAMS
    }
    clean_query = urlencode(clean_params, doseq=True)
    # Fragment entfernen, Query säubern
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, clean_query, "")
    )


def deduplicate(results: list[dict]) -> list[dict]:
    """Dedupliziere nach kanonischer URL, behalte Reihenfolge."""
    seen = set()
    unique = []
    cleaned = 0
    for r in results:
        original_url = r["url"]
        canonical = canonicalize_url(original_url)
        if canonical != original_url:
            r["url"] = canonical
            cleaned += 1
        if canonical not in seen:
            seen.add(canonical)
            unique.append(r)
    if cleaned > 0:
        sys.stderr.write(f"  URL-Canonical: {cleaned} URLs bereinigt\n")
    dupes = len(results) - len(unique)
    if dupes > 0:
        sys.stderr.write(f"  Dedup: {dupes} Duplikate entfernt\n")
    return unique


# --- Source-Type Vorab-Klassifikation (URL-basiert, kein Crawl nötig) ---

_SOURCE_TYPE_RULES = [
    (
        re.compile(r"arxiv\.org|pubmed\.ncbi|/pmc/articles/|cochranelibrary\.com"),
        "academic",
    ),
    (
        re.compile(
            r"nature\.com/articles/|science\.org/doi/|thelancet\.com|bmj\.com|nejm\.org"
        ),
        "academic",
    ),
    (re.compile(r"frontiersin\.org/articles/|\.edu/|/research/|/paper"), "academic"),
    (re.compile(r"/docs/|/documentation/|/api/|/reference/"), "docs"),
    (re.compile(r"who\.int/|rki\.de/|cdc\.gov/"), "docs"),
    (
        re.compile(
            r"rtings\.com|soundguys\.com|tomshardware\.com|techradar\.com|"
            r"notebookcheck\.|chip\.de/test|computerbild\.de/artikel|"
            r"testberichte\.de|all3dp\.com|cnet\.com/reviews|wirecutter\.com|"
            r"/review/|/test/|/benchmark|/bestenliste"
        ),
        "review",
    ),
    # Manufacturer/Brand (Marketing-Bias)
    (
        re.compile(
            r"samsung\.com/|apple\.com/|sony\.|bose\.com/|sennheiser\.com/|"
            r"jabra\.com/|anker\.com/|bambulab\.com/|creality\.com/|"
            r"nvidia\.com/(?!developer)|amd\.com/(?!developer)|intel\.com/(?!developer)|"
            r"/product/|/produkt/|/shop/"
        ),
        "manufacturer",
    ),
    (re.compile(r"github\.com/.+/blob/|github\.com/.+/wiki"), "code"),
    (re.compile(r"/blog/|/posts?/"), "blog"),
    (re.compile(r"stackoverflow\.com|stackexchange\.com|/forum|forum\."), "forum"),
    (re.compile(r"geizhals\.|skinflint\.|pricespy\."), "price"),
    # Nachrichten (domain-basiert + path-basiert)
    (
        re.compile(
            r"reuters\.com|apnews\.com|bbc\.com|bbc\.co\.uk|theguardian\.com|"
            r"nytimes\.com|washingtonpost\.com|tagesschau\.de|zeit\.de/(?!zett)|"
            r"spiegel\.de|sueddeutsche\.de|faz\.net|dw\.com|"
            r"/news/|/artikel/|/article|/aktuell"
        ),
        "news",
    ),
    # Finanzen
    (
        re.compile(
            r"finanztip\.de|finanzfluss\.de|justetf\.com|extraetf\.com|"
            r"handelsblatt\.com|wiwo\.de|boerse\.de|onvista\.de|finanzen\.net|"
            r"/etf/|/sparplan|/geldanlage|/depot"
        ),
        "finance",
    ),
    # Lokale Bewertungen / Guides
    (
        re.compile(
            r"yelp\.(de|com)|falstaff\.com|tripadvisor\.|"
            r"prinz\.de|tip-berlin\.de|mit-vergnuegen\.|"
            r"feinschmecker\.de|geheimtippmuenchen\.de|"
            r"/restaurant|/geheimtipp|/lokaltipp"
        ),
        "local",
    ),
]


def _classify_source_type(url: str) -> str:
    """URL-basierte Source-Type-Klassifikation (leichtgewichtig, vor Crawl)."""
    for pattern, stype in _SOURCE_TYPE_RULES:
        if pattern.search(url):
            return stype
    return "general"


# --- Source-Credibility (Trust-Level pro Domain) ---
_CREDIBILITY_RULES = [
    # High trust: Primärquellen
    (
        re.compile(
            r"arxiv\.org|pubmed\.ncbi|cochranelibrary\.com|nature\.com/articles/|"
            r"science\.org/doi/|who\.int|rki\.de|cdc\.gov|efsa\.europa\.eu|"
            r"bfarm\.de|ema\.europa\.eu"
        ),
        "high",
    ),
    # High trust: Hersteller (authoritative für Specs, nicht für Qualitätsurteile)
    (
        re.compile(
            r"bambulab\.com|creality\.com|elegoo\.com|prusa3d\.com|anycubic\.com|"
            r"samsung\.com|apple\.com|sony\.|bose\.com|sennheiser\.com|"
            r"nvidia\.com|amd\.com|intel\.com|raspberrypi\.com|"
            r"developer\.mozilla\.org|docs\.python\.org"
        ),
        "high",
    ),
    # Medium trust: Unabhängige Tests/Reviews
    (
        re.compile(
            r"rtings\.com|tomshardware\.com|notebookcheck\.|chip\.de|"
            r"computerbild\.de|wirecutter\.com|cnet\.com|techradar\.com|"
            r"soundguys\.com|all3dp\.com|heise\.de|golem\.de|"
            r"testberichte\.de|stiftung-warentest\.de|finanztest\.de"
        ),
        "medium",
    ),
    # Medium trust: Preisvergleicher
    (re.compile(r"geizhals\.|idealo\.de|skinflint\.|pricespy\."), "medium"),
    # Low trust: Affiliate/Commercial/Booking patterns
    (
        re.compile(
            r"affiliate|deal|coupon|angebot.*vergleich|bestcheck\.|"
            r"mydealz\.de|schnaeppchenfuchs|"
            r"quandoo\.|opentable\.|bookatable\.|thefork\."
        ),
        "low",
    ),
]


def _classify_credibility(url: str, domain: str) -> str:
    """Domain-basierte Credibility-Klassifikation (high/medium/standard/low)."""
    for pattern, level in _CREDIBILITY_RULES:
        if pattern.search(url) or pattern.search(domain):
            return level
    return "standard"


def apply_domain_cap(results: list[dict], max_per_domain: int = 2) -> list[dict]:
    """Begrenze URLs pro Domain. Behält die zuerst gefundenen (höchstes Ranking)."""
    domain_counts: dict[str, int] = {}
    capped = []
    removed = 0
    for r in results:
        d = r.get("domain", "")
        domain_counts[d] = domain_counts.get(d, 0) + 1
        if domain_counts[d] <= max_per_domain:
            capped.append(r)
        else:
            removed += 1
    if removed > 0:
        sys.stderr.write(f"  Domain-Cap ({max_per_domain}/host): {removed} entfernt\n")
    return capped


def apply_diversity_selection(results: list[dict], target: int = 15) -> list[dict]:
    """Quelltyp-Diversität sicherstellen.

    Wenn ein Source-Type >50% der Ergebnisse ausmacht und wir >target URLs haben,
    kürze den überrepräsentierten Typ auf 50% (von hinten = niedrigstes Ranking).
    """
    if len(results) <= target:
        # Annotiere auch bei wenigen Ergebnissen
        for r in results:
            r["source_type"] = _classify_source_type(r["url"])
            r["credibility"] = _classify_credibility(r["url"], r.get("domain", ""))
        return results

    # Source-Types + Credibility annotieren
    for r in results:
        r["_source_type"] = _classify_source_type(r["url"])
        r["_credibility"] = _classify_credibility(r["url"], r.get("domain", ""))

    # Typ-Verteilung zählen
    type_counts: dict[str, int] = {}
    for r in results:
        t = r["_source_type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    max_per_type = max(len(results) // 2, 3)  # 50% Cap, mindestens 3
    trimmed = []
    type_kept: dict[str, int] = {}

    for r in results:
        t = r["_source_type"]
        type_kept[t] = type_kept.get(t, 0) + 1
        if type_kept[t] <= max_per_type:
            trimmed.append(r)

    removed = len(results) - len(trimmed)
    if removed > 0:
        # Typ-Statistik für stderr
        type_str = ", ".join(f"{t}={c}" for t, c in sorted(type_counts.items()))
        sys.stderr.write(
            f"  Diversity-Filter: {removed} entfernt "
            f"(Cap {max_per_type}/Typ) | Typen: {type_str}\n"
        )

    # Source-Type und Credibility als permanente Felder übernehmen
    for r in trimmed:
        r["source_type"] = r.pop("_source_type", "general")
        r["credibility"] = r.pop("_credibility", "standard")

    return trimmed


def ensure_coverage(
    results: list[dict], queries: list[str], search_fn, max_results: int
) -> list[dict]:
    """Intent-aware Coverage: Garantiere Mindestabdeckung kritischer Quelltypen.

    Bei Produkt/Vergleichs-Queries: mindestens 1 manufacturer + 1 review + 1 price.
    Bei Wissenschaft: mindestens 1 academic.
    """
    # Nur bei >5 Ergebnissen sinnvoll (sonst haben wir eh zu wenig)
    if len(results) < 5:
        return results

    # Quelltypen zählen
    types_present = set()
    for r in results:
        st = r.get("source_type") or _classify_source_type(r["url"])
        types_present.add(st)

    # Prüfe ob Query ein Produktvergleich/Kaufberatung ist
    query_text = " ".join(queries).lower()
    is_product = any(
        kw in query_text
        for kw in [
            "test",
            "vergleich",
            "best",
            "review",
            "kaufen",
            "empfehlung",
            "unter",
            "euro",
            "€",
            "budget",
            "printer",
            "drucker",
            "kopfhörer",
            "headphone",
            "gpu",
            "monitor",
            "laptop",
            "tablet",
            "kamera",
        ]
    )
    is_academic = any(
        kw in query_text
        for kw in [
            "study",
            "studie",
            "research",
            "paper",
            "meta-analysis",
            "clinical",
            "trial",
            "efficacy",
            "wirkung",
        ]
    )
    is_news = any(
        kw in query_text
        for kw in [
            "news",
            "aktuell",
            "nachrichten",
            "meldung",
            "breaking",
            "release",
            "launch",
            "announce",
            "ankündig",
            "timeline",
            "regulation",
            "gesetz",
            "verordnung",
            "umsetzung",
        ]
    )
    is_finance = any(
        kw in query_text
        for kw in [
            "etf",
            "sparplan",
            "broker",
            "depot",
            "aktie",
            "fond",
            "anlage",
            "rendite",
            "zinsen",
            "finanzen",
            "investier",
            "geldanlage",
            "portfolio",
            "dividende",
            "kredit",
            "tagesgeld",
        ]
    )
    is_local = any(
        kw in query_text
        for kw in [
            "restaurant",
            "geheimtipp",
            "café",
            "cafe",
            "kneipe",
            "essen gehen",
            "stadtteil",
            "viertel",
            "schwabing",
            "kreuzberg",
            "altstadt",
            "innenstadt",
        ]
    )

    补充_queries = []

    if is_product:
        if "manufacturer" not in types_present:
            # Versuche Hersteller-Seite zu finden
            补充_queries.append(
                f"site:bambulab.com OR site:creality.com OR site:elegoo.com {queries[0]}"
            )
        if "price" not in types_present:
            补充_queries.append(f"site:geizhals.de {queries[0]}")

    if is_academic and "academic" not in types_present:
        补充_queries.append(f"site:pubmed.ncbi.nlm.nih.gov {queries[0]}")

    if is_news and "news" not in types_present:
        补充_queries.append(
            f"site:reuters.com OR site:tagesschau.de OR site:spiegel.de {queries[0]}"
        )

    if is_finance and "finance" not in types_present:
        补充_queries.append(
            f"site:finanztip.de OR site:justetf.com OR site:finanzfluss.de {queries[0]}"
        )

    if is_local and "local" not in types_present:
        补充_queries.append(f"{queries[0]} Erfahrungen Bewertungen Geheimtipp")

    if not 补充_queries:
        return results

    sys.stderr.write(
        f"  Coverage-Fill: {len(补充_queries)} Nachsuchen für fehlende Typen\n"
    )
    fill_max = max(3, max_results // 3)
    if len(补充_queries) == 1:
        extras = [search_fn(补充_queries[0], fill_max)]
    else:
        from concurrent.futures import ThreadPoolExecutor

        workers = min(MAX_SEARCH_WORKERS, len(补充_queries))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            extras = list(pool.map(lambda q: search_fn(q, fill_max), 补充_queries))

    for extra in extras:
        for r in extra:
            if not any(existing["domain"] == r["domain"] for existing in results):
                results.append(r)

    return results


def main():
    # Argparse manuell (leichtgewichtig, keine Dependency)
    args = sys.argv[1:]
    engine = "startpage"
    max_results = 10
    max_urls_total = 0  # 0 = kein Gesamt-Limit
    with_snippets = False
    geizhals_mode = False
    funnel_stages = None
    quality_thresholds = None
    diversity_target = 15  # Default: 15 URLs Diversity-Target
    domain_cap = 2  # Default: 2 URLs pro Domain
    depth_mode = None  # None = nicht gesetzt, manuelle Werte gelten
    # Track welche Flags explizit gesetzt wurden (für --depth Komposition)
    _explicit_flags: set[str] = set()
    queries = []

    i = 0
    while i < len(args):
        if args[i] == "--engine" and i + 1 < len(args):
            engine = args[i + 1]
            i += 2
        elif args[i] == "--max" and i + 1 < len(args):
            max_results = int(args[i + 1])
            _explicit_flags.add("max")
            i += 2
        elif args[i] == "--max-urls" and i + 1 < len(args):
            max_urls_total = int(args[i + 1])
            i += 2
        elif args[i] == "--depth" and i + 1 < len(args):
            depth_mode = args[i + 1]
            i += 2
        elif args[i] == "--diversity-target" and i + 1 < len(args):
            diversity_target = int(args[i + 1])
            _explicit_flags.add("diversity_target")
            i += 2
        elif args[i] == "--domain-cap" and i + 1 < len(args):
            domain_cap = int(args[i + 1])
            _explicit_flags.add("domain_cap")
            i += 2
        elif args[i] == "--with-snippets":
            with_snippets = True
            i += 1
        elif args[i] == "--geizhals":
            geizhals_mode = True
            i += 1
        elif args[i] == "--funnel" and i + 1 < len(args):
            funnel_stages = [int(x) for x in args[i + 1].split(",")]
            i += 2
        elif args[i] == "--quality-threshold" and i + 1 < len(args):
            quality_thresholds = [float(x) for x in args[i + 1].split(",")]
            i += 2
        elif args[i] == "--help" or args[i] == "-h":
            print(__doc__)
            sys.exit(0)
        elif re.match(r"^[012]?>>?", args[i]):
            # Shell-Redirect (z.B. "2>/tmp/file", ">out.json") als Arg geleakt → überspringen
            sys.stderr.write(f"  WARNUNG: Shell-Redirect '{args[i]}' ignoriert\n")
            i += 1
            # Separater Pfad nach Redirect (z.B. "2>" "/tmp/file")
            if (
                args[i - 1].rstrip(">") == ""
                and i < len(args)
                and not args[i].startswith("--")
            ):
                i += 1
        elif not args[i].startswith("--"):
            queries.append(args[i])
            i += 1
        else:
            sys.stderr.write(f"  WARNUNG: Unbekanntes Flag '{args[i]}' ignoriert\n")
            i += 1  # Flag überspringen
            # Wenn nächstes Arg kein Flag ist, gehört es zum unbekannten Flag → auch überspringen
            if i < len(args) and not args[i].startswith("--"):
                sys.stderr.write(
                    f"  WARNUNG: '{args[i]}' übersprungen (Wert von unbekanntem Flag)\n"
                )
                i += 1

    if not queries:
        sys.stderr.write(
            "Verwendung: fast-search.py [--engine startpage|ddg] [--max N] "
            "[--max-urls N] [--depth quick|standard|deep|ultra] "
            "[--with-snippets] [--geizhals] QUERY...\n"
        )
        sys.exit(1)

    # --depth Preset: Setzt Defaults, explizite Flags gewinnen immer
    if depth_mode is not None:
        _depth_presets = {
            "quick": {"domain_cap": 2, "diversity_target": 10, "max_results": 8},
            "standard": {"domain_cap": 2, "diversity_target": 15, "max_results": 10},
            "deep": {"domain_cap": 4, "diversity_target": 25, "max_results": 15},
            "ultra": {"domain_cap": 5, "diversity_target": 50, "max_results": 20},
        }
        if depth_mode not in _depth_presets:
            sys.stderr.write(
                f"  FEHLER: Ungültiger --depth Modus '{depth_mode}'. "
                f"Gültig: {', '.join(_depth_presets)}\n"
            )
            sys.exit(1)
        _preset = _depth_presets[depth_mode]
        # Nur überschreiben wenn NICHT explizit per Flag gesetzt
        if "domain_cap" not in _explicit_flags:
            domain_cap = _preset["domain_cap"]
        if "diversity_target" not in _explicit_flags:
            diversity_target = _preset["diversity_target"]
        if "max" not in _explicit_flags:
            max_results = _preset["max_results"]
        sys.stderr.write(
            f"  Depth: {depth_mode} (domain_cap={domain_cap}, "
            f"diversity_target={diversity_target}, max/query={max_results})\n"
        )

    # Geizhals-Modus: Automatisch site:geizhals.de + Preisextraktion
    if geizhals_mode:
        run_geizhals(queries)
        return

    search_fn = search_ddg if engine == "ddg" else search_startpage
    fallback_fn = search_startpage if engine == "ddg" else search_ddg
    all_results = []
    start = time.monotonic()

    def _search_one(q):
        """Eine Query ausführen mit Fallback."""
        sys.stderr.write(f"  Searching: {q}\n")
        results = search_fn(q, max_results)
        if not results:
            sys.stderr.write(f"    → 0 URLs, Fallback auf {fallback_fn.__name__}...\n")
            results = fallback_fn(q, max_results)
        sys.stderr.write(f"    → {len(results)} URLs\n")
        return results

    if len(queries) == 1:
        all_results = _search_one(queries[0])
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        workers = min(MAX_SEARCH_WORKERS, len(queries))
        sys.stderr.write(f"  Parallel: {len(queries)} Queries × {workers} Workers\n")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_search_one, q): q for q in queries}
            for fut in as_completed(futures):
                all_results.extend(fut.result())

    all_results = deduplicate(all_results)
    all_results = ensure_coverage(all_results, queries, search_fn, max_results)
    all_results = deduplicate(all_results)  # Dedup nach Coverage-Fill
    all_results = apply_domain_cap(all_results, max_per_domain=domain_cap)
    all_results = apply_diversity_selection(all_results, target=diversity_target)

    # Gesamt-URL-Limit anwenden (nach Filterung, vor Ausgabe)
    if max_urls_total > 0 and len(all_results) > max_urls_total:
        sys.stderr.write(f"  Max-URLs-Limit: {len(all_results)} → {max_urls_total}\n")
        all_results = all_results[:max_urls_total]

    elapsed = time.monotonic() - start
    depth_info = f", depth={depth_mode}" if depth_mode else ""

    sys.stderr.write(
        f"  Total: {len(all_results)} unique URLs in {elapsed:.1f}s "
        f"({len(queries)} queries via {engine}{depth_info})\n"
    )

    if funnel_stages:
        # Funnel-Modus: Führe mehrstufiges Crawling automatisch durch
        run_funnel(all_results, funnel_stages, quality_thresholds or [])
    elif with_snippets:
        # Vollständige Ergebnisse mit Snippets + Metadaten als JSON ausgeben
        json.dump(
            [
                {
                    "url": r["url"],
                    "title": r.get("title", ""),
                    "snippet": r.get("snippet", ""),
                    "domain": r.get("domain", ""),
                    "source_type": r.get(
                        "source_type", _classify_source_type(r["url"])
                    ),
                    "credibility": r.get(
                        "credibility",
                        _classify_credibility(r["url"], r.get("domain", "")),
                    ),
                }
                for r in all_results
            ],
            sys.stdout,
            indent=2,
            ensure_ascii=False,
        )
        sys.stdout.write("\n")
    else:
        # URL-Liste als JSON-Array ausgeben (kompatibel mit research-crawler.py stdin)
        json.dump([r["url"] for r in all_results], sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        # Metadaten auf stderr
        sys.stderr.write("  Domains: ")
        domains = {}
        for r in all_results:
            domains[r["domain"]] = domains.get(r["domain"], 0) + 1
        for d, c in sorted(domains.items(), key=lambda x: -x[1])[:10]:
            sys.stderr.write(f"{d}({c}) ")
        sys.stderr.write("\n")


def _geizhals_one(q: str) -> dict:
    """Eine Geizhals-Query ausführen: Suche → Preisextraktion."""
    search_query = f"site:geizhals.de {q}"
    sys.stderr.write(f"  Geizhals-Suche: {q}\n")
    results = search_startpage(search_query, max_results=5)
    sys.stderr.write(f"    → {len(results)} Geizhals-URLs\n")

    if not results:
        return {"query": q, "error": "Keine Geizhals-Treffer"}

    best_url = results[0]["url"]
    price_data = extract_geizhals_price(best_url)

    if price_data.get("price"):
        sys.stderr.write(
            f"    Bestpreis: {price_data['price']:.2f} "
            f"{price_data.get('currency', 'EUR')}\n"
        )
    else:
        sys.stderr.write("    Preis nicht extrahierbar\n")

    return {
        "query": q,
        "bestprice": price_data.get("price"),
        "currency": price_data.get("currency", "EUR"),
        "product": price_data.get("title", ""),
        "url": best_url,
        "variants": [
            {"url": r["url"], "title": r.get("title", "")} for r in results[1:]
        ],
    }


def run_geizhals(queries: list[str]):
    """Geizhals-Preisabfrage: site:-Suche → Bestpreis per og:price:amount."""
    start = time.monotonic()

    if len(queries) == 1:
        all_results = [_geizhals_one(queries[0])]
    else:
        from concurrent.futures import ThreadPoolExecutor

        workers = min(MAX_SEARCH_WORKERS, len(queries))
        sys.stderr.write(f"  Parallel: {len(queries)} Produkte × {workers} Workers\n")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            all_results = list(pool.map(_geizhals_one, queries))

    elapsed = time.monotonic() - start
    sys.stderr.write(f"  Geizhals komplett in {elapsed:.1f}s\n")

    json.dump(all_results, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def run_funnel(
    initial_results: list[dict],
    stages: list[int],
    quality_thresholds: list[float],
):
    """Mehrstufiges Crawling: Search → Shallow → Medium → Deep.

    Jede Stufe filtert nach Quality-Threshold, dann crawlt tiefer.
    Gibt nach der letzten Stufe das finale JSON auf stdout aus.

    In-Process-Import von research-crawler.crawl() statt subprocess.run()
    (Performance-Audit 2026-03-28: spart ~500ms/Stage Python-Startup).
    """
    import asyncio
    import importlib.util
    from pathlib import Path

    # research-crawler.py als Modul laden (Dateiname mit Bindestrich → importlib)
    crawler_path = Path(__file__).parent / "research-crawler.py"
    spec = importlib.util.spec_from_file_location("research_crawler", crawler_path)
    crawler_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(crawler_mod)

    urls = [r["url"] for r in initial_results]

    for stage_idx, max_chars in enumerate(stages):
        if not urls:
            sys.stderr.write(f"  Stage {stage_idx + 1}: No URLs left, stopping.\n")
            break

        sys.stderr.write(
            f"  Stage {stage_idx + 1}/{len(stages)}: "
            f"{len(urls)} URLs × {max_chars} chars\n"
        )

        # Globale Variable im Crawler-Modul setzen (statt CLI-Flag)
        crawler_mod.MAX_CHARS_PER_URL = max_chars

        # In-Process crawl() Aufruf
        try:
            results_raw = asyncio.run(crawler_mod.crawl(urls))
        except Exception as e:
            sys.stderr.write(f"  Crawler failed at stage {stage_idx + 1}: {e}\n")
            break

        # Ergebnis-Dicts aufbereiten (gleicher Output wie CLI-Modus)
        results = []
        for r in results_raw:
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

        # Letzte Stufe → alles ausgeben
        if stage_idx == len(stages) - 1:
            json.dump(results, sys.stdout, indent=2, ensure_ascii=False)
            sys.stdout.write("\n")
            ok = [r for r in results if not r.get("error") and not r.get("boilerplate")]
            sys.stderr.write(
                f"  Final: {len(ok)} usable results, "
                f"~{sum(r.get('chars', 0) for r in ok) // 3:,} tokens\n"
            )
            break

        # Zwischen-Stufe → filtern
        threshold = (
            quality_thresholds[stage_idx] if stage_idx < len(quality_thresholds) else 4
        )
        good = [
            r["url"]
            for r in results
            if r.get("quality", 0) > threshold
            and not r.get("boilerplate")
            and not r.get("error")
        ]
        dropped = len(urls) - len(good)
        sys.stderr.write(
            f"    Filter (Q>{threshold}): {len(good)} kept, {dropped} dropped\n"
        )
        urls = good

    sys.stderr.write("  Funnel complete.\n")


if __name__ == "__main__":
    import signal

    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    try:
        main()
    except BrokenPipeError:
        sys.stderr.close()
        sys.exit(1)
    finally:
        _close_client()
