"""Retrieval-Augmented Generation over the Supabase (pgvector) product store.

Responsibilities:
  * chunk + embed (Voyage) + store scraped products in Supabase
  * list / delete products
  * retrieve relevant chunks for a query and answer with Claude, grounded only
    in that context.
"""
import json

from anthropic import Anthropic

import config
import db
import embeddings
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


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY is not set (see backend/.env).")
        _client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


def _chunks_for(product: ProductData) -> list[str]:
    """Turn a product into a handful of self-contained text chunks."""
    price_bits = []
    if product.price:
        bit = f"current price {product.price}"
        if product.price_date:
            bit += f" (as of {product.price_date})"
        price_bits.append(bit)
    if product.regular_price:
        price_bits.append(f"regular price {product.regular_price}")
    if product.promo_price:
        bit = f"sale price {product.promo_price}"
        if product.price_valid_until:
            bit += f" (until {product.price_valid_until})"
        price_bits.append(bit)
    elif product.price_valid_until:
        price_bits.append(f"price valid until {product.price_valid_until}")
    pricing = "; ".join(price_bits) or "price N/A"
    model_bit = f"Model: {product.model}. " if product.model else ""
    header = (
        f"{product.title}. Brand: {product.brand or 'N/A'}. {model_bit}{pricing}. "
        f"Rating: {product.rating or 'N/A'}. "
        f"Costco item number: {product.item_code}."
    )
    chunks = [header]
    if product.description:
        chunks.append(f"{product.title} — Description: {product.description}")
    if product.features:
        chunks.append(f"{product.title} — Features: " + "; ".join(product.features))
    if product.specifications:
        spec_txt = "; ".join(f"{k}: {v}" for k, v in product.specifications.items())
        chunks.append(f"{product.title} — Specifications: {spec_txt}")
    return chunks


def index_product(product: ProductData) -> int:
    """Upsert the product record + replace its embedded chunks in Supabase."""
    sb = db.client()
    # Upsert the full record (edit/list without re-scraping).
    sb.table("products").upsert(
        {"item_code": product.item_code, "data": json.loads(product.model_dump_json())}
    ).execute()
    # Idempotent: clear prior chunks, then insert fresh embedded ones.
    sb.table("product_chunks").delete().eq("item_code", product.item_code).execute()

    chunks = _chunks_for(product)
    vectors = embeddings.embed(chunks, input_type="document")
    rows = [
        {"item_code": product.item_code, "content": chunk, "embedding": vec}
        for chunk, vec in zip(chunks, vectors)
    ]
    if rows:
        sb.table("product_chunks").insert(rows).execute()
    return len(rows)


def _product_from_row(row: dict) -> ProductData:
    """Reconstruct a ProductData from a `products.data` jsonb row."""
    data = row.get("data") or {}
    if isinstance(data, str):
        data = json.loads(data)
    return ProductData(**data)


def list_products() -> list[ProductData]:
    rows = db.client().table("products").select("data").execute().data or []
    return [_product_from_row(r) for r in rows]


def get_product(item_code: str) -> ProductData | None:
    rows = (
        db.client()
        .table("products")
        .select("data")
        .eq("item_code", item_code)
        .limit(1)
        .execute()
        .data
        or []
    )
    return _product_from_row(rows[0]) if rows else None


def update_product(product: ProductData) -> ProductData:
    """Save edited fields (re-chunks/re-embeds so chat context reflects them)."""
    index_product(product)
    return product


def delete_product(item_code: str) -> None:
    # chunks cascade-delete via the FK.
    db.client().table("products").delete().eq("item_code", item_code).execute()


def count_products() -> int:
    res = (
        db.client()
        .table("products")
        .select("item_code", count="exact")
        .execute()
    )
    return res.count or 0


