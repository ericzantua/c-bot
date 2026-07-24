"""Persistent, user-editable app settings (currently: AI answering guidelines).

Stored in Supabase (single `settings` row) so edits survive restarts and are
shared between the cloud API and local ingestion. Edited via GET/PUT /settings.
"""
import db

DEFAULT_GUIDELINES = (
    "Before recommending a product, ask ONE or TWO brief clarifying questions "
    "tailored to the category, then recommend from the indexed products:\n"
    "- TVs: ask their preferred screen size and price range.\n"
    "- Computers / desktops: ask which specs matter (CPU, RAM, storage) and budget.\n"
    "- Laptops: ask what they'll mainly use it for (work, school, gaming, travel) "
    "and how important portability / battery life is.\n"
    "- Appliances: ask about available space / dimensions and capacity.\n"
    "Keep the questions short and conversational. If the shopper has already given "
    "these details, skip the questions and answer directly."
)


def get_guidelines() -> str:
    rows = (
        db.client()
        .table("settings")
        .select("answer_guidelines")
        .eq("id", 1)
        .limit(1)
        .execute()
        .data
        or []
    )
    stored = rows[0].get("answer_guidelines") if rows else None
    return stored or DEFAULT_GUIDELINES


def set_guidelines(text: str) -> str:
    db.client().table("settings").upsert(
        {"id": 1, "answer_guidelines": text}
    ).execute()
    return get_guidelines()
