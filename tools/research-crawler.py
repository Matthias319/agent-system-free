#!/home/maetzger/.claude/tools/.venv/bin/python
"""
Research-Crawler: Parallele Content-Extraktion mit httpx + trafilatura.

Nimmt URLs entgegen (JSON via stdin oder CLI-Argumente), extrahiert den
Haupttext parallel und gibt strukturiertes JSON auf stdout zurück.
Statistik auf stderr.

Verwendung:
    # CLI-Argumente
    python3 research-crawler.py "https://example.com" "https://example.org"

    # JSON via stdin
    echo '["https://example.com", "https://example.org"]' | python3 research-crawler.py

    # Mit Content-Limit pro URL
    python3 research-crawler.py --max-chars 6000 "https://example.com"
"""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import sys
import time
from html import unescape as html_unescape
from urllib.parse import urlparse

import httpx
import trafilatura

# curl_cffi für TLS-Fingerprint-Impersonation (umgeht Bot-Detection)
try:
    from curl_cffi.requests import AsyncSession as CurlAsyncSession

    HAS_CURL_CFFI = True
except ImportError:
    CurlAsyncSession = None  # type: ignore[assignment,misc]
    HAS_CURL_CFFI = False

# Konfiguration — ProDesk 600 G3 (i7-6700, 4C/8T, 32GB)
MAX_CONCURRENT = 32  # Global-Semaphore (Codex-Empfehlung: 32 mit Per-Domain-Throttle)
MAX_PER_DOMAIN = 2  # Per-Domain-Semaphore (verhindert 429/403-Bursts)
TIMEOUT_SECONDS = 12
MAX_CHARS_PER_URL = 0  # 0 = kein Limit, wird via --max-chars gesetzt
FRESHNESS_WEIGHT = 1.0  # Freshness-Gewichtung (CLI: --freshness-weight)
EXTRACTOR_VERSION = "3"  # Bumped: full-content cache + selectolax-triage (2026-03-28)

# Cache-TTL nach Source-Type (Sekunden)
CACHE_TTL = {
    "news": 3600,  # 1h
    "blog": 21600,  # 6h
    "forum": 14400,  # 4h
    "docs": 86400,  # 24h
    "code": 86400,  # 24h
    "review": 43200,  # 12h
    "price": 1800,  # 30min
    "video": 43200,  # 12h
    "manufacturer": 86400,  # 24h
    "finance": 3600,  # 1h (Kurse/Konditionen ändern sich)
    "local": 43200,  # 12h (Restaurants/Bewertungen stabil)
    "default": 14400,  # 4h
}
# Negative Cache-TTL für Fehler
CACHE_TTL_ERROR = {
    "timeout": 300,  # 5min (transient)
    "429": 600,  # 10min (rate limit)
    "403": 3600,  # 1h (bot detection — unlikely to change soon)
    "404": 86400,  # 24h (gone)
    "default": 600,  # 10min
}
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Boilerplate-Patterns die auf Nav-Müll oder nicht-extrahierten Content hinweisen
BOILERPLATE_PATTERNS = [
    r"Hover to load",
    r"View All\]",
    r"Cookie\s*(Policy|Settings|Consent)",
    r"Accept\s*All\s*Cookies",
    r"Enable\s*JavaScript",
    r"Please\s*enable\s*JS",
    r"Performing\s*security\s*verification",
]
BOILERPLATE_RE = re.compile("|".join(BOILERPLATE_PATTERNS), re.IGNORECASE)


# ── URL-Cache ────────────────────────────────────────────────────────────────


def _normalize_url(url: str) -> str:
    """URL normalisieren: lowercase scheme/host, Fragment weg, Query sortiert, utm_* weg."""
    from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

    p = urlparse(url)
    host = (p.hostname or "").lower().removeprefix("www.")
    # Query-Parameter: utm_*, gclid, fbclid entfernen, Rest sortieren
    params = parse_qs(p.query, keep_blank_values=True)
    clean_params = {
        k: v
        for k, v in sorted(params.items())
        if not k.startswith("utm_") and k not in ("gclid", "fbclid", "srsltid")
    }
    clean_query = urlencode(clean_params, doseq=True)
    # Fragment komplett entfernen, Path beibehalten
    return urlunparse((p.scheme.lower(), host, p.path, p.params, clean_query, ""))


def _init_cache_db() -> "sqlite3.Connection | None":
    """Cache-DB initialisieren. Gibt Connection zurück oder None bei Fehler."""
    import sqlite3
    from pathlib import Path

    db_path = Path(__file__).parent / "url-cache.db"
    try:
        db = sqlite3.connect(str(db_path), timeout=5)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=3000")
        db.execute("""
            CREATE TABLE IF NOT EXISTS url_cache (
                normalized_url    TEXT PRIMARY KEY,
                requested_url     TEXT NOT NULL,
                final_url         TEXT NOT NULL DEFAULT '',
                source_type       TEXT NOT NULL DEFAULT 'general',
                status            TEXT NOT NULL DEFAULT 'ok',
                title             TEXT NOT NULL DEFAULT '',
                content           TEXT NOT NULL DEFAULT '',
                chars             INTEGER NOT NULL DEFAULT 0,
                pub_date          TEXT,
                etag              TEXT,
                last_modified     TEXT,
                error             TEXT,
                extractor_version TEXT NOT NULL,
                fetched_at        INTEGER NOT NULL,
                expires_at        INTEGER NOT NULL,
                hit_count         INTEGER NOT NULL DEFAULT 0
            )
        """)
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_cache_expires ON url_cache(expires_at)"
        )
        db.commit()
        return db
    except Exception as e:
        sys.stderr.write(f"  Cache-DB Fehler: {e}\n")
        return None


def _cache_get(db: "sqlite3.Connection", url: str) -> "dict | None":
    """Cache-Lookup. Gibt gecachtes Ergebnis zurück oder None bei Miss/Expired."""
    norm = _normalize_url(url)
    now = int(time.time())
    row = db.execute(
        """SELECT requested_url, final_url, source_type, status, title, content,
                  chars, pub_date, etag, last_modified, error, extractor_version,
                  fetched_at, expires_at
           FROM url_cache WHERE normalized_url = ? AND expires_at > ?
           AND extractor_version = ?""",
        (norm, now, EXTRACTOR_VERSION),
    ).fetchone()
    if row is None:
        return None
    # Hit-Count erhöhen
    db.execute(
        "UPDATE url_cache SET hit_count = hit_count + 1 WHERE normalized_url = ?",
        (norm,),
    )
    return {
        "url": row[0],  # requested_url
        "source_type": row[2],
        "status": row[3],
        "title": row[4],
        "content": row[5],
        "chars": row[6],
        "pub_date": row[7],
        "etag": row[8],
        "last_modified": row[9],
        "error": row[10],
        "cached": True,
    }


