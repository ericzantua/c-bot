"""Retrieval-Augmented Generation over the local ChromaDB product store.

Responsibilities:
  * chunk + embed + store scraped products (embeddings via sentence-transformers)
  * list / delete products
  * retrieve relevant chunks for a query and answer with Claude, grounded only
    in that context.
"""
import json

from anthropic import Anthropic

import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions

import config
import settings_store
from models import Citation, Message, ProductData

# Marker Claude emits when the asked-about product isn't in the retrieved context,
# so the backend can trigger the on-demand ingestion UI.
NOT_FOUND_MARKER = "[PRODUCT_NOT_FOUND]"

_SYSTEM_PROMPT = (
    "You are C-Bot, a warm, down-to-earth assistant who helps people with Costco "
    "products — think of a knowledgeable friend who happens to work the floor, "
    "not a corporate chatbot.\n\n"
    "GROUNDING (non-negotiable): Use ONLY the information in the 'CONTEXT' block "
    "of the user's message. It has two parts: PRODUCTS (product data) and "
    "KNOWLEDGE (Costco policies, rules, membership, returns and other reference "
    "docs). Answer product questions from PRODUCTS and policy/general Costco "
    "questions from KNOWLEDGE. Never invent specs, prices, ratings, or policies. "
    "If the shopper asks about a PRODUCT that isn't in PRODUCTS, don't guess — "
    "reply with exactly this token on its own first line:\n"
    f"{NOT_FOUND_MARKER}\n"
    "then, in your own natural voice, say you don't have that one yet and ask for "
    "its Costco item number. Do NOT use this token for policy/general questions — "
    "if KNOWLEDGE doesn't cover it, just say you don't have that information.\n\n"
    "HOW TO SOUND HUMAN:\n"
    "- Talk like a real person: contractions, everyday words, natural rhythm. "
    "Vary how you open — don't start every reply with 'Great news!' or 'Sure!'.\n"
    "- Be warm but genuine. Skip marketing fluff, hype, and exclamation-point "
    "overload. Give a real opinion or recommendation when asked for one.\n"
    "- Answer what they actually asked first, briefly, then add a detail or two "
    "only if it helps. Don't recite every spec.\n"
    "- Your replies may be read aloud, so write for the ear: flowing sentences "
    "rather than tables or long bullet lists, no markdown symbols or long URLs, "
    "and say prices and numbers the way a person would speak them.\n"
    "- For a comparison, weave the key differences into a short, conversational "
    "rundown — a couple of quick points are fine, but keep it sounding spoken, "
    "not like a spec sheet."
)

_client: Anthropic | None = None
_collection = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY is not set (see backend/.env).")
        _client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


_chroma_client = None
_embed_fn = None


def chroma_client():
    """Shared persistent Chroma client (products + knowledge)."""
    global _chroma_client
    if _chroma_client is None:
        # anonymized_telemetry=False silences ChromaDB's noisy telemetry warnings.
        _chroma_client = chromadb.PersistentClient(
            path=config.CHROMA_DIR,
            settings=Settings(anonymized_telemetry=False),
        )
    return _chroma_client


def embedding_function():
    """Shared local embedding function (loaded once)."""
    global _embed_fn
    if _embed_fn is None:
        _embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=config.EMBED_MODEL
        )
    return _embed_fn


