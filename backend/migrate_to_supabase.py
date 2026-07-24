"""One-time migration: local ChromaDB  ->  Supabase (pgvector), re-embedding
every chunk with Voyage.

Run ONCE on your Mac after creating the Supabase schema and setting SUPABASE_URL,
SUPABASE_SERVICE_KEY, and VOYAGE_API_KEY in backend/.env:

    cd backend && . .venv/bin/activate && python migrate_to_supabase.py

Idempotent: re-running upserts the same products/re-adds knowledge. It reads the
OLD store read-only and writes via the new rag/knowledge modules.
"""
import json

import chromadb
from chromadb.config import Settings

import config
import knowledge
import rag
from models import ProductData


def _open(name: str):
    client = chromadb.PersistentClient(
        path=config.CHROMA_DIR, settings=Settings(anonymized_telemetry=False)
    )
    try:
        return client.get_collection(name)
    except Exception:  # noqa: BLE001 — collection may not exist
        return None


def migrate_products() -> int:
    col = _open(config.COLLECTION_NAME)
    if not col:
        print("No products collection found — skipping.")
        return 0
    data = col.get(include=["metadatas"])
    seen: dict[str, ProductData] = {}
    for meta in data.get("metadatas") or []:
        raw = meta.get("_data")
        code = meta.get("item_code")
        if not (raw and code) or code in seen:
            continue
        try:
            seen[code] = ProductData(**json.loads(raw))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    for code, product in seen.items():
        n = rag.index_product(product)
        print(f"  product {code}: {product.title!r} -> {n} chunks")
    return len(seen)


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
    for did, g in grouped.items():
        ordered = [t for _, t in sorted(g["chunks"], key=lambda x: x[0])]
        full_text = "\n\n".join(ordered)
        info = knowledge.add_document(g["title"], full_text, g["source"])
        print(f"  doc {info['doc_id']}: {g['title']!r} -> {info['chunks']} chunks")
    return len(grouped)


if __name__ == "__main__":
    print("Migrating products…")
    p = migrate_products()
    print("Migrating knowledge…")
    k = migrate_knowledge()
    print(f"\nDone. {p} products, {k} knowledge docs migrated to Supabase.")
