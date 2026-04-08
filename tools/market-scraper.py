#!/home/maetzger/.claude/tools/.venv/bin/python
"""Kleinanzeigen Marktpreis-Scraper — httpx + selectolax.

Features: IQR-Filterung, Seller-Profil-Check, Scam-Erkennung, TGTBT-Warnungen,
Spec-Extraction, Beschreibungs-Risiken, dynamische Pagination, Multi-Kategorie-Suche.
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from statistics import median, quantiles
from urllib.parse import quote, unquote

import httpx
from selectolax.lexbor import LexborHTMLParser

# --- Config ---
BASE_URL = "https://www.kleinanzeigen.de"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
}
SESSION = httpx.Client(headers=HEADERS, follow_redirects=True, timeout=15)

# --- Location (Seeheim-Jugenheim) ---
HOME_PLZ = "64342"
HOME_LOCATION_ID = "4509"  # Kleinanzeigen-interne ID für 64342


def get_search_radius(median_price):
    """Dynamic radius in km based on product value — worth the drive?"""
    if not median_price or median_price < 50:
        return 15
    elif median_price < 150:
        return 30
    elif median_price < 500:
        return 50
    elif median_price < 1000:
        return 75
    elif median_price < 2000:
        return 100
    else:
        return 150


# Seller trust badges — ordered by trust level (higher = better)
TRUST_BADGES = {
    "TOP Zufriedenheit",
    "Besonders zuverlässig",
    "Besonders freundlich",
    "Sehr zuverlässig",
    "Sehr freundlich",
    "Zuverlässig",
    "Freundlich",
    "OK Zufriedenheit",
}


def fetch_page(url):
    """Fetch a page and return LexborHTMLParser tree."""
    resp = SESSION.get(url)
    resp.raise_for_status()
    return LexborHTMLParser(resp.text)


def discover_categories(search_term):
    """Fetch the search page and extract sidebar categories."""
    encoded = quote(search_term, safe="")
    url = f"{BASE_URL}/s-{encoded}/k0"
    tree = fetch_page(url)

    heading = tree.css_first("h1")
    heading_text = heading.text(strip=True) if heading else ""

    # Kleinanzeigen converts search terms to hyphenated lowercase in URLs
    # "iPad Pro 12,9 M1" -> "ipad-pro-12%2C9-m1" or "ipad-pro-12,9-m1"
    href_slug = re.sub(r"[\s]+", "-", search_term.lower())

    categories = []
    for a in tree.css('a[href*="/k0c"]'):
        href = a.attrs.get("href", "")
        href_decoded = unquote(href).lower()
        # Match: either URL-encoded, plain, or hyphenated version
        if not (
            encoded.lower() in href_decoded
            or search_term.lower() in href_decoded
            or href_slug in href_decoded
        ):
            continue
        text = a.text(strip=True)
        # Look for count in parent and grandparent
        parent_text = ""
        if a.parent:
            parent_text = a.parent.text()
        if not re.search(r"\(\d+\)", parent_text) and a.parent and a.parent.parent:
            parent_text = a.parent.parent.text()
        count_match = re.search(r"\((\d+)\)", parent_text)
        if text and count_match:
            categories.append(
                {"text": text, "count": int(count_match.group(1)), "href": href}
            )

    # Angebote-Filter link
    offer_link = tree.css_first('a[href*="anzeige:angebote"]')
    offer_href = offer_link.attrs.get("href") if offer_link else None

    return {
        "heading": heading_text,
        "categories": sorted(categories, key=lambda c: c["count"], reverse=True),
        "offer_filter": offer_href,
        "base_url": url,
    }


def select_best_category(categories, search_term, fallback_index=0):
    """Pick the most relevant category by token overlap instead of just count.

    Scores each category name against the search term tokens.
    Brand tokens get bonus, generic words get malus.
    Falls back to count-based selection if no score > 1.
    """
    if not categories:
        return {"text": "Alle", "count": 0, "href": ""}
    if len(categories) == 1:
        return categories[0]

    search_tokens = set(re.split(r"[\s\-/]+", search_term.lower()))

    # Brand tokens get double weight
    brands = {
        "apple",
        "iphone",
        "ipad",
        "macbook",
        "imac",
        "airpods",
        "samsung",
        "galaxy",
        "pixel",
        "google",
        "oneplus",
        "xiaomi",
        "huawei",
        "sony",
        "playstation",
        "ps5",
        "ps4",
        "xbox",
        "nintendo",
        "switch",
        "nvidia",
        "rtx",
        "gtx",
        "geforce",
        "radeon",
        "amd",
        "intel",
        "lenovo",
        "thinkpad",
        "dell",
        "hp",
        "asus",
        "acer",
        "bose",
        "sennheiser",
        "jabra",
        "marshall",
    }

    # Generic category words → malus
    generic = {
        "weitere",
        "weiteres",
        "sonstige",
        "sonstiges",
        "sonstiger",
        "zubehör",
        "accessories",
        "teile",
        "ersatzteile",
    }

    best_cat = None
    best_score = -1

    for cat in categories:
        cat_tokens = set(re.split(r"[\s\-/&]+", cat["text"].lower()))
        # Base score: overlap count
        overlap = search_tokens & cat_tokens
        score = len(overlap)
        # Brand bonus: +2 per brand token in overlap
        score += 2 * len(overlap & brands)
        # Generic malus: -3 per generic token in category name
        score -= 3 * len(cat_tokens & generic)
        # Tiebreaker: larger category wins (tiny bonus)
        score += cat["count"] * 0.0001

        if score > best_score:
            best_score = score
            best_cat = cat

    # Only use smart selection if meaningful score
    if best_score > 1:
        return best_cat

    # Fallback: count-based (original behavior)
    idx = min(fallback_index, len(categories) - 1)
    return categories[idx]


def build_filtered_url(category_href, price_min=None, price_max=None):
    """Build a filtered URL with category + offers only + price range.

    Kleinanzeigen URL structure: /s-CATEGORY/FILTERS.../SEARCH_TERM/k0cID
    Filters go BEFORE the search term, not after it.
    The search term is the segment immediately before /k0c.
    """
    url = category_href
    # Find the search term segment (right before /k0c)
    match = re.match(r"(.*/)([^/]+)(/k0c.*)$", url)
    if not match:
        return url

    prefix, search_seg, suffix = match.groups()

    # Build filter segments
    filters = []
    if "/anzeige:angebote" not in url:
        filters.append("anzeige:angebote")
    if price_min and price_max and "preis:" not in url:
        filters.append(f"preis:{price_min}:{price_max}")

    filter_str = "/".join(filters)
    if filter_str:
        url = f"{prefix}{filter_str}/{search_seg}{suffix}"
    else:
        url = category_href

    return url


def extract_listings(tree):
    """Extract listings from a search results page."""
    listings = []
    for item in tree.css("article.aditem"):
        title_el = item.css_first(".ellipsis")
        price_el = item.css_first(".aditem-main--middle--price-shipping--price")
        url_el = item.css_first('a[href*="/s-anzeige/"]')
        date_el = item.css_first(".aditem-main--top--right")
        loc_el = item.css_first(".aditem-main--top--left")
        bottom_el = item.css_first(".aditem-main--bottom")

        title = title_el.text(strip=True) if title_el else ""
        url = url_el.attrs.get("href", "") if url_el else ""
        date_str = date_el.text(strip=True) if date_el else ""

        # Location: "12345 Stadtname"
        location = ""
        if loc_el:
            loc_text = loc_el.text(strip=True)
            loc_text = re.sub(r"^\s*\W*\s*", "", loc_text)
            location = loc_text

        # Shipping: check for "Versand möglich" or "Direkt kaufen" tag
        shipping = False
        if bottom_el:
            tags = bottom_el.css("span.simpletag")
            for tag in tags:
                tag_text = tag.text(strip=True).lower()
                if "versand" in tag_text or "direkt kaufen" in tag_text:
                    shipping = True
                    break

        # Price: direct text only, skip nested old-price <s> elements
        price_text = price_el.text(deep=False).strip() if price_el else ""

        # Parse German price: "1.234 €" or "1.234,50 € VB"
        price = None
        if price_text:
            cleaned = price_text.replace("€", "").replace("VB", "").strip()
            cleaned = re.sub(r"[^\d.,]", "", cleaned)
            if cleaned:
                cleaned = cleaned.replace(".", "").replace(",", ".")
                try:
                    price = float(cleaned)
                except ValueError:
                    pass

        listings.append(
            {
                "title": title,
                "price": price,
                "priceText": price_text,
                "date": date_str,
                "url": url,
                "location": location,
                "shipping": shipping,
            }
        )

    # Determine current page number
    current_page = 1
    current_el = tree.css_first(".pagination-current")
    if current_el:
        m = re.search(r"\d+", current_el.text())
        if m:
            current_page = int(m.group())

    # Collect all pagination links with page numbers
    page_links = {}
    for a in tree.css("a.pagination-page"):
        href = a.attrs.get("href", "")
        m = re.search(r"seite:(\d+)", href)
        if m:
            page_links[int(m.group(1))] = href

    # Pick the next page (current + 1)
    next_page_href = page_links.get(current_page + 1)

    return listings, next_page_href


def classify_age(date_str):
    """Classify listing age from the date string."""
    date_str = date_str.strip()
    if not date_str:
        return "unknown", None

    today = datetime.now().date()

    if "heute" in date_str.lower():
        return "fresh", 0
    if "gestern" in date_str.lower():
        return "fresh", 1

    # Try DD.MM.YYYY format
    match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", date_str)
    if match:
        try:
            posted = datetime(
                int(match.group(3)), int(match.group(2)), int(match.group(1))
            ).date()
            days = (today - posted).days
            if days <= 2:
                return "fresh", days
            elif days <= 7:
                return "normal", days
            elif days <= 14:
                return "negotiable", days
            elif days <= 30:
                return "stale", days
            else:
                return "expired", days
        except ValueError:
            pass

    # DD.MM. (without year)
    match = re.search(r"(\d{2})\.(\d{2})\.", date_str)
    if match:
        try:
            posted = datetime(
                today.year, int(match.group(2)), int(match.group(1))
            ).date()
            if posted > today:
                posted = posted.replace(year=today.year - 1)
            days = (today - posted).days
            if days <= 2:
                return "fresh", days
            elif days <= 7:
                return "normal", days
            elif days <= 14:
                return "negotiable", days
            elif days <= 30:
                return "stale", days
            else:
                return "expired", days
        except ValueError:
            pass

    return "unknown", None


PARTS_STRONG = [
    "ersatzteil",
    "ersatzteile",
    "für bastler",
    "zum basteln",
    "nicht funktionsfähig",
    "funktioniert nicht",
    "ohne funktion",
]

# Groups of synonyms — 2+ words from SAME group = part listing
# 1 word from group + price < 50% median = suspected part (post-filter)
PARTS_GROUPS = [
    ["display", "screen", "bildschirm", "lcd", "oled", "led panel"],
    ["tastatur", "keyboard"],
    ["akku", "battery", "batterie"],
    ["trackpad", "touchpad"],
    ["lüfter", "fan"],
    ["scharnier", "hinge"],
    ["netzteil", "charger", "ladekabel", "ladegerät"],
    ["gehäuse", "housing", "palmrest"],
    ["flexkabel", "flex cable"],
]


def _count_part_signals(title_lower):
    """Count part keyword signals: (strong_hit, groups_hit, synonym_hit).

    Returns:
        strong_hit: True if a strong part keyword matched
        groups_hit: number of different part groups with at least 1 match
        synonym_hit: True if 2+ words from the same group matched
    """
    strong_hit = any(kw in title_lower for kw in PARTS_STRONG)
    groups_hit = 0
    synonym_hit = False
    for group in PARTS_GROUPS:
        matches = sum(1 for kw in group if kw in title_lower)
        if matches >= 1:
            groups_hit += 1
        if matches >= 2:
            synonym_hit = True
    return strong_hit, groups_hit, synonym_hit


def extract_specs(title):
    """Extrahiere technische Specs aus Listing-Titeln (CPU, RAM, SSD, GPU)."""
    specs = {}
    t = title or ""

    # CPU: i7-6700, i5-8350U, Ryzen 5 5600X
    cpu = re.search(
        r"(i[357]-\d{4,5}\w*|Ryzen\s*\d\s*\d{4}\w*|Xeon\s*E\d-\d+\w*)",
        t,
        re.IGNORECASE,
    )
    if cpu:
        specs["cpu"] = cpu.group(1).strip()

    # Step 1: Explicit keyword matches (RAM with keyword, Storage with keyword)
    ram_explicit = re.search(
        r"(\d{1,3})\s*GB\s*(?:RAM|DDR\d?|Arbeitsspeicher)",
        t,
        re.IGNORECASE,
    )
    storage_explicit = re.search(
        r"(\d{3,4})\s*GB\s*(?:SSD|NVMe|M\.2)|(\d)\s*TB\s*(?:SSD|NVMe|HDD)?",
        t,
        re.IGNORECASE,
    )

    # Step 2: Apply explicit matches
    storage_val = None
    if storage_explicit:
        if storage_explicit.group(1):
            storage_val = int(storage_explicit.group(1))
        elif storage_explicit.group(2):
            storage_val = int(storage_explicit.group(2)) * 1000
        specs["storage_gb"] = storage_val

    if ram_explicit:
        val = int(ram_explicit.group(1))
        if val in (4, 8, 16, 32, 64, 128):
            specs["ram_gb"] = val

    # Step 3: Bare "NGB" without keyword → storage if ≥128, RAM if ≤64
    if "ram_gb" not in specs or "storage_gb" not in specs:
        bare = re.findall(
            r"(\d{1,3})\s*GB(?!\s*(?:RAM|DDR|SSD|NVMe|M\.))", t, re.IGNORECASE
        )
        for b in bare:
            val = int(b)
            if val >= 128 and "storage_gb" not in specs:
                specs["storage_gb"] = val
                storage_val = val
            elif val <= 64 and val in (4, 8, 16, 32, 64) and "ram_gb" not in specs:
                specs["ram_gb"] = val

    # GPU: RTX 3060, GTX 1080 Ti, RX 6700 XT
    gpu = re.search(
        r"((?:RTX|GTX|RX)\s*\d{3,4}(?:\s*(?:Ti|Super|XT))?)",
        t,
        re.IGNORECASE,
    )
    if gpu:
        specs["gpu"] = gpu.group(1).strip()

    # Display: 14", 15,6 Zoll, 13.3"
    display = re.search(r"(\d{2}[,.]?\d?)\s*(?:Zoll|\"|\u2033)", t)
    if display:
        specs["display"] = display.group(1).replace(",", ".")

    return specs if specs else None


def filter_listings(listings, context_keywords=None, exclude_keywords=None):
    """Filter listings and return (clean, filtered_out)."""
    clean = []
    for item in listings:
        reason = None
        title_lower = (item.get("title") or "").lower()
        price = item.get("price")

        # Null-Preise
        if price is None:
            reason = "kein_preis"
        # Platzhalter
        elif price <= 1 or price >= 9999:
            reason = "platzhalter"
        # Tausch
        elif any(w in title_lower for w in ["tausch", "im tausch", " gegen "]):
            reason = "tausch"
        # Zu verschenken
        elif "verschenk" in title_lower:
            reason = "verschenken"
        # Defekt
        elif any(
            w in title_lower
            for w in ["defekt", "kaputt", "broken", "display riss", "glasbruch"]
        ):
            reason = "defekt"

        # Ersatzteile (starke Indikatoren oder 2+ Synonyme aus SELBER Gruppe)
        # Schwächere Signale (2+ verschiedene Gruppen) → Post-Filter mit Preischeck
        if not reason:
            strong, _groups, synonym = _count_part_signals(title_lower)
            if strong or synonym:
                reason = "ersatzteil"

        # Kontextfilter (exclude_keywords)
        if not reason and exclude_keywords:
            for kw in exclude_keywords:
                if kw.lower() in title_lower:
                    reason = f"kontext:{kw}"
                    break

        # Alter
        if not reason:
            age_cat, days = classify_age(item.get("date", ""))
            item["age_category"] = age_cat
            item["age_days"] = days
            if age_cat == "expired":
                reason = "karteileiche"
        else:
            age_cat, days = classify_age(item.get("date", ""))
            item["age_category"] = age_cat
            item["age_days"] = days

        item["filtered_reason"] = reason
        item["included_in_median"] = 0 if reason else 1
        clean.append(item)

    return clean


def apply_price_anchor(listings, neupreis):
    """Filter listings outside a plausible price window around the new price.

    Window: 15%-130% of neupreis. Listings outside get filtered_reason="preis_anker".
    Only affects listings that are currently included_in_median.
    """
    if not neupreis or neupreis <= 0:
        return listings

    floor = neupreis * 0.15
    ceiling = neupreis * 1.30

    anchored = 0
    for item in listings:
        if not item.get("included_in_median"):
            continue
        price = item.get("price")
        if price is not None and (price < floor or price > ceiling):
            item["filtered_reason"] = "preis_anker"
            item["included_in_median"] = 0
            anchored += 1

    if anchored:
        print(
            f"  Preis-Anker ({int(floor)}-{int(ceiling)}€): {anchored} gefiltert",
            file=sys.stderr,
        )
    return listings


def fetch_listing_description(listing_url):
    """Fetch the description text from a listing detail page."""
    try:
        full_url = (
            listing_url if listing_url.startswith("http") else BASE_URL + listing_url
        )
        resp = SESSION.get(full_url)
        resp.raise_for_status()

        # Detect redirect (deleted/expired listings redirect to search pages)
        if "/s-anzeige/" not in str(resp.url):
            return ""

        tree = LexborHTMLParser(resp.text)

        # Primary: #viewad-description-text (standard Kleinanzeigen layout)
        desc_el = tree.css_first("#viewad-description-text")
        if not desc_el:
            # Fallback: itemprop="description"
            desc_el = tree.css_first('[itemprop="description"]')
        if not desc_el:
            return ""

        # Get text, normalize whitespace but keep line breaks
        text = desc_el.text(strip=True)
        # Collapse multiple spaces/newlines
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()[:1000]  # cap at 1000 chars
    except Exception:
        return ""


def check_seller(listing_url):
    """Check a seller profile for account age and trust badges."""
    try:
        full_url = (
            listing_url if listing_url.startswith("http") else BASE_URL + listing_url
        )
        tree = fetch_page(full_url)
        body_text = tree.text()

        # Account aktiv seit
        aktiv_match = re.search(r"Aktiv seit\s*([\d.]+)", body_text)
        aktiv_seit = aktiv_match.group(1) if aktiv_match else None

        # Nutzertyp
        nutzer_match = re.search(r"(Privater Nutzer|Gewerblicher Nutzer)", body_text)
        nutzer_typ = nutzer_match.group(1) if nutzer_match else "unbekannt"

        # Badges
        badges = []
        for badge_el in tree.css(".userbadge-tag"):
            badge_text = badge_el.text(strip=True)
            if badge_text:
                badges.append(badge_text)

        # Seller listing count (Anzahl Anzeigen)
        listing_count = None
        listing_match = re.search(r"\b(\d{1,5})\s*Anzeige", body_text)
        if listing_match:
            count = int(listing_match.group(1))
            if count < 100000:  # Sanity: no listing ID leakage
                listing_count = count

        # Follower count (optional)
        follower_count = None
        follower_match = re.search(r"(\d+)\s*Follower", body_text)
        if follower_match:
            follower_count = int(follower_match.group(1))

        # Account-Alter berechnen
        account_age_days = None
        is_scam = False
        scam_signals = []
        if aktiv_seit:
            try:
                parts = aktiv_seit.split(".")
                if len(parts) == 3:
                    reg_date = datetime(
                        int(parts[2]), int(parts[1]), int(parts[0])
                    ).date()
                    account_age_days = (datetime.now().date() - reg_date).days
                    if account_age_days < 14:
                        scam_signals.append("account<14d")
                    elif account_age_days < 30:
                        scam_signals.append("account<30d")
            except (ValueError, IndexError):
                pass

        # Trust check
        has_trust = bool(set(badges) & TRUST_BADGES)

        # Erweiterte Scam-Indikatoren
        if listing_count is not None and listing_count <= 1:
            if account_age_days is not None and account_age_days < 90:
                scam_signals.append("erstinserat")
        if not has_trust and account_age_days is not None and account_age_days < 60:
            scam_signals.append("kein_trust_jung")

        # Entscheidung: harte Signale oder Kombi
        if "account<14d" in scam_signals:
            is_scam = True  # < 2 Wochen = immer verdächtig
        elif "account<30d" in scam_signals and not has_trust:
            is_scam = True  # < 30 Tage ohne Trust
        elif len(scam_signals) >= 2 and not has_trust:
            is_scam = True  # 2+ schwache Signale ohne Trust

        return {
            "aktiv_seit": aktiv_seit,
            "nutzer_typ": nutzer_typ,
            "badges": badges,
            "account_age_days": account_age_days,
            "listing_count": listing_count,
            "follower_count": follower_count,
            "is_scam": is_scam,
            "scam_signals": scam_signals,
            "has_trust": has_trust,
            "reachable": True,
        }
    except Exception as e:
        return {
            "aktiv_seit": None,
            "nutzer_typ": "unbekannt",
            "badges": [],
            "account_age_days": None,
            "listing_count": None,
            "follower_count": None,
            "is_scam": False,
            "has_trust": False,
            "reachable": False,
            "error": str(e),
        }


# Risk-Keywords in Beschreibungen → Warnflag für Smart-Picks
_RISK_KEYWORDS = {
    "bios_lock": ["bios gesperrt", "bios locked", "bios password", "bios-passwort"],
    "mdm_lock": ["mdm", "device management", "jamf", "intune", "gesperrt"],
    "bastler": ["bastler", "zum basteln", "für bastler", "bastelware"],
    "firmen": ["firmenauflösung", "büroauflösung", "insolvenz"],
    "icloud": ["icloud gesperrt", "icloud locked", "aktivierungssperre"],
    "ohne_nt": ["ohne netzteil", "ohne ladegerät", "kein netzteil", "kein ladekabel"],
    "ohne_hdd": ["ohne festplatte", "ohne ssd", "ohne hdd", "keine festplatte"],
    "defekt": [
        "defekt",
        "kaputt",
        "wasserschaden",
        "water damage",
        "displaybruch",
        "display gebrochen",
        "geht nicht an",
        "startet nicht",
        "funktioniert nicht",
    ],
}


def detect_description_risks(description, title=""):
    """Erkennt Risiko-Keywords in Listing-Titel + Beschreibung."""
    text = f"{title} {description or ''}".lower()
    if not text.strip():
        return []
    risks = []
    for risk_type, keywords in _RISK_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            risks.append(risk_type)
    return risks


# Too-Good-To-Be-True (TGTBT) — Warnflags statt binärer Scam-Erkennung
# Basiert auf Recherche aktueller Betrugsmaschen (2024-2025):
# Gehackte Accounts, KI-Fotos, Dringlichkeits-Masche
_URGENCY_KEYWORDS = [
    "notverkauf",
    "muss schnell weg",
    "schnellverkauf",
    "dringend verkauf",
    "muss sofort raus",
    "brauche das geld",
    "umzug morgen",
    "sofort abholen",
    "heute noch",
    "nur heute",
    "schnell zuschlagen",
    "nur noch heute",
    "letzte chance",
]


def detect_tgtbt_flags(listing, median_price):
    """Erkennt Too-Good-To-Be-True Warnsignale.

    Returns list of warning flags (nicht Scam, sondern Vorsichtshinweise).
    """
    flags = []
    price = listing.get("price", 0)
    desc = (listing.get("description") or "").lower()
    title = (listing.get("title") or "").lower()

    # 1. Preis deutlich unter Median (< 60%)
    if median_price and price and price < median_price * 0.60:
        discount = round((1 - price / median_price) * 100)
        flags.append(f"preis_{discount}pct_unter_median")

    # 2. Dringlichkeits-Signale in Beschreibung oder Titel
    text = f"{title} {desc}"
    for kw in _URGENCY_KEYWORDS:
        if kw in text:
            flags.append("dringlichkeit")
            break

    # 3. Preis + Dringlichkeit = starkes Warnsignal
    if "dringlichkeit" in flags and any("preis_" in f for f in flags):
        flags.append("tgtbt_kombi")

    return flags


def calculate_stats(listings):
    """Calculate median, IQR, and clean stats from included listings."""
    included = [listing for listing in listings if listing.get("included_in_median")]
    prices = sorted([listing["price"] for listing in included if listing.get("price")])

    if not prices:
        return {
            "median": None,
            "q1": None,
            "q3": None,
            "min": None,
            "max": None,
            "n": 0,
        }

    med = median(prices)

    if len(prices) >= 4:
        q = quantiles(prices, n=4)
        q1, q3 = q[0], q[2]
        iqr = q3 - q1
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr

        # Mark IQR outliers
        for listing in listings:
            if listing.get("included_in_median") and listing.get("price"):
                if listing["price"] < lower or listing["price"] > upper:
                    listing["included_in_median"] = 0
                    listing["filtered_reason"] = "iqr_outlier"

        # Recalculate after IQR
        final_prices = sorted(
            [
                listing["price"]
                for listing in listings
                if listing.get("included_in_median") and listing.get("price")
            ]
        )
        if final_prices:
            med = median(final_prices)
            if len(final_prices) >= 4:
                q = quantiles(final_prices, n=4)
                q1, q3 = q[0], q[2]
            else:
                q1, q3 = final_prices[0], final_prices[-1]
            return {
                "median": round(med),
                "q1": round(q1),
                "q3": round(q3),
                "min": round(final_prices[0]),
                "max": round(final_prices[-1]),
                "n": len(final_prices),
            }
    else:
        q1, q3 = prices[0], prices[-1]

    return {
        "median": round(med),
        "q1": round(q1),
        "q3": round(q3),
        "min": round(prices[0]),
        "max": round(prices[-1]),
        "n": len(prices),
    }


def flag_suspected_parts(listings, stats):
    """Post-filter: flag listings with part keywords AND price < 50% median."""
    med = stats.get("median", 0)
    if not med:
        return listings
    threshold = med * 0.50
    flagged = 0
    for listing in listings:
        if not listing.get("included_in_median") or not listing.get("price"):
            continue
        if listing["price"] >= threshold:
            continue
        title_lower = (listing.get("title") or "").lower()
        _strong, groups_hit, _synonym = _count_part_signals(title_lower)
        if groups_hit >= 1:
            listing["included_in_median"] = 0
            listing["filtered_reason"] = "ersatzteil_verdacht"
            flagged += 1
    if flagged:
        print(
            f"  Ersatzteil-Verdacht: {flagged} gefiltert (Preis < 50% Median + Bauteil-Keywords)",
            file=sys.stderr,
        )
    return listings


def score_listings(listings, stats):
    """Score each included listing on a 0-100 scale with 5 dimensions.

    Dimensions:
    - Preis-Vorteil (0-25): Abstand zum Median
    - Verkäufer-Trust (0-30): Badges + Account-Alter
    - Verhandlungs-Potenzial (0-20): Anzeigen-Alter
    - Komfort (0-15): Versand, Beschreibung, Anzeigenanzahl
    - Frische-Risiko (0 bis -10): Alte Anzeigen = Risiko
    """
    med = stats.get("median", 0)
    if not med:
        return listings

    for listing in listings:
        if not listing.get("included_in_median") or not listing.get("price"):
            listing["score"] = 0
            listing["score_breakdown"] = {}
            continue

        # 1. Preis-Vorteil (0-25): linear, cap bei -30% unter Median
        price_ratio = listing["price"] / med
        price_score = round(max(0, min(25, (1 - price_ratio) / 0.30 * 25)))

        # 2. Verkäufer-Trust (0-30): Badges (0-20) + Account-Alter (0-10)
        badges = (listing.get("seller_badges") or "").lower()
        badge_score = 0
        if "na ja" in badges or "naja" in badges:
            badge_score = 0
        elif "top zufriedenheit" in badges:
            badge_score = 20
        elif "sehr" in badges:
            badge_score = 14
        elif badges:
            badge_score = 8

        account_age = listing.get("seller_age_days")
        age_trust_score = 0
        if account_age is not None:
            if account_age > 730:  # >2 Jahre
                age_trust_score = 10
            elif account_age > 365:  # >1 Jahr
                age_trust_score = 7
            elif account_age > 180:  # >6 Monate
                age_trust_score = 4
            # <6 Monate = 0

        trust_score = badge_score + age_trust_score

        # 3. Verhandlungs-Potenzial (0-20): Anzeigen-Alter
        age = listing.get("age_days") or 0
        if age > 14:
            nego_score = 20
        elif age > 7:
            nego_score = 14
        elif age > 3:
            nego_score = 8
        else:
            nego_score = 4

        # 4. Komfort (0-15): Versand + Beschreibung + mehrere Anzeigen
        comfort_score = 0
        if listing.get("shipping"):
            comfort_score += 8
        if listing.get("description"):
            comfort_score += 4
        seller_listings = listing.get("seller_listing_count")
        if seller_listings and seller_listings > 1:
            comfort_score += 3

        # 5. Frische-Risiko (0 bis -18): Ältere Anzeigen = wahrscheinlich
        # verkauft oder abandoned. Gems verstecken sich in der Masse,
        # aber >14 Tage ist ein starkes Signal.
        if age and age > 30:
            fresh_penalty = -18
        elif age and age > 21:
            fresh_penalty = -12
        elif age and age > 14:
            fresh_penalty = -7
        elif age and age > 7:
            fresh_penalty = -3
        else:
            fresh_penalty = 0

        # 6. Beschreibungs-Risiko (0 bis -15): BIOS-Lock, MDM, Bastler etc.
        risks = detect_description_risks(
            listing.get("description", ""), listing.get("title", "")
        )
        listing["risk_flags"] = risks
        risk_penalty = 0
        for risk in risks:
            if risk in ("bios_lock", "mdm_lock", "icloud", "defekt"):
                risk_penalty -= 10  # Harte Locks/Defekte = schwerer Malus
            elif risk in ("bastler", "ohne_hdd"):
                risk_penalty -= 5
            elif risk in ("ohne_nt", "firmen"):
                risk_penalty -= 3
        risk_penalty = max(-15, risk_penalty)

        # 7. TGTBT-Flags (informativ, kein Score-Malus)
        tgtbt = detect_tgtbt_flags(listing, med)
        listing["tgtbt_flags"] = tgtbt

        total = (
            price_score
            + trust_score
            + nego_score
            + comfort_score
            + fresh_penalty
            + risk_penalty
        )
        listing["score"] = max(0, total)
        listing["score_breakdown"] = {
            "price": price_score,
            "trust": trust_score,
            "negotiation": nego_score,
            "comfort": comfort_score,
            "freshness": fresh_penalty,
            "risk": risk_penalty,
        }

    return listings


def run_nearby_search(
    search_term, filter_url, stats, exclude_keywords=None, neupreis=None
):
    """Lightweight location-filtered search to find best nearby listing.

    Uses the same category/filters as the main search but adds location + radius.
    Only fetches 2 pages max to keep request count low.
    """
    med = stats.get("median")
    if not med:
        return None

    radius = get_search_radius(med)

    # Build location URL from the existing filter URL
    # Input:  /s-CATEGORY/FILTERS/SEARCH/k0cCATID
    # Output: /s-PLZ/CATEGORY/FILTERS/SEARCH/k0cCATIDlLOCIDrRADIUS
    url = filter_url

    # Insert PLZ after /s-
    url = re.sub(r"^/s-", f"/s-{HOME_PLZ}/", url)

    # Append location + radius to the category suffix (k0cXXX -> k0cXXXlYYYYrZZ)
    url = re.sub(r"(k0c\d+)(.*)?$", rf"\1l{HOME_LOCATION_ID}r{radius}", url)

    full_url = BASE_URL + url if not url.startswith("http") else url
    print(f"[Nearby] Suche im Umkreis {radius}km um {HOME_PLZ}", file=sys.stderr)

    all_listings = []
    next_href = None
    for page in range(1, 3):  # max 2 pages
        page_url = full_url if page == 1 else (BASE_URL + next_href)
        try:
            soup = fetch_page(page_url)
            page_listings, next_href = extract_listings(soup)
            if not page_listings:
                break
            all_listings.extend(page_listings)
            if page == 1:
                print(f"  {len(page_listings)} Inserate auf Seite 1", file=sys.stderr)
            if not next_href:
                break
            time.sleep(1.0)
        except Exception as e:
            print(f"  Nearby Seite {page} Fehler: {e}", file=sys.stderr)
            break

    if not all_listings:
        print("  Keine Nearby-Ergebnisse", file=sys.stderr)
        return None

    # Filter + Score
    all_listings = filter_listings(all_listings, exclude_keywords=exclude_keywords)
    if neupreis:
        all_listings = apply_price_anchor(all_listings, neupreis)
    score_listings(all_listings, stats)

    # Best scored nearby listing
    scored = sorted(
        [
            listing
            for listing in all_listings
            if listing.get("included_in_median")
            and listing.get("price")
            and listing.get("score", 0) > 0
        ],
        key=lambda x: x["score"],
        reverse=True,
    )

    if not scored:
        print("  Keine passenden Nearby-Angebote nach Filter", file=sys.stderr)
        return None

    best = scored[0]
    # Extract distance from location text if available
    loc_text = best.get("location", "")
    dist_match = re.search(r"\((\d+)\s*km\)", loc_text)
    distance_km = int(dist_match.group(1)) if dist_match else None

    # Clean location text
    clean_loc = re.sub(r"\s*\(\d+\s*km\)", "", loc_text).strip()
    clean_loc = re.sub(r"\s+", " ", clean_loc)

    pick = {
        "title": best.get("title", ""),
        "price": best.get("price"),
        "score": best.get("score", 0),
        "shipping": best.get("shipping", False),
        "url": best.get("url", ""),
        "age_days": best.get("age_days"),
        "age_category": best.get("age_category", ""),
        "location": clean_loc,
        "distance_km": distance_km,
        "radius_km": radius,
        "seller_badges": best.get("seller_badges", ""),
        "seller_since": best.get("seller_since", ""),
    }
    print(
        f"  TOP Nearby: {pick['title'][:40]} — {int(pick['price'])}€ ({clean_loc})",
        file=sys.stderr,
    )
    return pick


def run_search(
    search_term,
    category_index=0,
    price_min=None,
    price_max=None,
    exclude_keywords=None,
    max_seller_checks=6,
    neupreis=None,
    neupreis_source=None,
):
    """Run a full market search and return structured results."""
    start_time = time.time()
    result = {"product": search_term, "steps": []}

    # Step 1: Discover categories
    print(f"[1/6] Kategorien suchen: {search_term}", file=sys.stderr)
    discovery = discover_categories(search_term)
    result["discovery"] = {
        "heading": discovery["heading"],
        "categories": discovery["categories"][:5],
    }

    if not discovery["categories"]:
        result["error"] = "Keine Kategorien gefunden"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result

    # Select categories (top 2 für breitere Abdeckung bei wenigen Listings)
    cat = select_best_category(
        discovery["categories"], search_term, fallback_index=category_index
    )
    result["selected_category"] = cat["text"]
    count_based = discovery["categories"][
        min(category_index, len(discovery["categories"]) - 1)
    ]
    if cat["text"] != count_based["text"]:
        print(
            f"  Kategorie: {cat['text']} ({cat['count']}) "
            f"[smart, statt: {count_based['text']}]",
            file=sys.stderr,
        )
    else:
        print(f"  Kategorie: {cat['text']} ({cat['count']})", file=sys.stderr)

    # Zweite Kategorie wenn wenige Listings in der ersten
    secondary_cats = [
        c
        for c in discovery["categories"]
        if c["href"] != cat["href"] and c["count"] >= 3
    ]
    search_categories = [cat]
    if secondary_cats and cat["count"] < 50:
        second = secondary_cats[0]
        search_categories.append(second)
        print(
            f"  + Kategorie 2: {second['text']} ({second['count']})",
            file=sys.stderr,
        )

    # Step 2+3: Fetch pages from all categories (dedup per URL)
    all_listings = []
    seen_urls = set()

    for cat_idx, search_cat in enumerate(search_categories):
        filtered_url = build_filtered_url(search_cat["href"], price_min, price_max)
        full_url = (
            BASE_URL + filtered_url
            if not filtered_url.startswith("http")
            else filtered_url
        )
        if cat_idx == 0:
            result["filter_url"] = filtered_url

        cat_label = f"Kat{cat_idx + 1}" if len(search_categories) > 1 else ""
        print(f"[2/6] {cat_label} Seite 1 laden: {full_url}", file=sys.stderr)
        soup = fetch_page(full_url)
        page_listings, next_href = extract_listings(soup)

        new_listings = []
        for lst in page_listings:
            url = lst.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                new_listings.append(lst)
        all_listings.extend(new_listings)
        print(
            f"  Seite 1: {len(page_listings)} Inserate "
            f"({len(new_listings)} neu, gesamt: {len(all_listings)})",
            file=sys.stderr,
        )

        # Dynamic pagination — mehr Seiten für bessere Gem-Abdeckung
        max_pages = 20
        prev_count = len(new_listings) if new_listings else 0
        for page_num in range(2, max_pages + 1):
            if not next_href:
                break
            page_url = (
                BASE_URL + next_href if not next_href.startswith("http") else next_href
            )
            print(f"[3/6] {cat_label} Seite {page_num} laden", file=sys.stderr)
            try:
                soup_p = fetch_page(page_url)
                page_listings, next_href = extract_listings(soup_p)
                if not page_listings:
                    break
                new_on_page = []
                for lst in page_listings:
                    url = lst.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        new_on_page.append(lst)
                all_listings.extend(new_on_page)
                new_count = len(new_on_page)
                print(
                    f"  Seite {page_num}: {len(page_listings)} Inserate "
                    f"({new_count} neu, gesamt: {len(all_listings)})",
                    file=sys.stderr,
                )
                if prev_count > 0 and new_count < prev_count * 0.3:
                    print("  Sättigung erreicht (< 30% neue)", file=sys.stderr)
                    break
                prev_count = new_count
                import random

                time.sleep(1.0 + random.random() * 1.5)  # 1-2.5s Jitter
            except Exception as e:
                print(f"  Seite {page_num} Fehler: {e}", file=sys.stderr)
                break

        if len(search_categories) > 1 and cat_idx < len(search_categories) - 1:
            time.sleep(1.5)  # Rate-Limit Schutz zwischen Kategorien

    total_raw = len(all_listings)

    # Step 3b: Spec-Extraction aus Titeln
    for lst in all_listings:
        specs = extract_specs(lst.get("title", ""))
        if specs:
            lst["specs"] = specs

    # Step 4: Filter
    print(f"[4/6] Filtern ({total_raw} roh)", file=sys.stderr)
    all_listings = filter_listings(all_listings, exclude_keywords=exclude_keywords)
    included = [
        listing for listing in all_listings if listing.get("included_in_median")
    ]
    total_clean = len(included)
    print(f"  {total_clean} nach Filter", file=sys.stderr)

    # Step 4b: Neupreis-Sanity-Check — Geizhals kann falsches Produkt liefern
    # Gebrauchtwaren kosten immer WENIGER als Neupreis.
    # Wenn neupreis < 70% vom Gebraucht-Median → falsches Produkt (z.B. Zubehör)
    if neupreis and included:
        pre_prices = sorted(
            [listing["price"] for listing in included if listing.get("price")]
        )
        pre_median = median(pre_prices) if pre_prices else 0
        if pre_median > 0 and neupreis < pre_median * 0.70:
            print(
                f"  ⚠ Neupreis {neupreis:.0f}€ < 70% von Median {pre_median:.0f}€ "
                f"— falsches Geizhals-Match verworfen",
                file=sys.stderr,
            )
            neupreis = None
            neupreis_source = None
        elif (
            pre_median > 0
            and neupreis > pre_median * 3
            and neupreis_source
            and "geizhals" in neupreis_source.lower()
        ):
            print(
                f"  ⚠ Neupreis {neupreis:.0f}€ >> Median {pre_median:.0f}€ "
                f"(> 3x) — Geizhals-Ergebnis verworfen",
                file=sys.stderr,
            )
            neupreis = None
            neupreis_source = None

    # Step 4c: Price anchor filter (if neupreis known and sane)
    if neupreis:
        all_listings = apply_price_anchor(all_listings, neupreis)
        included = [
            listing for listing in all_listings if listing.get("included_in_median")
        ]
        total_clean = len(included)
        print(f"  {total_clean} nach Preis-Anker", file=sys.stderr)

    # Step 5: Seller checks
    print("[5/6] Verkäufer prüfen", file=sys.stderr)
    # Pre-median for scam detection
    pre_prices = sorted(
        [listing["price"] for listing in included if listing.get("price")]
    )
    pre_median = median(pre_prices) if pre_prices else 0

    # Collect URLs to check: scam suspects + cheapest for recommendation
    urls_to_check = {}  # url -> listing index mapping

    # Scam suspects: price < 70% of pre-median (verschärft von 85%)
    scam_threshold = pre_median * 0.70
    for i, listing in enumerate(all_listings):
        if (
            listing.get("included_in_median")
            and listing.get("price")
            and listing["price"] < scam_threshold
        ):
            if listing.get("url") and len(urls_to_check) < 5:
                urls_to_check[listing["url"]] = {"index": i, "reason": "scam_check"}

    # Cheapest listings: also check seller trust for scoring
    sorted_included = sorted(
        [
            (i, listing)
            for i, listing in enumerate(all_listings)
            if listing.get("included_in_median") and listing.get("price")
        ],
        key=lambda x: x[1]["price"],
    )
    for idx, (i, listing) in enumerate(sorted_included[:3]):
        if listing.get("url") and listing["url"] not in urls_to_check:
            urls_to_check[listing["url"]] = {"index": i, "reason": "trust_check"}

    total_scam = 0

    if urls_to_check:
        print(f"  {len(urls_to_check)} Verkäufer-Profile prüfen", file=sys.stderr)
        for url, info in urls_to_check.items():
            seller = check_seller(url)
            idx = info["index"]

            if not seller["reachable"]:
                # Listing deleted/unreachable -> remove from analysis
                all_listings[idx]["included_in_median"] = 0
                all_listings[idx]["filtered_reason"] = "nicht_erreichbar"
                print(f"    {url[:60]}... -> nicht erreichbar", file=sys.stderr)
                continue

            all_listings[idx]["seller_type"] = seller["nutzer_typ"]
            all_listings[idx]["seller_since"] = seller["aktiv_seit"]
            all_listings[idx]["seller_badges"] = ", ".join(seller["badges"])
            all_listings[idx]["seller_listing_count"] = seller.get("listing_count")
            all_listings[idx]["seller_follower_count"] = seller.get("follower_count")

            if seller["is_scam"]:
                all_listings[idx]["is_scam"] = 1
                all_listings[idx]["scam_reason"] = ", ".join(
                    seller.get("scam_signals", [])
                )
                all_listings[idx]["included_in_median"] = 0
                all_listings[idx]["filtered_reason"] = "scam"
                total_scam += 1
                signals = seller.get("scam_signals", [])
                print(
                    f"    SCAM: {', '.join(signals) if signals else 'Account < 30d'}",
                    file=sys.stderr,
                )
            else:
                trust_info = "Trust" if seller["has_trust"] else "kein Trust"
                age_info = f"{seller.get('account_age_days', '?')}d"
                listing_info = (
                    f", {seller.get('listing_count', '?')} Anzeigen"
                    if seller.get("listing_count")
                    else ""
                )
                all_listings[idx]["seller_age_days"] = seller.get("account_age_days")
                print(f"    {trust_info}, {age_info}{listing_info}", file=sys.stderr)
    else:
        print("  Keine Seller-Checks nötig", file=sys.stderr)

    # Build recommendation: cheapest listing with trust badges
    # "NA JA Zufriedenheit" = unzureichend, wird ausgeschlossen
    recommendation = None
    trust_listings = sorted(
        [
            listing
            for listing in all_listings
            if listing.get("included_in_median")
            and listing.get("price")
            and listing.get("seller_badges")
            and "zufriedenheit" in (listing.get("seller_badges") or "").lower()
            and "na ja" not in (listing.get("seller_badges") or "").lower()
        ],
        key=lambda x: x["price"],
    )
    if trust_listings:
        best = trust_listings[0]
        recommendation = {
            "price": best["price"],
            "title": best.get("title", ""),
            "url": best.get("url", ""),
            "seller_since": best.get("seller_since", ""),
            "seller_age_days": best.get("seller_age_days"),
            "badges": [
                b.strip()
                for b in (best.get("seller_badges") or "").split(",")
                if b.strip()
            ],
        }
        best["is_recommended"] = 1
        print(f"    EMPFEHLUNG: {best.get('title', '?')}", file=sys.stderr)

    # Step 6: Final calculation
    print("[6/6] Statistik berechnen", file=sys.stderr)
    stats = calculate_stats(all_listings)
    _total_final = len(
        [
            listing
            for listing in all_listings
            if listing.get("included_in_median")
            or not listing.get("filtered_reason")
            or listing.get("filtered_reason") == "iqr_outlier"
        ]
    )
    # total_final = after scam filter, before IQR
    total_after_scam = len(
        [
            listing
            for listing in all_listings
            if not listing.get("filtered_reason")
            or listing.get("filtered_reason") == "iqr_outlier"
        ]
    )
    total_in_median = stats["n"]

    duration = int(time.time() - start_time)

    # Ersatzteil-Post-Filter (nach Stats, vor Scoring)
    flag_suspected_parts(all_listings, stats)
    # Stats nach Post-Filter neu berechnen
    stats = calculate_stats(all_listings)

    # Scoring
    score_listings(all_listings, stats)
    scored = sorted(
        [
            listing
            for listing in all_listings
            if listing.get("included_in_median")
            and listing.get("price")
            and listing.get("score", 0) > 0
        ],
        key=lambda x: x["score"],
        reverse=True,
    )
    smart_picks = scored[:5]  # Top 5 für Agent-Validierung (finale 3 wählt Agent)

    # Fetch descriptions for Smart Picks (detail pages)
    if smart_picks:
        print(
            f"[6b/6] Beschreibungen laden ({len(smart_picks)} Picks)",
            file=sys.stderr,
        )
        for p in smart_picks:
            if p.get("url"):
                desc = fetch_listing_description(p["url"])
                p["description"] = desc
                if desc:
                    short = desc[:60].replace("\n", " ")
                    print(f"    ✓ {short}...", file=sys.stderr)
                time.sleep(0.3)

    # Nearby search (lightweight, 2 pages max)
    nearby_pick = run_nearby_search(
        search_term,
        filtered_url,
        stats,
        exclude_keywords=exclude_keywords,
        neupreis=neupreis,
    )

    # Fetch description for Nearby Pick
    if nearby_pick and nearby_pick.get("url"):
        desc = fetch_listing_description(nearby_pick["url"])
        nearby_pick["description"] = desc
        if desc:
            short = desc[:60].replace("\n", " ")
            print(f"    Nearby Beschreibung: {short}...", file=sys.stderr)

    # Age distribution
    age_dist = {"fresh": [], "normal": [], "negotiable": [], "stale": [], "expired": []}
    for listing in all_listings:
        cat_key = listing.get("age_category", "unknown")
        if (
            cat_key in age_dist
            and listing.get("price")
            and listing.get("included_in_median")
        ):
            age_dist[cat_key].append(listing["price"])

    # Post-IQR TGTBT scan: check IQR-excluded listings with good seller profiles
    # These could be hacked accounts (good trust but suspiciously low price)
    tgtbt_warnings = []
    good_badges = {
        "TOP Zufriedenheit",
        "Besonders zuverlässig",
        "Besonders freundlich",
        "Sehr zuverlässig",
        "Sehr freundlich",
    }
    for listing in all_listings:
        if listing.get("filtered_reason") != "iqr_outlier":
            continue
        if not listing.get("price") or not listing.get("seller_badges"):
            continue
        badges_set = {b.strip() for b in listing.get("seller_badges", "").split(",")}
        has_good = bool(badges_set & good_badges)
        if (
            has_good
            and stats.get("median")
            and listing["price"] < stats["median"] * 0.75
        ):
            pct = round((1 - listing["price"] / stats["median"]) * 100)
            tgtbt_warnings.append(
                {
                    "title": listing.get("title", ""),
                    "price": listing["price"],
                    "url": listing.get("url", ""),
                    "seller_badges": listing.get("seller_badges", ""),
                    "seller_since": listing.get("seller_since", ""),
                    "pct_under_median": pct,
                    "warning": f"IQR-Ausreißer mit Top-Badges: {pct}% unter Median. "
                    f"Möglicherweise gehackter Account — vor Kauf genau prüfen!",
                }
            )
    if tgtbt_warnings:
        print(
            f"  ⚠ {len(tgtbt_warnings)} TGTBT-Warnungen (IQR-Ausreißer mit guten Badges)",
            file=sys.stderr,
        )

    # Build final result
    result.update(
        {
            "total_raw": total_raw,
            "total_clean": total_clean,
            "total_scam": total_scam,
            "total_final": total_after_scam,
            "total_in_median": total_in_median,
            "stats": stats,
            "smart_picks": [
                {
                    "title": p.get("title", ""),
                    "price": p.get("price"),
                    "score": p.get("score", 0),
                    "score_breakdown": p.get("score_breakdown", {}),
                    "shipping": p.get("shipping", False),
                    "url": p.get("url", ""),
                    "age_days": p.get("age_days"),
                    "age_category": p.get("age_category", ""),
                    "seller_badges": p.get("seller_badges", ""),
                    "seller_since": p.get("seller_since", ""),
                    "account_age_days": p.get("seller_age_days"),
                    "seller_listing_count": p.get("seller_listing_count"),
                    "seller_follower_count": p.get("seller_follower_count"),
                    "description": p.get("description", ""),
                    "risk_flags": p.get("risk_flags", []),
                    "tgtbt_flags": p.get("tgtbt_flags", []),
                    "specs": p.get("specs"),
                }
                for p in smart_picks
            ],
            "nearby_pick": nearby_pick,
            "tgtbt_warnings": tgtbt_warnings,
            "recommendation": recommendation,
            "neupreis": neupreis,
            "neupreis_source": neupreis_source,
            "duration_seconds": duration,
            "age_distribution": {
                k: {"count": len(v), "median": round(median(v)) if v else None}
                for k, v in age_dist.items()
            },
            "listings": all_listings,
        }
    )

    # Auto-generate agent analysis (eliminates LLM inference bottleneck)
    result["agent_analysis"] = generate_agent_analysis(result)

    # JSON output (to stdout)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def generate_agent_analysis(result):
    """Algorithmische Agent-Analyse — ersetzt LLM-Inferenz komplett.

    Generiert Markteinschätzung, Pick-Begründungen, Preisvorschläge und Fazit
    basierend auf den gleichen Regeln die vorher der Agent manuell anwenden musste.
    """
    stats = result.get("stats", {})
    med = stats.get("median", 0)
    neupreis = result.get("neupreis")
    age_dist = result.get("age_distribution", {})
    picks = result.get("smart_picks", [])
    nearby = result.get("nearby_pick")
    total = result.get("total_in_median", 0)

    # --- Markteinschätzung ---
    stale_count = age_dist.get("stale", {}).get("count", 0)
    nego_count = age_dist.get("negotiable", {}).get("count", 0)
    _fresh_count = age_dist.get("fresh", {}).get("count", 0)
    verhandelbar_pct = round((stale_count + nego_count) / max(total, 1) * 100)

    if total > 50 and verhandelbar_pct > 40:
        market_type = "Käufermarkt"
        market_detail = f"Hohes Angebot ({total} Inserate), {verhandelbar_pct}% bereits verhandelbar"
    elif total > 20 and verhandelbar_pct > 25:
        market_type = "Ausgewogener Markt"
        market_detail = (
            f"Gutes Angebot ({total} Inserate), {verhandelbar_pct}% verhandelbar"
        )
    elif total < 10:
        market_type = "Verkäufermarkt"
        market_detail = f"Wenig Angebot ({total} Inserate), wenig Verhandlungsspielraum"
    else:
        market_type = "Leichter Käufermarkt"
        market_detail = f"{total} Inserate verfügbar, {verhandelbar_pct}% verhandelbar"

    if neupreis and med:
        diff_pct = round((neupreis - med) / neupreis * 100)
        if diff_pct > 0:
            market_detail += f". Gebraucht {diff_pct}% unter Neupreis"
        else:
            market_detail += (
                f". Gebraucht {abs(diff_pct)}% über Neupreis (hohe Nachfrage)"
            )

    analysis = {"market": f"{market_type}: {market_detail}."}

    # --- Pick-Begründungen + Preisvorschläge ---
    def suggest_price(pick):
        """Preisvorschlag basierend auf Alter (Skill-Regeln)."""
        price = pick.get("price", 0)
        age_cat = pick.get("age_category", "normal")
        age_days = pick.get("age_days", 5)

        if age_cat == "fresh" or (age_days and age_days <= 2):
            discount = 0.06  # 5-8%
        elif age_cat == "normal" or (age_days and age_days <= 7):
            discount = 0.10  # 8-12%
        elif age_cat == "negotiable" or (age_days and age_days <= 14):
            discount = 0.15  # 12-18%
        else:
            discount = 0.20  # 15-25%

        # TOP Trust → weniger aggressiv
        badges = (pick.get("seller_badges") or "").lower()
        if "top zufriedenheit" in badges:
            discount *= 0.7

        suggested = round(price * (1 - discount))
        # Nicht unter IQR-Minimum
        iqr_min = stats.get("min", 0)
        if iqr_min and suggested < iqr_min:
            suggested = iqr_min
        return suggested

    def pick_reason(pick, idx):
        """Begründung für einen Pick."""
        parts = []
        price = pick.get("price", 0)
        badges = pick.get("seller_badges") or ""
        age_days = pick.get("age_days", 0)
        shipping = pick.get("shipping", False)

        if med and price < med:
            pct_under = round((1 - price / med) * 100)
            parts.append(f"{pct_under}% unter Median")

        if "NA JA" in badges or "Naja" in badges:
            pass  # "NA JA Zufriedenheit" = kein positiver Hinweis
        elif "TOP" in badges or "Sehr" in badges:
            parts.append("vertrauenswürdiger Verkäufer")
        elif badges:
            parts.append("Seller mit Trust-Badges")

        if age_days and age_days > 7:
            parts.append("verhandelbar (>7 Tage online)")
        elif age_days and age_days <= 2:
            parts.append("frisch eingestellt")

        if shipping:
            parts.append("Versand verfügbar")

        if pick.get("description"):
            desc = pick["description"].lower()
            if "ovp" in desc or "rechnung" in desc or "originalverpackung" in desc:
                parts.append("OVP/Rechnung vorhanden")
            if "neuwertig" in desc or "top zustand" in desc or "wie neu" in desc:
                parts.append("Zustand neuwertig")

        # Risk flags
        risk_flags = pick.get("risk_flags", [])
        if risk_flags:
            parts.append(f"⚠ Risiko: {', '.join(risk_flags)}")

        # TGTBT flags — informational warning
        tgtbt = pick.get("tgtbt_flags", [])
        if tgtbt:
            parts.append("⚠ TGTBT-Warnung: Angebot prüfen!")

        return (
            ", ".join(parts[:5]).capitalize()
            if parts
            else "Gutes Preis-Leistungs-Verhältnis"
        )

    for i, pick in enumerate(picks[:3], 1):
        suggested = suggest_price(pick)
        reason = pick_reason(pick, i)
        price = pick.get("price", 0)
        age_days = pick.get("age_days", 5)

        # Suggest-Text: Kontextabhängig
        if suggested >= price:
            hint = "bereits am Preisfloor, sofort zuschlagen"
        elif price - suggested < 20:
            hint = "minimaler Spielraum"
        elif age_days and age_days <= 2:
            hint = "frisch eingestellt, max 5-8% verhandeln"
        elif age_days and age_days <= 7:
            hint = "8-12% Verhandlungsspielraum"
        elif age_days and age_days <= 14:
            hint = "12-18% Verhandlungsspielraum"
        else:
            hint = "15-25% Verhandlungsspielraum"

        analysis[f"pick{i}_reason"] = reason
        analysis[f"pick{i}_suggest"] = f"{suggested}€ — {hint}"

    # --- Nearby ---
    if nearby and nearby.get("price"):
        nb_price = nearby["price"]
        nb_suggested = round(nb_price * 0.90)  # Abholung: 10% extra
        iqr_min = stats.get("min", 0)
        if iqr_min and nb_suggested < iqr_min:
            nb_suggested = iqr_min

        nb_dist = nearby.get("distance_km") or nearby.get("radius_km", "?")
        analysis["nearby_reason"] = (
            f"Abholung in {nearby.get('location', '?')} ({nb_dist} km), "
            f"kein Versandrisiko, sofort testen"
        )
        analysis["nearby_suggest"] = (
            f"{nb_suggested}€ — bei Abholung 10% Verhandlungsspielraum"
        )

    # --- Fazit ---
    if nearby and nearby.get("price") and picks:
        best_price = picks[0].get("price", 0)
        nb_price = nearby["price"]
        if nb_price <= best_price * 1.05:
            analysis["fazit"] = (
                "Nearby-Angebot preislich konkurrenzfähig — Abholung empfohlen "
                "(kein Versandrisiko, sofort prüfbar)."
            )
        else:
            diff = int(nb_price - best_price)
            analysis["fazit"] = (
                f"Versand-Angebote {diff}€ günstiger. "
                f"Nearby nur bei Bedarf an sofortiger Verfügbarkeit."
            )
    elif picks:
        analysis["fazit"] = (
            f"Empfehlung: Pick #1 kontaktieren, "
            f"mit {suggest_price(picks[0])}€ einsteigen."
        )
    else:
        analysis["fazit"] = "Wenige Angebote verfügbar — Geduld empfohlen."

    # --- TGTBT Summary ---
    tgtbt_labels = [f"#{i}" for i, p in enumerate(picks[:3], 1) if p.get("tgtbt_flags")]
    if nearby and nearby.get("tgtbt_flags"):
        tgtbt_labels.append("Nearby")
    if tgtbt_labels:
        analysis["tgtbt_warning"] = (
            f"⚠ Too-Good-To-Be-True bei {', '.join(tgtbt_labels)}: "
            f"Preis deutlich unter Median oder Dringlichkeits-Keywords. "
            f"Vor Kauf Verkäufer-Profil und Bezahlmethode genau prüfen!"
        )

    # --- Post-IQR TGTBT Warnings (hacked accounts) ---
    iqr_warnings = result.get("tgtbt_warnings", [])
    if iqr_warnings:
        warn_lines = [
            f"  • {w['title'][:50]} ({int(w['price'])}€, -{w['pct_under_median']}%)"
            for w in iqr_warnings[:3]
        ]
        analysis["hacked_account_warning"] = (
            f"⚠ {len(iqr_warnings)} Inserate mit Top-Bewertungen aber IQR-Ausreißer-Preis "
            f"(mögliche gehackte Accounts):\n" + "\n".join(warn_lines)
        )

    return analysis


def generate_html(result, output_path):
    """Fill the HTML template with search results."""
    from html import escape as html_escape  # noqa: F811

    template_path = Path(__file__).parent / "market-report-template.html"
    template = template_path.read_text(encoding="utf-8")

    stats = result.get("stats", {})
    neupreis = result.get("neupreis")
    now = datetime.now()

    # Simple replacements
    replacements = {
        "{{PRODUCT_NAME}}": result.get("product", "?"),
        "{{DATE}}": now.strftime("%d.%m.%Y"),
        "{{TIMESTAMP}}": now.strftime("%d.%m.%Y %H:%M"),
        "{{CATEGORY}}": result.get("selected_category", ""),
        "{{DURATION}}": str(result.get("duration_seconds", "?")),
        "{{MEDIAN}}": str(stats.get("median", "—")),
        "{{TOTAL_IN_MEDIAN}}": str(result.get("total_in_median", 0)),
        "{{RANGE_MIN}}": str(stats.get("min", "—")),
        "{{RANGE_MAX}}": str(stats.get("max", "—")),
        "{{Q1}}": str(stats.get("q1", "—")),
        "{{Q3}}": str(stats.get("q3", "—")),
        "{{NEUPREIS}}": str(int(neupreis)) if neupreis else "—",
        "{{NEUPREIS_SOURCE}}": result.get("neupreis_source", "—"),
        "{{TOTAL_RAW}}": str(result.get("total_raw", 0)),
        "{{TOTAL_CLEAN}}": str(result.get("total_clean", 0)),
        "{{TOTAL_SCAM}}": str(result.get("total_scam", 0)),
    }

    # Ersparnis (kann negativ sein wenn Gebraucht > Neupreis, z.B. RTX 5090)
    if neupreis and stats.get("median"):
        diff = int(neupreis - stats["median"])
        pct = round(abs(diff) / neupreis * 100)
        if diff > 0:
            replacements["{{ERSPARNIS_NOTE}}"] = f"Ersparnis {diff}€ ({pct}%)"
        else:
            replacements["{{ERSPARNIS_NOTE}}"] = (
                f"Aufschlag +{abs(diff)}€ (+{pct}%) über Neupreis"
            )
    else:
        replacements["{{ERSPARNIS_NOTE}}"] = "—"

    # Hero Recommendations (Top Best + Top Nearby)
    hero_html = ""
    pick1 = result.get("smart_picks", [None])[0] if result.get("smart_picks") else None
    nearby = result.get("nearby_pick")

    if pick1 or nearby:
        hero_html = '<div class="hero-recs fade-up">\n'

        if pick1 and pick1.get("price"):
            p1_url = pick1.get("url", "")
            if p1_url and not p1_url.startswith("http"):
                p1_url = f"https://www.kleinanzeigen.de{p1_url}"
            p1_badges = ""
            for b in (pick1.get("seller_badges") or "").split(", "):
                if b.strip():
                    p1_badges += f'<span class="hero-rec__badge">{b.strip()}</span>'
            p1_since = pick1.get("seller_since", "")
            p1_meta_parts = []
            if pick1.get("shipping"):
                p1_meta_parts.append("Versand")
            else:
                p1_meta_parts.append("Nur Abholung")
            if pick1.get("age_days") is not None:
                p1_meta_parts.append(f"{pick1['age_days']}d online")
            if p1_since:
                p1_meta_parts.append(f"Verkäufer seit {p1_since}")
            p1_meta = " · ".join(p1_meta_parts)
            hero_html += f"""    <div class="hero-rec hero-rec--best" <!--AGENT_HIDE_RECO-->>
        <div class="hero-rec__label">Top-Empfehlung</div>
        <div class="hero-rec__price">{int(pick1["price"])}€</div>
        <div class="hero-rec__title">{html_escape(pick1.get("title", ""))}</div>
        <div class="hero-rec__meta">{p1_meta}</div>
        <div class="hero-rec__badges">{p1_badges}</div>
        <a class="hero-rec__link" href="{p1_url}" target="_blank">Anzeige öffnen →</a>
    </div>\n"""

        if nearby and nearby.get("price"):
            nb_url = nearby.get("url", "")
            if nb_url and not nb_url.startswith("http"):
                nb_url = f"https://www.kleinanzeigen.de{nb_url}"
            nb_loc = nearby.get("location", "Unbekannt")
            nb_dist = (
                f"{nearby['distance_km']} km"
                if nearby.get("distance_km")
                else f"≤{nearby.get('radius_km', '?')} km"
            )
            nb_meta = f"{nb_loc} · {nb_dist}"
            if nearby.get("age_days") is not None:
                nb_meta += f" · {nearby['age_days']}d online"
            hero_html += f"""    <div class="hero-rec hero-rec--nearby" <!--AGENT_HIDE_NEARBY_HERO-->>
        <div class="hero-rec__label">Top Lokal</div>
        <div class="hero-rec__price">{int(nearby["price"])}€</div>
        <div class="hero-rec__title">{html_escape(nearby.get("title", ""))}</div>
        <div class="hero-rec__meta">{nb_meta}</div>
        <a class="hero-rec__link" href="{nb_url}" target="_blank">Anzeige öffnen →</a>
    </div>\n"""

        hero_html += "</div>"

    replacements["{{HERO_RECS_HTML}}"] = hero_html

    # Smart Picks (dynamisch 1-3 Cards mit Beschreibung + Seller-Info)
    picks = result.get("smart_picks", [])
    picks_html = ""
    for i, p in enumerate(picks):
        idx = i + 1
        full_url = p.get("url", "")
        if full_url and not full_url.startswith("http"):
            full_url = f"https://www.kleinanzeigen.de{full_url}"
        price_str = f"{int(p['price'])}€" if p.get("price") else "—"
        ship_str = "Versand" if p.get("shipping") else "Nur Abholung"
        age_str = f"{p.get('age_days', '?')}d online"

        # Description block (from detail page)
        desc = p.get("description", "")
        desc_html = ""
        if desc:
            # Escape HTML, truncate
            desc_safe = html_escape(desc[:300])
            desc_html = f'<div class="smart-pick__desc">{desc_safe}</div>'

        # Score badge — color-coded by value
        score_val = p.get("score", 0)
        if score_val >= 70:
            score_color = "var(--green)"
            score_bg = "rgba(109,184,122,0.12)"
        elif score_val >= 40:
            score_color = "var(--accent)"
            score_bg = "var(--accent-dim)"
        else:
            score_color = "var(--red)"
            score_bg = "rgba(212,103,90,0.12)"

        # Score breakdown text
        breakdown = p.get("score_breakdown", {})
        breakdown_parts = []
        for key, label in [
            ("price", "Preis"),
            ("trust", "Trust"),
            ("negotiation", "Verh."),
            ("comfort", "Komf."),
            ("freshness", "Frische"),
        ]:
            val = breakdown.get(key, 0)
            if val != 0:
                breakdown_parts.append(
                    f"{label} {val:+d}" if val < 0 else f"{label} {val}"
                )
        breakdown_str = " · ".join(breakdown_parts)
        breakdown_html = (
            f'<div class="smart-pick__score-breakdown">{breakdown_str}</div>'
            if breakdown_str
            else ""
        )

        # Seller badges + since + account age + listing count
        seller_html = ""
        badges_str = p.get("seller_badges", "")
        since_str = p.get("seller_since", "")
        account_age = p.get("account_age_days")
        listing_count = p.get("seller_listing_count")
        if badges_str or since_str or account_age is not None:
            seller_parts = ""
            if badges_str:
                for b in badges_str.split(", "):
                    if b.strip():
                        seller_parts += (
                            f'<span class="smart-pick__seller-badge">{b.strip()}</span>'
                        )
            # Account age + listing count as combined info line
            age_parts = []
            if since_str:
                age_parts.append(f"Aktiv seit {since_str}")
            if account_age is not None:
                years = account_age / 365
                if years >= 1:
                    age_parts.append(
                        f"{years:.0f} {'Jahr' if years < 1.5 else 'Jahre'}"
                    )
                else:
                    months = account_age / 30
                    age_parts.append(
                        f"{months:.0f} {'Monat' if months < 1.5 else 'Monate'}"
                    )
            if listing_count:
                age_parts.append(f"{listing_count} Anzeigen")
            if age_parts:
                seller_parts += f'<span class="smart-pick__seller-since">{" · ".join(age_parts)}</span>'
            seller_html = f'<div class="smart-pick__seller">{seller_parts}</div>'

        # Risk flags + TGTBT badges
        flags_html = ""
        risk_flags = p.get("risk_flags", [])
        tgtbt_flags = p.get("tgtbt_flags", [])
        if risk_flags or tgtbt_flags:
            flag_badges = ""
            for rf in risk_flags:
                flag_badges += (
                    f'<span class="smart-pick__flag smart-pick__flag--risk">'
                    f"⚠ {html_escape(rf)}</span>"
                )
            for tf in tgtbt_flags:
                flag_badges += (
                    f'<span class="smart-pick__flag smart-pick__flag--tgtbt">'
                    f"⚠ {html_escape(tf)}</span>"
                )
            flags_html = f'<div class="smart-pick__flags">{flag_badges}</div>'

        # Specs badges
        specs_html = ""
        specs = p.get("specs")
        if specs:
            spec_badges = ""
            spec_labels = {
                "cpu": "CPU",
                "ram_gb": "RAM",
                "storage_gb": "Storage",
                "gpu": "GPU",
                "display": "Display",
            }
            for sk, sv in specs.items():
                label = spec_labels.get(sk, sk)
                unit = "GB" if sk in ("ram_gb", "storage_gb") else ""
                spec_badges += (
                    f'<span class="smart-pick__spec">{label}: {sv}{unit}</span>'
                )
            specs_html = f'<div class="smart-pick__specs">{spec_badges}</div>'

        picks_html += f"""<div class="smart-pick" <!--AGENT_HIDE_{idx}-->>
        <div class="smart-pick__rank">{idx}</div>
        <div class="smart-pick__body">
            <div class="smart-pick__title">{p.get("title", "—")}</div>
            <div class="smart-pick__meta">
                <span class="smart-pick__price">{price_str}</span>
                <span class="smart-pick__score" style="color:{score_color};background:{score_bg}">Score {score_val}</span>
                <span class="smart-pick__ship">{ship_str} · {age_str}</span>
            </div>
            {breakdown_html}
            {specs_html}
            {flags_html}
            {desc_html}
            <!--AGENT_NOTE_{idx}-->
            {seller_html}
            <div class="smart-pick__reason">{{{{PICK{idx}_REASON}}}}</div>
            <div class="smart-pick__action">
                <span class="smart-pick__suggest-label">Vorschlag:</span>
                <span class="smart-pick__suggest-price">{{{{PICK{idx}_SUGGEST}}}}</span>
            </div>
            <a class="smart-pick__link" href="{full_url}" target="_blank">Anzeige öffnen →</a>
        </div>
    </div>\n"""
    replacements["{{SMART_PICKS_HTML}}"] = picks_html

    # Nearby Pick (mit Beschreibung)
    nearby = result.get("nearby_pick")
    if nearby and nearby.get("price"):
        nb_url = nearby.get("url", "")
        if nb_url and not nb_url.startswith("http"):
            nb_url = f"https://www.kleinanzeigen.de{nb_url}"
        nb_price = f"{int(nearby['price'])}€"
        nb_loc = nearby.get("location", "Unbekannt")
        nb_dist = (
            f"{nearby['distance_km']} km"
            if nearby.get("distance_km")
            else f"≤{nearby.get('radius_km', '?')} km"
        )

        # Description block
        nb_desc = nearby.get("description", "")
        nb_desc_html = ""
        if nb_desc:
            nb_desc_safe = html_escape(nb_desc[:300])
            nb_desc_html = f'<div class="smart-pick__desc">{nb_desc_safe}</div>'

        nearby_html = f"""<div class="smart-pick smart-pick--nearby" <!--AGENT_HIDE_NEARBY-->>
        <div class="smart-pick__rank" style="border-color:var(--green);color:var(--green)">&#8962;</div>
        <div class="smart-pick__body">
            <div class="smart-pick__title">{nearby.get("title", "—")}</div>
            <div class="smart-pick__meta">
                <span class="smart-pick__price">{nb_price}</span>
                <span class="smart-pick__score">Score {nearby.get("score", 0)}</span>
                <span class="smart-pick__ship">{nb_loc} · {nb_dist}</span>
            </div>
            {nb_desc_html}
            <!--AGENT_NOTE_NEARBY-->
            <div class="smart-pick__reason">{{{{NEARBY_REASON}}}}</div>
            <div class="smart-pick__action">
                <span class="smart-pick__suggest-label">Vorschlag:</span>
                <span class="smart-pick__suggest-price">{{{{NEARBY_SUGGEST}}}}</span>
            </div>
            <a class="smart-pick__link" href="{nb_url}" target="_blank">Anzeige öffnen →</a>
        </div>
    </div>"""
    else:
        nearby_html = ""
    replacements["{{NEARBY_PICK_HTML}}"] = nearby_html

    # Age distribution bars
    age_labels = {
        "fresh": ("Frisch (0-2d)", "kaum Spielraum"),
        "normal": ("Normal (3-7d)", "leicht verhandelbar"),
        "negotiable": ("Verhandelbar (8-14d)", "gut verhandelbar"),
        "stale": ("Länger online (15-30d)", "stark verhandelbar"),
    }
    age_dist = result.get("age_distribution", {})
    max_count = max((v.get("count", 0) for v in age_dist.values()), default=1) or 1
    bars_html = ""
    for key, (label, hint) in age_labels.items():
        v = age_dist.get(key, {})
        count = v.get("count", 0)
        med_price = v.get("median")
        pct = round(count / max_count * 100) if count else 0
        value_str = f"{count}× · {med_price}€" if med_price else f"{count}×"
        bars_html += f"""<div class="bar-row">
            <div class="bar-label">{label}</div>
            <div class="bar-track"><div class="bar-fill" style="width:{pct}%"></div></div>
            <div class="bar-value">{value_str}</div>
        </div>\n"""
    replacements["{{AGE_BARS}}"] = bars_html

    # Listing rows (top 10 cheapest included)
    included = sorted(
        [
            listing
            for listing in result.get("listings", [])
            if listing.get("included_in_median") and listing.get("price")
        ],
        key=lambda x: x["price"],
    )[:10]
    rows_html = ""
    for listing in included:
        url = listing.get("url", "")
        full_url = (
            f"https://www.kleinanzeigen.de{url}"
            if url and not url.startswith("http")
            else url
        )
        title = listing.get("title", "")[:60]
        age = listing.get("age_category", "")
        price = int(listing["price"])
        rows_html += f"""<tr>
            <td class="price-col">{price}€</td>
            <td><a href="{full_url}" target="_blank">{title}</a></td>
            <td>{age}</td>
        </tr>\n"""
    replacements["{{LISTING_ROWS}}"] = rows_html

    # History section (load from DB if available)
    history_html = ""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        import importlib

        market_db = importlib.import_module("market-db")
        market_db.init_db()
        db = market_db.get_db()
        history = market_db.get_history(db, result.get("product", ""))
        db.close()

        if len(history) > 1:
            history_html = '<div class="section fade-up">\n'
            history_html += '    <div class="section-title">Preisverlauf</div>\n'
            for h in history[:10]:
                dt = h["searched_at"][:10]
                med = int(h["median_price"]) if h["median_price"] else "?"
                n = h.get("total_in_median", "?")
                history_html += f"""    <div class="history-row">
        <div class="history-date">{dt}</div>
        <div class="history-price">{med}€</div>
        <div class="history-detail">n={n}</div>
    </div>\n"""

            # Trend
            if len(history) >= 2:
                first = history[-1]["median_price"]
                last = history[0]["median_price"]
                if first and last:
                    diff = last - first
                    if diff < 0:
                        trend_class = "trend-down"
                        arrow = "↓"
                    elif diff > 0:
                        trend_class = "trend-up"
                        arrow = "↑"
                    else:
                        trend_class = "trend-stable"
                        arrow = "→"
                    history_html += (
                        '    <div class="history-row"><div class="history-date"></div>'
                    )
                    history_html += f'<div class="history-price {trend_class}">{arrow} {abs(int(diff))}€</div>'
                    history_html += (
                        '<div class="history-detail">seit erster Messung</div></div>\n'
                    )

            history_html += "</div>"
    except Exception:
        pass

    replacements["{{HISTORY_SECTION}}"] = history_html

    # Apply all replacements
    html = template
    for key, value in replacements.items():
        html = html.replace(key, str(value) if value is not None else "—")

    # Use pre-generated agent analysis to fill placeholders
    analysis = result.get("agent_analysis") or generate_agent_analysis(result)
    agent_replacements = {
        "{{AGENT_MARKET}}": analysis.get("market", ""),
        "{{AGENT_FAZIT}}": analysis.get("fazit", ""),
    }
    for i in range(1, 4):
        agent_replacements[f"{{{{PICK{i}_REASON}}}}"] = analysis.get(
            f"pick{i}_reason", ""
        )
        agent_replacements[f"{{{{PICK{i}_SUGGEST}}}}"] = analysis.get(
            f"pick{i}_suggest", ""
        )
    agent_replacements["{{NEARBY_REASON}}"] = analysis.get("nearby_reason", "")
    agent_replacements["{{NEARBY_SUGGEST}}"] = analysis.get("nearby_suggest", "")

    # TGTBT warning banner
    tgtbt_warn = analysis.get("tgtbt_warning", "")
    if tgtbt_warn:
        agent_replacements["{{TGTBT_WARNING_HTML}}"] = (
            '<div class="agent-insight" style="background:rgba(255,152,0,0.12);'
            "border-left:4px solid #ff9800;padding:12px 16px;margin:12px 0;"
            'border-radius:8px">'
            '<div class="agent-insight__label" style="color:#ff9800">'
            "⚠ Vorsicht</div>"
            f'<div class="agent-insight__text">{tgtbt_warn}</div></div>'
        )
    else:
        agent_replacements["{{TGTBT_WARNING_HTML}}"] = ""

    # Hacked account warning banner
    hacked_warn = analysis.get("hacked_account_warning", "")
    if hacked_warn:
        hacked_lines = hacked_warn.replace("\n", "<br>")
        agent_replacements["{{HACKED_ACCOUNT_WARNING_HTML}}"] = (
            '<div class="agent-insight" style="background:rgba(212,103,90,0.12);'
            "border-left:4px solid var(--red);padding:12px 16px;margin:12px 0;"
            'border-radius:8px">'
            '<div class="agent-insight__label" style="color:var(--red)">'
            "⚠ Gehackte Accounts?</div>"
            f'<div class="agent-insight__text">{hacked_lines}</div></div>'
        )
    else:
        agent_replacements["{{HACKED_ACCOUNT_WARNING_HTML}}"] = ""

    for key, value in agent_replacements.items():
        html = html.replace(key, str(value))

    # Sweep: remove any remaining unfilled placeholders
    html = re.sub(r"\{\{[A-Z0-9_]+\}\}", "", html)

    # Store analysis in result for JSON output
    result["agent_analysis"] = analysis

    Path(output_path).write_text(html, encoding="utf-8")

    # Update report index
    update_report_index(Path(output_path).parent)

    return output_path


def update_report_index(reports_dir):
    """Generate an index.html listing all market reports, newest first."""
    import re as _re

    reports_dir = Path(reports_dir)
    market_files = list(reports_dir.glob("market-*.html"))

    if not market_files:
        return

    # Parse metadata from each report
    entries = []
    for f in market_files:
        try:
            content = f.read_text(encoding="utf-8")

            # Extract embedded creation timestamp (from footer: "28.02.2026 23:35")
            ts_match = _re.search(
                r"Jarvis Market-Scraper · (\d{2}\.\d{2}\.\d{4} \d{2}:\d{2})", content
            )
            if ts_match:
                created = datetime.strptime(ts_match.group(1), "%d.%m.%Y %H:%M")
            else:
                created = datetime.fromtimestamp(f.stat().st_mtime)

            m = _re.search(r"<title>Marktwert-Analyse:\s*(.+?)</title>", content)
            product = (
                m.group(1)
                if m
                else f.stem.replace("market-", "").replace("-", " ").title()
            )

            m2 = _re.search(
                r'class="stat-value">(\d+)€</div>\s*<div class="stat-label">Median',
                content,
            )
            median = f"{m2.group(1)}€" if m2 else "—"
        except Exception:
            created = datetime.fromtimestamp(f.stat().st_mtime)
            product = f.stem.replace("market-", "").replace("-", " ").title()
            median = "—"

        entries.append(
            {"file": f, "created": created, "product": product, "median": median}
        )

    # Sort by embedded creation timestamp, newest first
    entries.sort(key=lambda e: e["created"], reverse=True)

    rows = ""
    for e in entries:
        date_str = e["created"].strftime("%d.%m.%Y %H:%M")
        rows += f"""        <tr>
            <td>{date_str}</td>
            <td><a href="{e["file"].name}">{e["product"]}</a></td>
            <td class="price-col">{e["median"]}</td>
        </tr>\n"""

    index_html = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Marktberichte</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,300..700;1,6..72,300..700&family=Outfit:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
:root {{
    --bg: #111110; --bg-card: #1f1e1c; --text: #e8e4de;
    --text-secondary: #b5afa5; --text-muted: #706b62;
    --accent: #cf865a; --accent-hover: #e09468;
    --accent-glow: rgba(207,134,90,0.08);
    --border: #2a2826; --border-light: #222120;
    --font-display: "Newsreader", Georgia, serif;
    --font-body: "Outfit", system-ui, sans-serif;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: var(--font-body); background: var(--bg);
    color: var(--text); line-height: 1.6;
    padding: 2rem; max-width: 720px; margin: 0 auto;
}}
body::before {{
    content: ""; position: fixed; top: -20%; left: 50%;
    transform: translateX(-50%); width: 800px; height: 600px;
    background: radial-gradient(ellipse, var(--accent-glow) 0%, transparent 70%);
    pointer-events: none; z-index: 0;
}}
h1 {{
    font-family: var(--font-display); font-weight: 400;
    font-size: 2rem; letter-spacing: -0.03em; margin-bottom: 0.3rem;
}}
.subtitle {{
    font-size: 0.8rem; color: var(--text-muted);
    margin-bottom: 2rem; font-weight: 300;
}}
table {{
    width: 100%; border-collapse: collapse; font-size: 0.85rem;
}}
th {{
    text-align: left; font-size: 0.65rem; text-transform: uppercase;
    letter-spacing: 0.07em; color: var(--text-muted); font-weight: 500;
    padding: 0.5rem 0.3rem; border-bottom: 1px solid var(--border);
}}
td {{
    padding: 0.6rem 0.3rem; border-bottom: 1px solid var(--border-light);
    color: var(--text-secondary); font-weight: 300;
}}
tr:hover td {{ background: rgba(255,255,255,0.04); }}
.price-col {{
    font-family: var(--font-display); font-size: 0.95rem;
    color: var(--text); text-align: right; white-space: nowrap;
}}
a {{ color: var(--text-secondary); text-decoration: none; transition: color 0.15s; }}
a:hover {{ color: var(--accent); }}
.footer {{
    margin-top: 3rem; padding-top: 1rem;
    border-top: 1px solid var(--border-light);
    font-size: 0.65rem; color: var(--text-muted); font-weight: 300;
}}
</style>
</head>
<body>
<h1>Marktberichte</h1>
<div class="subtitle">{len(entries)} Analysen · neueste zuerst</div>
<table>
    <thead>
        <tr><th>Datum</th><th>Produkt</th><th>Median</th></tr>
    </thead>
    <tbody>
{rows}    </tbody>
</table>
<div class="footer">Jarvis Market-Scraper · Auto-Index</div>
</body>
</html>"""

    (reports_dir / "index.html").write_text(index_html, encoding="utf-8")


