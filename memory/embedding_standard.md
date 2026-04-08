---
name: Embedding Standard
description: gemini-embedding-2-preview ist der Standard-Embedding-Modell für alle Projekte — API-Details und Nutzungsrichtlinien
type: feedback
---

# Embedding Standard: Gemini Embedding 2 Preview

**Modell**: `gemini-embedding-2-preview`
**API**: Google Gemini (`from google import genai`)
**Standard-Dimensionen**: 768 (Matryoshka — bestes Qualität/Größe-Verhältnis)
**Max Input**: 8.192 Tokens
**Multimodal**: Text, Image, Video, Audio, PDF

## Task Types (IMMER setzen für bessere Qualität)

| Task Type | Wann |
|-----------|------|
| `RETRIEVAL_DOCUMENT` | Dokumente/Skills indexieren |
| `RETRIEVAL_QUERY` | Suchanfragen embedden |
| `SEMANTIC_SIMILARITY` | Ähnlichkeitsvergleiche |
| `CODE_RETRIEVAL_QUERY` | Code-Suche |

## Python-Pattern

```python
from google import genai

client = genai.Client(api_key=GEMINI_API_KEY)
result = client.models.embed_content(
    model="gemini-embedding-2-preview",
    contents=["Text zum Embedden"],
    config={"output_dimensionality": 768},  # Matryoshka: 128-3072
)
embedding = result.embeddings[0].values  # list[float], 768d
```

## Regeln

- **IMMER** `gemini-embedding-2-preview` für Embedding-Aufgaben (kein sentence-transformers, kein OpenAI)
- **IMMER** `output_dimensionality: 768` setzen (Default ist 3072 — zu groß für Pi)
- **IMMER** passenden `task_type` mitgeben wenn die API es unterstützt
- Embedding-Spaces verschiedener Modelle sind NICHT kompatibel — bei Modellwechsel muss alles neu embeddet werden
- Bereits genutzt in: Graph RAG (`graph-rag.py`), geplant für Skill Router
