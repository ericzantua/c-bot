"""One-time migration: local ChromaDB  ->  Supabase (pgvector), re-embedding
every chunk with Voyage.

Run ONCE on your Mac after creating the Supabase schema and setting SUPABASE_URL,
SUPABASE_SERVICE_KEY, and VOYAGE_API_KEY in backend/.env:

    cd backend && . .venv/bin/activate && python migrate_to_supabase.py

Idempotent: re-running upserts the same products/re-adds knowledge. It reads the
OLD store read-only and writes via the new rag/knowledge modules.
"""
import json
import time

import chromadb
from chromadb.config import Settings

import config
import knowledge
import rag
from models import ProductData

# Voyage's free tier (no payment method) allows only a few requests/min. Pace
# each embed call so we never burst past it. Override with MIGRATE_DELAY.
import os

DELAY = float(os.getenv("MIGRATE_DELAY", "25"))


def _open(name: str):
    client = chromadb.PersistentClient(
        path=config.CHROMA_DIR, settings=Settings(anonymized_telemetry=False)
    )
    try:
        return client.get_collection(name)
    except Exception:  # noqa: BLE001 — collection may not exist
        return None


def _product_from_legacy(code: str, metas: list[dict], docs: list[str]) -> ProductData:
    """Rebuild a ProductData from pre-`_data` chunks: bare metadata + chunk text."""
    base = metas[0] if metas else {}
    description = ""
    features: list[str] = []
    for doc in docs:
        if " — Description: " in doc:
            description = doc.split(" — Description: ", 1)[1].strip()
        elif " — Features: " in doc:
            feats = doc.split(" — Features: ", 1)[1].strip()
            features = [f.strip() for f in feats.split(";") if f.strip()]
    return ProductData(
        item_code=code,
        title=base.get("title", ""),
        brand=base.get("brand") or None,
        price=base.get("price") or None,
        description=description or None,
        features=features,
        url=base.get("url") or None,
    )


def migrate_products() -> int:
    col = _open(config.COLLECTION_NAME)
    if not col:
        print("No products collection found — skipping.")
        return 0
    data = col.get(include=["metadatas", "documents"])
    metas = data.get("metadatas") or []
    docs = data.get("documents") or []
    # Group chunks by item_code (handles both `_data` and legacy formats).
    grouped: dict[str, dict] = {}
    for meta, doc in zip(metas, docs):
        code = meta.get("item_code")
        if not code:
            continue
        g = grouped.setdefault(code, {"metas": [], "docs": [], "data": None})
        g["metas"].append(meta)
        g["docs"].append(doc)
        if meta.get("_data") and not g["data"]:
            g["data"] = meta["_data"]

    products: dict[str, ProductData] = {}
    for code, g in grouped.items():
        if g["data"]:
            try:
                products[code] = ProductData(**json.loads(g["data"]))
                continue
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        products[code] = _product_from_legacy(code, g["metas"], g["docs"])

    for i, (code, product) in enumerate(products.items()):
        if i:
            time.sleep(DELAY)  # stay under Voyage's free-tier rate limit
        n = rag.index_product(product)
        print(f"  product {code}: {product.title!r} -> {n} chunks", flush=True)
    return len(products)


def migrate_knowledge() -> int:
    col = _open("costco_knowledge")
    if not col:
        print("No knowledge collection found — skipping.")
        return 0
    data = col.get(include=["metadatas", "documents"])
    metas = data.get("metadatas") or []
    docs = data.get("documents") or []
    # Group chunk texts by doc_id, ordered by their stored chunk index.
    grouped: dict[str, dict] = {}
    for meta, text in zip(metas, docs):
        did = meta.get("doc_id")
        if not did:
            continue
        g = grouped.setdefault(
            did, {"title": meta.get("title", ""), "source": meta.get("source", ""), "chunks": []}
        )
        g["chunks"].append((meta.get("chunk", 0), text))
    for i, (did, g) in enumerate(grouped.items()):
        if i:
            time.sleep(DELAY)
        ordered = [t for _, t in sorted(g["chunks"], key=lambda x: x[0])]
        full_text = "\n\n".join(ordered)
        info = knowledge.add_document(g["title"], full_text, g["source"])
        print(f"  doc {info['doc_id']}: {g['title']!r} -> {info['chunks']} chunks", flush=True)
    return len(grouped)


if __name__ == "__main__":
    print("Migrating products…")
    p = migrate_products()
    print("Migrating knowledge…")
    time.sleep(DELAY)  # gap between the two phases too
    k = migrate_knowledge()
    print(f"\nDone. {p} products, {k} knowledge docs migrated to Supabase.")
