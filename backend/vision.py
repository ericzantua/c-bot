"""Extract Costco item numbers from an uploaded photo using Claude vision."""
import base64
import json
import re

from anthropic import Anthropic

import config

_client: Anthropic | None = None

# Costco item numbers are typically 6-7 digits.
_ITEM_CODE_RE = re.compile(r"\b\d{6,7}\b")

_MEDIA_TYPES = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
    b"RIFF": "image/webp",  # WEBP starts with RIFF....WEBP
}

_PROMPT = (
    "This image is a Costco price tag, shelf label, or product package. "
    "Find every Costco item number visible in it. Costco item numbers are "
    "6 or 7 digit numbers, often labelled 'Item' or printed near the price. "
    "Do NOT include prices, weights, phone numbers, UPC/barcodes (12-13 digits), "
    "or dates. Respond with ONLY a JSON array of the item-number strings you find, "
    'e.g. ["1858512","3118678"]. If you find none, respond with [].'
)


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY is not set (see backend/.env).")
        _client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


def _detect_media_type(data: bytes, fallback: str) -> str:
    for signature, media_type in _MEDIA_TYPES.items():
        if data.startswith(signature):
            return media_type
    return fallback or "image/jpeg"


def extract_item_codes(image_bytes: bytes, content_type: str = "") -> tuple[list[str], str]:
    """Return (item_codes, note). Note carries any parse fallback info."""
    media_type = _detect_media_type(image_bytes, content_type)
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    client = _get_client()
    response = client.messages.create(
        model=config.VISION_MODEL,
        max_tokens=512,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": _PROMPT},
                ],
            }
        ],
    )

    text = "".join(block.text for block in response.content if block.type == "text").strip()

    codes, note = _parse_codes(text)
    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique = [c for c in codes if not (c in seen or seen.add(c))]
    return unique, note


def _parse_codes(text: str) -> tuple[list[str], str]:
    """Parse a JSON array of codes, falling back to a regex scan."""
    match = re.search(r"\[.*?\]", text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            codes = [str(c).strip() for c in parsed if str(c).strip()]
            if codes:
                return codes, ""
            return [], "Claude reported no item numbers in the image."
        except (json.JSONDecodeError, ValueError):
            pass
    # Fallback: pull 6-7 digit numbers directly from the reply text.
    codes = _ITEM_CODE_RE.findall(text)
    if codes:
        return codes, "Parsed item numbers from a non-JSON vision reply."
    return [], "Could not identify any item numbers in the image."
