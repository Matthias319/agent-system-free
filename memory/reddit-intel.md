# Reddit Intelligence Mining — Kompaktdokumentation

*Erstellt 2026-03-01 nach 2 Sessions, ~33 MCP-Batches, 15+ Profile*

## Was ist das?

Systematisches Mining von Reddit (r/ClaudeCode, r/ClaudeAI) nach Power-User-Insights
für Claude Code. Nutzt den `reddit-mcp-buddy` MCP-Server für strukturierten Zugriff
auf Posts, Kommentare und User-Profile.

## Reddit MCP Server

**Installiert in** `~/.claude/settings.json` unter `mcpServers.reddit`.
Anonym (kein Auth), **10 Requests/Minute** Rate Limit.

### Verfügbare Tools

| Tool | Wofür | Rate-Cost |
|------|-------|-----------|
| `browse_subreddit` | 25 Posts scannen (sort/time/limit) | 1 Req |
| `get_post_details` | Post + Top-Kommentare laden | 1 Req |
| `user_analysis` | Profil: Karma, Top-Subs, Posts, Kommentare | ~2 Req |
| `search_reddit` | Suche (ACHTUNG: Subreddit-Filter broken) | 1 Req |

### MCP-Kommunikation (da Tools nicht direkt verfügbar)

Das MCP wird per subprocess JSON-RPC angesprochen:

```python
import subprocess, json, time

proc = subprocess.Popen(['npx', '-y', 'reddit-mcp-buddy'],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

def send(msg):
    proc.stdin.write(json.dumps(msg) + '\n')
    proc.stdin.flush()
def recv():
    line = proc.stdout.readline().strip()
    try: return json.loads(line) if line else None
    except: return {'raw': line}

# PFLICHT: Init-Sequenz
send({'jsonrpc':'2.0','id':1,'method':'initialize','params':{
    'protocolVersion':'2024-11-05','capabilities':{},
    'clientInfo':{'name':'q','version':'1'}}})
recv()
send({'jsonrpc':'2.0','method':'notifications/initialized'})

# Beispiel: Subreddit browsen
send({'jsonrpc':'2.0','id':2,'method':'tools/call','params':{
    'name':'browse_subreddit',
    'arguments':{'subreddit':'ClaudeCode','sort':'top','time':'month','limit':25}}})
result = recv()

# Beispiel: Post deep-dive
send({'jsonrpc':'2.0','id':3,'method':'tools/call','params':{
    'name':'get_post_details',
    'arguments':{'post_id':'1rh5pcm','include_comments':True,
                 'comment_sort':'top','max_comments':12}}})
result = recv()

# Beispiel: User-Profil
send({'jsonrpc':'2.0','id':4,'method':'tools/call','params':{
    'name':'user_analysis',
    'arguments':{'username':'karanb192'}}})
result = recv()

proc.terminate()
```

### Kritische Learnings

1. **3 Calls pro Batch** — nach 3 Calls oft Rate Limit. `time.sleep(1)` zwischen Calls.
2. **search_reddit Subreddit-Filter funktioniert nicht** — `browse_subreddit` nutzen.
3. **user_analysis verbraucht ~2 Requests** statt 1.
4. **Ergebnisse in Datei schreiben** statt inline parsen (Output zu lang für Context).
5. **JSON-Parsing mit try/except** — Rate-Limit-Errors kommen als Raw-Text statt JSON.
6. **Accounts < 3 Monate** oft Content-Creator, nicht echte Power User.

### Optimaler Mining-Flow

```
Phase 1: Discovery (1 Call)
  browse_subreddit(sort=top, time=month, limit=25)
  → Posts nach Upvote-Ratio (95%+) und Comment-Count filtern

Phase 2: Deep-Dive (2 Calls)
  get_post_details × 2 für Top-Posts
  → Top-Kommentare nach technischem Gehalt filtern

Phase 3: Pause (60s Rate Limit)

Phase 4: Profile (2 Calls)
  user_analysis × 2 für beste Kommentatoren
  → Andere Subs + Posts entdecken

Phase 5: Content-Crawl (kein MCP)
  research-crawler.py für Blogs/Repos der Power User
  → URLs aus Profilen extrahieren

Effizienz: ~0.7 verwertbare Gems pro Batch
Diminishing Returns: Nach ~25 Batches pro Thema
```

### Qualitätsfilter-Heuristiken

- **Upvote-Ratio 95%+** = genuiner technischer Content
- **70-89%** = kontrovers, aber manchmal wertvoll (prüfen)
- **< 70%** = Marketing, Selbstpromotion, oder kontrovers — skip
- **Kommentare mit 50+ Pts in Tech-Posts** = oft die eigentlichen Gems
- **AI-Commenter erkennen**: Gleiches Template über Posts, 3 Monate Account, unrealistisch hohe Aktivität

## Implementierte Gems (2026-03-01)

### LSP Code-Navigation
- **pyright 1.1.408** installiert (npm global)
- **`ENABLE_LSP_TOOL=1`** in settings.json gesetzt
- **pyright-lsp Plugin** war schon aktiviert, Prozess läuft
- **Dokumentiert** in CLAUDE.md + tool-efficiency.md
- **Erwartung**: 98% weniger Token bei Code-Navigation vs Grep

### rtk (Rust Token Killer)
- **v0.23.0** installiert in `~/.local/bin/rtk` (ARM64 Binary)
- **Benchmark (mission-control-v2, 1366 .py Dateien)**:
  - git log -20: 86% Ersparnis (7.341→1.030 chars)
  - find *.py: 85% (1.087→164)
  - ls -la: 71% (1.436→419)
  - git status: 69% (434→135)
  - Gesamt: ~54% Token-Reduktion pro Session
- **Warnung**: Bei kurzen Outputs (< 200 chars) neutral oder schlechter
- **Nutzung**: `rtk <befehl>` oder `~/.local/bin/rtk <befehl>`

### tee-to-file Regel
- In CLAUDE.md: Bei langen Outputs `cmd 2>&1 | tee /tmp/output.log | tail -20`
- Vermeidet doppelte Testläufe wenn Details gebraucht werden

### Single-Purpose Sessions
- In CLAUDE.md: Kein Themenwechsel in Sessions, ~39% Perf-Degradation bei Topic-Mixing

## Nicht-implementierte Gems (Backlog)

| Gem | Warum noch nicht | Aufwand |
|-----|------------------|---------|
| effort Parameter (API) | Nur über API, nicht CC CLI nativ | Mittel |
| /insights Befehl | Einmal manuell testen | 1 min |
| SubagentStart/Stop Hooks | Use Cases unklar | Mittel |
| YAML Frontmatters auf .md | Nur für größere Projekte relevant | Niedrig |
| Sonnet 4.6 für Subagents | Konträr zur aktuellen "nur Opus" Regel | Diskussion |
| Hook Safety Levels | Nice-to-have | Niedrig |

## Vollständiger Intel-Report

Detaillierter Report mit allen 23+ Gems, Profilen und Quellen:
`~/shared/notizen/reddit-intel-log.md`
