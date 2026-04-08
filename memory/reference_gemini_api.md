---
name: gemini-api-current
description: Aktuelle Gemini API Model-Namen, Endpoints, Pricing, Free Tier (Stand 2026-03-17)
type: reference
---

## Gemini 3 Model Family (aktuell SOTA, Stand 2026-03-17)

| Model | Model-ID | Free Tier | Pricing/1M tokens |
|-------|----------|-----------|-------------------|
| Gemini 3.1 Pro | `gemini-3.1-pro-preview` | Nein (billing required) | — |
| Gemini 3 Flash | `gemini-3-flash-preview` | Ja | $0.05-$0.15 |
| Gemini 3.1 Flash-Lite | `gemini-3.1-flash-lite-preview` | Ja | noch günstiger |

## REST API Format

```
POST https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent
Header: x-goog-api-key: $GEMINI_API_KEY
Header: Content-Type: application/json

Body:
{
  "contents": [{
    "parts": [{"text": "prompt"}]
  }]
}
```

## Python SDK

```python
from google import genai
client = genai.Client()
response = client.models.generate_content(
    model="gemini-3-flash-preview",
    contents="prompt",
)
```

## Key für Matthias' Server

`GEMINI_API_KEY` in `~/.env` vorhanden (AIzaSy...).

## Neue Features bei Gemini 3

- `thinking_level` Parameter: minimal/low/medium/high (ersetzt thinking_budget)
- `media_resolution` Parameter: low/medium/high/ultra high
- Thought signatures für multi-turn function calling
- Nano Banana 2 = Gemini 3.1 Flash Image (Bildgenerierung)
- Nano Banana Pro = Gemini 3 Pro Image

**Quelle**: ai.google.dev/gemini-api/docs/models, blog.google, docs.cloud.google.com (alle 2026-03-17 gecrawlt)