def get_collection():
    """Lazily create the persistent product collection."""
    global _collection
    if _collection is None:
        _collection = chroma_client().get_or_create_collection(
            name=config.COLLECTION_NAME,
            embedding_function=embedding_function(),
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def _chunks_for(product: ProductData) -> list[str]:
    """Turn a product into a handful of self-contained text chunks."""
    price_bits = []
    if product.price:
        price_bits.append(f"current price {product.price}")
    if product.regular_price:
        price_bits.append(f"regular price {product.regular_price}")
    if product.promo_price:
        price_bits.append(f"promo price {product.promo_price}")
    if product.price_valid_until:
        price_bits.append(f"promo valid until {product.price_valid_until}")
    pricing = "; ".join(price_bits) or "price N/A"
    header = (
        f"{product.title}. Brand: {product.brand or 'N/A'}. {pricing}. "
        f"Rating: {product.rating or 'N/A'}. "
        f"Costco item number: {product.item_code}."
    )
    chunks = [header]
    if product.description:
        chunks.append(f"{product.title} — Description: {product.description}")
    if product.features:
        chunks.append(f"{product.title} — Features: " + "; ".join(product.features))
    return chunks


def index_product(product: ProductData) -> int:
    """Replace any existing chunks for this item and store fresh ones."""
    collection = get_collection()
    # Idempotent: clear prior chunks for this item before re-adding.
    collection.delete(where={"item_code": product.item_code})

    chunks = _chunks_for(product)
    ids = [f"{product.item_code}-{i}" for i in range(len(chunks))]
    # Store the full record as JSON so products can be listed/edited without
    # re-scraping (metadata values must be primitives — a JSON string is fine).
    data_json = product.model_dump_json()
    metadatas = [
        {
            "item_code": product.item_code,
            "title": product.title,
            "price": product.price,
            "_data": data_json,
        }
        for _ in chunks
    ]
    collection.add(ids=ids, documents=chunks, metadatas=metadatas)
    return len(chunks)


def _product_from_meta(meta: dict) -> ProductData:
    """Reconstruct a full ProductData from a chunk's stored metadata."""
    raw = meta.get("_data")
    if raw:
        try:
            return ProductData(**json.loads(raw))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    # Legacy fallback (pre-_data records).
    return ProductData(
        item_code=meta.get("item_code", ""),
        title=meta.get("title", ""),
        price=meta.get("price", ""),
    )


def list_products() -> list[ProductData]:
    collection = get_collection()
    data = collection.get(include=["metadatas"])
    seen: dict[str, ProductData] = {}
    for meta in data.get("metadatas") or []:
        code = meta.get("item_code")
        if code and code not in seen:
            seen[code] = _product_from_meta(meta)
    return list(seen.values())


def get_product(item_code: str) -> ProductData | None:
    data = get_collection().get(where={"item_code": item_code}, include=["metadatas"])
    metas = data.get("metadatas") or []
    return _product_from_meta(metas[0]) if metas else None


def update_product(product: ProductData) -> ProductData:
    """Save edited fields (re-chunks/re-embeds so chat context reflects them)."""
    index_product(product)
    return product


def delete_product(item_code: str) -> None:
    get_collection().delete(where={"item_code": item_code})


def count_products() -> int:
    return len(list_products())


def _retrieve(question: str, k: int):
    collection = get_collection()
    if collection.count() == 0:
        return [], []
    result = collection.query(
        query_texts=[question],
        n_results=min(k, collection.count()),
        include=["documents", "metadatas"],
    )
    docs = (result.get("documents") or [[]])[0]
    metas = (result.get("metadatas") or [[]])[0]
    return docs, metas


_LANG_NAMES = {
    "en": "English",
    "yue": "Cantonese, written in Traditional Chinese characters",
    "es": "Spanish",
    "fr": "French",
}


def _parse_json_obj(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


def chat(
    question: str, history: list[Message], language: str = "en"
) -> tuple[str, str, str, str, list[Citation], bool]:
    """Returns (answer, answer_en, question_foreign, question_en, citations, not_found)."""
    """Answer a question grounded in retrieved product context."""
    docs, metas = _retrieve(question, config.TOP_K)
    product_context = (
        "\n\n".join(f"- {doc}" for doc in docs) if docs else "(no products are indexed yet)"
    )

    # Pull relevant reference-doc chunks (policies, rules, etc.).
    import knowledge  # local import avoids a circular import at module load

    kchunks = knowledge.retrieve(question, 4)

    context_parts = [f"PRODUCTS:\n{product_context}"]
    if kchunks:
        ktext = "\n\n".join(f"- ({title}) {text}" for text, title in kchunks)
        context_parts.append(f"KNOWLEDGE (Costco policies / reference docs):\n{ktext}")
    context = "\n\n".join(context_parts)

    # Distinct products used as context, for citation chips.
    citations: list[Citation] = []
    seen: set[str] = set()
    for meta in metas:
        code = meta.get("item_code")
        if code and code not in seen:
            seen.add(code)
            citations.append(Citation(item_code=code, title=meta.get("title", "")))

    messages = [{"role": m.role, "content": m.content} for m in history]
    messages.append(
        {
            "role": "user",
            "content": f"CONTEXT:\n{context}\n\nQUESTION: {question}",
        }
    )

    system = _SYSTEM_PROMPT
    guidelines = settings_store.get_guidelines().strip()
    if guidelines:
        system += (
            "\n\nANSWERING GUIDELINES (follow these when helping a shopper "
            "choose a product):\n" + guidelines
        )
    client = _get_client()

    # English: single reply, marker-based (unchanged behaviour).
    if not language or language == "en":
        response = client.messages.create(
            model=config.CHAT_MODEL, max_tokens=2048, system=system, messages=messages
        )
        answer = "".join(b.text for b in response.content if b.type == "text").strip()
        not_found = NOT_FOUND_MARKER in answer
        if not_found:
            answer = answer.replace(NOT_FOUND_MARKER, "").strip()
            citations = []
        return answer, answer, question, question, citations, not_found

    # Non-English: one call producing both languages (for the two-tab UI).
    lang_name = _LANG_NAMES.get(language, "English")
    system += (
        f"\n\nBILINGUAL OUTPUT: The shopper is using {lang_name}. IGNORE the earlier "
        f"instruction about the {NOT_FOUND_MARKER} token. Instead reply with ONLY a "
        "JSON object (no code fence, no extra text) with these exact keys:\n"
        f'  "answer_foreign": your full reply written in {lang_name};\n'
        '  "answer_en": the exact same reply written in English;\n'
        f'  "question_foreign": the user\'s question written in {lang_name};\n'
        '  "question_en": the user\'s question written in English;\n'
        '  "product_not_found": true only if the user asked about a PRODUCT that is '
        "not in the PRODUCTS context (then answer_* should say you don't have that "
        "product yet and ask for its Costco item number), otherwise false.\n"
        "Keep brand names, product names, and Costco item numbers unchanged. Apply "
        "all the grounding and guideline rules above when composing the reply."
    )
    response = client.messages.create(
        model=config.CHAT_MODEL, max_tokens=3000, system=system, messages=messages
    )
    raw = "".join(b.text for b in response.content if b.type == "text").strip()
    data = _parse_json_obj(raw)
    answer_foreign = (data.get("answer_foreign") or "").strip() or raw
    answer_en = (data.get("answer_en") or "").strip() or answer_foreign
    q_foreign = (data.get("question_foreign") or question).strip()
    q_en = (data.get("question_en") or question).strip()
    not_found = bool(data.get("product_not_found"))
    if not_found:
        citations = []
    return answer_foreign, answer_en, q_foreign, q_en, citations, not_found
