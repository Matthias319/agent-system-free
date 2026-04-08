#!/home/maetzger/.claude/tools/.venv/bin/python
"""academic-search.py — Akademische Paper-Suche + Section-Extraktion.

Discovery via arXiv API + OpenAlex API, Deep-Dive via PyMuPDF Section-Extraktion.

Usage:
    # Phase 1: Abstracts suchen
    academic-search.py search "query" [--limit 20] [--year 2025-2026]
        → JSON mit Abstracts, sortiert nach Relevanz × Citations

    # Phase 2: Paper-Sections extrahieren
    academic-search.py extract ARXIV_ID [--sections abstract,results,discussion]
    academic-search.py extract --doi DOI [--sections abstract,results,discussion]
    academic-search.py extract --url PDF_URL [--sections abstract,results,discussion]

    # Sections: abstract, introduction, methods, results, discussion, conclusion, all
    # Default: abstract,results,discussion (~1-3K Token pro Paper)
"""

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

# ── Konfiguration ──────────────────────────────────────────────

ARXIV_API = "https://export.arxiv.org/api/query"
OPENALEX_API = "https://api.openalex.org/works"

SECTION_ALIASES = {
    "abstract": ["ABSTRACT"],
    "introduction": [
        "INTRODUCTION",
        "1 INTRODUCTION",
        "1. INTRODUCTION",
        "I. INTRODUCTION",
    ],
    "related": ["RELATED WORK", "2 RELATED WORK", "BACKGROUND", "LITERATURE REVIEW"],
    "methods": [
        "METHOD",
        "METHODS",
        "METHODOLOGY",
        "APPROACH",
        "OUR APPROACH",
        "PROPOSED METHOD",
        "FRAMEWORK",
        "MODEL",
        "SYSTEM",
    ],
    "results": [
        "RESULTS",
        "EXPERIMENTS",
        "EXPERIMENTAL RESULTS",
        "EVALUATION",
        "EXPERIMENTAL SETUP",
        "FINDINGS",
    ],
    "discussion": ["DISCUSSION", "ANALYSIS", "DISCUSSION AND ANALYSIS"],
    "conclusion": [
        "CONCLUSION",
        "CONCLUSIONS",
        "CONCLUSION AND FUTURE WORK",
        "CONCLUDING REMARKS",
        "SUMMARY",
    ],
}

DEFAULT_SECTIONS = "abstract,results,discussion"

HTTP_HEADERS = {
    "User-Agent": "academic-search/1.0 (research tool; mailto:noreply@example.com)",
}


# ── arXiv API ──────────────────────────────────────────────────


def search_arxiv(query: str, limit: int = 20, year: str | None = None) -> list[dict]:
    """arXiv API durchsuchen. Gibt Papers mit Abstracts zurück."""
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": limit,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    t0 = time.monotonic()
    with httpx.Client(timeout=15, follow_redirects=True, headers=HTTP_HEADERS) as c:
        r = c.get(ARXIV_API, params=params)
        r.raise_for_status()
    latency = int((time.monotonic() - t0) * 1000)

    import xml.etree.ElementTree as ET

    root = ET.fromstring(r.text)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    entries = root.findall("a:entry", ns)

    papers = []
    for e in entries:
        arxiv_id_raw = e.find("a:id", ns).text.strip()
        arxiv_id = arxiv_id_raw.split("/abs/")[-1]

        published = e.find("a:published", ns).text[:10]
        pub_year = int(published[:4])

        # Year-Filter (einfach: "2025-2026" → range)
        if year:
            parts = year.split("-")
            y_from = int(parts[0])
            y_to = int(parts[1]) if len(parts) > 1 else y_from
            if pub_year < y_from or pub_year > y_to:
                continue

        title = e.find("a:title", ns).text.strip().replace("\n", " ")
        abstract = e.find("a:summary", ns).text.strip().replace("\n", " ")
        authors = [a.find("a:name", ns).text for a in e.findall("a:author", ns)]

        pdf_link = None
        for link in e.findall("a:link", ns):
            if link.get("title") == "pdf":
                pdf_link = link.get("href")

        categories = [c.get("term") for c in e.findall("a:category", ns)]

        papers.append(
            {
                "source": "arxiv",
                "arxiv_id": arxiv_id,
                "doi": None,
                "title": title,
                "abstract": abstract,
                "authors": authors[:5],
                "year": pub_year,
                "published": published,
                "citations": None,  # arXiv hat keine Citation-Counts
                "pdf_url": pdf_link,
                "categories": categories[:5],
            }
        )

    print(f"  arXiv: {len(papers)}/{len(entries)} Papers, {latency}ms", file=sys.stderr)
    return papers