def _cache_put(
    db: "sqlite3.Connection",
    url: str,
    result: dict,
    source_type: str = "general",
) -> None:
    """Ergebnis in Cache schreiben."""
    norm = _normalize_url(url)
    now = int(time.time())
    # TTL bestimmen
    if result.get("error"):
        err = result["error"]
        if "Timeout" in err:
            ttl = CACHE_TTL_ERROR["timeout"]
        elif "429" in err:
            ttl = CACHE_TTL_ERROR["429"]
        elif "403" in err:
            ttl = CACHE_TTL_ERROR["403"]
        elif "404" in err:
            ttl = CACHE_TTL_ERROR["404"]
        else:
            ttl = CACHE_TTL_ERROR["default"]
    else:
        ttl = CACHE_TTL.get(source_type, CACHE_TTL["default"])
    db.execute(
        """INSERT OR REPLACE INTO url_cache
           (normalized_url, requested_url, final_url, source_type, status,
            title, content, chars, pub_date, error, extractor_version,
            fetched_at, expires_at, hit_count)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
        (
            norm,
            url,
            result.get("final_url", url),
            source_type,
            "error" if result.get("error") else "ok",
            result.get("title", ""),
            result.get("content", ""),
            result.get("chars", 0),
            result.get("pub_date"),
            result.get("error"),
            EXTRACTOR_VERSION,
            now,
            now + ttl,
        ),
    )


def _cache_cleanup(db: "sqlite3.Connection") -> int:
    """Abgelaufene Einträge löschen. Gibt Anzahl gelöschter Zeilen zurück."""
    now = int(time.time())
    cursor = db.execute("DELETE FROM url_cache WHERE expires_at <= ?", (now,))
    db.commit()
    return cursor.rowcount


# ── Domain-Authority-Tiers ───────────────────────────────────────────────────

# Domain-Authority-Tiers (Microsoft Credibility Critic Pattern)
DOMAIN_AUTHORITY = {
    "high": {
        # Tech / AI
        "arxiv.org",
        "anthropic.com",
        "openai.com",
        "ai.meta.com",
        "research.google",
        "deepmind.google",
        "docs.python.org",
        "developer.mozilla.org",
        "w3.org",
        "ietf.org",
        "github.com",
        "huggingface.co",
        "pytorch.org",
        "tensorflow.org",
        "microsoft.com",
        # Wissenschaft / Medizin
        "nature.com",
        "science.org",
        "acm.org",
        "ieee.org",
        "ncbi.nlm.nih.gov",  # PubMed + PMC
        "pubmed.ncbi.nlm.nih.gov",
        "cochranelibrary.com",
        "who.int",
        "thelancet.com",
        "bmj.com",
        "nejm.org",
        "cell.com",
        "pnas.org",
        "nih.gov",
        "cdc.gov",
        # Deutsche Forschung
        "dkfz.de",
        "rki.de",
        "mpg.de",
        "fraunhofer.de",
        "helmholtz.de",
        "dfg.de",
        # Allgemeinwissen
        "wikipedia.org",
        # Recht / Gesetzgebung (DE + EU)
        "gesetze-im-internet.de",
        "dejure.org",
        "recht.bund.de",
        "rechtsprechung-im-internet.de",
        "eur-lex.europa.eu",
        # Consumer / Verbraucherschutz
        "test.de",  # Stiftung Warentest
        "verbraucherzentrale.de",
        # Umwelt / Klima
        "umweltbundesamt.de",
        # Statistik / Daten
        "ec.europa.eu",  # Eurostat + EU-Policy
        "oecd.org",
        "data.worldbank.org",
        "govdata.de",
        # DACH Recht
        "ris.bka.gv.at",  # AT-Rechtsinformationssystem
        "fedlex.admin.ch",  # CH-Bundesrecht
        "admin.ch",
        # Tech (fehlte trotz hoher Nutzung)
        "stackoverflow.com",
    },
    "medium": {
        "dev.to",
        "arstechnica.com",
        "theregister.com",
        "heise.de",
        "golem.de",
        "chip.de",
        "techcrunch.com",
        "theverge.com",
        "wired.com",
        "thenewstack.io",
        "infoq.com",
        "realpython.com",
        "martinfowler.com",
        "simonwillison.net",
        "lilianweng.github.io",
        "redis.io",
        "nginx.org",
        # Wissenschaft / Medizin (medium)
        "biomedcentral.com",
        "springer.com",
        "sciencedirect.com",
        "wiley.com",
        "frontiersin.org",
        "mdpi.com",
        "pharmawiki.ch",
        "gelbe-liste.de",
        "drugbank.com",
        "drugs.com",
        "uptodate.com",
        "amboss.com",
        "drugcom.de",
        # Deutsche Wissens-Quellen
        "bpb.de",
        "destatis.de",
        "bundesregierung.de",
        # Nachrichten (international)
        "reuters.com",
        "apnews.com",
        "bbc.com",
        "bbc.co.uk",
        "theguardian.com",
        "nytimes.com",
        "washingtonpost.com",
        # Nachrichten (deutsch)
        "tagesschau.de",
        "zeit.de",
        "spiegel.de",
        "sueddeutsche.de",
        "faz.net",
        "dw.com",
        # Finanzen
        "finanztip.de",
        "finanzfluss.de",
        "justetf.com",
        "extraetf.com",
        "handelsblatt.com",
        "wiwo.de",
        "boerse.de",
        "onvista.de",
        # Lokale Bewertungen / Guides
        "yelp.de",
        "yelp.com",
        "falstaff.com",
        "prinz.de",
        "tip-berlin.de",
        "muenchen.de",
        "berlin.de",
        "hamburg.de",
        "feinschmecker.de",
        "geheimtippmuenchen.de",
        "mit-vergnuegen.com",
        "cntraveller.de",
        # DIY / Maker / Hardware
        "raspberrypi.com",
        "adafruit.com",
        "sparkfun.com",
        "instructables.com",
        "hackaday.com",
        "all3dp.com",
        "tomshardware.com",
        "notebookcheck.net",
        "phoronix.com",
        "anandtech.com",
        "servethehome.com",
        # Recht (medium)
        "bundesgerichtshof.de",
        "bundesverfassungsgericht.de",
        "bmj.de",
        "bundesanzeiger.de",
        # DACH Nachrichten
        "derstandard.at",
        "nzz.ch",
        "orf.at",
        "srf.ch",
        "oesterreich.gv.at",
        # Consumer / Tests
        "oekotest.de",
        "rtings.com",
        "adac.de",
        "lebensmittelwarnung.de",
        # Umwelt / Klima / Wetter
        "dwd.de",
        "bfn.de",
        "umweltbundesamt.at",
        "bafu.admin.ch",
        # Statistik DACH
        "statistik.at",
        "data.gv.at",
        "opendata.swiss",
        # Tech (medium)
        "go.dev",
        "rust-lang.org",
        "docs.docker.com",
        "kubernetes.io",
    },
}

# Source-Type-Klassifikation anhand URL-Patterns
SOURCE_TYPE_PATTERNS = [
    (r"arxiv\.org/abs/|arxiv\.org/pdf/", "academic"),
    (r"pubmed\.ncbi|/pmc/articles/|cochranelibrary\.com", "academic"),
    (
        r"nature\.com/articles/|science\.org/doi/|thelancet\.com|bmj\.com|nejm\.org",
        "academic",
    ),
    (r"frontiersin\.org/articles/|mdpi\.com/\d+", "academic"),
    (r"\.edu/|/research/|/paper", "academic"),
    (r"/docs/|/documentation/|/api/|/reference/", "docs"),
    (r"pharmawiki\.ch|gelbe-liste\.de|drugbank\.com|drugs\.com", "docs"),
    (r"who\.int/|rki\.de/|cdc\.gov/|dkfz\.de/", "docs"),
    (r"github\.com/.+/blob/|github\.com/.+/wiki", "code"),
    # Review/Test-Quellen (Autoresearch Runde 3: 16/17 "general" bei Produkt-Vergleich)
    (
        r"rtings\.com|soundguys\.com|tomshardware\.com|techradar\.com|"
        r"notebookcheck\.|chip\.de/test|computerbild\.de/artikel|"
        r"testberichte\.de|hifi-forum\.de|kopfhoerer\.de|"
        r"all3dp\.com|3djake\.|cnet\.com/reviews|wirecutter\.com|"
        r"phoronix\.com|servethehome\.com|hackaday\.com|anandtech\.com|"
        r"/review/|/test/|/benchmark|/bestenliste",
        "review",
    ),
    # Manufacturer/Brand-Seiten (Marketing-Bias, Specs oft geschönt)
    (
        r"samsung\.com/|apple\.com/|sony\.|bose\.com/|sennheiser\.com/|"
        r"jabra\.com/|anker\.com/|bambulab\.com/|creality\.com/|"
        r"nvidia\.com/(?!developer)|amd\.com/(?!developer)|intel\.com/(?!developer)|"
        r"/product/|/produkt/|/shop/",
        "manufacturer",
    ),
    (r"/blog/|/posts?/|medium\.com/", "blog"),
    (r"stackoverflow\.com|stackexchange\.com|/forum|forum\.", "forum"),
    (r"youtube\.com|youtu\.be", "video"),
    # Nachrichten-Quellen (erweitert)
    (
        r"reuters\.com|apnews\.com|bbc\.com|bbc\.co\.uk|theguardian\.com|"
        r"nytimes\.com|washingtonpost\.com|tagesschau\.de|zeit\.de/(?!zett)|"
        r"spiegel\.de|sueddeutsche\.de|faz\.net|dw\.com|"
        r"derstandard\.at|nzz\.ch",
        "news",
    ),
    (r"/news/|/artikel/|/article|/aktuell", "news"),
    # Finanz-Quellen
    (
        r"finanztip\.de|finanzfluss\.de|justetf\.com|extraetf\.com|"
        r"handelsblatt\.com|wiwo\.de|boerse\.de|onvista\.de|"
        r"finanzen\.net|wallstreetjournal\.com|bloomberg\.com|"
        r"/etf/|/sparplan|/geldanlage|/depot",
        "finance",
    ),
    # Lokale Bewertungen / Guides
    (
        r"yelp\.(de|com)|falstaff\.com|tripadvisor\.|"
        r"prinz\.de|tip-berlin\.de|mit-vergnuegen\.|"
        r"muenchen\.de|berlin\.de|hamburg\.de|"
        r"/restaurant|/geheimtipp|/stadtfuehr|/lokaltipp",
        "local",
    ),
    # Preis/Shop-Quellen
    (r"geizhals\.|idealo\.|amazon\.|skinflint\.|pricespy\.", "price"),
]


def _load_preferred_domains() -> set[str]:
    """Domain-Prefer Learnings aus skill_learnings laden (automatisch gelernt)."""
    try:
        import sqlite3
        from pathlib import Path

        db_path = Path(__file__).parent / "skill-tracker.db"
        if not db_path.exists():
            return set()
        db = sqlite3.connect(str(db_path))
        rows = db.execute(
            "SELECT pattern FROM skill_learnings "
            "WHERE category = 'domain_prefer' AND confidence >= 0.7"
        ).fetchall()
        db.close()
        return {r[0] for r in rows}
    except Exception:
        return set()


# Beim Import laden (einmalig pro Prozess)
_PREFERRED_DOMAINS = _load_preferred_domains()


def _classify_url(url: str) -> tuple[str, int, str]:
    """Domain-Tier und Source-Type aus URL ableiten.

    Returns (domain_tier, domain_bonus, source_type).
    Nutzt DOMAIN_AUTHORITY (statisch) + domain_prefer Learnings (dynamisch).
    """
    domain = urlparse(url).netloc.removeprefix("www.") if url else ""
    domain_tier = "standard"
    domain_bonus = 0
    for tier, domains in DOMAIN_AUTHORITY.items():
        if any(domain.endswith(d) or domain == d for d in domains):
            domain_tier = tier
            domain_bonus = 2 if tier == "high" else 1
            break

    # Dynamischer Bonus: domain_prefer Learnings (+1 Quality)
    if domain_bonus == 0 and domain in _PREFERRED_DOMAINS:
        domain_bonus = 1
        domain_tier = "learned"

    source_type = "general"
    for pattern, stype in SOURCE_TYPE_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            source_type = stype
            break

    return domain_tier, domain_bonus, source_type


# Date-Patterns für Fallback-Extraktion aus Content
DATE_PATTERNS = [
    re.compile(r"(\d{4}-\d{2}-\d{2})"),  # ISO: 2026-03-01
    re.compile(r"Published\s+(?:on\s+)?(\w+\s+\d{1,2},?\s+\d{4})", re.IGNORECASE),
    re.compile(r"Updated\s+(?:on\s+)?(\w+\s+\d{1,2},?\s+\d{4})", re.IGNORECASE),
]


def _extract_pub_date_meta(html: str) -> str | None:
    """Publikationsdatum aus HTML-Meta-Tags und <time>-Elementen extrahieren."""
    from datetime import date as _date

    # Meta-Tags mit Priorität (häufigste zuerst)
    _META_PATTERNS = [
        re.compile(
            r'<meta\s+(?:[^>]*?)property\s*=\s*["\']article:published_time["\']'
            r'\s+(?:[^>]*?)content\s*=\s*["\']([^"\']+)["\']',
            re.IGNORECASE,
        ),
        re.compile(
            r'<meta\s+(?:[^>]*?)content\s*=\s*["\']([^"\']+)["\']'
            r'\s+(?:[^>]*?)property\s*=\s*["\']article:published_time["\']',
            re.IGNORECASE,
        ),
        re.compile(
            r'<meta\s+(?:[^>]*?)name\s*=\s*["\']date["\']'
            r'\s+(?:[^>]*?)content\s*=\s*["\']([^"\']+)["\']',
            re.IGNORECASE,
        ),
        re.compile(
            r'<meta\s+(?:[^>]*?)content\s*=\s*["\']([^"\']+)["\']'
            r'\s+(?:[^>]*?)name\s*=\s*["\']date["\']',
            re.IGNORECASE,
        ),
        re.compile(r'<time\s+[^>]*datetime\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE),
    ]
    # Nur im <head> + ersten 5K suchen (Performance)
    snippet = html[:5000]
    for pat in _META_PATTERNS:
        m = pat.search(snippet)
        if m:
            raw = m.group(1).strip()
            # ISO-8601 mit optionalem Zeitanteil: "2026-03-01T12:00:00Z" → "2026-03-01"
            iso_date = raw[:10]
            try:
                _date.fromisoformat(iso_date)
                return iso_date
            except ValueError:
                continue
    return None


def extract_pub_date(html: str, url: str) -> str | None:
    """Publikationsdatum extrahieren: Meta-Tags → trafilatura → None."""
    # Schneller Meta-Tag-Check zuerst (kein trafilatura-Overhead)
    meta_date = _extract_pub_date_meta(html)
    if meta_date:
        return meta_date
    # Fallback: trafilatura bare_extraction
    try:
        result = trafilatura.bare_extraction(html, url=url, with_metadata=True)
        if result:
            pub_date = getattr(result, "date", None)
            if pub_date:
                return str(pub_date)  # ISO-Format: "2026-03-01"
    except Exception:
        pass
    return None


def _parse_english_date(raw: str) -> str | None:
    """Parse englische Datumsformate wie 'March 1, 2026' → '2026-03-01'."""
    import calendar

    months = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
    months.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
    parts = raw.replace(",", "").split()
    if len(parts) == 3:
        month_str, day_str, year_str = parts
        month = months.get(month_str.lower())
        if month:
            try:
                return f"{int(year_str):04d}-{month:02d}-{int(day_str):02d}"
            except ValueError:
                pass
    return None


def extract_pub_date_fallback(content: str) -> str | None:
    """Fallback: Datum aus Content via Regex extrahieren."""
    from datetime import date as _date

    for pattern in DATE_PATTERNS:
        match = pattern.search(content[:2000])  # Nur Anfang durchsuchen
        if match:
            raw = match.group(1)
            # ISO-Format direkt zurückgeben
            try:
                _date.fromisoformat(raw)
                return raw
            except ValueError:
                pass
            # Englisches Datumsformat parsen (March 1, 2026)
            parsed = _parse_english_date(raw)
            if parsed:
                return parsed
    return None


def compute_freshness_bonus(pub_date: str | None) -> int:
    """Freshness-Bonus basierend auf Publikationsdatum."""
    from datetime import date as _date

    if not pub_date:
        return 0  # Unbekannt = neutral
    try:
        days_old = (_date.today() - _date.fromisoformat(pub_date)).days
    except ValueError:
        return 0

    if days_old <= 30:
        bonus = 2  # Letzter Monat
    elif days_old <= 90:
        bonus = 1  # Letzte 3 Monate
    elif days_old <= 365:
        bonus = 0  # Letztes Jahr
    elif days_old <= 730:
        bonus = -1  # 1-2 Jahre
    else:
        bonus = -2  # >2 Jahre

    return int(bonus * FRESHNESS_WEIGHT)


def compute_quality(
    content: str, chars: int, url: str = "", pub_date: str | None = None
) -> dict:
    """Qualitäts-Score mit Domain-Authority und Source-Type.

    Returns dict mit quality (0-10), reason, is_boilerplate,
    domain_tier, source_type.
    """
    domain_tier, domain_bonus, source_type = _classify_url(url)
    base_meta = {
        "domain_tier": domain_tier,
        "source_type": source_type,
    }

    if not content or chars < 50:
        return {
            "quality": 0,
            "reason": "kein Content",
            "is_boilerplate": True,
            **base_meta,
        }

    boilerplate_matches = len(BOILERPLATE_RE.findall(content))
    lines = content.split("\n")
    non_empty_lines = [line for line in lines if line.strip()]
    avg_line_len = sum(len(line) for line in non_empty_lines) / max(
        len(non_empty_lines), 1
    )

    # Boilerplate-Check: >3 Matches
    if boilerplate_matches > 3:
        return {
            "quality": 2,
            "reason": f"{boilerplate_matches} Boilerplate-Patterns",
            "is_boilerplate": True,
            **base_meta,
        }

    # Zu kurz für sinnvollen Content
    if chars < 200:
        return {
            "quality": 1,
            "reason": "zu kurz (<200 chars)",
            "is_boilerplate": True,
            **base_meta,
        }

    # Qualitäts-Indikatoren
    headings = len([line for line in lines if line.startswith("#")])
    numbers = len([w for w in content.split() if any(c.isdigit() for c in w)])
    paragraphs = len([line for line in non_empty_lines if len(line) > 100])

    score = 5  # Basis-Score
    if headings >= 3:
        score += 1
    if headings >= 8:
        score += 1
    if numbers >= 20:
        score += 1
    if paragraphs >= 5:
        score += 1
    if avg_line_len > 60:
        score += 1
    if chars < 500:
        score -= 2
    if boilerplate_matches > 0:
        score -= 1

    # Domain-Authority-Bonus
    score += domain_bonus

    # Manufacturer-Malus (Marketing-Bias: Specs oft geschönt, kein unabhängiger Test)
    if source_type == "manufacturer":
        score -= 2

    # Freshness-Bonus
    freshness_bonus = compute_freshness_bonus(pub_date)
    score += freshness_bonus

    score = max(1, min(10, score))
    return {
        "quality": score,
        "reason": "ok",
        "is_boilerplate": False,
        "freshness_bonus": freshness_bonus,
        "pub_date": pub_date,
        **base_meta,
    }


# ── Cross-Referencing: Claim-Extraktion ──────────────────────────────────────


def extract_claims(results: list[dict]) -> list[dict]:
    """Extrahiere faktische Behauptungen aus Crawl-Ergebnissen und zähle Quellenübereinstimmungen.

    Sucht nach Zahlen, Vergleichen und Bewertungen in den Texten und gruppiert
    ähnliche Claims über Quellen hinweg. Gibt eine Liste von Claims mit
    Quellenzuordnung zurück.
    """
    import re as _re
    from collections import defaultdict

    # Patterns für extrahierbare Claims
    claim_patterns = [
        # Zahlen mit Einheit (z.B. "500 mm/s", "40h Akku", "108 MP")
        _re.compile(
            r"(\d+[\.,]?\d*)\s*(mm/s|MB/s|GB/s|Wh|mAh|MP|fps|Hz|nits|dB|lm|W|kg|g|mm|cm|m|"
            r"GB|TB|GHz|MHz|ms|μs|ns|EUR|€|\$|USD|Stunden|hours|h)\b",
            _re.IGNORECASE,
        ),
        # Prozentangaben
        _re.compile(r"(\d+[\.,]?\d*)\s*(%|Prozent|percent)", _re.IGNORECASE),
        # Vergleichsaussagen ("X ist besser/schneller/günstiger als Y")
        _re.compile(
            r"([\w-]+)\s+(?:ist|is|war|are)\s+"
            r"(besser|schlechter|schneller|langsamer|günstiger|teurer|"
            r"better|worse|faster|slower|cheaper|more expensive)\s+"
            r"(?:als|than)\s+([\w-]+)",
            _re.IGNORECASE,
        ),
        # Bewertungen/Scores ("8.5/10", "4.5 von 5", "92%")
        _re.compile(
            r"(\d+[\.,]?\d*)\s*(?:/|von|out of)\s*(\d+)",
            _re.IGNORECASE,
        ),
    ]

    # Claims pro Quelle extrahieren
    all_claims = []
    for r in results:
        if r.get("error") or r.get("is_boilerplate") or not r.get("content"):
            continue

        content = r["content"][:8000]  # Nur ersten 8K analysieren
        url = r["url"]
        domain = r.get("domain_tier", "standard")
        source_type = r.get("source_type", "general")

        for pattern in claim_patterns:
            for match in pattern.finditer(content):
                # Kontext extrahieren (50 chars vor und nach dem Match)
                start = max(0, match.start() - 50)
                end = min(len(content), match.end() + 50)
                context = content[start:end].replace("\n", " ").strip()

                all_claims.append(
                    {
                        "claim": match.group(0).strip(),
                        "context": context,
                        "url": url,
                        "domain_tier": domain,
                        "source_type": source_type,
                        "quality": r.get("quality", 0),
                    }
                )

    # Claims gruppieren: gleiche Zahlen/Einheiten über Quellen hinweg
    claim_groups = defaultdict(list)
    for c in all_claims:
        # Normalisiere den Claim für Gruppierung (lowercase, Leerzeichen normalisieren)
        key = _re.sub(r"\s+", " ", c["claim"].lower().strip())
        # Komma→Punkt für Zahlenvergleich
        key = key.replace(",", ".")
        claim_groups[key].append(c)

    # Nur Claims mit >=2 UNABHÄNGIGEN Quellen sind cross-referenziert
    # (Codex-Review: len(claims)>=2 war falsch — gleiche URL kann mehrfach matchen)
    cross_referenced = []
    for key, claims in sorted(
        claim_groups.items(), key=lambda x: -len({c["url"] for c in x[1]})
    ):
        unique_sources = list({c["url"] for c in claims})
        if len(unique_sources) >= 2:
            # avg_quality über unique Sources, nicht raw Matches
            seen_urls: set[str] = set()
            quality_sum = 0.0
            for c in claims:
                if c["url"] not in seen_urls:
                    seen_urls.add(c["url"])
                    quality_sum += c["quality"]
            cross_referenced.append(
                {
                    "claim": claims[0]["claim"],
                    "source_count": len(unique_sources),
                    "sources": unique_sources[:5],
                    "avg_quality": round(quality_sum / len(unique_sources), 1),
                    "context_sample": claims[0]["context"],
                }
            )

    return cross_referenced[:30]  # Top-30 cross-referenced Claims


MAX_HTML_BYTES = 2 * 1024 * 1024  # 2MB — genug für schwere Seiten (inline JS/CSS)


async def _fetch_html(
    url: str,
    curl_session,  # CurlAsyncSession | None
    httpx_client: httpx.AsyncClient,
) -> str:
    """HTML abrufen: curl_cffi → httpx-Fallback bei Fehler. Size-Limit 512KB."""
    last_err = None

    # Versuch 1: curl_cffi (Chrome-TLS-Impersonation)
    if curl_session is not None:
        try:
            r = await curl_session.get(
                url, timeout=TIMEOUT_SECONDS, allow_redirects=True
            )
            # Nicht-HTML skippen (PDF, Bilder, Downloads)
            ct = r.headers.get("content-type", "")
            if ct and not any(t in ct for t in ("text/html", "text/plain", "xml")):
                raise ValueError(f"Nicht-HTML: {ct.split(';')[0]}")
            if r.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"HTTP {r.status_code}",
                    request=None,  # type: ignore[arg-type]
                    response=type("R", (), {"status_code": r.status_code})(),  # type: ignore[arg-type]
                )
            text = r.text
            if len(text) > MAX_HTML_BYTES:
                text = text[:MAX_HTML_BYTES]
            return text
        except (ValueError, httpx.HTTPStatusError):
            raise  # Nicht-HTML und HTTP-Fehler nicht mit httpx retryen
        except Exception as e:
            last_err = e
            # Fallthrough zu httpx

    # Versuch 2: httpx (Fallback wenn curl_cffi fehlt ODER fehlgeschlagen)
    try:
        response = await httpx_client.get(url, follow_redirects=True)
        ct = response.headers.get("content-type", "")
        if ct and not any(t in ct for t in ("text/html", "text/plain", "xml")):
            raise ValueError(f"Nicht-HTML: {ct.split(';')[0]}")
        response.raise_for_status()
        text = response.text
        if len(text) > MAX_HTML_BYTES:
            text = text[:MAX_HTML_BYTES]
        return text
    except Exception:
        # Wenn beide scheitern, den aussagekräftigeren Fehler werfen
        if last_err is not None:
            raise last_err
        raise


def _extract_selectolax(html: str) -> str:
    """Lightweight-Extraktion via selectolax (10-50x schneller als trafilatura).

    Für Triage-Phase (--max-chars < 1500): kein Markdown, keine Links,
    aber ausreichend für Boilerplate-Erkennung und grobe Quality-Bewertung.
    """
    try:
        from selectolax.lexbor import LexborHTMLParser

        tree = LexborHTMLParser(html)
        for tag in tree.css("nav,header,footer,script,style,aside,form"):
            tag.decompose()
        body = tree.body
        text = body.text(separator="\n", strip=True) if body else ""
        lines = [line for line in text.split("\n") if line.strip()]
        return "\n".join(lines)
    except Exception:
        return ""


def _extract_content_sync(html: str, url: str) -> tuple[str, str | None]:
    """Synchrone Content-Extraktion (läuft im ThreadPool, nicht im Event-Loop).

    Returns: (content, pub_date)
    Bei Triage (MAX_CHARS_PER_URL < 1500): selectolax-first (10-50x schneller).
    Sonst: trafilatura für strukturiertes Markdown mit Links und Tabellen.
    """
    content = None
    pub_date = None

    # Triage-Modus: selectolax-first (Performance-Audit 2026-03-28)
    if 0 < MAX_CHARS_PER_URL < 1500:
        content = _extract_selectolax(html)
        pub_date = extract_pub_date_fallback(content) if content else None
        return content or "", pub_date

    # Standard/Deep: volle trafilatura-Extraktion
    try:
        content = trafilatura.extract(
            html,
            url=url,
            output_format="markdown",
            include_links=True,
            include_tables=True,
            include_comments=False,
            deduplicate=True,
        )
    except Exception:
        pass

    # Fallback: selectolax wenn trafilatura fehlschlägt
    if not content:
        content = _extract_selectolax(html)

    # Datum: nur Regex (billig). bare_extraction-Fallback entfernt (Performance-Audit
    # 2026-03-28: doppelter trafilatura-Parse eliminiert, Freshness-Bonus=0 bei Miss).
    pub_date = extract_pub_date_fallback(content) if content else None

    return content or "", pub_date


async def fetch_and_extract(
    curl_session,  # CurlAsyncSession | None
    httpx_client: httpx.AsyncClient,
    fetch_semaphore: asyncio.Semaphore,
    extract_semaphore: asyncio.Semaphore,
    url: str,
    domain_semaphore: asyncio.Semaphore | None = None,
) -> dict:
    """URL abrufen und extrahieren mit entkoppelten Semaphoren.

    Separate Semaphoren für echtes Pipelining (Performance-Audit 2026-03-28):
    - fetch_semaphore (32): begrenzt parallele HTTP-Requests
    - extract_semaphore (CPU_COUNT): begrenzt CPU-bound trafilatura-Extraktion
    - domain_semaphore (2/domain): verhindert 429/403-Bursts (nur für Fetch)

    Fetch gibt seinen Slot frei BEVOR Extract startet → neue URLs können
    bereits fetchen während andere noch extrahieren.
    """
    t0 = time.monotonic()
    try:
        # ── Fetch-Phase (I/O-bound) ──
        async with fetch_semaphore:
            if domain_semaphore is not None:
                await domain_semaphore.acquire()
            try:
                html = await _fetch_html(url, curl_session, httpx_client)
            finally:
                if domain_semaphore is not None:
                    domain_semaphore.release()
        t_fetch = time.monotonic()

        # Titel sofort extrahieren (billig, Regex)
        title_match = re.search(
            r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL
        )
        title = title_match.group(1).strip() if title_match else url
        title = html_unescape(title)

        # ── Extract-Phase (CPU-bound) ──
        async with extract_semaphore:
            loop = asyncio.get_running_loop()
            content, pub_date = await loop.run_in_executor(
                None, _extract_content_sync, html, url
            )
        t_extract = time.monotonic()
        fetch_ms = int((t_fetch - t0) * 1000)
        extract_ms = int((t_extract - t_fetch) * 1000)

        # Content-Limit: NICHT hier kürzen — voller Content wird gecacht.
        # Kürzung erfolgt in crawl() nach cache_put (Cache/Depth-Fix).
        full_content = content or ""
        full_chars = len(full_content)
        quality = compute_quality(full_content, full_chars, url, pub_date)
        latency = int((time.monotonic() - t0) * 1000)

        return {
            "url": url,
            "title": title,
            "content": full_content,
            "chars": full_chars,
            "quality": quality["quality"],
            "is_boilerplate": quality["is_boilerplate"],
            "domain_tier": quality.get("domain_tier", "standard"),
            "source_type": quality.get("source_type", "general"),
            "pub_date": pub_date,
            "freshness_bonus": quality.get("freshness_bonus", 0),
            "latency_ms": latency,
            "fetch_ms": fetch_ms,
            "extract_ms": extract_ms,
            "error": None,
        }

    except (httpx.TimeoutException, TimeoutError):
        latency = int((time.monotonic() - t0) * 1000)
        domain_tier, _, source_type = _classify_url(url)
        return {
            "url": url,
            "title": "",
            "content": "",
            "chars": 0,
            "quality": 0,
            "is_boilerplate": False,
            "domain_tier": domain_tier,
            "source_type": source_type,
            "latency_ms": latency,
            "error": f"Timeout nach {TIMEOUT_SECONDS}s",
        }
    except httpx.HTTPStatusError as e:
        latency = int((time.monotonic() - t0) * 1000)
        domain_tier, _, source_type = _classify_url(url)
        return {
            "url": url,
            "title": "",
            "content": "",
            "chars": 0,
            "quality": 0,
            "is_boilerplate": False,
            "domain_tier": domain_tier,
            "source_type": source_type,
            "latency_ms": latency,
            "error": f"HTTP {e.response.status_code}",
        }
    except Exception as e:
        latency = int((time.monotonic() - t0) * 1000)
        domain_tier, _, source_type = _classify_url(url)
        return {
            "url": url,
            "title": "",
            "content": "",
            "chars": 0,
            "quality": 0,
            "is_boilerplate": False,
            "domain_tier": domain_tier,
            "source_type": source_type,
            "latency_ms": latency,
            "error": str(e),
        }


def _get_domain(url: str) -> str:
    """Registrable Domain aus URL extrahieren (für Per-Domain-Throttling)."""
    try:
        from urllib.parse import urlparse

        host = urlparse(url).hostname or ""
        parts = host.split(".")
        # TLD+1: "www.example.co.uk" → "example.co.uk"
        return ".".join(parts[-2:]) if len(parts) >= 2 else host
    except Exception:
        return "unknown"


async def crawl(urls: list[str], use_cache: bool = True) -> list[dict]:
    """Alle URLs parallel abrufen mit Global- und Per-Domain-Throttling + Cache."""
    # Triage-Modus (selectolax-first): Cache deaktivieren um Poisoning zu vermeiden.
    # selectolax-Plaintext darf nicht als kanonischer Cache-Eintrag gespeichert werden,
    # da spätere Deep-Stages trafilatura-Markdown erwarten (Codex-Review 2026-03-28).
    if 0 < MAX_CHARS_PER_URL < 1500:
        use_cache = False

    # ── Cache-Phase: Hits sofort zurückgeben ──────────────────────────────
    cache_db = _init_cache_db() if use_cache else None
    cached_results: dict[str, dict] = {}  # url → result
    urls_to_fetch: list[str] = []

    if cache_db is not None:
        cleaned = _cache_cleanup(cache_db)
        if cleaned > 0:
            sys.stderr.write(f"  Cache: {cleaned} expired entries cleaned\n")
        for url in urls:
            hit = _cache_get(cache_db, url)
            if hit is not None:
                # Quality auf vollem Content berechnen (Kürzung erfolgt am Ende von crawl())
                content = hit["content"]
                chars = len(content) if content else 0
                quality = compute_quality(content, chars, url, hit.get("pub_date"))
                cached_results[url] = {
                    "url": hit["url"],
                    "title": hit.get("title", ""),
                    "content": content,
                    "chars": chars,
                    "quality": quality["quality"],
                    "is_boilerplate": quality["is_boilerplate"],
                    "domain_tier": quality.get("domain_tier", "standard"),
                    "source_type": hit.get("source_type", "general"),
                    "pub_date": hit.get("pub_date"),
                    "freshness_bonus": quality.get("freshness_bonus", 0),
                    "latency_ms": 0,
                    "fetch_ms": 0,
                    "extract_ms": 0,
                    "error": hit.get("error") if hit["status"] == "error" else None,
                }
            else:
                urls_to_fetch.append(url)
        n_hits = len(cached_results)
        if n_hits > 0:
            sys.stderr.write(f"  Cache: {n_hits} hits, {len(urls_to_fetch)} to fetch\n")
    else:
        urls_to_fetch = list(urls)

    # ── Fetch-Phase: nur Cache-Misses abrufen ────────────────────────────
    fetch_results: list[dict] = []
    if urls_to_fetch:
        # Entkoppelte Semaphoren (Performance-Audit 2026-03-28):
        # - fetch: I/O-bound, viele parallele Requests ok
        # - extract: CPU-bound, auf Kernanzahl begrenzen
        import os

        cpu_count = os.cpu_count() or 4
        fetch_semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        extract_semaphore = asyncio.Semaphore(cpu_count)

        # Per-Domain-Semaphores
        domain_semaphores: dict[str, asyncio.Semaphore] = {}
        for url in urls_to_fetch:
            domain = _get_domain(url)
            if domain not in domain_semaphores:
                domain_semaphores[domain] = asyncio.Semaphore(MAX_PER_DOMAIN)

        n_domains = len(domain_semaphores)
        sys.stderr.write(
            f"  Throttling: fetch={MAX_CONCURRENT}, extract={cpu_count}, "
            f"{MAX_PER_DOMAIN}/domain ({n_domains} domains)\n"
        )

        # curl_cffi
        curl_session = None
        if HAS_CURL_CFFI:
            curl_session = CurlAsyncSession(impersonate="chrome")
            sys.stderr.write("  [curl_cffi] Chrome-TLS-Impersonation aktiv\n")
        else:
            sys.stderr.write("  [httpx] Kein curl_cffi — TLS-Fingerprint erkennbar\n")

        transport = httpx.AsyncHTTPTransport(retries=2)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(TIMEOUT_SECONDS),
            headers={"User-Agent": USER_AGENT},
            transport=transport,
            limits=httpx.Limits(max_connections=48, max_keepalive_connections=16),
        ) as httpx_client:
            tasks = [
                fetch_and_extract(
                    curl_session,
                    httpx_client,
                    fetch_semaphore,
                    extract_semaphore,
                    url,
                    domain_semaphores.get(_get_domain(url)),
                )
                for url in urls_to_fetch
            ]
            fetch_results = list(await asyncio.gather(*tasks))

        if curl_session is not None:
            await curl_session.close()

        # Neue Ergebnisse in Cache schreiben
        if cache_db is not None:
            for r in fetch_results:
                _cache_put(cache_db, r["url"], r, r.get("source_type", "general"))
            cache_db.commit()

    # Cache-DB schließen
    if cache_db is not None:
        cache_db.close()

    # ── Ergebnisse in Original-Reihenfolge zusammenführen ────────────────
    fetch_by_url = {r["url"]: r for r in fetch_results}
    final = []
    for url in urls:
        if url in cached_results:
            final.append(cached_results[url])
        elif url in fetch_by_url:
            final.append(fetch_by_url[url])

    # ── Content-Limit anwenden (NACH Cache-Write, Cache/Depth-Fix) ────
    if MAX_CHARS_PER_URL > 0:
        for r in final:
            if r.get("content") and len(r["content"]) > MAX_CHARS_PER_URL:
                r["content"] = r["content"][:MAX_CHARS_PER_URL] + "\n\n[... gekürzt]"
                r["chars"] = len(r["content"])

    return final


def collect_urls() -> list[str]:
    """URLs aus stdin (JSON) und/oder CLI-Argumenten sammeln."""
    urls = []

    # CLI-Argumente (alles nach dem Script-Namen)
    if len(sys.argv) > 1:
        urls.extend(sys.argv[1:])

    # stdin: JSON-Array oder eine URL pro Zeile (nur wenn keine CLI-Args)
    if not urls and not sys.stdin.isatty():
        stdin_data = sys.stdin.read().strip()
        if stdin_data:
            try:
                parsed = json.loads(stdin_data)
                if isinstance(parsed, list):
                    urls.extend(parsed)
                elif isinstance(parsed, str):
                    urls.append(parsed)
            except json.JSONDecodeError:
                for line in stdin_data.split("\n"):
                    line = line.strip()
                    if line and line.startswith("http"):
                        urls.append(line)

    # URL-Validierung: Protokoll-Prefix sicherstellen
    validated = []
    for url in urls:
        url = url.strip()
        if not url:
            continue
        if not url.startswith(("http://", "https://")):
            # Auto-fix: https:// voranstellen wenn es wie eine Domain aussieht
            if "." in url and " " not in url:
                url = "https://" + url
            else:
                print(
                    f"  Übersprungen (kein gültiges URL-Format): {url!r}",
                    file=sys.stderr,
                )
                continue
        validated.append(url)

    # Duplikate entfernen, Reihenfolge beibehalten
    seen = set()
    unique = []
    for url in validated:
        if url not in seen:
            seen.add(url)
            unique.append(url)

    return unique


def load_blocklist() -> set[str]:
    """Domain-Blocklist aus skill_learnings laden (automatisch generiert)."""
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


def extract_outbound_links(
    results: list[dict], already_crawled: set[str], max_links: int = 20
) -> list[str]:
    """Extrahiere hochwertige ausgehende Links aus Crawl-Ergebnissen.

    Sucht nach Markdown-Links [text](url) im Content und filtert:
    - Nur http(s)-URLs
    - Nicht bereits gecrawlte URLs
    - Bevorzugt high/medium-tier Domains
    - Keine geblockten Domains
    """
    from urllib.parse import urlparse as _urlparse

    link_re = re.compile(r"\[([^\]]+)\]\((https?://[^\)]+)\)")
    blocked = {
        "youtube.com",
        "twitter.com",
        "x.com",
        "facebook.com",
        "instagram.com",
        "linkedin.com",
        "pinterest.com",
        "tiktok.com",
        "reddit.com",
        "quora.com",
    }

    candidates = []  # (url, domain_tier_score, source_idx)
    seen = set()

    for idx, r in enumerate(results):
        if r.get("error") or r.get("is_boilerplate") or not r.get("content"):
            continue
        content = r["content"]
        for match in link_re.finditer(content):
            url = match.group(2).rstrip(".,;)")
            if url in seen or url in already_crawled:
                continue
            seen.add(url)
            try:
                domain = _urlparse(url).netloc.removeprefix("www.")
            except Exception:
                continue
            if domain in blocked or not domain:
                continue
            # Domain-Tier-Score für Sortierung
            tier_score = 0
            for tier, domains in DOMAIN_AUTHORITY.items():
                if any(domain.endswith(d) or domain == d for d in domains):
                    tier_score = 2 if tier == "high" else 1
                    break
            candidates.append((url, tier_score, idx))

    # Sortiere nach Domain-Tier (high zuerst), dann nach Position im Content
    candidates.sort(key=lambda x: (-x[1], x[2]))
    return [c[0] for c in candidates[:max_links]]


def _pop_flag(name: str, with_value: bool = False, cast=str):
    """Sicheres Flag-Parsing aus sys.argv. Gibt (found, value) zurück.

    Bei with_value=True: Gibt den Wert zurück (gecastet), oder None bei fehlendem/ungültigem Wert.
    Bei with_value=False: Gibt True/False zurück (Boolean-Flag).
    """
    if name not in sys.argv:
        return False, None
    if not with_value:
        sys.argv.remove(name)
        return True, None
    idx = sys.argv.index(name)
    if idx + 1 >= len(sys.argv):
        sys.argv.pop(idx)
        print(f"  WARNUNG: {name} braucht einen Wert, ignoriert", file=sys.stderr)
        return True, None
    raw = sys.argv[idx + 1]
    try:
        value = cast(raw)
    except (ValueError, TypeError):
        sys.argv.pop(idx)
        sys.argv.pop(idx)
        print(
            f"  WARNUNG: {name} Wert '{raw}' ungültig ({cast.__name__}), ignoriert",
            file=sys.stderr,
        )
        return True, None
    sys.argv.pop(idx)
    sys.argv.pop(idx)
    return True, value


def main():
    global MAX_CHARS_PER_URL, FRESHNESS_WEIGHT
    min_quality = 0  # 0 = kein Filter, wird via --min-quality gesetzt
    use_cache = True
    do_cross_ref = False
    follow_links = 0  # 0 = kein Link-Following

    # Boolean-Flags
    found, _ = _pop_flag("--no-cache")
    if found:
        use_cache = False
    found, _ = _pop_flag("--cross-ref")
    if found:
        do_cross_ref = True

    # Flags mit Wert
    _, val = _pop_flag("--follow-links", with_value=True, cast=int)
    if val is not None:
        follow_links = val

    emit_events_path = None
    _, val = _pop_flag("--emit-events", with_value=True, cast=str)
    if val is not None:
        emit_events_path = val

    _, val = _pop_flag("--freshness-weight", with_value=True, cast=float)
    if val is not None:
        FRESHNESS_WEIGHT = val

    track_skill = None
    _, val = _pop_flag("--track", with_value=True, cast=str)
    if val is not None:
        track_skill = val

    _, val = _pop_flag("--min-quality", with_value=True, cast=int)
    if val is not None:
        min_quality = val

    _, val = _pop_flag("--max-chars", with_value=True, cast=int)
    if val is not None:
        MAX_CHARS_PER_URL = val

    urls = collect_urls()

    # Medium-Subdomains (alle 403, datenbasiert bestätigt)
    medium_suffixes = (
        "medium.com",
        "devgenius.io",
        "plainenglish.io",
        "towardsai.net",
        "betterprogramming.pub",
    )

    # Pre-Filter: Geblockte Domains überspringen
    blocklist = load_blocklist()
    if blocklist or medium_suffixes:
        before = len(urls)
        urls = [
            u
            for u in urls
            if urlparse(u).netloc.removeprefix("www.") not in blocklist
            and not urlparse(u).netloc.removeprefix("www.").endswith(medium_suffixes)
        ]
        skipped = before - len(urls)
        if skipped > 0:
            bl_preview = ", ".join(sorted(blocklist)[:5])
            if len(blocklist) > 5:
                bl_preview += "..."
            print(
                f"  Blocklist: {skipped} URLs übersprungen ({bl_preview})",
                file=sys.stderr,
            )

    if not urls:
        print("Verwendung:", file=sys.stderr)
        print('  python3 research-crawler.py "URL1" "URL2" ...', file=sys.stderr)
        print(
            '  echo \'["URL1","URL2"]\' | python3 research-crawler.py',
            file=sys.stderr,
        )
        print("  --max-chars N           Content pro URL begrenzen", file=sys.stderr)
        print(
            "  --min-quality N         Ergebnisse mit Q<N aus Output entfernen",
            file=sys.stderr,
        )
        print(
            "  --freshness-weight F    Freshness-Gewichtung (default: 1.0)",
            file=sys.stderr,
        )
        print(
            "  --track SKILL           Auto skill_run Lifecycle in skill-tracker.db",
            file=sys.stderr,
        )
        print(
            "  --no-cache              Cache deaktivieren (immer frisch fetchen)",
            file=sys.stderr,
        )
        sys.exit(1)

    limit_info = f", max {MAX_CHARS_PER_URL} chars/URL" if MAX_CHARS_PER_URL > 0 else ""
    print(
        f"Crawle {len(urls)} URLs (max {MAX_CONCURRENT} parallel{limit_info})...",
        file=sys.stderr,
    )
    start = time.monotonic()

    results = asyncio.run(crawl(urls, use_cache=use_cache))

    # --follow-links: Outbound-Links aus gecrawlten Seiten extrahieren und nachladen
    if follow_links > 0:
        already_crawled = set(urls)
        discovered = extract_outbound_links(
            results, already_crawled, max_links=follow_links
        )
        if discovered:
            print(
                f"  Follow-Links: {len(discovered)} neue URLs aus Content extrahiert",
                file=sys.stderr,
            )
            follow_results = asyncio.run(crawl(discovered, use_cache=use_cache))
            # Nur gute Ergebnisse anhängen (Q>=5, kein Boilerplate, kein Error)
            good_follows = [
                r
                for r in follow_results
                if not r.get("error")
                and not r.get("is_boilerplate")
                and r.get("quality", 0) >= 5
            ]
            if good_follows:
                # Markiere als Follow-Link-Ergebnis
                for r in good_follows:
                    r["followed_link"] = True
                results.extend(good_follows)
                print(
                    f"  Follow-Links: {len(good_follows)}/{len(discovered)} nutzbar, "
                    f"angehängt (gesamt: {len(results)} Quellen)",
                    file=sys.stderr,
                )
            else:
                print(
                    "  Follow-Links: Keine nutzbaren Follow-Up-Quellen",
                    file=sys.stderr,
                )
        else:
            print(
                "  Follow-Links: Keine neuen Links in Content gefunden",
                file=sys.stderr,
            )

    elapsed = time.monotonic() - start

    # Statistik auf stderr
    ok = sum(1 for r in results if not r["error"])
    fail = sum(1 for r in results if r["error"])
    boilerplate = sum(1 for r in results if r.get("is_boilerplate"))
    total_chars = sum(r["chars"] for r in results)
    avg_quality = sum(r.get("quality", 0) for r in results if not r["error"]) / max(
        ok, 1
    )

    # Tier-Verteilung berechnen
    tiers = {}
    for r in results:
        t = r.get("domain_tier", "?")
        tiers[t] = tiers.get(t, 0) + 1
    tier_str = ", ".join(f"{k}={v}" for k, v in sorted(tiers.items()))

    print(
        f"{ok} OK, {fail} fehlgeschlagen, {boilerplate} Boilerplate, "
        f"{total_chars:,} chars, Ø Qualität {avg_quality:.1f}/10 ({elapsed:.1f}s)",
        file=sys.stderr,
    )
    print(f"  Tiers: {tier_str}", file=sys.stderr)

    # Timing-Analyse (nur wenn URLs gefetcht wurden, nicht bei reinem Cache-Hit)
    fetch_times = [
        r.get("fetch_ms", 0)
        for r in results
        if not r["error"] and r.get("fetch_ms", 0) > 0
    ]
    extract_times = [
        r.get("extract_ms", 0)
        for r in results
        if not r["error"] and r.get("extract_ms", 0) > 0
    ]
    if fetch_times:
        print(
            f"  Timing: fetch avg={sum(fetch_times) // len(fetch_times)}ms "
            f"(max={max(fetch_times)}ms), "
            f"extract avg={sum(extract_times) // len(extract_times)}ms "
            f"(max={max(extract_times)}ms)",
            file=sys.stderr,
        )

    if fail > 0:
        for r in results:
            if r["error"]:
                print(f"  FEHLER: {r['url']} -> {r['error']}", file=sys.stderr)
    if boilerplate > 0:
        for r in results:
            if r.get("is_boilerplate") and not r["error"]:
                print(
                    f"  BOILERPLATE: {r['url']} (Q={r.get('quality', 0)})",
                    file=sys.stderr,
                )

    # Events für Observability — IMMER in DB schreiben + optional als File
    events = []
    for r in results:
        domain = urlparse(r["url"]).netloc.removeprefix("www.") if r["url"] else ""
        if not domain:
            continue  # Skip events for URLs without valid domain (Finding 17)
        status = "ok"
        if r["error"]:
            status = "error"
        elif r.get("is_boilerplate"):
            status = "boilerplate"
        events.append(
            {
                "source": "crawler",
                "event_type": "url_fetch",
                "domain": domain,
                "status": status,
                "latency_ms": r.get("latency_ms"),
                "value_num": r.get("quality", 0),
                "value_text": r.get("error"),
                "meta": json.dumps(
                    {
                        "chars": r["chars"],
                        "tier": r.get("domain_tier", "standard"),
                        "type": r.get("source_type", "general"),
                        "pub_date": r.get("pub_date"),
                        "freshness_bonus": r.get("freshness_bonus", 0),
                    }
                ),
            }
        )

    # Direkt in DB schreiben (kein separater events-batch Call nötig)
    try:
        import sqlite3
        from pathlib import Path

        db_path = Path(__file__).parent / "skill-tracker.db"
        if db_path.exists():
            db = sqlite3.connect(str(db_path))
            for ev in events:
                db.execute(
                    """INSERT INTO events (source, event_type, domain, status,
                       latency_ms, value_num, value_text, meta)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        ev["source"],
                        ev["event_type"],
                        ev["domain"],
                        ev["status"],
                        ev["latency_ms"],
                        ev["value_num"],
                        ev["value_text"],
                        ev.get("meta"),
                    ),
                )
            db.commit()
            db.close()
            print(f"  Events: {len(events)} → DB", file=sys.stderr)
    except Exception as e:
        print(f"  Events: DB-Fehler ({e}), skip", file=sys.stderr)

    # --track: Automatischer skill_run-Lifecycle
    if track_skill:
        try:
            import sqlite3 as _sq
            from pathlib import Path as _Pt

            _db_path = _Pt(__file__).parent / "skill-tracker.db"
            if _db_path.exists():
                _db = _sq.connect(str(_db_path))
                # Run erstellen
                _cur = _db.execute(
                    "INSERT INTO skill_runs (skill_name, context) VALUES (?, ?)",
                    (
                        track_skill,
                        json.dumps({"urls": len(urls), "mode": "auto-track"}),
                    ),
                )
                _run_id = _cur.lastrowid
                # Metriken einfügen
                _metrics = [
                    (_run_id, "urls_total", len(urls), "count"),
                    (_run_id, "urls_ok", ok, "count"),
                    (_run_id, "urls_failed", fail, "count"),
                    (_run_id, "urls_boilerplate", boilerplate, "count"),
                    (_run_id, "quality_avg", round(avg_quality, 1), "score"),
                    (_run_id, "total_chars", total_chars, "chars"),
                    (_run_id, "duration", round(elapsed, 1), "seconds"),
                ]
                for _m in _metrics:
                    _db.execute(
                        """INSERT INTO skill_metrics (run_id, metric_name, metric_value, metric_unit)
                           VALUES (?, ?, ?, ?)
                           ON CONFLICT(run_id, metric_name) DO UPDATE SET
                             metric_value = excluded.metric_value""",
                        _m,
                    )
                # Run abschließen
                _db.execute(
                    """UPDATE skill_runs SET
                         status = 'completed',
                         completed_at = strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'),
                         duration_seconds = ?
                       WHERE id = ?""",
                    (round(elapsed, 1), _run_id),
                )
                _db.commit()
                _db.close()
                print(
                    f"  Track: run_id={_run_id} ({track_skill}), {ok}/{len(urls)} OK, Q={avg_quality:.1f}",
                    file=sys.stderr,
                )
        except Exception as _e:
            print(f"  Track: Fehler ({_e})", file=sys.stderr)

    # Optional: Events auch als File exportieren (für Legacy-Kompatibilität)
    if emit_events_path:
        from pathlib import Path as _Path

        _Path(emit_events_path).write_text(json.dumps(events, ensure_ascii=False))
        print(f"  Events: {len(events)} → {emit_events_path}", file=sys.stderr)

    # --min-quality Filter anwenden
    if min_quality > 0:
        before_filter = len(results)
        results = [
            r for r in results if r.get("quality", 0) >= min_quality or r.get("error")
        ]
        filtered = before_filter - len(results)
        if filtered > 0:
            print(
                f"  Quality-Filter (Q>={min_quality}): {filtered} entfernt, "
                f"{len(results)} verbleibend",
                file=sys.stderr,
            )

    # Cross-Referencing (optional)
    cross_ref_data = None
    if do_cross_ref:
        cross_ref_data = extract_claims(results)
        n_claims = len(cross_ref_data)
        if n_claims > 0:
            print(
                f"  Cross-Ref: {n_claims} Claims über ≥2 Quellen bestätigt",
                file=sys.stderr,
            )
        else:
            print(
                "  Cross-Ref: Keine quellenübergreifenden Claims gefunden",
                file=sys.stderr,
            )

    # Ergebnisse als JSON auf stdout
    output = []
    for r in results:
        entry = {
            "url": r["url"],
            "title": r["title"],
            "content": r["content"],
            "chars": r["chars"],
            "quality": r.get("quality", 0),
            "domain_tier": r.get("domain_tier", "standard"),
            "source_type": r.get("source_type", "general"),
            "pub_date": r.get("pub_date"),
            "freshness_bonus": r.get("freshness_bonus", 0),
        }
        if r["error"]:
            entry["error"] = r["error"]
        if r.get("is_boilerplate"):
            entry["boilerplate"] = True
        if r.get("followed_link"):
            entry["followed_link"] = True
        output.append(entry)

    # Bei --cross-ref: Wrapper-Objekt mit Sources + Claims
    if do_cross_ref and cross_ref_data is not None:
        wrapper = {
            "sources": output,
            "cross_referenced_claims": cross_ref_data,
            "meta": {
                "total_sources": len(output),
                "ok_sources": ok,
                "cross_ref_claims": len(cross_ref_data),
                "avg_quality": round(avg_quality, 1),
            },
        }
        json.dump(wrapper, sys.stdout, ensure_ascii=False, indent=2)
    else:
        json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
    print(file=sys.stdout)


if __name__ == "__main__":
    import signal

    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    try:
        main()
    except BrokenPipeError:
        sys.stderr.close()
        sys.exit(1)
