# Web Rules (on-demand geladen via Rules Router)

## Web-Content-Extraktion: Entscheidungsbaum

| Situation | Tool | ~Tokens | Speed |
|-----------|------|---------|-------|
| Haupttext einer Seite | `research-crawler.py` (Multi-URL) oder `trafilatura` (Einzel) | 50-500 | 0.1s |
| Spezifische Elemente (CSS) | `httpx` + `selectolax` | 50-200 | 0.08s |
| JS-gerenderte Seite | `agent-browser` CLI | ~14.000 | 3.9s |
| Interaktion (Klicks, QA) | Playwright MCP | ~21.000 | 3.8s |

**IMMER research-crawler.py statt WebFetch** (72-80% weniger Tokens, automatisches Tracking).
**WebFetch ist OBSOLET.** Einzige Ausnahme: JS-Rendering + agent-browser funktioniert nicht.

### trafilatura (Einzel-URL)
```python
import httpx, trafilatura
html = httpx.Client(timeout=30).get(url).text
content = trafilatura.extract(html, output_format="markdown", include_links=True)
```

### httpx + selectolax (strukturierte Extraktion)
```python
from selectolax.lexbor import LexborHTMLParser
tree = LexborHTMLParser(httpx.Client(timeout=30).get(url).text)
items = [a.attrs.get("href") for a in tree.css("a.item")]
```

### agent-browser CLI (JS-Seiten)
```bash
agent-browser open URL && agent-browser snapshot && agent-browser close
```

## URL-Discovery: fast-search.py

**fast-search.py ersetzt natives WebSearch KOMPLETT.**
Startpage-basiert, 0.5s/Query, 60x schneller, automatische Blocklist.

```bash
~/.claude/tools/fast-search.py "query1" "query2" \
  | ~/.claude/tools/research-crawler.py --max-chars 6000 --track web-search
```

### WebSearch: NUR diese 2 Fälle
| `site:tiktok.com` Queries | fast-search.py filtert TikTok |
| `site:reddit.com` Queries | fast-search.py filtert Reddit |

**ALLES andere → fast-search.py.** Kein Fallback.

## Preisvergleich
`~/.claude/tools/fast-search.py --geizhals "Produktname"` (~1s, Bestpreis + Varianten)

## GitHub-Recherche
**Topic-Suche >> Text-Suche.** `gh search repos --topic X --sort stars`
**Anti-Pattern:** `gh search repos "text query"` findet Müll.

## Context7 vs fast-search.py
| API-Docs einer bekannten Library | **Context7** |
| Aktuelle Events, News, Blog-Posts | **fast-search.py** + Crawler |
| Troubleshooting | **fast-search.py** + Crawler |
| GitHub Repo-Discovery | **gh CLI** + fast-search.py |
