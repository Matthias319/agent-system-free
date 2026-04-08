#!/home/maetzger/.claude/tools/.venv/bin/python
"""
Product-Image-Fetcher: Holt Produktbilder von Herstellerseiten,
resized auf max 600px, gibt base64-Data-URIs als JSON zurück.

Verwendung:
    # JSON via stdin: [{"name": "Produkt", "url": "https://..."}]
    echo '[{"name":"Torras Ostand","url":"https://torraslife.com/collections/..."}]' \
      | python3 product-image-fetcher.py

    # CLI mit --products (Name=URL Paare)
    python3 product-image-fetcher.py \
      --products "Torras Ostand=https://torraslife.com/..." \
                 "Pitaka Edge=https://ipitaka.com/..."

    # Nur Namen (sucht automatisch via fast-search.py)
    python3 product-image-fetcher.py --products "Torras Ostand iPhone 17 Pro Max"

    # Aus research-crawler Output (extrahiert Bilder aus bereits gecrawlten URLs)
    cat /tmp/ws-result.json | python3 product-image-fetcher.py --from-crawl \
      --names "Torras Ostand" "Pitaka Edge"

Output: JSON-Array mit {"name", "data_uri", "source_url", "alt"} pro Produkt.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

# --- Optionale Imports ---

try:
    from curl_cffi.requests import AsyncSession as CurlAsyncSession

    HAS_CURL_CFFI = True
except ImportError:
    CurlAsyncSession = None
    HAS_CURL_CFFI = False

try:
    from PIL import Image

    HAS_PIL = True
except ImportError:
    HAS_PIL = False

import httpx

# --- Konfiguration ---

MAX_CONCURRENT = 12  # ProDesk 600 G3: Bilder sind I/O-bound, 2× Pi-Wert
TIMEOUT_SECONDS = 12
MAX_IMAGE_DIM = 600  # Max Breite/Höhe in Pixel
JPEG_QUALITY = 85

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Patterns die auf Logos/Icons/Junk hinweisen
JUNK_PATTERNS = re.compile(
    r"logo|icon|flag|badge|banner|sprite|spacer|pixel|tracking|"
    r"payment|paypal|visa|mastercard|amex|apple.pay|google.pay|"
    r"shopify.*static|gravatar|avatar|profile|social|share|"
    r"\.svg|1x1|blank\.gif",
    re.IGNORECASE,
)

# CDN-Patterns die auf Produktbilder hinweisen
PRODUCT_IMAGE_PATTERNS = [
    re.compile(r"cdn\.shopify\.com/s/files/.*\.(jpg|webp|png)", re.I),
    re.compile(r"cdn/shop/files/.*\.(jpg|webp|png)", re.I),
    re.compile(r"cdn/shop/products/.*\.(jpg|webp|png)", re.I),
    re.compile(r"cdn\.sanity\.io/images/", re.I),
    re.compile(r"store\.storeimages\.cdn-apple\.com/.*/is/", re.I),
    re.compile(r"product.*\.(jpg|jpeg|webp|png)", re.I),
    re.compile(r"(main|hero|featured|primary).*\.(jpg|jpeg|webp|png)", re.I),
]


# --- Hilfsfunktionen ---


def _is_junk(src: str, alt: str = "") -> bool:
    """Prüft ob eine Bild-URL auf Junk (Logo, Icon, etc.) hinweist."""
    return bool(JUNK_PATTERNS.search(f"{src} {alt}"))


def _is_product_image(src: str) -> bool:
    """Prüft ob eine URL auf ein Produktbild hinweist."""
    return any(p.search(src) for p in PRODUCT_IMAGE_PATTERNS)


def _score_image(src: str, alt: str, position: int) -> float:
    """Scored ein Bild nach Wahrscheinlichkeit, ein Produktbild zu sein."""
    score = 0.0

    if _is_junk(src, alt):
        return -100.0

    # CDN-Pattern-Bonus
    if _is_product_image(src):
        score += 5.0

    # Größenhinweise in URL
    width_match = re.search(r"width[=_](\d+)", src, re.I)
    if width_match:
        w = int(width_match.group(1))
        if w >= 400:
            score += 3.0
        elif w >= 200:
            score += 1.0
        elif w < 100:
            score -= 2.0

    for hint in ["_large", "_grande", "_1024", "_2048", "_1200", "2x", "3x"]:
        if hint in src.lower():
            score += 2.0
            break

    for hint in ["_small", "_tiny", "_thumb", "_icon", "_mini", "50x50", "60x60"]:
        if hint in src.lower():
            score -= 3.0

    # Alt-Text mit Produkthinweisen
    alt_lower = alt.lower()
    for keyword in [
        "case",
        "hülle",
        "phone",
        "iphone",
        "product",
        "magsafe",
        "cover",
        "schutz",
        "review",
        "test",
    ]:
        if keyword in alt_lower:
            score += 2.0
            break

    # Frühes Bild = wahrscheinlicher Produktbild
    if position < 3:
        score += 2.0
    elif position < 8:
        score += 1.0
    elif position > 20:
        score -= 1.0

    return score


def _abs_url(src: str, base_url: str) -> str:
    """Macht eine URL absolut."""
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("/"):
        parsed = urlparse(base_url)
        return f"{parsed.scheme}://{parsed.netloc}{src}"
    if not src.startswith("http"):
        return urljoin(base_url, src)
    return src


def _upgrade_image_url(src: str) -> str:
    """CDN-spezifische URL-Upgrades für höhere Auflösung."""
    if "cdn/shop/" in src or "cdn.shopify.com" in src:
        # Shopify: _small entfernen, width hochsetzen
        src = re.sub(r"_(small|tiny|thumb|compact|medium)\.", ".", src)
        src = re.sub(r"width=\d+", "width=1200", src)
        if "width=" not in src:
            sep = "&" if "?" in src else "?"
            src = f"{src}{sep}width=1200"
        return src

    if "cdn-apple.com" in src:
        # Apple: quadratisch 1200px
        src = re.sub(r"wid=\d+", "wid=1200", src)
        src = re.sub(r"hei=\d+", "hei=1200", src)
        if "wid=" not in src:
            sep = "&" if "?" in src else "?"
            src = f"{src}{sep}wid=1200&hei=1200&fmt=jpeg&qlt=95"
        return src

    if "cdn.sanity.io" in src:
        src = src.rstrip("\\")
        if "?" not in src:
            src = f"{src}?w=1200&h=1200&fit=crop&fm=jpg"
        return src

    return src


def _extract_images_from_html(html: str, base_url: str) -> list[dict]:
    """Extrahiert Bild-Kandidaten aus HTML mit Scoring."""
    results = []

    # 1. og:image
    og_match = re.search(
        r'<meta[^>]*property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']',
        html,
        re.I,
    )
    if not og_match:
        og_match = re.search(
            r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*property=["\']og:image["\']',
            html,
            re.I,
        )
    if og_match:
        og_src = og_match.group(1).replace("&amp;", "&")
        if not _is_junk(og_src):
            results.append(
                {"src": _abs_url(og_src, base_url), "alt": "og:image", "score": 8.0}
            )

    # 2. Alle <img> Tags
    for idx, m in enumerate(re.finditer(r"<img\s[^>]*>", html, re.I | re.DOTALL)):
        tag = m.group(0)

        src_match = re.search(r'src=["\']([^"\']+)["\']', tag, re.I)
        if not src_match:
            src_match = re.search(r'data-src=["\']([^"\']+)["\']', tag, re.I)
        if not src_match:
            continue

        src = src_match.group(1).replace("&amp;", "&")

        # srcset: höchste Auflösung nehmen
        srcset_match = re.search(r'srcset=["\']([^"\']+)["\']', tag, re.I)
        if srcset_match:
            parts = [
                p.strip()
                for p in srcset_match.group(1).replace("&amp;", "&").split(",")
                if p.strip()
            ]
            if parts:
                best = parts[-1].split()[0]
                if best and not best.startswith("data:"):
                    src = best

        if src.startswith("data:") or src.endswith(".svg"):
            continue

        alt_match = re.search(r'alt=["\']([^"\']*)["\']', tag, re.I)
        alt = alt_match.group(1) if alt_match else ""

        abs_src = _abs_url(src, base_url)
        score = _score_image(abs_src, alt, idx)

        if score > -50:
            results.append({"src": abs_src, "alt": alt[:120], "score": score})

    # Deduplizieren
    seen = set()
    unique = []
    for r in results:
        key = re.sub(r"[?&](width|height|w|h|wid|hei)=\d+", "", r["src"])
        if key not in seen:
            seen.add(key)
            unique.append(r)

    unique.sort(key=lambda x: x["score"], reverse=True)
    return unique


# --- HTTP ---


async def _fetch_html(url, curl_session, httpx_client):
    """Lädt HTML einer Seite."""
    try:
        if curl_session is not None:
            r = await curl_session.get(
                url, timeout=TIMEOUT_SECONDS, allow_redirects=True
            )
            if r.status_code >= 400:
                return None
            return r.text
        r = await httpx_client.get(url, follow_redirects=True)
        r.raise_for_status()
        return r.text
    except Exception:
        return None


async def _fetch_image_bytes(url, curl_session, httpx_client) -> bytes | None:
    """Lädt Bilddaten herunter."""
    try:
        if curl_session is not None:
            r = await curl_session.get(
                url, timeout=TIMEOUT_SECONDS, allow_redirects=True
            )
            if r.status_code >= 400:
                return None
            return r.content
        r = await httpx_client.get(url, follow_redirects=True)
        r.raise_for_status()
        return r.content
    except Exception:
        return None


def _process_image(raw_bytes: bytes) -> str | None:
    """Resized auf MAX_IMAGE_DIM, konvertiert zu JPEG, gibt base64-Data-URI zurück."""
    if not HAS_PIL:
        return f"data:image/jpeg;base64,{base64.b64encode(raw_bytes).decode('ascii')}"

    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img = img.convert("RGB")
        img.thumbnail((MAX_IMAGE_DIM, MAX_IMAGE_DIM), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=JPEG_QUALITY)
        return (
            f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"
        )
    except Exception as e:
        print(f"  PIL-Fehler: {e}", file=sys.stderr)
        return None


# --- Strategien ---


async def _strategy_from_url(name, url, curl_session, httpx_client, semaphore):
    """Strategie 1: Produktbild von gegebener URL extrahieren."""
    async with semaphore:
        html = await _fetch_html(url, curl_session, httpx_client)
        if not html:
            return None

        candidates = _extract_images_from_html(html, url)
        if not candidates:
            return None

        for cand in candidates[:3]:
            img_url = _upgrade_image_url(cand["src"])
            raw = await _fetch_image_bytes(img_url, curl_session, httpx_client)
            if raw and len(raw) > 1000:
                data_uri = _process_image(raw)
                if data_uri:
                    return {
                        "name": name,
                        "data_uri": data_uri,
                        "source_url": img_url,
                        "alt": cand.get("alt", name),
                    }
    return None


async def _strategy_search(name, curl_session, httpx_client, semaphore):
    """Strategie 2: URL via fast-search.py finden, dann Bild extrahieren."""
    fast_search = Path.home() / ".claude/tools/fast-search.py"
    if not fast_search.exists():
        return None

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(fast_search),
            f"{name} official product page",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        urls = json.loads(stdout.decode())
        if not urls:
            return None
    except Exception:
        return None

    for url in urls[:3]:
        result = await _strategy_from_url(
            name, url, curl_session, httpx_client, semaphore
        )
        if result:
            return result
    return None


async def _strategy_from_crawl(
    name, crawl_results, curl_session, httpx_client, semaphore
):
    """Strategie 3: Bilder aus bereits gecrawlten Seiten extrahieren."""
    name_words = set(name.lower().split())

    scored_urls = []
    for item in crawl_results:
        if item.get("error") or item.get("boilerplate"):
            continue
        title = (item.get("title") or "").lower()
        url = item.get("url", "")

        match_score = sum(1 for w in name_words if len(w) > 2 and w in title) + sum(
            0.5 for w in name_words if len(w) > 2 and w in url.lower()
        )

        if match_score > 0:
            scored_urls.append((match_score, url))

    scored_urls.sort(key=lambda x: x[0], reverse=True)

    for _, url in scored_urls[:3]:
        result = await _strategy_from_url(
            name, url, curl_session, httpx_client, semaphore
        )
        if result:
            return result
    return None


# --- Hauptfunktion ---


async def fetch_product_images(
    products: list[dict],
    crawl_data: list[dict] | None = None,
) -> list[dict]:
    """Holt Produktbilder für eine Liste von Produkten.

    Strategie-Kaskade pro Produkt: URL → Crawl-Daten → Suche
    """
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    t0 = time.monotonic()

    curl_session = None
    if HAS_CURL_CFFI:
        curl_session = CurlAsyncSession(impersonate="chrome131")
        print("  [curl_cffi] Chrome-TLS aktiv", file=sys.stderr)

    results = []
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        timeout=httpx.Timeout(TIMEOUT_SECONDS),
    ) as httpx_client:

        async def _fetch_one(product):
            name = product["name"]
            url = product.get("url")

            # Kaskade
            if url:
                r = await _strategy_from_url(
                    name, url, curl_session, httpx_client, semaphore
                )
                if r:
                    return r

            if crawl_data:
                r = await _strategy_from_crawl(
                    name, crawl_data, curl_session, httpx_client, semaphore
                )
                if r:
                    return r

            r = await _strategy_search(name, curl_session, httpx_client, semaphore)
            return r

        fetched = await asyncio.gather(
            *[_fetch_one(p) for p in products],
            return_exceptions=True,
        )
        for item in fetched:
            if isinstance(item, dict):
                results.append(item)
            elif isinstance(item, Exception):
                print(f"  Fehler: {item}", file=sys.stderr)

    if curl_session:
        await curl_session.close()

    elapsed = time.monotonic() - t0
    print(
        f"{len(results)}/{len(products)} Bilder gefunden ({elapsed:.1f}s)",
        file=sys.stderr,
    )
    return results


def main():
    global MAX_IMAGE_DIM  # noqa: PLW0603

    parser = argparse.ArgumentParser(description="Product Image Fetcher")
    parser.add_argument(
        "--products", nargs="*", help='Produkte als "Name" oder "Name=URL"'
    )
    parser.add_argument(
        "--from-crawl",
        action="store_true",
        help="Crawl-JSON von stdin, Bilder extrahieren",
    )
    parser.add_argument("--names", nargs="*", help="Produktnamen (für --from-crawl)")
    parser.add_argument(
        "--max-dim",
        type=int,
        default=MAX_IMAGE_DIM,
        help=f"Max Pixel (default: {MAX_IMAGE_DIM})",
    )
    args = parser.parse_args()
    MAX_IMAGE_DIM = args.max_dim

    crawl_data = None
    products = []

    if args.from_crawl:
        crawl_data = json.loads(sys.stdin.read())
        if args.names:
            products = [{"name": n} for n in args.names]
        else:
            print("Fehler: --from-crawl benötigt --names", file=sys.stderr)
            sys.exit(1)
    elif args.products:
        for p in args.products:
            if "=" in p:
                name, url = p.split("=", 1)
                products.append({"name": name.strip(), "url": url.strip()})
            else:
                products.append({"name": p.strip()})
    elif not sys.stdin.isatty():
        products = json.loads(sys.stdin.read())
    else:
        parser.print_help()
        sys.exit(1)

    if not products:
        print("Keine Produkte angegeben.", file=sys.stderr)
        sys.exit(1)

    print(f"Suche Bilder für {len(products)} Produkte...", file=sys.stderr)
    results = asyncio.run(fetch_product_images(products, crawl_data))
    json.dump(results, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
