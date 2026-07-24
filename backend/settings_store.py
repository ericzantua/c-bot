"""Persistent, user-editable app settings (currently: AI answering guidelines).

Stored as JSON on disk so edits survive restarts. Edited via GET/PUT /settings.
"""
import json
import os

SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "settings.json")

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


def _load() -> dict:
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def get_guidelines() -> str:
    return _load().get("answer_guidelines") or DEFAULT_GUIDELINES


def set_guidelines(text: str) -> str:
    data = _load()
    data["answer_guidelines"] = text
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return get_guidelines()
