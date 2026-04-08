#!/home/maetzger/.claude/tools/.venv/bin/python
"""
Report-Renderer: Token-effiziente HTML-Report-Generierung.

Agent liefert kompaktes JSON → Renderer baut daraus vollständige HTML-Reports
im "Warm Dark Editorial" Design mit vorgefertigten Templates.

Token-Ersparnis: ~80-95% vs. manueller HTML-Generierung.

Verwendung:
    python3 report-renderer.py render research data.json -o report.html
    python3 report-renderer.py render comparison data.json -o report.html
    cat data.json | python3 report-renderer.py render auto -o report.html
    python3 report-renderer.py schema research   # JSON-Schema anzeigen
    python3 report-renderer.py list               # Verfügbare Templates
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime
from html import escape as html_escape
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent / "report-templates"
BASE_CSS_FILE = TEMPLATES_DIR / "_base.css"
DEFAULT_OUTPUT = Path.home() / "shared" / "reports"
_HTML_TAG_SPLIT_RE = re.compile(r"(</?[A-Za-z][^>]*?>)")
_HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>]*?>")
_HTML_ENTITY_RE = re.compile(r"&(?![A-Za-z][A-Za-z0-9]+;|#\d+;|#x[0-9A-Fa-f]+;)")


# ── Minimal Markdown → HTML ──────────────────────────────────────────────────


def _escape_text_fragment(text: str) -> str:
    """Escape plain text without double-escaping existing HTML entities."""
    text = _HTML_ENTITY_RE.sub("&amp;", text)
    return text.replace("<", "&lt;").replace(">", "&gt;")


def _apply_markdown(text: str, *, convert_newlines: bool = True) -> str:
    """Apply the renderer's minimal Markdown syntax to already-safe text."""
    if not text:
        return ""
    t = text
    # Code (vor bold/italic, damit ` nicht interferiert)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    # Bold
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    # Italic
    t = re.sub(r"\*(.+?)\*", r"<em>\1</em>", t)
    # Links
    t = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: (
            f'<a href="{html_escape(m.group(2), quote=True)}" '
            f'target="_blank" rel="noopener">{m.group(1)}</a>'
        ),
        t,
    )
    # Citation references: [Q1], [Q2], etc. → cp-citation-ref buttons
    t = re.sub(
        r"\[Q(\d+)\]",
        lambda m: (
            f'<button class="cp-citation-ref" data-citation="{m.group(1)}" '
            f'aria-expanded="false" onclick="toggleCitation(this)">'
            f"Q{m.group(1)}</button>"
        ),
        t,
    )
    if convert_newlines:
        t = t.replace("\n", "<br>")
    return t


def md(text: str) -> str:
    """Minimal Markdown → HTML für Inline-Content-Felder.

    Unterstützt: **bold**, *italic*, `code`, [text](url), \n→<br>.
    Akzeptiert auch rohes HTML: <strong>, <em>, <br>, <a href="...">.
    """
    if not text:
        return ""
    # Sichere HTML-Tags vor dem Escaping schützen (Platzhalter)
    _safe = []

    def _protect(m: re.Match) -> str:
        _safe.append(m.group(0))
        return f"\x00SAFE{len(_safe) - 1}\x00"

    t = text
    # <a href="...">...</a> und <a href='...'>...</a> schützen
    t = re.sub(
        r"""<a\s+[^>]*href\s*=\s*["'][^"']*["'][^>]*>.*?</a>""",
        _protect,
        t,
        flags=re.DOTALL,
    )
    # <strong>...</strong>, <em>...</em> schützen
    t = re.sub(r"<(strong|em)>(.*?)</\1>", _protect, t, flags=re.DOTALL)
    # <br>, <br/>, <br /> schützen
    t = re.sub(r"<br\s*/?>", _protect, t)
    # <img ...> schützen (für annotierte Screenshots in Guides)
    t = re.sub(r"<img\s+[^>]+>", _protect, t)
    # <details>...<summary>...</summary>...</details> schützen (Collapsibles)
    t = re.sub(r"<details[^>]*>.*?</details>", _protect, t, flags=re.DOTALL)

    # Jetzt sicher escapen (nur noch unsicheres HTML wird escaped)
    t = html_escape(t)

    # Platzhalter wiederherstellen (reverse: äußere Blöcke zuerst,
    # damit verschachtelte innere Marker danach aufgelöst werden)
    for i in range(len(_safe) - 1, -1, -1):
        t = t.replace(f"\x00SAFE{i}\x00", _safe[i])

    return _apply_markdown(t)


def rich_text(text: str) -> str:
    """Markdown + rohes HTML für Body-/Block-Felder.

    HTML-Tags bleiben erhalten, reiner Text wird weiterhin escaped.
    Markdown wird nur auf Textsegmente angewendet, nicht auf die HTML-Tags selbst.
    """
    if not text:
        return ""
    if "<" not in text or ">" not in text:
        return _apply_markdown(_escape_text_fragment(text))

    parts = []
    for part in _HTML_TAG_SPLIT_RE.split(text):
        if not part:
            continue
        if _HTML_TAG_RE.fullmatch(part):
            parts.append(part)
            continue
        parts.append(
            _apply_markdown(
                _escape_text_fragment(part),
                convert_newlines=bool(part.strip()),
            )
        )
    return "".join(parts)


# ── Template Loading ─────────────────────────────────────────────────────────


def load_css() -> str:
    """Shared CSS laden."""
    return BASE_CSS_FILE.read_text(encoding="utf-8")


def load_template(name: str) -> str:
    """HTML-Template laden."""
    path = TEMPLATES_DIR / f"{name}.html"
    if not path.exists():
        print(f"Template '{name}' nicht gefunden: {path}", file=sys.stderr)
        sys.exit(1)
    return path.read_text(encoding="utf-8")


# ── Compact JSON Alias Resolver ──────────────────────────────────────────────

# Short-key aliases for token-efficient JSON from agents (~20-25% savings)
_KEY_ALIASES = {
    "t": "title",
    "s": "subtitle",
    "hl": "highlights",
    "sx": "sections",
    "src": "sources",
    "hd": "heading",
    "bd": "body",
    "q": "quality",
    "u": "url",
    "n": "note",
    "v": "value",
    "l": "label",
    "hr": "hero",
    "ey": "eyebrow",
    "ch": "chips",
}


def _expand_aliases(data):
    """Recursively expand short-key aliases to full keys.

    Backward-compatible: if both short and full key exist, full key wins.
    """
    if isinstance(data, dict):
        expanded = {}
        # First pass: collect all full keys present in original dict
        full_keys_present = {k for k in data if k not in _KEY_ALIASES}
        for k, val in data.items():
            full_key = _KEY_ALIASES.get(k, k)
            # Skip alias if the full key is already present in the original dict
            if k in _KEY_ALIASES and full_key in full_keys_present:
                continue
            expanded[full_key] = _expand_aliases(val)
        return expanded
    if isinstance(data, list):
        return [_expand_aliases(item) for item in data]
    return data


# ── Smart Router ─────────────────────────────────────────────────────────────


def fingerprint_data(data: dict) -> dict:
    """Phase 1: Analyse der JSON-Datenstruktur."""
    return {
        "has_options": "options" in data,
        "has_kpis": "kpis" in data,
        "has_steps": "steps" in data,
        "has_timeline": "timeline" in data,
        "has_radar": "radar" in data,
        "has_distribution": "distribution" in data,
        "has_tags": "tags" in data,
        "has_matrix": "matrix" in data,
        "has_sections": "sections" in data,
        "has_sources": "sources" in data,
        "has_bars": "bars" in data,
        "has_table": "table" in data,
        "has_cta": "cta" in data,
        "has_gauge": "gauge" in data,
        # Deep Research v2 signals
        "has_verified": "verified" in data,
        "has_pullquotes": "pullquotes" in data,
        "has_keyfacts": "keyfacts" in data,
        "has_conflicts": "conflicts" in data,
        "has_kernaussage": "kernaussage" in data,
        "has_confidence_gauge": "confidence_gauge" in data,
        "has_source_bars": "source_bars" in data,
        # Lokal-Guide signals
        "has_locations": "locations" in data,
        "has_route": "route" in data,
        "has_quickcompare": "quickcompare" in data,
        "has_insider_tip": "insider_tip" in data,
        # Content-Pattern signals
        "has_price_cards": "price_cards" in data,
        "has_guides": "guides" in data,
        "has_callouts": "callouts" in data,
        "has_key_insights": "key_insights" in data,
        "has_progress": "progress" in data,
        "has_svg_bars": "svg_bars" in data,
        "option_count": len(data.get("options", [])),
        "section_count": len(data.get("sections", [])),
        "source_count": len(data.get("sources", [])),
        "kpi_count": len(data.get("kpis", [])),
        "has_confidence": any(s.get("confidence") for s in data.get("sections", [])),
        "has_prices": any(
            "preis" in str(v).lower() or "€" in str(v) or "$" in str(v)
            for v in [data.get("title", "")]
            + [s.get("title", "") for s in data.get("sections", [])]
        ),
        "text_heavy": sum(len(s.get("body", "")) for s in data.get("sections", []))
        > 2000,
    }


ARCHETYPE_CONFIG = {
    # max_w und accent werden NICHT überschrieben — Design-Sprache aus _base.css
    # gilt immer (740px, Kupfer #cf865a). Nur accent_secondary für Viz-Kontrast.
    "market": {"accent_secondary": "#c9a84a"},
    "deep-research": {"accent_secondary": "#cf865a"},
    "deep-research-v2": {"accent_secondary": "#6d8bb8"},
    "head-to-head": {"accent_secondary": "#6db87a"},
    "multi-compare": {"accent_secondary": "#cf865a"},
    "briefing": {"accent_secondary": "#cf865a"},
    "narrative": {"accent_secondary": "#a88b6d"},
    "how-to": {"accent_secondary": "#6db87a"},
    "exploration": {"accent_secondary": "#b07cc6"},
    "lokal-guide": {"accent_secondary": "#cf865a"},
}


def select_archetype(data: dict, fp: dict) -> str:
    """Phase 2: Archetyp-Selektion basierend auf Fingerprint."""
    # Expliziter Typ hat Vorrang → map auf Archetyp
    explicit = data.get("type", "")
    type_map = {
        "research": "deep-research",
        "deep-research-v2": "deep-research-v2",
        "lokal-guide": "lokal-guide",
        "dashboard": "briefing",
        "guide": "how-to",
        "comparison": "head-to-head",
    }
    if explicit in type_map:
        return type_map[explicit]

    # Heuristic: Lokal-Guide pattern (locations/route signals)
    if fp["has_locations"] or fp["has_route"]:
        return "lokal-guide"

    # Heuristic: Deep Research v2 (verified + pullquotes/keyfacts)
    if fp["has_verified"] or fp["has_pullquotes"] or fp["has_keyfacts"]:
        return "deep-research-v2"

    # Heuristic: Product/Price signals + sources → deep-research-v2
    # (deep-research-v2 template renders PRICE_CARDS, CTA, TABLE, SOURCE_BARS
    #  which the plain research template does NOT)
    has_product_signals = (
        fp["has_price_cards"]
        or fp["has_cta"]
        or fp["has_source_bars"]
        or (fp["has_table"] and data.get("table", {}).get("variant") == "comparison")
    )
    if has_product_signals and fp["has_sources"]:
        return "deep-research-v2"

    # Heuristic selection (original patterns)
    if fp["has_steps"]:
        return "how-to"
    if fp["has_options"] and fp["option_count"] >= 5:
        return "multi-compare"
    if fp["has_options"] and fp["option_count"] <= 4:
        return "head-to-head"
    if fp["has_prices"] or (fp["has_table"] and fp["has_bars"]):
        return "market"
    if fp["has_kpis"] and fp["kpi_count"] >= 3 and not fp["text_heavy"]:
        return "briefing"
    if fp["has_timeline"] or fp["text_heavy"]:
        return "narrative"
    if fp["has_tags"] or (fp["has_sections"] and not fp["has_sources"]):
        return "exploration"
    if fp["has_sources"] and fp["has_confidence"]:
        return "deep-research"
    if fp["has_sources"] and fp["section_count"] >= 2:
        return "deep-research"
    return "deep-research"