def save_to_db(result, product_name, category=None):
    """Save search results to market.db via market-db.py functions."""
    sys.path.insert(0, str(Path(__file__).parent))
    import importlib

    market_db = importlib.import_module("market-db")
    market_db.init_db()
    db = market_db.get_db()

    product_id = market_db.upsert_product(
        db, product_name, category, result.get("filter_url")
    )

    stats = result.get("stats", {})
    stats_dict = {
        "total_raw": result.get("total_raw"),
        "total_clean": result.get("total_clean"),
        "total_scam": result.get("total_scam", 0),
        "total_final": result.get("total_final"),
        "total_in_median": result.get("total_in_median"),
        "median": stats.get("median"),
        "q1": stats.get("q1"),
        "q3": stats.get("q3"),
        "min": stats.get("min"),
        "max": stats.get("max"),
        "source_url": result.get("filter_url"),
        "duration_seconds": result.get("duration_seconds"),
        "new_bestprice": result.get("neupreis"),
        "new_bestprice_source": result.get("neupreis_source"),
        "report_filename": result.get("report_filename"),
    }
    search_id = market_db.save_search(db, product_id, stats_dict)

    listings_data = []
    for listing in result.get("listings", []):
        listings_data.append(
            {
                "title": listing.get("title"),
                "price": listing.get("price"),
                "price_text": listing.get("priceText"),
                "date_posted": listing.get("date"),
                "age_category": listing.get("age_category"),
                "url": listing.get("url"),
                "location": listing.get("location"),
                "shipping": listing.get("shipping", False),
                "seller_type": listing.get("seller_type"),
                "seller_since": listing.get("seller_since"),
                "is_scam": listing.get("is_scam", 0),
                "filtered_reason": listing.get("filtered_reason"),
                "included_in_median": listing.get("included_in_median", 1),
                "seller_badges": listing.get("seller_badges"),
                "is_recommended": listing.get("is_recommended", 0),
            }
        )
    if listings_data:
        market_db.save_listings(db, search_id, listings_data)

    db.close()
    return search_id, product_id


