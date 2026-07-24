"""Reference-document knowledge base (Costco rules, policies, FAQs, etc.).

Documents are chunked, embedded, and stored in a separate Chroma collection
(shares the client + embedder with rag.py). Chat retrieval pulls relevant
chunks alongside product data so C-Bot can answer policy/membership/return
questions grounded in these docs.
"""
import io
import re
import uuid

import rag

KNOWLEDGE_COLLECTION = "costco_knowledge"

_kcol = None


def get_kcollection():
    global _kcol
    if _kcol is None:
        _kcol = rag.chroma_client().get_or_create_collection(
            name=KNOWLEDGE_COLLECTION,
            embedding_function=rag.embedding_function(),
            metadata={"hnsw:space": "cosine"},
        )
    return _kcol


def _chunk_text(text: str, target: int = 900, hard_max: int = 1600) -> list[str]:
    """Split text into ~target-sized chunks on paragraph boundaries."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    cur = ""
    for p in paras:
        if cur and len(cur) + len(p) > target:
            chunks.append(cur.strip())
            cur = p
        else:
            cur = f"{cur}\n\n{p}" if cur else p
    if cur.strip():
        chunks.append(cur.strip())

    # Hard-split any oversized chunk so embeddings stay meaningful.
    out: list[str] = []
    for c in chunks:
        while len(c) > hard_max:
            cut = c.rfind(" ", 0, hard_max)
            cut = cut if cut > target else hard_max
            out.append(c[:cut].strip())
            c = c[cut:].strip()
        if c:
            out.append(c)
    return out


def extract_text(filename: str, data: bytes) -> str:
    """Extract plain text from an uploaded file (.txt / .md / .pdf)."""
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)
    # text-like
    return data.decode("utf-8", errors="replace")


def add_document(title: str, text: str, source: str = "") -> dict:
    """Chunk + embed + store a document. Returns its summary."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Document has no extractable text.")
    chunks = _chunk_text(text)
    if not chunks:
        raise ValueError("Document produced no chunks.")

    doc_id = uuid.uuid4().hex[:12]
    title = (title or "Untitled document").strip()
    collection = get_kcollection()
    collection.add(
        ids=[f"{doc_id}-{i}" for i in range(len(chunks))],
        documents=chunks,
        metadatas=[
            {"doc_id": doc_id, "title": title, "source": source, "chunk": i}
            for i in range(len(chunks))
        ],
    )
    return {"doc_id": doc_id, "title": title, "source": source, "chunks": len(chunks)}


def list_documents() -> list[dict]:
    data = get_kcollection().get(include=["metadatas"])
    docs: dict[str, dict] = {}
    for meta in data.get("metadatas") or []:
        did = meta.get("doc_id")
        if not did:
            continue
        if did not in docs:
            docs[did] = {
                "doc_id": did,
                "title": meta.get("title", ""),
                "source": meta.get("source", ""),
                "chunks": 0,
            }
        docs[did]["chunks"] += 1
    return list(docs.values())


def delete_document(doc_id: str) -> None:
    get_kcollection().delete(where={"doc_id": doc_id})


def retrieve(query: str, k: int = 4) -> list[tuple[str, str]]:
    """Return up to k (chunk_text, doc_title) relevant to the query."""
    collection = get_kcollection()
    if collection.count() == 0:
        return []
    res = collection.query(
        query_texts=[query],
        n_results=min(k, collection.count()),
        include=["documents", "metadatas"],
    )
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    return [(d, m.get("title", "")) for d, m in zip(docs, metas)]
