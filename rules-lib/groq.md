# Groq API — Modell-Referenz (Stand April 2026)

Geladen via Rules Router bei Keywords: groq, whisper, transkription, speech-to-text, tts, lpu

## API-Basics

- **Base URL:** `https://api.groq.com/openai/v1`
- **Auth:** `Authorization: Bearer $GROQ_API_KEY`
- **Format:** OpenAI-kompatibel — funktioniert mit OpenAI SDKs (`base_url` ändern)
- **SDKs:** `pip install groq` (offiziell), OpenAI SDK, LiteLLM (`groq/` Prefix), AI SDK (`@ai-sdk/groq`)
- **Responses API:** Beta — kompatibel mit OpenAIs Responses API (Text, Bild, Function Calling)

## Modelle — Chat/Completion

### Production (stabil, für Produktivumgebungen)

| Modell | Model-ID | Context | Max Output | Speed | Input/1M | Output/1M | Stärken |
|--------|----------|---------|------------|-------|----------|-----------|---------|
| **Llama 3.1 8B** | `llama-3.1-8b-instant` | 131K | 131K | 840 T/s | $0.05 | $0.08 | Schnellstes, günstigstes. Prototyping, hoher Durchsatz |
| **Llama 3.3 70B** | `llama-3.3-70b-versatile` | 131K | 32K | ~394 T/s | $0.59 | $0.79 | Qualitätsmodell. Komplexes Reasoning, Summarization |
| **GPT-OSS 120B** | `openai/gpt-oss-120b` | 131K | 65K | 500 T/s | $0.15 | $0.60 | OpenAI Open-Weight-Flaggschiff (MoE). Reasoning, Code, Browser |
| **GPT-OSS 20B** | `openai/gpt-oss-20b` | 131K | 65K | 1.000 T/s | $0.075 | $0.30 | Schnellstes Groq-Modell. Gleiche Architektur wie 120B |

### Preview (nur Evaluation, kann kurzfristig entfernt werden)

| Modell | Model-ID | Context | Max Output | Speed | Input/1M | Output/1M | Stärken |
|--------|----------|---------|------------|-------|----------|-----------|---------|
| **Llama 4 Scout** | `meta-llama/llama-4-scout-17b-16e-instruct` | 131K | 8K | ~594 T/s | $0.11 | $0.34 | Vision-fähig (Bild-Input), MoE |
| **Qwen3 32B** | `qwen/qwen3-32b` | 131K | 40K | ~662 T/s | $0.29 | $0.59 | Reasoning (reasoningFormat: parsed/raw/hidden) |
| **GPT-OSS Safeguard 20B** | `openai/gpt-oss-safeguard-20b` | 131K | 65K | 1.000 T/s | $0.075 | $0.30 | Safety-Variante des GPT-OSS 20B |
| **Kimi K2 Instruct** | `moonshotai/kimi-k2-instruct-0905` | 131K | — | — | $1.00 | $3.00 | Moonshot AI. Teuerste Option |
| **Allam 2 7B** | `allam-2-7b` | — | — | — | — | — | Arabisches Sprachmodell |
| **Llama Guard 4 12B** | `meta-llama/llama-guard-4-12b` | — | — | — | — | — | Safety/Moderation |

### Compound-Systeme (Agentic AI)

| Modell | Model-ID | Context | Max Output | Speed | Besonderheiten |
|--------|----------|---------|------------|-------|---------------|
| **Groq Compound** | `groq/compound` | 131K | 8K | ~450 T/s | Web-Search, Code-Execution, Multi-Step-Reasoning |
| **Groq Compound Mini** | `groq/compound-mini` | 131K | 8K | ~450 T/s | Leichtgewichtige Variante |

Built-In Tools Pricing: Basic Search $5/1K Req, Advanced Search $8/1K, Visit Website $1/1K, Code Exec $0.18/h.

### Prompt Caching

Verfügbar für GPT-OSS 120B, GPT-OSS 20B und Kimi K2. **50% Rabatt** auf gecachte Input-Tokens.
Gecachte Tokens zählen **nicht** gegen Rate Limits.

| Modell | Uncached Input/1M | Cached Input/1M |
|--------|-------------------|-----------------|
| GPT-OSS 120B | $0.15 | $0.075 |
| GPT-OSS 20B | $0.075 | $0.0375 |
| Kimi K2 | $1.00 | $0.50 |

### Batch API