def _retrieve(query_vec: list[float], k: int):
    """Return (docs, metas) — chunk texts + {item_code, title} for citations."""
    if not query_vec:
        return [], []
    rows = (
        db.client()
        .rpc("match_products", {"query_embedding": query_vec, "match_count": k})
        .execute()
        .data
        or []
    )
    docs, metas = [], []
    for r in rows:
        docs.append(r.get("content", ""))
        data = r.get("data") or {}
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, ValueError):
                data = {}
        metas.append(
            {"item_code": r.get("item_code", ""), "title": data.get("title", "")}
        )
    return docs, metas


_LANG_NAMES = {
    "en": "English",
    "yue": "Cantonese, written in Traditional Chinese characters",
    "es": "Spanish",
    "fr": "French",
    "hi": "Hindi",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "pt": "Portuguese",
}


def chat(
    question: str, history: list[Message], language: str = "en"
) -> tuple[str, str, str, str, list[Citation], bool]:
    """Returns (answer, answer_en, question_foreign, question_en, citations, not_found)."""
    """Answer a question grounded in retrieved product context."""
    # Embed the question once, reuse for both product + knowledge retrieval.
    query_vec = embeddings.embed_query(question)
    docs, metas = _retrieve(query_vec, config.TOP_K)
    product_context = (
        "\n\n".join(f"- {doc}" for doc in docs) if docs else "(no products are indexed yet)"
    )

    # Pull relevant reference-doc chunks (policies, rules, etc.).
    import knowledge  # local import avoids a circular import at module load

    kchunks = knowledge.retrieve(query_vec, 4)

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

    # Non-English: one call producing both languages via a FORCED tool call. The
    # SDK returns tool_use.input as a validated dict, so the English field always
    # comes back structured — this replaces free-text JSON parsing, which
    # intermittently failed (truncation / stray braces) and left the English tab
    # blank or showing the foreign text.
    lang_name = _LANG_NAMES.get(language, language)
    system += (
        f"\n\nBILINGUAL OUTPUT: The shopper is using {lang_name}. IGNORE the earlier "
        f"instruction about the {NOT_FOUND_MARKER} token. Instead, ALWAYS reply by calling "
        "the `provide_bilingual_answer` tool, filling every field. Keep brand names, product "
        "names, and Costco item numbers unchanged across both languages. Apply all the "
        "grounding and guideline rules above when composing the reply."
    )
    tool = {
        "name": "provide_bilingual_answer",
        "description": "Return the assistant's reply and the user's question, each in both languages.",
        "input_schema": {
            "type": "object",
            "properties": {
                "answer_foreign": {"type": "string", "description": f"The full reply written in {lang_name}."},
                "answer_en": {"type": "string", "description": "The exact same reply written in English."},
                "question_foreign": {"type": "string", "description": f"The user's question written in {lang_name}."},
                "question_en": {"type": "string", "description": "The user's question written in English."},
                "product_not_found": {
                    "type": "boolean",
                    "description": (
                        "True only if the user asked about a PRODUCT not present in the PRODUCTS "
                        "context (then the answers should say you don't have it yet and ask for its "
                        "Costco item number); otherwise false."
                    ),
                },
            },
            "required": ["answer_foreign", "answer_en", "question_foreign", "question_en", "product_not_found"],
        },
    }
    response = client.messages.create(
        model=config.CHAT_MODEL,
        max_tokens=4096,
        system=system,
        messages=messages,
        tools=[tool],
        tool_choice={"type": "tool", "name": "provide_bilingual_answer"},
    )
    data = next(
        (b.input for b in response.content
         if b.type == "tool_use" and b.name == "provide_bilingual_answer"),
        {},
    )
    answer_foreign = (data.get("answer_foreign") or "").strip()
    answer_en = (data.get("answer_en") or "").strip() or answer_foreign
    q_foreign = (data.get("question_foreign") or question).strip()
    q_en = (data.get("question_en") or question).strip()
    not_found = bool(data.get("product_not_found"))
    if not_found:
        citations = []
    return answer_foreign, answer_en, q_foreign, q_en, citations, not_found