def search_openalex(query: str, limit: int = 20, year: str | None = None) -> list[dict]:
    """OpenAlex API durchsuchen. 250M+ Werke, mit Citation-Counts."""
    filters = ["is_oa:true"]
    if year:
        parts = year.split("-")
        filters.append(f"from_publication_date:{parts[0]}-01-01")

    params = {
        "search": query,
        "filter": ",".join(filters),
        "sort": "relevance_score:desc",
        "per_page": limit,
        "select": "id,doi,title,publication_date,cited_by_count,open_access,"
        "authorships,abstract_inverted_index,primary_location",
    }
    t0 = time.monotonic()
    with httpx.Client(timeout=15, follow_redirects=True, headers=HTTP_HEADERS) as c:
        r = c.get(OPENALEX_API, params=params)
        r.raise_for_status()
    latency = int((time.monotonic() - t0) * 1000)
    data = r.json()

    papers = []
    for w in data.get("results", []):
        # Abstract aus Inverted Index rekonstruieren
        abs_idx = w.get("abstract_inverted_index") or {}
        if abs_idx:
            words = {}
            for word, positions in abs_idx.items():
                for pos in positions:
                    words[pos] = word
            abstract = " ".join(words[k] for k in sorted(words.keys()))
        else:
            abstract = ""

        doi = w.get("doi")
        # arXiv-ID aus Location extrahieren
        arxiv_id = None
        loc = w.get("primary_location") or {}
        landing = loc.get("landing_page_url") or ""
        if "arxiv.org" in landing:
            m = re.search(r"(\d{4}\.\d{4,5})", landing)
            if m:
                arxiv_id = m.group(1)

        oa = w.get("open_access") or {}
        pdf_url = oa.get("oa_url")

        authors = []
        for auth in (w.get("authorships") or [])[:5]:
            name = (auth.get("author") or {}).get("display_name")
            if name:
                authors.append(name)

        pub_date = w.get("publication_date", "")

        papers.append(
            {
                "source": "openalex",
                "arxiv_id": arxiv_id,
                "doi": doi,
                "title": w.get("title", ""),
                "abstract": abstract,
                "authors": authors,
                "year": int(pub_date[:4]) if pub_date else None,
                "published": pub_date,
                "citations": w.get("cited_by_count", 0),
                "pdf_url": pdf_url,
                "categories": [],
            }
        )

    total = data.get("meta", {}).get("count", "?")
    print(
        f"  OpenAlex: {len(papers)} Papers (von {total}), {latency}ms", file=sys.stderr
    )
    return papers


# ── Deduplizierung + Ranking ────────────────────────────────────