50% Rabatt auf alle bezahlten Modelle. Asynchrone Verarbeitung (24h–7d). Kein Impact auf Standard-Rate-Limits.

## GPT-OSS 120B — Details & Bekannte Probleme

- **Architektur:** Mixture-of-Experts (MoE), 120B Parameter, Release August 2025
- **Built-In Tools:** Browser Search (Basic + Visit), Code Interpreter (Python)
- **Benchmark:** Erreicht/übertrifft OpenAI o4-mini auf vielen Benchmarks

**Bekannte Einschränkungen:**
- `strict` Structured Output funktioniert **nicht** (LangChain Issue #34155)
- `tool_choice=required` wird teilweise ignoriert
- **Workaround:** JSON-Mode statt Structured Output verwenden

**Prompt-Engineering:** Siehe `~/.claude/rules-lib/prompting.md` für die 7 Goldenen Regeln (Zettel #67).
Kurzfassung: Evidence-Pflicht im Schema > Flachtext statt XML > Constraints in User-Message > Experten-Rolle.

## Modelle — Audio (Whisper)

| Modell | Model-ID | Speed | Pricing/h | Max File | Qualität |
|--------|----------|-------|-----------|----------|----------|
| **Whisper Large v3** | `whisper-large-v3` | 217x Echtzeit | $0.111 | 100 MB | Höchste Genauigkeit, multilingual |
| **Whisper Large v3 Turbo** | `whisper-large-v3-turbo` | 228x Echtzeit | $0.04 | 100 MB | 63% günstiger, ~1% höhere WER |

**Empfehlung:** `whisper-large-v3-turbo` für die meisten Fälle. `whisper-large-v3` nur bei maximaler Genauigkeitsanforderung.

## Zentrale Transkriptions-Config

Optimale Whisper-Parameter für alle unsere Tools (Copy-Paste-ready):

```python
# Groq Whisper — Optimale Parameter
WHISPER_CONFIG = {
    "model": "whisper-large-v3-turbo",      # Standard. Nur v3 bei max. Genauigkeit
    "response_format": "verbose_json",       # Enthält Segmente + Timestamps + Language
    "language": "de",                        # Explizit setzen → verhindert Fehlklassifikation
    "temperature": 0.0,                      # Deterministisch, weniger Halluzination
    "timestamp_granularities": ["segment"],  # "word" nur wenn wirklich nötig (langsamer)
}

# Prompt-Hints: Verbessern Genauigkeit bei Fachsprache/Eigennamen
# Maximal ~224 Tokens. Enthalten typische Begriffe aus dem Audio.
WHISPER_PROMPTS = {
    "legal":    "act legal, Insolvenzverwalter, Gläubigerversammlung, § 94 InsO, Aktenzeichen",
    "meeting":  "Matthias, act legal, Action Items, Follow-Up, nächste Schritte",
    "general":  "",  # Kein Prompt → Whisper entscheidet selbst
}
```

```bash
# curl-Beispiel (für Shell-Scripts)
curl -s https://api.groq.com/openai/v1/audio/transcriptions \
  -H "Authorization: Bearer $GROQ_API_KEY" \
  -F "model=whisper-large-v3-turbo" \
  -F "file=@audio.mp3" \
  -F "response_format=verbose_json" \
  -F "language=de" \
  -F "temperature=0.0" \
  -F "prompt=act legal, Matthias"
```

```python
# Python-Beispiel (Groq SDK)
from groq import Groq

client = Groq()
with open("audio.mp3", "rb") as f:
    result = client.audio.transcriptions.create(
        model="whisper-large-v3-turbo",
        file=f,
        response_format="verbose_json",
        language="de",
        temperature=0.0,
        prompt="act legal, Matthias",
    )
```

**Wann welches `response_format`:**
| Format | Wann |
|--------|------|
| `verbose_json` | Standard. Enthält Timestamps, Segmente, Sprach-Erkennung |
| `json` | Nur Text + Sprache, weniger Overhead |
| `text` | Reiner Text, minimaler Output |
| `srt` / `vtt` | Untertitel-Export |

**Wann `whisper-large-v3` statt Turbo:**
- Starker Dialekt oder Akzent
- Schlechte Audioqualität (Hintergrundlärm, Telefon)
- Mehrere Sprecher mit Überlappung
- Genauigkeit >99% erforderlich

## Modelle — Text-to-Speech

| Modell | Speed | Pricing/1M chars | Max Input | Status |
|--------|-------|-------------------|-----------|--------|
| Orpheus English (Canopy Labs) | 100 chars/s | $22.00 | 50K chars | Preview |
| Orpheus Arabic Saudi | 100 chars/s | $40.00 | 50K chars | Preview |

## Modelle — Embedding

**Nicht verfügbar.** Groq hat Embeddings als niedrige Priorität eingestuft. Kein Zeitplan.

**Alternativen:**
- DeepInfra (Qwen3-Embedding-8B — aktuell MTEB-Spitze)
- HuggingFace Inference Endpoints
- Mixedbread (leichtgewichtig)
- OpenAI Embeddings API

Hinweis: Die Groq Python-SDK enthält Embedding-Code-Stubs → kein funktionierender Endpoint.

## Rate Limits

### Developer Plan (bezahlt)

| Modell | TPM | RPM |
|--------|-----|-----|
| Llama 3.1 8B | 250K | 1K |
| Llama 3.3 70B | 300K | 1K |
| GPT-OSS 120B | 250K | 1K |
| GPT-OSS 20B | 250K | 1K |
| Llama 4 Scout | 300K | 1K |
| Qwen3 32B | 300K | 1K |
| Compound/Mini | 200K | 200 |
| Whisper v3 | 200K ASH | 300 |
| Whisper v3 Turbo | 400K ASH | 400 |

TPM = Tokens/Min, ASH = Audio Seconds/Hour.

### Free Tier (ohne Kreditkarte)

| Modell | RPM | RPD | TPM | TPD |
|--------|-----|-----|-----|-----|
| Llama 3.1 8B | 30 | 14.400 | 6K | 500K |
| Llama 3.3 70B | 30 | 1.000 | 12K | 100K |
| GPT-OSS 120B | 30 | 1.000 | 8K | 200K |
| GPT-OSS 20B | 30 | 1.000 | 8K | 200K |
| Llama 4 Scout | 30 | 1.000 | 30K | 500K |
| Qwen3 32B | 60 | 1.000 | 6K | 500K |
| Kimi K2 | 60 | 1.000 | 10K | 300K |
| Whisper v3/Turbo | 20 | 2.000 | — | — |

Whisper Free Tier: 7.200 Audio-Sekunden/Stunde (≈ 2h Audio pro Stunde Echtzeit).

## Empfehlung für unseren Use Case

### Transkription: `whisper-large-v3-turbo`
- 63% günstiger als v3 ($0.04 vs. $0.111/h) bei nahezu gleicher Qualität
- 228x Echtzeit — selbst 2h Meetings in <30s
- Ausreichend für deutsche Meetings, Diktate, Interviews
- Siehe "Zentrale Transkriptions-Config" oben für optimale Parameter

### Summarization/Analyse: `openai/gpt-oss-120b`
- Bestes Qualitäts-/Preis-Verhältnis auf Groq
- 131K Context → komplette Meeting-Transkripte in einem Call
- Prompt-Engineering-Regeln beachten (→ `~/.claude/rules-lib/prompting.md`, Zettel #67)
- Bei einfacheren Tasks: `openai/gpt-oss-20b` (3x schneller, halb so teuer)

### Warum:
- **GPT-OSS 120B > Llama 3.3 70B** für Analyse: Stärkeres Reasoning, günstigerer Input ($0.15 vs $0.59), größerer Max Output (65K vs 32K)
- **GPT-OSS 120B > Kimi K2** preislich: 6.7x günstiger Input, 5x günstiger Output
- **Whisper Turbo > v3** in 95% der Fälle: Marginal schlechtere WER, massiv günstiger

## Quellen

- https://groq.com/pricing — Offizielle Pricing-Page
- https://console.groq.com/docs/models — Modell-Dokumentation
- https://console.groq.com/docs/responses-api — Responses API Docs
- https://www.grizzlypeaksoftware.com/articles/p/groq-api-free-tier-limits-in-2026-what-you-actually-get-uwysd6mb — Free Tier Limits 2026
- https://groq.com/blog/whisper-large-v3-turbo-now-available-on-groq-combining-speed-quality-for-speech-recognition — Whisper Turbo Announcement
- https://community.groq.com/t/when-will-embedding-models-be-available-in-groq/509 — Embedding Status
- https://github.com/langchain-ai/langchain/issues/34155 — GPT-OSS Structured Output Bug