# Archetype → Template mapping
_ARCH_TO_TEMPLATE = {
    "market": "research",
    "deep-research": "research",
    "deep-research-v2": "deep-research-v2",
    "head-to-head": "comparison",
    "multi-compare": "comparison",
    "briefing": "dashboard",
    "narrative": "research",
    "how-to": "guide",
    "exploration": "generic",
    "lokal-guide": "lokal-guide",
}


def detect_type(data: dict) -> str:
    """Backward-compatible: maps archetype → template type."""
    fp = fingerprint_data(data)
    archetype = select_archetype(data, fp)
    return _ARCH_TO_TEMPLATE.get(archetype, "generic")


# ── Content Generators ───────────────────────────────────────────────────────
# Jeder Generator nimmt JSON-Daten und gibt HTML-Content-Blocks zurück.


def _highlights_html(items: list[str]) -> str:
    """Nummerierte Highlights-Liste."""
    if not items:
        return ""
    lis = []
    for i, item in enumerate(items, 1):
        lis.append(
            f'<li><span class="hl-num">{i}</span>'
            f'<span class="hl-text">{md(item)}</span></li>'
        )
    return f'<ul class="highlights">{"".join(lis)}</ul>'


def _stat_cards_html(kpis: list[dict]) -> str:
    """Stat-Cards Grid."""
    if not kpis:
        return ""
    cards = []
    for i, kpi in enumerate(kpis):
        cls = "stat-card primary" if i == 0 else "stat-card"
        val = html_escape(str(kpi.get("value", "")))
        label = html_escape(str(kpi.get("label", "")))
        note = kpi.get("note", "")
        note_html = f'<div class="stat-note">{html_escape(note)}</div>' if note else ""
        delta = kpi.get("delta", "")
        trend_dir = kpi.get("trend", "")
        trend = _trend_html(delta, trend_dir) if delta else ""
        cards.append(
            f'<div class="{cls}">'
            f'<div class="stat-value">{val} {trend}</div>'
            f'<div class="stat-label">{label}</div>'
            f"{note_html}</div>"
        )
    return f'<div class="stat-grid">{"".join(cards)}</div>'


def _sections_html(sections: list[dict]) -> str:
    """Content-Sektionen mit hierarchischer Gruppierung.

    Sections mit "level": "part" werden als Teil-Header (h2, volle Breite,
    accent-Linie) gerendert. Alle folgenden Sections ohne level werden als
    Sub-Sections (h3) innerhalb dieses Teils dargestellt.

    Unterstützte Felder pro Section:
      - title/heading: Überschrift
      - body: Fließtext (Markdown)
      - items: Bullet-Liste
      - collapsed: true → <details> statt offener Block
      - level: "part" → Teil-Header mit visueller Trennung
      - callout: "warn"|"tip" → farbiges Callout-Box
      - badge: Text für inline-Badge am Titel
    """
    if not sections:
        return ""
    parts = []
    in_part = False
    for sec in sections:
        title = html_escape(sec.get("title", sec.get("heading", "")))
        body = rich_text(sec.get("body", ""))
        items = sec.get("items", [])
        items_html = ""
        if items:
            lis = [f"<li>{md(item)}</li>" for item in items]
            items_html = f'<ul class="section-list">{"".join(lis)}</ul>'

        level = sec.get("level", "")
        callout = sec.get("callout", "")
        badge = sec.get("badge", "")
        confidence = sec.get("confidence", "")

        # Callout-Wrapping
        if callout and body:
            cls = "callout-warn" if callout == "warn" else "callout-tip"
            body = f'<div class="callout {cls} rich-text">{body}</div>'

        # Confidence-Indikator
        conf_html = ""
        if confidence and confidence in ("high", "medium", "inferred"):
            conf_labels = {
                "high": "Belegt",
                "medium": "Teilbelegt",
                "inferred": "Inferenz",
            }
            conf_html = (
                f' <span class="confidence-indicator confidence-{confidence}">'
                f"{conf_labels[confidence]}</span>"
            )

        # Badge am Titel
        badge_html = ""
        if badge:
            badge_cls = "badge-accent"
            if any(
                w in badge.lower() for w in ("stark", "hoch", "robust", "konsistent")
            ):
                badge_cls = "badge-green"
            elif any(w in badge.lower() for w in ("gemischt", "moderat", "schwach")):
                badge_cls = "badge-yellow"
            elif any(w in badge.lower() for w in ("negativ", "gescheitert", "kein")):
                badge_cls = "badge-red"
            badge_html = f' <span class="badge {badge_cls}">{html_escape(badge)}</span>'

        # Teil-Header (level: "part")
        if level == "part":
            if in_part:
                parts.append("</div>")  # schließe vorherigen Teil
            parts.append(
                f'<div class="part-group">'
                f'<h2 class="part-header">{title}{badge_html}{conf_html}</h2>'
                f'<div class="section-body part-intro rich-text">{body}</div>'
            )
            in_part = True
        elif sec.get("collapsed"):
            parts.append(
                f'<details class="collapse"><summary>{title}{badge_html}{conf_html}</summary>'
                f'<div class="collapse-body rich-text">{body}{items_html}</div></details>'
            )
        else:
            tag = "h3" if in_part else "h2"
            parts.append(
                f'<section class="content-section"><{tag}>{title}{badge_html}{conf_html}</{tag}>'
                f'<div class="section-body rich-text">{body}</div>{items_html}</section>'
            )

    if in_part:
        parts.append("</div>")  # schließe letzten Teil
    return "".join(parts)


def _sources_html(sources: list[dict]) -> str:
    """Quellen-Liste mit Quality-Badges, Trust-Level und Typ-Badges (cp-*)."""
    if not sources:
        return ""
    has_trust = any(s.get("trust_level") for s in sources)
    has_type = any(s.get("type") for s in sources)
    # New cp-source-item layout when trust/type fields present
    if has_trust or has_type:
        items = []
        for i, src in enumerate(sources):
            title = html_escape(src.get("title", src.get("t", "")))
            url = src.get("url", src.get("u", ""))
            quality = src.get("quality", src.get("q", ""))
            trust = src.get("trust_level", "")
            stype = src.get("type", "")
            # Trust badge (cp-trust-badge)
            trust_html = ""
            if trust:
                _tl = {
                    "high": "Verifiziert",
                    "medium": "Teilweise geprüft",
                    "low": "Ungeprüft",
                    "academic": "Akademisch",
                }
                trust_html = (
                    f'<span class="cp-trust-badge cp-trust-badge--{html_escape(trust)}">'
                    f"{html_escape(_tl.get(trust, trust.title()))}</span>"
                )
            # Type badge (cp-source-badge)
            type_html = ""
            if stype:
                _sl = {
                    "academic": "Akademisch",
                    "journalistic": "Journalistisch",
                    "blog": "Blog",
                    "ai": "KI-generiert",
                }
                type_html = (
                    f'<span class="cp-source-badge cp-source-badge--{html_escape(stype)}">'
                    f"{html_escape(_sl.get(stype, stype.title()))}</span>"
                )
            # Trust meter bar
            meter_html = ""
            if trust:
                _mp = {"high": 100, "academic": 90, "medium": 60, "low": 30}
                pct = _mp.get(trust, 50)
                lvl = "high" if pct >= 70 else "medium" if pct >= 50 else "low"
                meter_html = (
                    f'<div class="cp-trust-meter"><div class="cp-trust-meter__bar">'
                    f'<div class="cp-trust-meter__fill cp-trust-meter__fill--{lvl}" '
                    f'style="width:{pct}%"></div></div>'
                    f'<span class="cp-trust-meter__label">{pct}%</span></div>'
                )
            q_html = ""
            if quality:
                q_cls = "badge-green" if int(quality) >= 7 else "badge-muted"
                q_html = f'<span class="badge {q_cls}">Q{quality}</span>'
            items.append(
                f'<div class="cp-source-item" id="source-{i + 1}">'
                f'<span class="cp-source-item__number">{i + 1}</span>'
                f'<div class="cp-source-item__meta">'
                f'<a href="{html_escape(url)}" target="_blank" rel="noopener" '
                f'class="cp-source-item__link">{title}</a>'
                f'<div class="cp-source-item__details">'
                f"{q_html}{trust_html}{type_html}{meter_html}"
                f"</div></div></div>"
            )
        return (
            '<div class="sources-section"><h2>Quellen</h2>'
            f'<div class="cp-source-list">{"".join(items)}</div></div>'
        )
    # Fallback: classic table (backward-compatible)
    rows = []
    for i, src in enumerate(sources):
        title = html_escape(src.get("title", src.get("t", "")))
        url = src.get("url", src.get("u", ""))
        quality = src.get("quality", src.get("q", ""))
        tier = src.get("domain_tier", "")
        q_cls = "badge-green" if quality and int(quality) >= 7 else "badge-muted"
        tier_html = (
            f'<span class="badge badge-accent">{html_escape(tier)}</span>'
            if tier
            else ""
        )
        rows.append(
            f'<tr id="source-{i + 1}">'
            f'<td><a href="{html_escape(url)}" target="_blank" '
            f'rel="noopener" class="source-link">{title}</a></td>'
            f'<td><span class="badge {q_cls}">Q{quality}</span></td>'
            f"<td>{tier_html}</td></tr>"
        )
    return (
        '<div class="sources-section"><h2>Quellen</h2>'
        '<div class="table-wrap"><table class="data-table">'
        "<thead><tr><th>Quelle</th><th>Qualität</th><th>Tier</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div></div>"
    )


def _agent_block_html(text: str) -> str:
    """Agent-Analyse-Block."""
    if not text:
        return ""
    return (
        '<div class="agent-block">'
        '<div class="agent-label">Agent-Analyse</div>'
        f"<div>{md(text)}</div></div>"
    )


def _table_html(table: dict) -> str:
    """Daten-Tabelle aus headers + rows.

    Supports variant="comparison" with highlight_col for "Empfohlen" badge.
    """
    if not table:
        return ""
    headers = table.get("headers", [])
    rows = table.get("rows", [])
    variant = table.get("variant", "")
    highlight_col = table.get("highlight_col")
    th_parts = []
    for ci, h in enumerate(headers):
        hl = ""
        if (
            variant == "comparison"
            and highlight_col is not None
            and ci == highlight_col
        ):
            hl = ' class="cp-highlight-col"'
        badge = (
            '<span class="cp-recommended-badge">Empfohlen</span>'
            if variant == "comparison"
            and highlight_col is not None
            and ci == highlight_col
            else ""
        )
        th_parts.append(f"<th{hl}>{html_escape(str(h))} {badge}</th>")
    th = "".join(th_parts)
    trs = []
    for row in rows:
        cells = row if isinstance(row, list) else list(row.values())
        tds = []
        for ci, c in enumerate(cells):
            hl = ""
            if (
                variant == "comparison"
                and highlight_col is not None
                and ci == highlight_col
            ):
                hl = ' class="cp-highlight-col"'
            tds.append(f"<td{hl}>{md(str(c))}</td>")
        trs.append(f"<tr>{''.join(tds)}</tr>")
    if variant == "comparison":
        return (
            '<div class="cp-comparison-wrapper"><table class="cp-comparison-table">'
            f"<thead><tr>{th}</tr></thead>"
            f"<tbody>{''.join(trs)}</tbody></table></div>"
        )
    return (
        f'<div class="table-wrap"><table class="data-table">'
        f"<thead><tr>{th}</tr></thead>"
        f"<tbody>{''.join(trs)}</tbody></table></div>"
    )