def _normalize_arxiv_id(p: dict) -> str | None:
    """arXiv-ID aus verschiedenen Quellen extrahieren."""
    if p.get("arxiv_id"):
        return p["arxiv_id"].split("v")[0]  # 2504.00914v1 → 2504.00914
    doi = p.get("doi") or ""
    # DOI-Pattern: 10.48550/arxiv.2602.15407
    m = re.search(r"10\.48550/arxiv\.(\d{4}\.\d{4,5})", doi, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


def _normalize_title(title: str) -> str:
    """Titel normalisieren für Dedup."""
    return re.sub(r"[^a-z0-9]", "", title.lower())[:80]


def _paper_key(p: dict) -> str:
    """Unique Key für Deduplizierung: arXiv-ID > Normalisierter Titel."""
    # arXiv-ID ist der beste Key (stabil über DOI-Varianten)
    arxiv = _normalize_arxiv_id(p)
    if arxiv:
        return f"arxiv:{arxiv}"
    # Titel-Hash als Fallback (normalisiert, keine Satzzeichen/Leerzeichen)
    title_norm = _normalize_title(p.get("title", ""))
    return f"title:{title_norm[:60]}"


def _relevance_score(paper: dict, query_words: set[str]) -> float:
    """Relevanz-Score mit Title-Boost, TF-gewichtetem Keyword-Overlap, Citations."""
    import math

    title = paper.get("title", "").lower()
    abstract = paper.get("abstract", "").lower()
    full_text = f"{title} {abstract}"

    # Title-Match: Keywords im Titel wiegen doppelt
    title_hits = sum(1 for w in query_words if w in title)
    abstract_hits = sum(1 for w in query_words if w in abstract)
    n_words = max(len(query_words), 1)
    keyword_score = (title_hits * 2 + abstract_hits) / (n_words * 3)  # normiert 0-1

    # Abstract-Dichte: Wie oft kommen Query-Words vor (nicht nur ob)
    total_mentions = sum(full_text.count(w) for w in query_words)
    density_score = min(1.0, total_mentions / (n_words * 3))

    # Citation-Boost (logarithmisch, mild)
    cites = paper.get("citations") or 0
    cite_score = math.log10(max(cites, 1) + 1) / 4

    # Aktualitäts-Boost
    year = paper.get("year") or 2020
    recency = max(0, (year - 2020)) / 6

    # Gesamtscore mit mehr Streuung
    return (
        keyword_score * 0.35 + density_score * 0.20 + cite_score * 0.25 + recency * 0.20
    )


def _merge_paper(existing: dict, new: dict) -> None:
    """Merge-Daten aus new in existing übernehmen."""
    if new.get("citations") and not existing.get("citations"):
        existing["citations"] = new["citations"]
    if new.get("pdf_url") and not existing.get("pdf_url"):
        existing["pdf_url"] = new["pdf_url"]
    if new.get("doi") and not existing.get("doi"):
        existing["doi"] = new["doi"]
    if new.get("arxiv_id") and not existing.get("arxiv_id"):
        existing["arxiv_id"] = new["arxiv_id"]
    if new["source"] not in existing["source"]:
        existing["source"] = f"{existing['source']}+{new['source']}"


def deduplicate_and_rank(papers: list[dict], query: str, limit: int = 20) -> list[dict]:
    """Papers deduplizieren, ranken, und top-N zurückgeben."""
    # Pass 1: Deduplizieren nach primary key (arXiv-ID oder Titel)
    seen = {}
    for p in papers:
        key = _paper_key(p)
        if key in seen:
            _merge_paper(seen[key], p)
        else:
            seen[key] = p

    # Pass 2: Titel-basierte Dedup für Cross-Source-Duplikate
    # (arXiv-ID-Key + Titel-Key können das gleiche Paper sein)
    title_index: dict[str, str] = {}  # norm_title → first key
    keys_to_remove = []
    for key, p in seen.items():
        norm_title = _normalize_title(p.get("title", ""))[:60]
        if norm_title in title_index:
            # Duplikat gefunden — in das existierende mergen
            primary_key = title_index[norm_title]
            _merge_paper(seen[primary_key], p)
            keys_to_remove.append(key)
        else:
            title_index[norm_title] = key
    for key in keys_to_remove:
        del seen[key]

    # Ranken
    query_words = {w.lower() for w in query.split() if len(w) > 2}
    ranked = sorted(
        seen.values(),
        key=lambda p: _relevance_score(p, query_words),
        reverse=True,
    )

    # Score hinzufügen
    for p in ranked:
        p["relevance"] = round(_relevance_score(p, query_words), 3)

    return ranked[:limit]


# ── Section-Extraktion ──────────────────────────────────────────


def _download_pdf(url: str) -> bytes:
    """PDF herunterladen."""
    with httpx.Client(timeout=30, follow_redirects=True, headers=HTTP_HEADERS) as c:
        r = c.get(url)
        r.raise_for_status()
    return r.content


def _is_likely_author_name(text: str) -> bool:
    """Erkennt Autorennamen / Affiliations die keine Section-Header sind."""
    # Typische Patterns: "Firstname Lastname", "University of ...", emails
    if re.search(r"@\w+\.", text):
        return True
    if re.search(r"university|institute|department|lab\b|school of", text, re.I):
        return True
    # Name-Pattern: 2-4 capitalized words ohne Zahlen
    words = text.split()
    if 1 <= len(words) <= 4 and all(w[0].isupper() and w.isalpha() for w in words):
        # Aber nicht echte Section-Headers
        section_keywords = {
            "Abstract",
            "Introduction",
            "Method",
            "Methods",
            "Results",
            "Discussion",
            "Conclusion",
            "Conclusions",
            "References",
            "Evaluation",
            "Experiments",
            "Related",
            "Background",
            "Approach",
            "Framework",
            "Overview",
            "Analysis",
            "Summary",
            "Appendix",
            "Acknowledgments",
            "Contributions",
        }
        if not any(w in section_keywords for w in words):
            return True
    return False


def _extract_sections(pdf_bytes: bytes) -> dict[str, str]:
    """PDF in Sections aufteilen via PyMuPDF Font-Size-Heuristik."""
    import pymupdf

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    sections: dict[str, str] = {}
    current_section = "PREAMBLE"
    sections[current_section] = ""

    # Erst Font-Größen-Statistik sammeln (Modus = Body-Text)
    font_sizes: list[float] = []
    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    if len(span["text"].strip()) > 5:
                        font_sizes.append(span["size"])

    if not font_sizes:
        doc.close()
        return sections

    # Body-Font = häufigste Größe
    from collections import Counter

    size_counts = Counter(round(s, 1) for s in font_sizes)
    body_size = size_counts.most_common(1)[0][0]

    for page in doc:
        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                line_text = ""
                max_size = 0.0
                is_bold = False
                for span in line["spans"]:
                    line_text += span["text"]
                    max_size = max(max_size, span["size"])
                    if "bold" in span.get("font", "").lower():
                        is_bold = True
                line_text = line_text.strip()
                if not line_text:
                    continue

                # Section-Header erkennen
                is_header = False
                # Muss signifikant größer als Body-Text sein ODER bold
                bigger_than_body = max_size > body_size + 0.5
                if len(line_text) < 100 and (bigger_than_body or is_bold):
                    clean = line_text.upper().strip()
                    # Autorennamen / Affiliations ausfiltern
                    if _is_likely_author_name(line_text):
                        pass
                    # Nummerierte Sections: "1 Introduction", "2.1 Methods"
                    elif re.match(r"^(\d+\.?\d*\.?\s+|[IVX]+\.?\s+)[A-Z]", clean):
                        is_header = True
                    # ALL-CAPS Sections: "ABSTRACT", "INTRODUCTION"
                    elif re.match(r"^[A-Z][A-Z\s&:,]{2,60}$", clean) and len(clean) > 3:
                        is_header = True
                    # Bold + Title-Case, mind. 2 Wörter
                    elif is_bold and len(line_text.split()) >= 2:
                        words = line_text.split()
                        if words[0][0].isupper() and len(line_text) > 8:
                            is_header = True

                if is_header:
                    current_section = line_text.strip()
                    if current_section not in sections:
                        sections[current_section] = ""
                else:
                    sections[current_section] += line_text + "\n"

    doc.close()
    return sections


def _match_section(section_name: str, requested: str) -> bool:
    """Prüft ob ein Section-Name zum angeforderten Typ passt."""
    clean = section_name.upper().strip()
    # Nummer entfernen: "3.1 RESULTS AND ANALYSIS" → "RESULTS AND ANALYSIS"
    clean = re.sub(r"^[\d.]+\s+", "", clean)
    clean = re.sub(r"^[IVX]+[.\s]\s*", "", clean)

    aliases = SECTION_ALIASES.get(requested, [])
    for alias in aliases:
        if alias in clean or clean.startswith(alias):
            return True
    return False


def extract_paper(
    arxiv_id: str | None = None,
    doi: str | None = None,
    pdf_url: str | None = None,
    requested_sections: list[str] | None = None,
) -> dict:
    """Paper herunterladen und Sections extrahieren."""
    if requested_sections is None:
        requested_sections = list(DEFAULT_SECTIONS.split(","))

    # PDF-URL ermitteln
    if pdf_url:
        url = pdf_url
    elif arxiv_id:
        clean_id = arxiv_id.replace("arxiv:", "").strip()
        url = f"https://arxiv.org/pdf/{clean_id}"
    elif doi:
        # DOI → OpenAlex → OA-URL
        with httpx.Client(timeout=10, follow_redirects=True, headers=HTTP_HEADERS) as c:
            r = c.get(
                f"https://api.openalex.org/works/doi:{doi}",
                params={"select": "open_access,title"},
            )
            if r.status_code == 200:
                data = r.json()
                oa = data.get("open_access", {})
                url = oa.get("oa_url")
                if not url:
                    return {"error": f"Kein OA-PDF für DOI {doi}", "doi": doi}
            else:
                return {"error": f"DOI nicht gefunden: {doi}", "doi": doi}
    else:
        return {"error": "Kein arxiv_id, doi, oder pdf_url angegeben"}

    # Download
    t0 = time.monotonic()
    try:
        pdf_bytes = _download_pdf(url)
    except Exception as e:
        return {"error": f"PDF-Download fehlgeschlagen: {e}", "url": url}
    dl_time = int((time.monotonic() - t0) * 1000)

    # Extraktion
    t0 = time.monotonic()
    all_sections = _extract_sections(pdf_bytes)
    parse_time = int((time.monotonic() - t0) * 1000)

    # Gewünschte Sections filtern (min. 100 chars, keine Noise-Sections)
    if "all" in (requested_sections or []):
        matched = {k: v for k, v in all_sections.items() if len(v) >= 50}
    else:
        matched = {}
        for sec_name, sec_text in all_sections.items():
            if len(sec_text) < 100:
                continue  # Mini-Sections (Überschriften, Figure-Labels) ignorieren
            for req in requested_sections or []:
                if _match_section(sec_name, req):
                    matched[sec_name] = sec_text
                    break

    total_chars = sum(len(v) for v in all_sections.values())
    selected_chars = sum(len(v) for v in matched.values())
    section_list = [
        {"name": k, "chars": len(v)} for k, v in all_sections.items() if len(v) > 50
    ]

    result = {
        "url": url,
        "arxiv_id": arxiv_id,
        "doi": doi,
        "download_ms": dl_time,
        "parse_ms": parse_time,
        "total_chars": total_chars,
        "total_tokens_est": total_chars // 4,
        "selected_chars": selected_chars,
        "selected_tokens_est": selected_chars // 4,
        "token_reduction": f"{100 - (selected_chars * 100 // max(total_chars, 1))}%",
        "all_sections": section_list,
        "sections": {k: v for k, v in matched.items()},
    }

    print(
        f"  Extract: {len(matched)}/{len(all_sections)} sections, "
        f"{selected_chars} chars ({selected_chars // 4} tok), "
        f"reduction {result['token_reduction']}, "
        f"dl={dl_time}ms parse={parse_time}ms",
        file=sys.stderr,
    )
    return result


# ── CLI ─────────────────────────────────────────────────────────


def cmd_search(args):
    """Paper-Suche über arXiv + OpenAlex."""
    query = " ".join(args.query)
    limit = args.limit
    year = args.year

    print(f"Academic Search: '{query}' (limit={limit}, year={year})", file=sys.stderr)

    # Parallel suchen
    arxiv_papers = []
    openalex_papers = []

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(search_arxiv, query, limit, year): "arxiv",
            pool.submit(search_openalex, query, limit, year): "openalex",
        }
        for f in as_completed(futures):
            source = futures[f]
            try:
                result = f.result()
                if source == "arxiv":
                    arxiv_papers = result
                else:
                    openalex_papers = result
            except Exception as e:
                print(f"  {source} FEHLER: {e}", file=sys.stderr)

    all_papers = arxiv_papers + openalex_papers
    ranked = deduplicate_and_rank(all_papers, query, limit)

    print(
        f"  Gesamt: {len(all_papers)} roh → {len(ranked)} nach Dedup+Ranking",
        file=sys.stderr,
    )

    # Statistiken
    with_abstract = sum(1 for p in ranked if len(p.get("abstract", "")) > 100)
    with_pdf = sum(1 for p in ranked if p.get("pdf_url"))
    with_cites = sum(1 for p in ranked if p.get("citations"))
    abstract_tokens = sum(len(p.get("abstract", "")) // 4 for p in ranked)

    stats = {
        "query": query,
        "year_filter": year,
        "total_raw": len(all_papers),
        "total_ranked": len(ranked),
        "with_abstract": with_abstract,
        "with_pdf": with_pdf,
        "with_citations": with_cites,
        "abstract_tokens_total": abstract_tokens,
    }
    print(f"  Stats: {json.dumps(stats)}", file=sys.stderr)

    output = {"stats": stats, "papers": ranked}
    json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
    print()


def cmd_extract(args):
    """Paper-Sections extrahieren."""
    sections = args.sections.split(",")

    result = extract_paper(
        arxiv_id=args.arxiv_id if not args.doi and not args.url else None,
        doi=args.doi,
        pdf_url=args.url,
        requested_sections=sections,
    )

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()


def main():
    parser = argparse.ArgumentParser(description="Academic Paper Search + Extraction")
    sub = parser.add_subparsers(dest="command")

    # search
    p_search = sub.add_parser("search", help="Paper-Suche via arXiv + OpenAlex")
    p_search.add_argument("query", nargs="+", help="Suchbegriffe")
    p_search.add_argument("--limit", type=int, default=20)
    p_search.add_argument(
        "--year", type=str, default=None, help="z.B. 2025 oder 2024-2026"
    )
    p_search.set_defaults(func=cmd_search)

    # extract
    p_extract = sub.add_parser("extract", help="Paper-Sections extrahieren")
    p_extract.add_argument("arxiv_id", nargs="?", help="arXiv-ID (z.B. 2602.24287)")
    p_extract.add_argument("--doi", type=str, help="DOI")
    p_extract.add_argument("--url", type=str, help="Direkte PDF-URL")
    p_extract.add_argument(
        "--sections",
        type=str,
        default=DEFAULT_SECTIONS,
        help="Komma-separiert: abstract,introduction,methods,results,discussion,conclusion,all",
    )
    p_extract.set_defaults(func=cmd_extract)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