def main():
    parser = argparse.ArgumentParser(description="Kleinanzeigen Marktpreis-Scraper")
    parser.add_argument("search_term", help="Suchbegriff")
    parser.add_argument(
        "--product-name", default=None, help="Produktname für DB (default: search_term)"
    )
    parser.add_argument(
        "--category", type=int, default=0, help="Kategorie-Index (0=größte)"
    )
    parser.add_argument("--category-name", default=None, help="Kategorie-Label für DB")
    parser.add_argument("--price-min", type=int, default=None, help="Mindestpreis")
    parser.add_argument("--price-max", type=int, default=None, help="Höchstpreis")
    parser.add_argument(
        "--exclude",
        nargs="*",
        default=[],
        help="Keywords zum Ausschließen",
    )
    parser.add_argument("--max-checks", type=int, default=6, help="Max Seller-Checks")
    parser.add_argument(
        "--neupreis", type=float, default=None, help="Neupreis für Vergleich"
    )
    parser.add_argument("--neupreis-source", default=None, help="Quelle des Neupreises")
    parser.add_argument(
        "--auto-geizhals",
        action="store_true",
        help="Neupreis automatisch via fast-search.py --geizhals ermitteln",
    )
    parser.add_argument(
        "--auto-exclude",
        action="store_true",
        help="Produkttyp-spezifische Exclude-Keywords automatisch setzen",
    )
    parser.add_argument("--save", action="store_true", help="In market.db speichern")
    parser.add_argument("--html", default=None, help="HTML-Report ausgeben (Pfad)")
    parser.add_argument(
        "--emit-events", default=None, help="Events-JSON für Observability ausgeben"
    )

    args = parser.parse_args()

    # --- Auto-Geizhals: Neupreis per Subprocess ermitteln ---
    neupreis = args.neupreis
    neupreis_source = args.neupreis_source
    if args.auto_geizhals and neupreis is None:
        product_query = args.product_name or args.search_term
        # Spec-Terms strippen die auf Geizhals Komponenten matchen statt Produkte
        # "ThinkPad T480 16GB" → "ThinkPad T480", "i7-6700 32GB 1TB SSD" → "i7-6700"
        geizhals_query = re.sub(
            r"\b\d+\s*(?:GB|TB|MB)\b", "", product_query, flags=re.IGNORECASE
        ).strip()
        geizhals_query = re.sub(
            r"\b(?:SSD|HDD|NVMe|DDR\d?|RAM)\b", "", geizhals_query, flags=re.IGNORECASE
        ).strip()
        geizhals_query = re.sub(r"\s+", " ", geizhals_query).strip()
        if not geizhals_query:
            geizhals_query = product_query  # Fallback
        print(f"[auto-geizhals] Suche: {geizhals_query}", file=sys.stderr)
        try:
            import subprocess

            proc = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).parent / "fast-search.py"),
                    "--geizhals",
                    geizhals_query,
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                gh_data = json.loads(proc.stdout)
                if gh_data and gh_data[0].get("bestprice"):
                    neupreis = float(gh_data[0]["bestprice"])
                    neupreis_source = "Geizhals"
                    print(
                        f"[auto-geizhals] Bestpreis: {neupreis:.0f}€ — "
                        f"{gh_data[0].get('product', '')[:60]}",
                        file=sys.stderr,
                    )
                else:
                    print("[auto-geizhals] Kein Bestpreis gefunden", file=sys.stderr)
        except Exception as e:
            print(f"[auto-geizhals] Fehler: {e}", file=sys.stderr)

    # --- Auto-Preisrange: Mindestens 10€ um Spam zu filtern ---
    price_min = args.price_min
    price_max = args.price_max
    if price_min is None and (args.auto_geizhals or neupreis is not None):
        price_min = 10

    # --- Auto-Exclude: Produkttyp-spezifische Keywords ---
    exclude_keywords = args.exclude if args.exclude else []
    if args.auto_exclude:
        name_lower = (args.product_name or args.search_term).lower()
        auto_kw = []
        if any(k in name_lower for k in ("rtx", "gtx", "radeon", "geforce", "rx ")):
            auto_kw = [
                "PC",
                "Laptop",
                "Notebook",
                "Komplett",
                "System",
                "Mining",
                "Rig",
            ]
        elif any(k in name_lower for k in ("iphone", "samsung galaxy", "pixel")):
            auto_kw = [
                "Hülle",
                "Case",
                "Folio",
                "Panzerglas",
                "Schutzglas",
                "Schutzfolie",
                "Displayschutz",
                "Cover",
                "Bumper",
                "Halterung",
                "Kabel",
                "Ladegerät",
                "Ladekabel",
                "Adapter",
                "Mikrofon",
                "Stativ",
                "Armband",
                "Handykette",
                "Ring",
                "Ständer",
                "Powerbank",
                "MagSafe",
                "Wallet",
                "Tasche",
                "Selfie",
            ]
        elif any(k in name_lower for k in ("ipad", "tab ")):
            auto_kw = [
                "Hülle",
                "Tastatur",
                "Keyboard",
                "Pencil",
                "Folio",
                "Case",
                "Cover",
                "Ständer",
                "Halterung",
                "Schutzglas",
                "Schutzfolie",
                "Displayschutz",
                "Tasche",
                "Sleeve",
                "Stift",
            ]
        elif any(
            k in name_lower for k in ("switch", "playstation", "xbox", "ps5", "ps4")
        ):
            auto_kw = [
                "Controller",
                "Spiel",
                "Spiele",
                "Game",
                "Games",
                "Headset",
                "Ladestation",
                "Skin",
                "Ständer",
                "Kamera",
                "VR",
                "Kabel",
                "HDMI",
                "Tasche",
                "Schutzfolie",
            ]
        elif any(k in name_lower for k in ("wh-", "airpods", "kopfhörer", "headphone")):
            auto_kw = [
                "Ohrpolster",
                "Polster",
                "Kabel",
                "Etui",
                "Case",
                "Hülle",
                "Bügel",
                "Ear Tips",
                "Adapter",
                "Ständer",
                "Halterung",
                "Tasche",
            ]
        elif any(
            k in name_lower
            for k in ("macbook", "thinkpad", "laptop", "notebook", "surface")
        ):
            auto_kw = [
                "Hülle",
                "Tasche",
                "Sleeve",
                "Tastatur",
                "Skin",
                "Adapter",
                "Hub",
                "Dock",
                "Docking",
                "Ständer",
                "Displayschutz",
                "Schutzfolie",
                "Maus",
                "Rucksack",
                "Ladegerät",
                "Netzteil",
            ]
        if auto_kw:
            print(
                f"[auto-exclude] +{len(auto_kw)} Keywords: {', '.join(auto_kw)}",
                file=sys.stderr,
            )
            exclude_keywords = exclude_keywords + auto_kw

    result = run_search(
        args.search_term,
        category_index=args.category,
        price_min=price_min,
        price_max=price_max,
        exclude_keywords=exclude_keywords or None,
        max_seller_checks=args.max_checks,
        neupreis=neupreis,
        neupreis_source=neupreis_source,
    )

    html_path = None
    if args.html and result.get("stats", {}).get("median"):
        html_path = generate_html(result, args.html)
        print(f"HTML: {html_path}", file=sys.stderr)

    if args.save and result.get("stats", {}).get("median"):
        product = args.product_name or args.search_term
        cat_name = args.category_name or result.get("selected_category")
        if html_path:
            result["report_filename"] = Path(html_path).name
        search_id, product_id = save_to_db(result, product, cat_name)
        print(
            f"DB: search_id={search_id}, product={product}, "
            f"median={result['stats']['median']}€",
            file=sys.stderr,
        )

    # Events für Observability emittieren
    if args.emit_events:
        stats = result.get("stats", {})
        events = [
            {
                "source": "market",
                "event_type": "search",
                "domain": "kleinanzeigen.de",
                "status": "ok" if stats.get("median") else "error",
                "latency_ms": int(result.get("duration_seconds", 0) * 1000),
                "value_num": stats.get("median"),
                "value_text": args.search_term,
                "meta": json.dumps(
                    {
                        "raw": result.get("total_raw", 0),
                        "clean": result.get("total_clean", 0),
                        "scam": result.get("total_scam", 0),
                        "final": result.get("total_final", 0),
                        "category": result.get("selected_category", ""),
                    }
                ),
            }
        ]
        Path(args.emit_events).write_text(json.dumps(events, ensure_ascii=False))
        print(f"Events: {len(events)} → {args.emit_events}", file=sys.stderr)


if __name__ == "__main__":
    main()
