"""Text embeddings via the Voyage AI API.

Serverless-friendly: a plain HTTPS call, no local model/torch. Used for both
indexing (input_type='document') and query time (input_type='query').
"""
import httpx

import config

_VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"


def embed(texts: list[str], input_type: str = "document") -> list[list[float]]:
    """Embed a batch of texts; preserves input order."""
    texts = [t for t in texts if t and t.strip()]
    if not texts:
        return []
    if not config.VOYAGE_API_KEY:
        raise RuntimeError("VOYAGE_API_KEY is not set (see backend/.env).")
    resp = httpx.post(
        _VOYAGE_URL,
        headers={"Authorization": f"Bearer {config.VOYAGE_API_KEY}"},
        json={
            "input": texts,
            "model": config.VOYAGE_MODEL,
            "input_type": input_type,
            "output_dimension": config.EMBED_DIM,
        },
        timeout=30,
    )
    resp.raise_for_status()
    items = resp.json()["data"]
    items.sort(key=lambda d: d["index"])
    return [d["embedding"] for d in items]


def embed_query(text: str) -> list[float]:
    """Embed a single search query."""
    vecs = embed([text], input_type="query")
    return vecs[0] if vecs else []