def _bars_html(bars: list[dict]) -> str:
    """Horizontale Balkendiagramme."""
    if not bars:
        return ""
    items = []
    max_val = max((b.get("value", 0) for b in bars), default=1) or 1
    for i, bar in enumerate(bars):
        label = html_escape(str(bar.get("label", "")))
        value = bar.get("value", 0)
        pct = min(100, (value / max_val) * 100)
        display = bar.get("display", str(value))
        delay = f"animation-delay: {i * 0.05}s"
        items.append(
            f'<div class="bar-row">'
            f'<span class="bar-label">{label}</span>'
            f'<div class="bar-track">'
            f'<div class="bar-fill" style="width:{pct:.0f}%;{delay}"></div></div>'
            f'<span class="bar-value">{html_escape(str(display))}</span></div>'
        )
    return f'<div class="bar-chart">{"".join(items)}</div>'


def _copyable_html(text: str, label: str = "Kopieren") -> str:
    """Kopierbarer Text-Block mit One-Click-Copy."""
    if not text:
        return ""
    escaped = html_escape(text)
    btn_id = f"copy-{abs(hash(text)) % 10000}"
    return (
        f'<div class="copyable" id="{btn_id}-wrap">'
        f'<pre class="copyable-text">{escaped}</pre>'
        f'<button class="copy-btn" onclick="'
        f"navigator.clipboard.writeText("
        f"document.getElementById('{btn_id}-wrap')"
        f".querySelector('.copyable-text').textContent)"
        f".then(()=>{{this.textContent='Kopiert!';setTimeout(()=>"
        f"this.textContent='{label}',1500)}})"
        f'">{label}</button></div>'
    )


def _metrics_footer_html(metrics: dict) -> str:
    """Metriken-Footer."""
    if not metrics:
        return ""
    items = []
    for key, val in metrics.items():
        items.append(
            f'<span class="metric"><span class="metric-label">'
            f"{html_escape(str(key))}</span> "
            f"{html_escape(str(val))}</span>"
        )
    return f'<div class="metrics-footer">{"".join(items)}</div>'


# ── New Visualization Generators ────────────────────────────────────────────


def _radar_chart_html(radar: dict) -> str:
    """Radar/Spider-Chart als SVG."""
    if not radar:
        return ""
    axes = radar.get("axes", [])
    datasets = radar.get("datasets", [])
    if len(axes) < 3 or not datasets:
        return ""

    n = len(axes)
    cx, cy, r = 150, 150, 120
    colors = [
        ("var(--accent)", "var(--accent-dim)"),
        ("var(--green)", "rgba(109,184,122,0.12)"),
        ("var(--yellow)", "rgba(201,168,74,0.12)"),
    ]

    # Grid lines (3 concentric rings)
    grid = ""
    for ring in (0.33, 0.66, 1.0):
        pts = []
        for i in range(n):
            angle = (2 * math.pi * i / n) - math.pi / 2
            px = cx + r * ring * math.cos(angle)
            py = cy + r * ring * math.sin(angle)
            pts.append(f"{px:.1f},{py:.1f}")
        grid += f'<polygon class="grid-line" points="{" ".join(pts)}"/>\n'

    # Axis lines
    axis_lines = ""
    for i in range(n):
        angle = (2 * math.pi * i / n) - math.pi / 2
        x2 = cx + r * math.cos(angle)
        y2 = cy + r * math.sin(angle)
        axis_lines += f'<line class="axis-line" x1="{cx}" y1="{cy}" x2="{x2:.1f}" y2="{y2:.1f}"/>\n'

    # Axis labels
    labels = ""
    for i, label in enumerate(axes):
        angle = (2 * math.pi * i / n) - math.pi / 2
        lx = cx + (r + 20) * math.cos(angle)
        ly = cy + (r + 20) * math.sin(angle)
        labels += f'<text class="axis-label" x="{lx:.1f}" y="{ly:.1f}">{html_escape(label)}</text>\n'

    # Data areas
    areas = ""
    for di, ds in enumerate(datasets[:3]):
        vals = ds.get("values", [])
        if len(vals) != n:
            continue
        pts = []
        dots = ""
        for i, v in enumerate(vals):
            frac = min(1, max(0, v / 100))
            angle = (2 * math.pi * i / n) - math.pi / 2
            px = cx + r * frac * math.cos(angle)
            py = cy + r * frac * math.sin(angle)
            pts.append(f"{px:.1f},{py:.1f}")
            stroke, _ = colors[di % len(colors)]
            dots += f'<circle class="data-point" cx="{px:.1f}" cy="{py:.1f}" style="fill:{stroke}"/>\n'
        stroke, fill = colors[di % len(colors)]
        areas += f'<polygon class="data-area" points="{" ".join(pts)}" style="fill:{fill};stroke:{stroke}"/>\n'
        areas += dots

    # Legend
    legend_items = ""
    for di, ds in enumerate(datasets[:3]):
        stroke, _ = colors[di % len(colors)]
        name = html_escape(ds.get("label", f"Dataset {di + 1}"))
        legend_items += (
            f'<span><span class="radar-legend-dot" style="background:{stroke}"></span>'
            f"{name}</span>"
        )

    return (
        f'<div class="radar-wrap">'
        f'<div><svg class="radar-chart" viewBox="0 0 300 300">'
        f"{grid}{axis_lines}{areas}{labels}</svg>"
        f'<div class="radar-legend">{legend_items}</div></div></div>'
    )


def _donut_chart_html(dist: dict) -> str:
    """Donut-Chart als SVG."""
    if not dist:
        return ""
    labels = dist.get("labels", [])
    values = dist.get("values", [])
    if not labels or not values or len(labels) != len(values):
        return ""

    total = sum(values) or 1
    palette = [
        "var(--accent)",
        "var(--green)",
        "var(--yellow)",
        "var(--red)",
        "var(--text-muted)",
        "#b07cc6",
    ]
    r = 70
    circumference = 2 * math.pi * r
    cx, cy = 90, 90

    segments = ""
    legend = ""
    offset = 0
    for i, (label, val) in enumerate(zip(labels, values)):
        pct = val / total
        dash = circumference * pct
        gap = circumference - dash
        color = palette[i % len(palette)]
        segments += (
            f'<circle cx="{cx}" cy="{cy}" r="{r}" '
            f'stroke="{color}" stroke-dasharray="{dash:.1f} {gap:.1f}" '
            f'stroke-dashoffset="{-offset:.1f}" '
            f'transform="rotate(-90 {cx} {cy})"/>\n'
        )
        offset += dash
        legend += (
            f'<div class="donut-legend-item">'
            f'<span class="donut-legend-dot" style="background:{color}"></span>'
            f"<span>{html_escape(label)}</span>"
            f'<span class="donut-legend-value">{val}</span></div>'
        )

    center_text = html_escape(dist.get("center", str(total)))

    return (
        f'<div class="donut-wrap">'
        f'<svg class="donut-chart" viewBox="0 0 180 180">'
        f"{segments}"
        f'<text class="donut-center" x="{cx}" y="{cy}">{center_text}</text></svg>'
        f'<div class="donut-legend">{legend}</div></div>'
    )


def _timeline_html(items: list[dict]) -> str:
    """Timeline-Visualisierung."""
    if not items:
        return ""
    nodes = []
    for i, item in enumerate(items):
        date = html_escape(str(item.get("date", "")))
        event = html_escape(item.get("event", ""))
        detail = md(item.get("detail", ""))
        delay = f"animation-delay: {i * 0.08}s"
        nodes.append(
            f'<div class="timeline-item" style="{delay}">'
            f'<div class="timeline-date">{date}</div>'
            f'<div class="timeline-title">{event}</div>'
            f'<div class="timeline-detail">{detail}</div></div>'
        )
    return f'<div class="timeline">{"".join(nodes)}</div>'


