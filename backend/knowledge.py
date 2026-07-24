"""Reference-document knowledge base (Costco rules, policies, FAQs, etc.).

Documents are chunked, embedded (Voyage), and stored in Supabase
(knowledge_docs + knowledge_chunks). Chat retrieval pulls relevant chunks
alongside product data so C-Bot can answer policy/membership/return questions
grounded in these docs.
"""
import io
import re
import uuid

import db
import embeddings


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
    sb = db.client()
    sb.table("knowledge_docs").insert(
        {"doc_id": doc_id, "title": title, "source": source, "chunks": len(chunks)}
    ).execute()

    vectors = embeddings.embed(chunks, input_type="document")
    rows = [
        {"doc_id": doc_id, "title": title, "content": chunk, "embedding": vec}
        for chunk, vec in zip(chunks, vectors)
    ]
    sb.table("knowledge_chunks").insert(rows).execute()
    return {"doc_id": doc_id, "title": title, "source": source, "chunks": len(chunks)}


def list_documents() -> list[dict]:
    rows = (
        db.client()
        .table("knowledge_docs")
        .select("doc_id, title, source, chunks")
        .execute()
        .data
        or []
    )
    return rows


def delete_document(doc_id: str) -> None:
    # chunks cascade-delete via the FK.
    db.client().table("knowledge_docs").delete().eq("doc_id", doc_id).execute()


def retrieve(query: str, k: int = 4) -> list[tuple[str, str]]:
    """Return up to k (chunk_text, doc_title) relevant to the query."""
    query_vec = embeddings.embed_query(query)
    if not query_vec:
        return []
    rows = (
        db.client()
        .rpc("match_knowledge", {"query_embedding": query_vec, "match_count": k})
        .execute()
        .data
        or []
    )
    return [(r.get("content", ""), r.get("title", "")) for r in rows]
