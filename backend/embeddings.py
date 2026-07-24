"""Text embeddings via the Voyage AI API.

Serverless-friendly: a plain HTTPS call, no local model/torch. Used for both
indexing (input_type='document') and query time (input_type='query'). Retries
on 429 (rate limit) with backoff — Voyage's free tier is a few requests/min.
"""
import time

import httpx

import config

_VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
_MAX_RETRIES = 6


def embed(texts: list[str], input_type: str = "document") -> list[list[float]]:
    """Embed a batch of texts (one API call); preserves input order."""
    texts = [t for t in texts if t and t.strip()]
    if not texts:
        return []
    if not config.VOYAGE_API_KEY:
        raise RuntimeError("VOYAGE_API_KEY is not set (see backend/.env).")
    payload = {
        "input": texts,
        "model": config.VOYAGE_MODEL,
        "input_type": input_type,
        "output_dimension": config.EMBED_DIM,
    }
    headers = {"Authorization": f"Bearer {config.VOYAGE_API_KEY}"}
    for attempt in range(_MAX_RETRIES):
        resp = httpx.post(_VOYAGE_URL, headers=headers, json=payload, timeout=30)
        if resp.status_code == 429 and attempt < _MAX_RETRIES - 1:
            retry_after = resp.headers.get("retry-after")
            wait = float(retry_after) if retry_after else min(2 ** attempt + 3, 25)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        items = resp.json()["data"]
        items.sort(key=lambda d: d["index"])
        return [d["embedding"] for d in items]
    resp.raise_for_status()  # exhausted retries
    return []


def embed_query(text: str) -> list[float]:
    """Embed a single search query."""
    vecs = embed([text], input_type="query")
    return vecs[0] if vecs else []