def _feature_matrix_html(matrix: dict) -> str:
    """Feature-Matrix mit Symbolen."""
    if not matrix:
        return ""
    features = matrix.get("features", [])
    options = matrix.get("options", [])
    if not features or not options:
        return ""

    th = "<th>Feature</th>" + "".join(f"<th>{html_escape(o)}</th>" for o in options)

    icon_map = {
        True: '<span class="fm-yes">\u2713</span>',
        False: '<span class="fm-no">\u2717</span>',
        "partial": '<span class="fm-partial">\u25d0</span>',
    }
    rows = []
    for feat in features:
        name = html_escape(feat.get("name", ""))
        cells = "<td>" + name + "</td>"
        for val in feat.get("values", []):
            icon = icon_map.get(val, f"<span>{html_escape(str(val))}</span>")
            cells += f"<td>{icon}</td>"
        rows.append(f"<tr>{cells}</tr>")

    return (
        f'<div class="table-wrap"><table class="feature-matrix">'
        f"<thead><tr>{th}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _tag_cloud_html(tags: list) -> str:
    """Tag-Cloud mit gewichteten Tags."""
    if not tags:
        return ""
    items = []
    for tag in tags:
        if isinstance(tag, str):
            label, weight = tag, 1
        else:
            label = tag.get("label", tag.get("name", ""))
            weight = tag.get("weight", 1)
        size = 0.65 + min(weight, 5) * 0.15
        cls = " primary" if weight >= 4 else ""
        items.append(
            f'<span class="tag-cloud-item{cls}" style="--tag-size:{size:.2f}rem">'
            f"{html_escape(label)}</span>"
        )
    return f'<div class="tag-cloud">{"".join(items)}</div>'


def _trend_html(delta: str, direction: str = "") -> str:
    """Inline Trend-Indikator."""
    if not delta:
        return ""
    if not direction:
        direction = (
            "up"
            if delta.startswith("+")
            else "down"
            if delta.startswith("-")
            else "flat"
        )
    return (
        f'<span class="trend trend-{direction}">'
        f'<span class="trend-arrow"></span>'
        f'<span class="trend-value">{html_escape(delta)}</span></span>'
    )


def _cta_block_html(ctas: list[dict]) -> str:
    """Smart Call-to-Action Block.

    Each CTA supports: label, url, icon (emoji/text), description, variant.
    variant: "primary" (accent bg), "secondary" (outline), "ghost" (minimal).
    """
    if not ctas:
        return ""
    # Check if any CTA has extended fields (icon/description/variant)
    has_extended = any(
        cta.get("icon") or cta.get("description") or cta.get("variant") for cta in ctas
    )
    if has_extended:
        # New cp-cta-card layout
        cards = []
        for cta in ctas:
            label = html_escape(cta.get("label", ""))
            url = cta.get("url", "#")
            icon = html_escape(cta.get("icon", ""))
            desc = html_escape(cta.get("description", ""))
            variant = cta.get("variant", "primary")
            icon_html = f'<div class="cp-cta-card__icon">{icon}</div>' if icon else ""
            desc_html = f'<div class="cp-cta-card__desc">{desc}</div>' if desc else ""
            act_cls = f"cp-cta-card__action cp-cta-card__action--{variant}"
            cards.append(
                f'<div class="cp-cta-card">'
                f"{icon_html}"
                f'<div class="cp-cta-card__title">{label}</div>'
                f"{desc_html}"
                f'<a href="{html_escape(url)}" class="{act_cls}" '
                f'target="_blank" rel="noopener">{label} \u2192</a></div>'
            )
        return f'<div class="cp-cta-grid">{"".join(cards)}</div>'
    # Fallback: classic simple CTA buttons
    btns = []
    for cta in ctas:
        label = html_escape(cta.get("label", ""))
        url = cta.get("url", "#")
        btns.append(
            f'<a href="{html_escape(url)}" class="cta-btn" '
            f'target="_blank" rel="noopener">{label}</a>'
        )
    return (
        f'<div class="cta-block">'
        f'<div class="cta-label">N\u00e4chste Schritte</div>'
        f'<div class="cta-actions">{"".join(btns)}</div></div>'
    )


def _gauge_html(gauge: dict) -> str:
    """Gauge/Meter als SVG."""
    if not gauge:
        return ""
    value = gauge.get("value", 0)
    max_val = gauge.get("max", 100)
    label = html_escape(gauge.get("label", ""))
    display = html_escape(str(gauge.get("display", str(value))))

    pct = min(1, max(0, value / max_val))
    r = 60
    half_circ = math.pi * r
    dash = half_circ * pct
    gap = half_circ - dash

    return (
        f'<div class="gauge-wrap">'
        f'<svg class="gauge-chart" viewBox="0 0 160 90">'
        f'<path class="gauge-track" d="M 20 80 A 60 60 0 0 1 140 80" />'
        f'<path class="gauge-fill" d="M 20 80 A 60 60 0 0 1 140 80" '
        f'stroke-dasharray="{dash:.1f} {gap:.1f}" />'
        f'<text class="gauge-value" x="80" y="72">{display}</text></svg>'
        f'<div class="gauge-label">{label}</div></div>'
    )


def _price_cards_html(cards: list[dict]) -> str:
    """Price Cards (cp-price-card) mit Trend-Indikatoren und Sparklines."""
    if not cards:
        return ""
    items = []
    for card in cards:
        name = html_escape(card.get("name", ""))
        price = html_escape(str(card.get("price", "")))
        unit = html_escape(card.get("unit", ""))
        trend = card.get("trend", "")
        updated = html_escape(card.get("updated", ""))
        url = card.get("url", "")
        sparkline_data = card.get("sparkline_data", [])
        # Trend indicator
        trend_cls = {
            "up": "cp-trend-indicator--up",
            "down": "cp-trend-indicator--down",
            "stable": "cp-trend-indicator--stable",
        }.get(trend, "")
        trend_arrow = {"up": "\u2191", "down": "\u2193", "stable": "\u2192"}.get(
            trend, ""
        )
        trend_html = (
            f'<div class="cp-price-card__trend"><span class="cp-trend-indicator {trend_cls}">{trend_arrow} {trend}</span></div>'
            if trend
            else ""
        )
        # Sparkline SVG
        sparkline_html = ""
        if sparkline_data and len(sparkline_data) >= 2:
            mn, mx = min(sparkline_data), max(sparkline_data)
            rng = mx - mn or 1
            w, h = 200, 28
            pts = []
            for i, v in enumerate(sparkline_data):
                x = i * w / (len(sparkline_data) - 1)
                y = h - ((v - mn) / rng) * (h - 2) - 1
                pts.append(f"{x:.1f},{y:.1f}")
            poly = " ".join(pts)
            # Area fill
            area = f"0,{h} {poly} {w},{h}"
            sparkline_html = (
                f'<svg class="cp-price-card__sparkline" viewBox="0 0 {w} {h}" preserveAspectRatio="none">'
                f'<polygon class="cp-sparkline-area" points="{area}"/>'
                f'<polyline class="cp-sparkline" points="{poly}"/></svg>'
            )
        unit_html = (
            f'<span class="cp-price-card__unit"> / {unit}</span>' if unit else ""
        )
        meta_parts = []
        if updated:
            meta_parts.append(f'<span class="cp-price-card__updated">{updated}</span>')
        if url:
            meta_parts.append(
                f'<a href="{html_escape(url)}" target="_blank" rel="noopener" class="cp-price-card__link">Details \u2192</a>'
            )
        meta_html = (
            f'<div class="cp-price-card__meta">{"".join(meta_parts)}</div>'
            if meta_parts
            else ""
        )
        items.append(
            f'<div class="cp-price-card">'
            f'<div class="cp-price-card__header"><div class="cp-price-card__name">{name}</div></div>'
            f'<div class="cp-price-card__price">{price}{unit_html}</div>'
            f"{trend_html}{sparkline_html}{meta_html}</div>"
        )
    return f'<div class="cp-price-cards">{"".join(items)}</div>'


def _guides_html(guides: list[dict]) -> str:
    """Guide-Cards (cp-guide-card) mit collapsible Schritt-für-Schritt-Anleitungen."""
    if not guides:
        return ""
    cards = []
    for gi, guide in enumerate(guides):
        title = html_escape(guide.get("title", ""))
        icon = html_escape(guide.get("icon", "\U0001f4d6"))
        difficulty = html_escape(guide.get("difficulty", ""))
        steps = guide.get("steps", [])
        expanded = "true" if gi == 0 else "false"
        diff_html = (
            f'<span class="cp-guide-card__difficulty">{difficulty}</span>'
            if difficulty
            else ""
        )
        steps_parts = []
        for i, step in enumerate(steps, 1):
            if isinstance(step, str):
                text, code = md(step), ""
            else:
                text = md(step.get("text", ""))
                code = step.get("code", "")
            code_html = ""
            if code:
                esc_code = html_escape(code)
                code_html = (
                    f'<div class="cp-guide-step__code">'
                    f"<code>{esc_code}</code>"
                    f'<button class="cp-guide-step__copy" data-copy="{esc_code}">Kopieren</button>'
                    f"</div>"
                )
            steps_parts.append(
                f'<div class="cp-guide-step">'
                f'<span class="cp-guide-step__number">{i}</span>'
                f"<div>{text}{code_html}</div></div>"
            )
        cards.append(
            f'<div class="cp-guide-card" aria-expanded="{expanded}">'
            f'<button class="cp-guide-card__header" data-guide-toggle>'
            f'<div class="cp-guide-card__title-group">'
            f'<div class="cp-guide-card__icon">{icon}</div>'
            f'<div><div class="cp-guide-card__title">{title}</div>{diff_html}</div></div>'
            f'<span class="cp-guide-card__chevron">\u25bc</span></button>'
            f'<div class="cp-guide-card__steps">{"".join(steps_parts)}</div></div>'
        )
    return f'<div class="cp-guide-cards-grid">{"".join(cards)}</div>'


# ── Presentation-Pattern Generators (Product/Deep Research/Lokal-Guide) ──────


def _verified_badge_html(v: dict) -> str:
    """Verified-Badge mit Shield-Icon und Details."""
    if not v:
        return ""
    links = v.get("links_checked", 0)
    facts = v.get("facts_confirmed", 0)
    unver = v.get("unverifiable", 0)
    ts = v.get("timestamp", "")
    ts_str = f" · {ts}" if ts else ""
    detail = f"{links} Links geprüft · {facts} Fakten bestätigt"
    if unver:
        detail += f" · {unver} nicht prüfbar"
    return (
        '<div class="mf2-verified">'
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>'
        '<polyline points="9 12 11 14 15 10"/></svg>'
        "<strong>Verifiziert</strong>"
        f"<span>{html_escape(detail)}{ts_str}</span>"
        "</div>"
    )


def _verified_footer_html(v: dict) -> str:
    """Verified-Footer am Ende des Reports."""
    if not v:
        return ""
    links = v.get("links_checked", 0)
    facts = v.get("facts_confirmed", 0)
    unver = v.get("unverifiable", 0)
    ts = v.get("timestamp", datetime.now().strftime("%d.%m.%Y, %H:%M"))
    detail = f"{links} Links erreichbar, {facts} Kernaussagen bestätigt"
    if unver:
        detail += f", {unver} Prognosen als nicht prüfbar markiert"
    return (
        '<div class="mf2-vfooter">'
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>'
        '<polyline points="9 12 11 14 15 10"/></svg>'
        f"<strong>Verifikation abgeschlossen</strong> — {html_escape(detail)}. "
        f"Stand: {html_escape(ts)}.</div>"
    )


def _pullquote_html(pq: dict | str) -> str:
    """Pull Quote mit dekorativem Anführungszeichen."""
    if not pq:
        return ""
    if isinstance(pq, str):
        pq = {"text": pq}
    text = pq.get("text", "")
    cite = pq.get("cite", "")
    cite_html = f"<cite>{html_escape(cite)}</cite>" if cite else ""
    return f'<blockquote class="pullquote"><p>{md(text)}</p>{cite_html}</blockquote>'


def _pullquotes_html(items: list) -> str:
    """Mehrere Pull Quotes."""
    if not items:
        return ""
    return "\n".join(_pullquote_html(pq) for pq in items)


def _keyfacts_html(facts: list[dict]) -> str:
    """Key-Fact Callout-Boxen mit großen Zahlen."""
    if not facts:
        return ""
    parts = []
    for f in facts:
        num = html_escape(str(f.get("number", f.get("value", ""))))
        label = html_escape(f.get("label", ""))
        ctx = md(f.get("text", f.get("context", "")))
        label_html = f'<span class="keyfact-label">{label}</span>' if label else ""
        parts.append(
            '<div class="keyfact">'
            f'<span class="keyfact-num">{num}</span>'
            f"{label_html}"
            f'<span class="keyfact-ctx">{ctx}</span></div>'
        )
    return "\n".join(parts)


def _conflict_html(conflict: dict | str) -> str:
    """Widerspruch/Conflict-Box."""
    if not conflict:
        return ""
    if isinstance(conflict, str):
        conflict = {"text": conflict}
    label = conflict.get("title", conflict.get("label", "Widerspruch zwischen Quellen"))
    text = conflict.get("body", conflict.get("text", ""))
    body = rich_text(text)
    return (
        '<div class="conflict-box">'
        '<div class="conflict-head">'
        '<svg class="conflict-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 '
        '0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3z"/><line x1="12" y1="9" x2="12" '
        'y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>'
        f'<span class="conflict-label">{html_escape(label)}</span></div>'
        f'<div class="conflict-body rich-text">{body}</div></div>'
    )


def _conflicts_html(items: list) -> str:
    if not items:
        return ""
    return "\n".join(_conflict_html(c) for c in items)


def _kernaussage_html(text: str) -> str:
    """Key Takeaway / Kernaussage-Box."""
    if not text:
        return ""
    return (
        '<div class="kernaussage">'
        '<div class="kernaussage-head">'
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 '
        '18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>'
        "<span>Kernaussage</span></div>"
        f"<p>{md(text)}</p></div>"
    )


def _insidertip_html(tip: str) -> str:
    """Insider-Tipp Callout-Box."""
    if not tip:
        return ""
    return (
        '<div class="insider-tip">'
        '<svg class="tip-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round"><path d="M15 14c.2-1 .7-1.7 1.5-2.5 '
        "1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 "
        '2.5"/><path d="M9 18h6"/><path d="M10 22h4"/></svg>'
        f"<p>{md(tip)}</p></div>"
    )


def _route_banner_html(route: dict) -> str:
    """Route-Banner mit Maps-Link für Lokal-Guide."""
    if not route:
        return ""
    stops = route.get("stops", [])
    title = route.get("title", "Empfohlene Route")
    maps_url = route.get("maps_url", "")
    # Auto-generate Maps URL if not provided
    if not maps_url and stops:
        from urllib.parse import quote

        parts = "/".join(quote(s) for s in stops)
        maps_url = f"https://www.google.com/maps/dir/{parts}"

    stop_nums = ""
    for i, s in enumerate(stops):
        num = f'<span class="route-stop-num">{i + 1}</span>'
        stop_nums += f'<span class="route-stop">{num} {html_escape(s)}</span>'
        if i < len(stops) - 1:
            stop_nums += '<span class="route-arrow">›</span>'

    return (
        '<div class="route-banner">'
        f"<h3>{html_escape(title)}</h3>"
        f'<div class="route-stops">{stop_nums}</div>'
        f'<a class="route-btn" href="{html_escape(maps_url)}" target="_blank" rel="noopener">'
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round"><polygon points="3 11 22 2 13 21 11 13 3 11"/></svg>'
        "Route in Maps öffnen</a></div>"
    )


def _locations_html(locs: list[dict]) -> str:
    """Location/Action Cards für Lokal-Guide."""
    if not locs:
        return ""
    cards = []
    for i, loc in enumerate(locs):
        name = html_escape(loc.get("name", ""))
        address = html_escape(loc.get("address", ""))
        rating = loc.get("rating", "")
        reviews = loc.get("reviews", "")
        price = html_escape(loc.get("price", ""))
        verdict = md(loc.get("verdict", ""))
        featured = "featured" if loc.get("featured") else ""
        plan_b = "plan-b" if loc.get("plan_b") else ""
        css_cls = f"location-card {featured} {plan_b}".strip()

        # Badges
        badges_html = ""
        for b in loc.get("badges", []):
            color = b.get("color", "muted")
            badges_html += f'<span class="badge badge-{color}">{html_escape(b.get("text", ""))}</span>'

        # Rating
        rating_html = ""
        if rating:
            stars = "★" * int(float(str(rating).replace(",", ".")))
            rev = f" · {reviews}" if reviews else ""
            rating_html = (
                f'<span class="badge badge-accent">{stars} {rating}{rev}</span>'
            )

        # Mood/Atmosphere tags
        mood_html = ""
        moods = loc.get("mood", [])
        if moods:
            tags = "".join(
                f'<span class="mood-tag">{html_escape(m)}</span>' for m in moods
            )
            mood_html = f'<div class="mood-tags">{tags}</div>'

        # Action buttons
        actions = ""
        maps_url = loc.get("maps_url", "")
        phone = loc.get("phone", "")
        web = loc.get("website", loc.get("web", ""))
        if maps_url:
            actions += (
                f'<a class="action-btn action-maps" href="{html_escape(maps_url)}" '
                f'target="_blank" rel="noopener">'
                '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
                '<path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/>'
                '<circle cx="12" cy="10" r="3"/></svg>Route</a>'
            )
        if phone:
            actions += (
                f'<a class="action-btn action-call" href="tel:{html_escape(phone)}">'
                '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
                '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 '
                "19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 "
                "2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 "
                "16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 "
                '2 0 0 1 22 16.92z"/></svg>Anrufen</a>'
            )
        if web:
            actions += (
                f'<a class="action-btn action-web" href="{html_escape(web)}" '
                'target="_blank" rel="noopener">'
                '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
                '<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/>'
                '<path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 '
                '0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>Web</a>'
            )
        actions_html = f'<div class="action-btns">{actions}</div>' if actions else ""

        # Hours
        hours = loc.get("hours", "")
        hours_html = ""
        if hours:
            hours_html = (
                '<span class="info-item">'
                '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
                '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>'
                f"</svg>{html_escape(hours)}</span>"
            )

        num_cls = "alt" if loc.get("plan_b") else ""
        cards.append(
            f'<div class="{css_cls}">'
            f'<div class="loc-top"><span class="loc-num {num_cls}">{i + 1}</span>'
            f'<div class="loc-info"><div class="loc-name">{name}</div>'
            f'<div class="loc-addr">{address}</div></div></div>'
            f'<div class="loc-badges">{rating_html}{badges_html}'
            + (f'<span class="badge badge-muted">{price}</span>' if price else "")
            + f"</div>{mood_html}"
            f'<div class="loc-verdict">{verdict}</div>'
            + (f'<div class="loc-info-row">{hours_html}</div>' if hours_html else "")
            + f"{actions_html}</div>"
        )
    return "\n".join(cards)


def _quickcompare_html(items: list[dict]) -> str:
    """Quick-Compare horizontal Strip."""
    if not items:
        return ""
    cards = []
    for item in items:
        rank = html_escape(item.get("rank", ""))
        name = html_escape(item.get("name", ""))
        rating = item.get("rating", "")
        price = html_escape(item.get("price", ""))
        top = " top" if item.get("top") else ""
        rating_html = f'<span class="qc-star">★</span> {rating}' if rating else ""
        cards.append(
            f'<div class="qc-item{top}">'
            f'<div class="qc-rank">{rank}</div>'
            f'<div class="qc-name">{name}</div>'
            f'<div class="qc-meta">{rating_html}'
            f"{f' <span class=qc-price>{price}</span>' if price else ''}"
            "</div></div>"
        )
    return f'<div class="quick-compare">{"".join(cards)}</div>'


def _callout_enhanced_html(callouts: list[dict]) -> str:
    """Enhanced callout boxes with SVG icons and semantic variants.

    Each callout: {"type": "info|success|warning|error|tip", "title": "...", "text": "..."}
    """
    if not callouts:
        return ""
    icons = {
        "info": (
            '<svg class="callout-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/>'
            '<line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>'
        ),
        "success": (
            '<svg class="callout-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="2" stroke-linecap="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>'
            '<polyline points="22 4 12 14.01 9 11.01"/></svg>'
        ),
        "warning": (
            '<svg class="callout-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="2" stroke-linecap="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 '
            '0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3z"/><line x1="12" y1="9" x2="12" '
            'y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>'
        ),
        "error": (
            '<svg class="callout-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/>'
            '<line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>'
        ),
        "tip": (
            '<svg class="callout-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="2" stroke-linecap="round"><path d="M15 14c.2-1 .7-1.7 1.5-2.5 '
            "1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 "
            '2.5"/><path d="M9 18h6"/><path d="M10 22h4"/></svg>'
        ),
    }
    parts = []
    for co in callouts:
        ctype = co.get("type", "info")
        title = html_escape(co.get("title", ctype.title()))
        text = md(co.get("text", ""))
        icon = icons.get(ctype, icons["info"])
        parts.append(
            f'<div class="callout-enhanced callout-{ctype}">'
            f"{icon}"
            f'<div class="callout-content">'
            f'<div class="callout-title">{title}</div>'
            f'<div class="callout-text">{text}</div>'
            f"</div></div>"
        )
    return "\n".join(parts)


def _key_insights_html(insights: list[dict]) -> str:
    """Key insight highlight blocks.

    Each insight: {"label": "Key Insight", "text": "..."}
    """
    if not insights:
        return ""
    parts = []
    for ins in insights:
        label = html_escape(ins.get("label", "Key Insight"))
        text = md(ins.get("text", ""))
        parts.append(
            '<div class="key-insight">'
            '<svg class="key-insight-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="2" stroke-linecap="round">'
            '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 '
            '5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>'
            f'<div class="key-insight-label">{label}</div>'
            f'<div class="key-insight-text">{text}</div>'
            "</div>"
        )
    return "\n".join(parts)


def _progress_bars_html(bars: list[dict]) -> str:
    """Progress indicator bars.

    Each bar: {"label": "RAM", "value": 87, "max": 100, "display": "14.2 / 16 GB"}
    """
    if not bars:
        return ""
    parts = []
    for bar in bars:
        label = html_escape(bar.get("label", ""))
        value = bar.get("value", 0)
        max_val = bar.get("max", 100)
        pct = min(100, int((value / max_val) * 100)) if max_val else 0
        display = html_escape(bar.get("display", f"{pct}%"))
        cls = (
            "progress-ok"
            if pct < 60
            else "progress-warn"
            if pct < 85
            else "progress-crit"
        )
        parts.append(
            '<div class="progress-group">'
            '<div class="progress-header">'
            f'<span class="progress-label">{label}</span>'
            f'<span class="progress-value">{display}</span></div>'
            '<div class="progress-track">'
            f'<div class="progress-fill {cls}" style="width:{pct}%"></div>'
            "</div></div>"
        )
    return "\n".join(parts)


def _svg_bar_chart_html(bars: list[dict], title: str = "") -> str:
    """SVG-based horizontal bar chart.

    Each bar: {"label": "...", "value": 85, "display": "85%", "color": "accent"}
    """
    if not bars:
        return ""
    max_val = max((b.get("value", 0) for b in bars), default=1) or 1
    bar_h = 24
    gap = 8
    label_w = 120
    value_w = 60
    chart_x = label_w + 10
    chart_w = 400
    total_w = chart_x + chart_w + value_w + 10
    total_h = len(bars) * (bar_h + gap) + gap

    color_map = {
        "accent": "var(--accent)",
        "green": "var(--green)",
        "yellow": "var(--yellow)",
        "red": "var(--red)",
    }

    elements = []
    for i, bar in enumerate(bars):
        y = i * (bar_h + gap) + gap
        label = html_escape(bar.get("label", ""))
        value = bar.get("value", 0)
        display = html_escape(bar.get("display", str(value)))
        color = color_map.get(bar.get("color", "accent"), "var(--accent)")
        pct_w = max(2, (value / max_val) * chart_w)

        # Background bar
        elements.append(
            f'<rect class="bar-bg" x="{chart_x}" y="{y}" '
            f'width="{chart_w}" height="{bar_h}" />'
        )
        # Foreground bar
        elements.append(
            f'<rect class="bar-fg" x="{chart_x}" y="{y}" '
            f'width="{pct_w:.0f}" height="{bar_h}" fill="{color}" />'
        )
        # Label
        elements.append(
            f'<text class="bar-text-label" x="{label_w}" y="{y + bar_h / 2 + 4}" '
            f'text-anchor="end">{label}</text>'
        )
        # Value
        elements.append(
            f'<text class="bar-text-value" x="{chart_x + chart_w + 8}" '
            f'y="{y + bar_h / 2 + 4}">{display}</text>'
        )

    title_html = f"<h4>{html_escape(title)}</h4>" if title else ""
    return (
        f'<div class="svg-bar-chart">{title_html}'
        f'<svg viewBox="0 0 {total_w} {total_h}" '
        f'preserveAspectRatio="xMidYMid meet">'
        f"{''.join(elements)}</svg></div>"
    )


def _source_bars_html(sources: list[dict]) -> str:
    """Source Quality Bars (animierte horizontale Balken)."""
    if not sources:
        return ""
    rows = []
    for s in sources:
        title = html_escape(s.get("title", ""))
        q = s.get("quality", 5)
        pct = min(100, int(q * 10))
        cls = "high" if q >= 8 else "mid"
        rows.append(
            f'<div class="src-bar-row">'
            f"<span>{title}</span>"
            f'<div class="src-bar"><div class="src-fill" style="width:{pct}%"></div></div>'
            f'<span class="src-score {cls}">{q}/10</span></div>'
        )
    return (
        '<div class="source-bars">'
        "<h4>Quellen-Qualität</h4>" + "\n".join(rows) + "</div>"
    )


def _confidence_gauge_html(gauge: dict) -> str:
    """SVG Confidence Gauge (halbkreisförmig)."""
    if not gauge:
        return ""
    value = gauge.get("value", 0)
    label = html_escape(gauge.get("label", "Konfidenz"))
    display = html_escape(gauge.get("display", f"{value}%"))
    # SVG arc: half-circle, 0-100 mapped to stroke-dasharray
    arc_len = 157  # approximate half-circle circumference for r=50
    fill_len = int(arc_len * min(100, max(0, value)) / 100)
    color = (
        "var(--green)"
        if value >= 70
        else "var(--yellow)"
        if value >= 40
        else "var(--red)"
    )
    return (
        '<div class="confidence-gauge-wrap">'
        '<svg class="confidence-gauge" viewBox="0 0 120 70">'
        f'<path class="cg-track" d="M 10 65 A 50 50 0 0 1 110 65"/>'
        f'<path class="cg-fill" d="M 10 65 A 50 50 0 0 1 110 65" '
        f'stroke="{color}" stroke-dasharray="{fill_len} {arc_len}"/>'
        f'<text x="60" y="58" text-anchor="middle" '
        f'font-family="var(--font-display)" font-size="18" fill="var(--text)">'
        f"{display}</text>"
        "</svg>"
        f'<span class="cg-label">{label}</span></div>'
    )


# ── IKEA Hero (Standard-Begrüßung) ───────────────────────────────────────────

_ARCHETYPE_EYEBROW = {
    "market": "Marktanalyse",
    "deep-research": "Analyse",
    "deep-research-v2": "Deep Research",
    "head-to-head": "Vergleich",
    "multi-compare": "Vergleich",
    "briefing": "Briefing",
    "narrative": "Bericht",
    "how-to": "Anleitung",
    "exploration": "Recherche",
    "lokal-guide": "Lokal-Guide",
}


def _hero_eyebrow_html(data: dict) -> str:
    """Eyebrow-Label über der Headline (Archetyp oder explizit)."""
    hero = data.get("hero", {})
    eyebrow = hero.get("eyebrow", "") if isinstance(hero, dict) else ""
    if not eyebrow:
        # Auto-generate from archetype
        fp = fingerprint_data(data)
        arch = select_archetype(data, fp)
        eyebrow = _ARCHETYPE_EYEBROW.get(arch, "Report")
    return f'<div class="hero-eyebrow">{html_escape(eyebrow)}</div>'


def _hero_strip_html(data: dict) -> str:
    """IKEA-style Summary Strip — Mini-Stat-Cards unter dem Subtitle."""
    hero = data.get("hero", {})
    stats = hero.get("stats", []) if isinstance(hero, dict) else []
    if not stats:
        # Auto-generate from KPIs (value/label pairs)
        kpis = data.get("kpis", [])
        if kpis:
            stats = [
                {"value": k.get("value", ""), "label": k.get("label", "")}
                for k in kpis[:4]
            ]
        else:
            # Fallback: generate from data structure
            sources = data.get("sources", [])
            sections = data.get("sections", [])
            locations = data.get("locations", [])
            if sources:
                stats.append({"value": str(len(sources)), "label": "Quellen"})
            if sections:
                stats.append({"value": str(len(sections)), "label": "Abschnitte"})
            if locations:
                stats.append({"value": str(len(locations)), "label": "Orte"})
    if not stats:
        return ""
    cards = []
    for stat in stats:
        val = str(stat.get("value", "")).strip()
        if not val:
            continue  # Skip stats with empty values
        label = html_escape(str(stat.get("label", "")))
        cards.append(
            f'<div class="hero-stat">'
            f'<div class="hero-stat-value">{html_escape(val)}</div>'
            f'<div class="hero-stat-label">{label}</div></div>'
        )
    if not cards:
        return ""
    return f'<div class="hero-strip">{"".join(cards)}</div>'


# ── Template-spezifische Renderer ────────────────────────────────────────────


def _common_blocks(data: dict, default_title: str = "Report") -> dict:
    """Shared block mappings used by all renderers."""
    hero_strip = _hero_strip_html(data)
    # Avoid KPI duplication: if hero-strip already rendered KPIs
    # (no explicit hero.stats but kpis[] present), skip stat-cards
    hero = data.get("hero", {})
    hero_has_explicit_stats = bool(
        hero.get("stats", []) if isinstance(hero, dict) else []
    )
    kpis = data.get("kpis", [])
    skip_stat_cards = bool(hero_strip) and not hero_has_explicit_stats and bool(kpis)
    return {
        "TITLE": html_escape(data.get("title", default_title)),
        "SUBTITLE": html_escape(
            data.get("subtitle", datetime.now().strftime("%d.%m.%Y"))
        ),
        "HERO_EYEBROW": _hero_eyebrow_html(data),
        "HERO_STRIP": hero_strip,
        "HIGHLIGHTS": _highlights_html(data.get("highlights", [])),
        "KPI_CARDS": "" if skip_stat_cards else _stat_cards_html(kpis),
        "SECTIONS": _sections_html(data.get("sections", [])),
        "SOURCES": _sources_html(data.get("sources", [])),
        "AGENT_ANALYSIS": _agent_block_html(data.get("agent", "")),
        "TABLE": _table_html(data.get("table", {})),
        "BARS": _bars_html(data.get("bars", [])),
        "METRICS": _metrics_footer_html(data.get("metrics", {})),
        "RADAR": _radar_chart_html(data.get("radar", {})),
        "DONUT": _donut_chart_html(data.get("distribution", {})),
        "TIMELINE": _timeline_html(data.get("timeline", [])),
        "FEATURE_MATRIX": _feature_matrix_html(data.get("matrix", {})),
        "TAG_CLOUD": _tag_cloud_html(data.get("tags", [])),
        "GAUGE": _gauge_html(data.get("gauge", {})),
        "CTA": _cta_block_html(data.get("cta", [])),
        "PRICE_CARDS": _price_cards_html(data.get("price_cards", [])),
        "GUIDES": _guides_html(data.get("guides", [])),
        "CALLOUTS": _callout_enhanced_html(data.get("callouts", [])),
        "KEY_INSIGHTS": _key_insights_html(data.get("key_insights", [])),
        "PROGRESS": _progress_bars_html(data.get("progress", [])),
        "SVG_BARS": _svg_bar_chart_html(
            data.get("svg_bars", []), data.get("svg_bars_title", "")
        ),
    }


def render_research(data: dict) -> dict:
    """Research/Analyse-Report."""
    return _common_blocks(data, "Research Report")


def render_comparison(data: dict) -> dict:
    """Vergleichs-Report (X vs Y)."""
    options = data.get("options", [])
    cols = []
    for opt in options:
        name = html_escape(opt.get("name", ""))
        pros = "".join(f'<li class="pro">{md(p)}</li>' for p in opt.get("pros", []))
        cons = "".join(f'<li class="con">{md(c)}</li>' for c in opt.get("cons", []))
        specs_html = ""
        specs = opt.get("specs", {})
        if specs:
            rows = "".join(
                f"<tr><td>{html_escape(k)}</td><td>{md(str(v))}</td></tr>"
                for k, v in specs.items()
            )
            specs_html = (
                f'<table class="data-table specs-table"><tbody>{rows}</tbody></table>'
            )
        cols.append(
            f'<div class="compare-col"><h3>{name}</h3>'
            f'<div class="pros-cons">'
            f'<ul class="pros-list">{pros}</ul>'
            f'<ul class="cons-list">{cons}</ul></div>'
            f"{specs_html}</div>"
        )

    verdict = data.get("verdict", "")
    blocks = _common_blocks(data, "Vergleich")
    blocks["COMPARE_GRID"] = f'<div class="compare-grid">{"".join(cols)}</div>'
    blocks["VERDICT"] = _agent_block_html(verdict) if verdict else ""
    return blocks


def render_dashboard(data: dict) -> dict:
    """Dashboard/KPI-Report."""
    return _common_blocks(data, "Dashboard")


def render_guide(data: dict) -> dict:
    """How-To/Guide-Report."""
    steps = data.get("steps", [])
    steps_html = []
    for i, step in enumerate(steps, 1):
        title = html_escape(step.get("title", f"Schritt {i}"))
        body = rich_text(step.get("body", ""))
        code = step.get("code", "")
        code_html = _copyable_html(code, "Code kopieren") if code else ""
        warn = step.get("warning", "")
        warn_html = (
            f'<div class="callout callout-warn">{md(warn)}</div>' if warn else ""
        )
        tip = step.get("tip", "")
        tip_html = f'<div class="callout callout-tip">{md(tip)}</div>' if tip else ""
        steps_html.append(
            f'<div class="guide-step">'
            f'<div class="step-num">{i}</div>'
            f"<div><h3>{title}</h3>"
            f'<div class="step-body rich-text">{body}</div>'
            f"{code_html}{warn_html}{tip_html}</div></div>"
        )

    prereqs = data.get("prerequisites", [])
    prereqs_html = ""
    if prereqs:
        items = "".join(f"<li>{md(p)}</li>" for p in prereqs)
        prereqs_html = (
            f'<div class="prereqs"><h2>Voraussetzungen</h2><ul>{items}</ul></div>'
        )

    blocks = _common_blocks(data, "Anleitung")
    blocks["PREREQUISITES"] = prereqs_html
    blocks["STEPS"] = "".join(steps_html)
    return blocks


def render_generic(data: dict) -> dict:
    """Generischer Fallback-Report."""
    return _common_blocks(data, "Report")


def render_deep_research_v2(data: dict) -> dict:
    """Deep Research v2 — mit Verified-Badge, Pull Quotes, Key-Facts, Confidence Gauge."""
    blocks = _common_blocks(data, "Research Report")
    blocks["VERIFIED_BADGE"] = _verified_badge_html(data.get("verified", {}))
    blocks["VERIFIED_FOOTER"] = _verified_footer_html(data.get("verified", {}))
    blocks["CONFIDENCE_GAUGE"] = _confidence_gauge_html(
        data.get("confidence_gauge", {})
    )
    blocks["PULLQUOTES"] = _pullquotes_html(data.get("pullquotes", []))
    blocks["KEYFACTS"] = _keyfacts_html(data.get("keyfacts", []))
    blocks["CONFLICTS"] = _conflicts_html(data.get("conflicts", []))
    blocks["KERNAUSSAGE"] = _kernaussage_html(data.get("kernaussage", ""))
    blocks["SOURCE_BARS"] = _source_bars_html(data.get("source_bars", []))
    return blocks


def render_lokal_guide(data: dict) -> dict:
    """Lokal-Guide — Action Cards, Route Banner, Quick-Compare."""
    blocks = _common_blocks(data, "Lokal-Guide")
    blocks["QUICKCOMPARE"] = _quickcompare_html(data.get("quickcompare", []))
    blocks["ROUTE_BANNER"] = _route_banner_html(data.get("route", {}))
    blocks["LOCATIONS"] = _locations_html(data.get("locations", []))
    blocks["INSIDER_TIP"] = _insidertip_html(data.get("insider_tip", ""))
    blocks["SOURCE_BARS"] = _source_bars_html(data.get("source_bars", []))
    blocks["VERIFIED_FOOTER"] = _verified_footer_html(data.get("verified", {}))
    return blocks


RENDERERS = {
    "research": render_research,
    "comparison": render_comparison,
    "dashboard": render_dashboard,
    "guide": render_guide,
    "generic": render_generic,
    "deep-research-v2": render_deep_research_v2,
    "lokal-guide": render_lokal_guide,
}


# ── JSON Schema Definitions ─────────────────────────────────────────────────

SCHEMAS = {
    "research": """{
  "type": "research",
  "title": "Titel des Reports",
  "subtitle": "Untertitel oder Datum",
  "highlights": ["Key Finding 1", "Key Finding 2", "Key Finding 3"],
  "kpis": [{"label": "Quellen", "value": "25", "note": "optional"}],
  "sections": [
    {
      "title": "Abschnitt-Titel",
      "body": "Fließtext mit **Markdown**",
      "items": ["Bullet 1", "Bullet 2"],
      "collapsed": false,
      "confidence": "high|medium|inferred (optional)"
    }
  ],
  "sources": [
    {"title": "Quelle", "url": "https://...", "quality": 8, "domain_tier": "high"}
  ],
  "agent": "Agent-Analyse Freitext",
  "table": {"headers": ["Spalte1", "Spalte2"], "rows": [["Wert1", "Wert2"]]},
  "bars": [{"label": "Item", "value": 85, "display": "85%"}],
  "metrics": {"Zeit": "45s", "Quellen": "25 URLs"}
}""",
    "comparison": """{
  "type": "comparison",
  "title": "Option A vs Option B",
  "subtitle": "Vergleichsanalyse",
  "highlights": ["Key Insight 1", "Key Insight 2"],
  "options": [
    {
      "name": "Option A",
      "pros": ["Vorteil 1", "Vorteil 2"],
      "cons": ["Nachteil 1"],
      "specs": {"Preis": "99€", "Performance": "Hoch"}
    }
  ],
  "verdict": "Empfehlung als Freitext",
  "sources": [{"title": "Quelle", "url": "https://...", "quality": 8}],
  "metrics": {"Quellen": "10"}
}""",
    "dashboard": """{
  "type": "dashboard",
  "title": "Dashboard-Titel",
  "subtitle": "Stand: 01.03.2026",
  "highlights": ["KPI 1 gestiegen", "KPI 2 stabil"],
  "kpis": [
    {"label": "Metrik", "value": "1.234", "note": "+5% vs. Vormonat"}
  ],
  "bars": [{"label": "Kategorie", "value": 75, "display": "75%"}],
  "table": {"headers": ["Name", "Wert"], "rows": [["Item", "123"]]},
  "agent": "Zusammenfassung der Trends",
  "metrics": {"Aktualisiert": "01.03.2026"}
}""",
    "guide": """{
  "type": "guide",
  "title": "Anleitung: XY einrichten",
  "subtitle": "Schritt-für-Schritt",
  "prerequisites": ["Python 3.13", "sudo-Rechte"],
  "steps": [
    {
      "title": "Paket installieren",
      "body": "Erklärender Text",
      "code": "pip install package",
      "warning": "Optionale Warnung",
      "tip": "Optionaler Tipp"
    }
  ],
  "sources": [{"title": "Docs", "url": "https://..."}],
  "metrics": {"Dauer": "~5 min"}
}""",
    "generic": """{
  "type": "generic",
  "title": "Report-Titel",
  "subtitle": "Untertitel",
  "highlights": ["Punkt 1", "Punkt 2"],
  "kpis": [{"label": "Metrik", "value": "42"}],
  "sections": [{"title": "Abschnitt", "body": "Inhalt", "items": ["Item"]}],
  "table": {"headers": ["A", "B"], "rows": [["1", "2"]]},
  "bars": [{"label": "X", "value": 50}],
  "agent": "Analyse-Text",
  "sources": [{"title": "Quelle", "url": "https://..."}],
  "metrics": {"Key": "Value"}
}""",
    "adaptive": """{
  "title": "Adaptiver Report-Titel",
  "subtitle": "Untertitel",
  "hero": {"eyebrow": "REPORT-TYP (optional, auto-generiert)", "chips": ["Chip 1", "Chip 2 (optional, auto-generiert aus KPIs)"]},
  "highlights": ["Key Finding 1", "Key Finding 2"],
  "kpis": [
    {"label": "Metrik", "value": "42", "note": "optional", "delta": "+5%", "trend": "up"}
  ],
  "sections": [
    {"title": "Abschnitt", "body": "**Markdown**", "items": ["Bullet"],
     "collapsed": false, "confidence": "high|medium|inferred",
     "level": "part", "badge": "Status", "callout": "warn|tip"}
  ],
  "options": [
    {"name": "Option A", "pros": ["Pro"], "cons": ["Con"], "specs": {"Key": "Value"}}
  ],
  "radar": {
    "axes": ["Dim1", "Dim2", "Dim3"],
    "datasets": [{"label": "Set A", "values": [80, 60, 90]}]
  },
  "distribution": {
    "labels": ["Kat1", "Kat2"], "values": [60, 40], "center": "100%"
  },
  "timeline": [
    {"date": "2026-01", "event": "Titel", "detail": "Beschreibung"}
  ],
  "matrix": {
    "options": ["Opt A", "Opt B"],
    "features": [{"name": "Feature", "values": [true, false]}]
  },
  "tags": [{"label": "Tag", "weight": 3}, "einfacher-tag"],
  "gauge": {"value": 75, "max": 100, "label": "Score", "display": "75%"},
  "bars": [{"label": "Item", "value": 85, "display": "85%"}],
  "table": {"headers": ["A", "B"], "rows": [["1", "2"]], "sortable": true},
  "cta": [{"label": "Aktion", "url": "https://..."}],
  "sources": [
    {"title": "Quelle", "url": "https://...", "quality": 8, "domain_tier": "high"}
  ],
  "agent": "Agent-Analyse Freitext",
  "verdict": "Empfehlung (bei Vergleichen)",
  "metrics": {"Key": "Value"},
  "steps": [{"title": "Schritt", "body": "Text", "code": "cmd"}],
  "prerequisites": ["Voraussetzung 1"],
  "callouts": [
    {"type": "info|success|warning|error|tip", "title": "Hinweis", "text": "Callout-Text"}
  ],
  "key_insights": [
    {"label": "Key Insight", "text": "Zentrale Erkenntnis hervorgehoben"}
  ],
  "progress": [
    {"label": "RAM", "value": 87, "max": 100, "display": "14.2 / 16 GB"}
  ],
  "svg_bars": [
    {"label": "Kategorie", "value": 85, "display": "85%", "color": "accent|green|yellow|red"}
  ],
  "svg_bars_title": "Titel des SVG-Balkendiagramms"
}""",
    "deep-research-v2": """{
  "type": "deep-research-v2",
  "title": "Deep Research Titel",
  "subtitle": "Analyse vom 14.03.2026",
  "verified": {
    "links_checked": 8,
    "facts_confirmed": 5,
    "unverifiable": 1,
    "timestamp": "14.03.2026, 15:30"
  },
  "highlights": ["Kernfinding 1", "Kernfinding 2", "Kernfinding 3"],
  "kpis": [{"label": "Quellen", "value": "25", "note": "davon 8 verifiziert"}],
  "confidence_gauge": {"value": 82, "label": "Gesamt-Konfidenz", "display": "82%"},
  "pullquotes": [
    {"text": "Zitat aus einer Quelle", "cite": "Quellenname, 2026"}
  ],
  "keyfacts": [
    {"number": "42%", "label": "Marktanteil", "text": "Beschreibung des Key-Facts"}
  ],
  "conflicts": [
    {"title": "Widerspruch", "body": "Quelle A sagt X, Quelle B sagt Y"}
  ],
  "kernaussage": "Die zentrale Erkenntnis in einem Satz.",
  "sections": [
    {
      "title": "Abschnitt",
      "body": "Fließtext mit **Markdown**",
      "items": ["Bullet 1"],
      "confidence": "high"
    }
  ],
  "source_bars": [
    {"title": "heise.de", "quality": 9},
    {"title": "reddit.com", "quality": 5}
  ],
  "sources": [{"title": "Quelle", "url": "https://...", "quality": 8}],
  "metrics": {"Zeit": "45s", "Quellen": "25 URLs"}
}""",
    "lokal-guide": """{
  "type": "lokal-guide",
  "title": "Lokal-Guide: Stadtteil XY",
  "subtitle": "Stand: 14.03.2026",
  "highlights": ["Top-Empfehlung: Name", "Beste Preis-Leistung: Name"],
  "quickcompare": [
    {"rank": "#1", "name": "Ort A", "rating": "4.9", "price": "ab 50€", "top": true},
    {"rank": "#2", "name": "Ort B", "rating": "4.7", "price": "ab 35€"}
  ],
  "route": {
    "title": "Empfohlene Route",
    "stops": ["Ort A, Stadt", "Ort B, Stadt", "Ort C, Stadt"]
  },
  "locations": [
    {
      "name": "Ort A",
      "address": "Musterstr. 1, 64297 Stadt",
      "rating": "4.9",
      "reviews": "127 Bewertungen",
      "price": "ab 50€",
      "verdict": "**Klare Empfehlung.** Begründung in 1-2 Sätzen.",
      "featured": true,
      "badges": [{"text": "Top-Bewertung", "color": "green"}],
      "mood": ["Modern", "Familienfreundlich"],
      "maps_url": "https://maps.google.com/?q=...",
      "phone": "+496151123456",
      "website": "https://example.com",
      "hours": "Mo-Fr 9-18 Uhr"
    }
  ],
  "insider_tip": "Insider-Tipp als Freitext.",
  "sources": [{"title": "Google Maps", "url": "https://..."}],
  "metrics": {"Orte geprüft": "8", "Quellen": "12"}
}""",
}


# ── Progressive JS Enhancement ───────────────────────────────────────────────

JS_DIR = TEMPLATES_DIR / "js"


def _load_js_modules(data: dict, fp: dict) -> str:
    """Phase 4: Progressive Enhancement — JS-Module laden wenn nötig."""
    modules = []

    # Theme toggle: immer laden (Dark/Light Mode)
    js_file = JS_DIR / "theme-toggle.js"
    if js_file.exists():
        modules.append(js_file.read_text())

    # Sortable: tables with >5 rows
    table = data.get("table", {})
    if len(table.get("rows", [])) > 5 or len(data.get("sources", [])) > 5:
        js_file = JS_DIR / "sortable.js"
        if js_file.exists():
            modules.append(js_file.read_text())

    # Scroll-reveal: Deep Research v2 / Lokal-Guide
    if fp.get("has_verified") or fp.get("has_pullquotes") or fp.get("has_locations"):
        js_file = JS_DIR / "scroll-reveal.js"
        if js_file.exists():
            modules.append(js_file.read_text())

    # Scroll-nav: >3 sections
    if fp["section_count"] > 3:
        js_file = JS_DIR / "scroll-nav.js"
        if js_file.exists():
            modules.append(js_file.read_text())

    # Tooltips + chart interaction: if charts present
    if fp["has_radar"] or fp["has_distribution"] or fp["has_gauge"]:
        for name in ("tooltips.js", "chart-interact.js"):
            js_file = JS_DIR / name
            if js_file.exists():
                modules.append(js_file.read_text())

    # TOC: many sections — collapsible TOC + sticky sidebar
    if fp["section_count"] > 5:
        js_file = JS_DIR / "toc.js"
        if js_file.exists():
            modules.append(js_file.read_text())
        js_file = JS_DIR / "sticky-toc.js"
        if js_file.exists():
            modules.append(js_file.read_text())

    # Filterable: if table has data-filterable attribute (set by renderer)
    js_file = JS_DIR / "filterable.js"
    if js_file.exists() and table.get("filterable"):
        modules.append(js_file.read_text())

    # Content interactions: citations, guide cards, click-to-copy
    has_citations = any("[Q" in s.get("body", "") for s in data.get("sections", []))
    has_guides = bool(data.get("guides"))
    has_trust_sources = any(s.get("trust_level") for s in data.get("sources", []))
    if has_citations or has_guides or has_trust_sources:
        js_file = JS_DIR / "content-interactions.js"
        if js_file.exists():
            modules.append(js_file.read_text())

    if not modules:
        return ""
    return "<script>\n" + "\n".join(modules) + "\n</script>"


# ── Auto-Visual-Enrichment ──────────────────────────────────────────────────


def _is_text_heavy(data: dict) -> bool:
    """True wenn Report nur Fließtext-Sections hat, ohne visuelle Komponenten."""
    if not data.get("sections"):
        return False
    visual_keys = (
        "highlights",
        "kpis",
        "callouts",
        "key_insights",
        "bars",
        "table",
        "radar",
        "distribution",
        "gauge",
        "progress",
        "svg_bars",
        "keyfacts",
        "pullquotes",
        "options",
        "steps",
        "locations",
        "quickcompare",
    )
    return not any(data.get(k) for k in visual_keys)


def _extract_first_sentence(text: str) -> str:
    """Ersten Satz extrahieren (max 180 Zeichen)."""
    if not text:
        return ""
    # Strip markdown/inline formatting and markers for clean extraction
    clean = re.sub(r"\[Q\d+\]", "", text)
    clean = re.sub(r"\[Eigene (?:Einschätzung|Inferenz)\]\s*", "", clean)
    clean = re.sub(r"\*\*(.+?)\*\*", r"\1", clean)
    clean = re.sub(r"\*(.+?)\*", r"\1", clean)
    clean = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", clean)
    # Split on sentence boundaries
    parts = re.split(r"(?<=[.!?])\s+", clean.strip(), maxsplit=1)
    first = parts[0].strip() if parts else ""
    if len(first) > 180:
        first = first[:177].rsplit(" ", 1)[0] + "..."
    return first


def _extract_bullets_from_body(body: str) -> tuple[str, list[str]]:
    """Bullet-Listen aus Body extrahieren → (remaining_body, items)."""
    lines = body.split("\n")
    items = []
    remaining = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            items.append(stripped[2:].strip())
        else:
            remaining.append(line)
    if len(items) >= 2:
        return "\n".join(remaining).strip(), items
    return body, []


def auto_enrich(data: dict) -> dict:
    """Auto-enrich text-heavy reports mit visuellen Elementen.

    Wird nur aktiv wenn der Report ausschließlich Fließtext-Sections enthält.
    Opt-out: "auto_enrich": false im JSON.
    """
    if data.get("auto_enrich") is False:
        return data
    if not _is_text_heavy(data):
        return data

    sections = data.get("sections", [])

    # 1. Auto-Items: Bullet-Listen aus Body extrahieren (VOR Highlights!)
    for sec in sections:
        if sec.get("items"):
            continue
        body = sec.get("body", "")
        remaining, items = _extract_bullets_from_body(body)
        if items:
            sec["items"] = items
            sec["body"] = remaining

    # 2. Auto-Highlights: Ersten Satz aus jeder Section (max 4)
    #    Nutzt den bereits bereinigten Body (ohne Bullets)
    highlights = []
    for sec in sections[:6]:
        sent = _extract_first_sentence(sec.get("body", ""))
        if sent and len(sent) > 20:
            highlights.append(sent)
    if highlights:
        data["highlights"] = highlights[:4]

    # 3. Auto-KPIs aus Struktur
    kpis = []
    sources = data.get("sources", [])
    if sources:
        qualities = [s.get("quality", 0) for s in sources if s.get("quality")]
        kpis.append({"label": "Quellen", "value": str(len(sources))})
        if qualities:
            avg_q = sum(qualities) / len(qualities)
            kpis.append({"label": "Ø Qualität", "value": f"{avg_q:.1f}/10"})
    kpis.append({"label": "Abschnitte", "value": str(len(sections))})
    if kpis:
        data["kpis"] = kpis

    # 4. Auto-Callouts: [Eigene Einschätzung] / Warnungen erkennen
    callouts = []
    for sec in sections:
        body = sec.get("body", "")
        # Eigene Einschätzung → Info-Callout + Marker aus Body entfernen
        for marker in ("[Eigene Einschätzung]", "[Eigene Inferenz]"):
            if marker in body:
                for sent in re.split(r"(?<=[.!?])\s+", body):
                    if marker in sent:
                        clean = sent.replace(marker, "").strip()
                        if clean:
                            callouts.append(
                                {
                                    "type": "info",
                                    "title": "Eigene Einschätzung",
                                    "text": clean,
                                }
                            )
                        break
                # Marker aus Body entfernen
                sec["body"] = re.sub(
                    r"\[Eigene (?:Einschätzung|Inferenz)\]\s*", "", body
                )
                break
        # Kritisch/Warnung → Warning-Callout
        for pattern in (
            r"(?i)\*\*(?:Kritisch|Warnung|Achtung|Wichtig):\*\*\s*(.+?)(?:\n|$)",
            r"(?i)(?:Kritisch|Einschränkung):\s*(.+?)(?:\n|$)",
        ):
            m = re.search(pattern, body)
            if m:
                callouts.append(
                    {
                        "type": "warning",
                        "title": "Wichtig",
                        "text": m.group(1).strip(),
                    }
                )
                break
    if callouts:
        data["callouts"] = callouts[:4]

    # 5. Auto-Badges: Keywords im Titel erkennen
    badge_rules = [
        (("checkliste", "checklist", "implementierung", "praxis"), "Praxis"),
        (("sicherheit", "security", "schutz", "hardening"), "Sicherheit"),
        (("angriff", "attack", "vektor", "risiko", "lehren"), "Risiko"),
        (("framework", "standard", "compliance"), "Framework"),
        (("empfehlung", "best practice"), "Empfohlen"),
    ]
    for sec in sections:
        if sec.get("badge"):
            continue
        title_lower = sec.get("title", "").lower()
        for keywords, badge in badge_rules:
            if any(kw in title_lower for kw in keywords):
                sec["badge"] = badge
                break

    return data


# ── Main Rendering Pipeline ─────────────────────────────────────────────────


def render(template_type: str, data: dict, output_path: str) -> str:
    """JSON-Daten mit Template rendern → HTML-Datei."""
    import time as _time

    _render_start = _time.monotonic()

    # Expand short-key aliases (transparent, backward-compatible)
    data = _expand_aliases(data)  # type: ignore[assignment]

    # Auto-enrich text-heavy reports with visual elements
    data = auto_enrich(data)

    # Template-Typ normalisieren
    if template_type == "auto":
        template_type = detect_type(data)
        print(f"Auto-detected: {template_type}", file=sys.stderr)

    if template_type not in RENDERERS:
        # Fallback auf generic
        print(f"Unbekannter Typ '{template_type}', nutze 'generic'", file=sys.stderr)
        template_type = "generic"

    # Content-Blocks generieren
    renderer = RENDERERS[template_type]
    blocks = renderer(data)

    # Base shell + template body slots laden
    base_file = TEMPLATES_DIR / "_base.html"
    template_file = TEMPLATES_DIR / f"{template_type}.html"
    if not template_file.exists():
        template_file = TEMPLATES_DIR / "generic.html"
    body_slots = template_file.read_text(encoding="utf-8")

    # Extract HEAD_EXTRA from template comment (e.g. <!-- HEAD_EXTRA: body { --max-w: 900px; } -->)
    head_extra_match = re.search(r"<!--\s*HEAD_EXTRA:\s*(.+?)\s*-->", body_slots)
    head_extra = head_extra_match.group(1) if head_extra_match else ""

    # Assemble: base shell with body slots injected
    template = base_file.read_text(encoding="utf-8")
    template = template.replace("{{BODY_SLOTS}}", body_slots)
    template = template.replace("{{HEAD_EXTRA}}", head_extra)

    # CSS laden und Archetype-Styling injizieren
    css = load_css()
    fp = fingerprint_data(data)
    archetype = select_archetype(data, fp)
    arch_config = ARCHETYPE_CONFIG.get(archetype, {})
    sec = arch_config.get("accent_secondary", "#cf865a")
    arch_css = f"body {{ --accent-secondary: {sec}; }}"
    html = template.replace("{{CSS}}", css + "\n" + arch_css)

    # Blocks einsetzen
    for key, value in blocks.items():
        html = html.replace(f"{{{{{key}}}}}", value or "")

    # Nicht ersetzte Platzhalter leeren (inkl. HTML-Kommentare mit HEAD_EXTRA)
    html = re.sub(r"<!--\s*HEAD_EXTRA:.*?-->", "", html)
    html = re.sub(r"\{\{[A-Z_]+\}\}", "", html)

    # JS-Module injizieren (Progressive Enhancement)
    js = _load_js_modules(data, fp)
    if js:
        html = html.replace("</body>", js + "\n</body>")

    # Citation-Integrity: Prüfe ob jede [Qn]-Referenz eine passende Quelle hat
    cited_ids = {int(m) for m in re.findall(r'data-citation="(\d+)"', html)}
    source_count = len(data.get("sources", []))
    if cited_ids:
        orphans = {q for q in cited_ids if q < 1 or q > source_count}
        if orphans:
            print(
                f"WARNUNG: Citation-Mismatch — [Q{', Q'.join(str(q) for q in sorted(orphans))}] "
                f"referenziert, aber nur {source_count} Quellen vorhanden",
                file=sys.stderr,
            )

    # Output schreiben
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    _render_ms = int((_time.monotonic() - _render_start) * 1000)
    print(
        f"Report generiert: {out} ({len(html):,} bytes, {_render_ms}ms)",
        file=sys.stderr,
    )

    # Event für Observability direkt in skill-tracker.db loggen
    try:
        import sqlite3

        _db_path = Path(__file__).parent / "skill-tracker.db"
        if _db_path.exists():
            _db = sqlite3.connect(str(_db_path))
            _db.execute(
                """INSERT INTO events (source, event_type, status, latency_ms, value_num, value_text, meta)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    "renderer",
                    "render",
                    "ok",
                    _render_ms,
                    len(html),
                    template_type,
                    json.dumps(
                        {"title": data.get("title", "")[:60], "output": str(out)}
                    ),
                ),
            )
            _db.commit()
            _db.close()
    except Exception:
        pass  # Observability darf nie den Render-Prozess stören

    return str(out)


# ── CLI ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Token-effiziente HTML-Report-Generierung"
    )
    sub = parser.add_subparsers(dest="command")

    # render
    p_render = sub.add_parser("render", help="JSON → HTML rendern")
    p_render.add_argument(
        "type",
        help="Template-Typ (research/comparison/dashboard/guide/generic/deep-research-v2/lokal-guide/auto)",
    )
    p_render.add_argument("data", nargs="?", help="JSON-Datei (oder stdin wenn leer)")
    p_render.add_argument("-o", "--output", required=True, help="Ausgabe-Pfad")

    # schema
    p_schema = sub.add_parser("schema", help="JSON-Schema für Template anzeigen")
    p_schema.add_argument("type", help="Template-Typ")

    # list
    sub.add_parser("list", help="Verfügbare Templates auflisten")

    args = parser.parse_args()

    if args.command == "render":
        # JSON laden
        if args.data:
            data = json.loads(Path(args.data).read_text())
        elif not sys.stdin.isatty():
            data = json.loads(sys.stdin.read())
        else:
            print("Fehler: JSON-Datei oder stdin erforderlich", file=sys.stderr)
            sys.exit(1)

        path = render(args.type, data, args.output)
        # Pfad auf stdout für Skill-Integration
        print(json.dumps({"path": path, "type": args.type}))

    elif args.command == "schema":
        if args.type in SCHEMAS:
            print(SCHEMAS[args.type])
        else:
            print(f"Unbekannter Typ: {args.type}", file=sys.stderr)
            print(f"Verfügbar: {', '.join(SCHEMAS.keys())}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "list":
        print("Verfügbare Report-Templates:")
        for name in sorted(SCHEMAS.keys()):
            schema = json.loads(SCHEMAS[name])
            fields = [k for k in schema.keys() if k != "type"]
            print(f"  {name:15} Felder: {', '.join(fields)}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
