"""Server-side text-to-speech. Provider-swappable via TTS_PROVIDER.

Returns (audio_bytes, media_type). Keeps the TTS API key on the server so the
frontend never sees it. Default provider is ElevenLabs (natural voices, free
tier, low-latency Flash model); OpenAI TTS is a drop-in alternative.
"""
import time

import httpx

import config

# After a provider (or a specific ElevenLabs key) reports quota-exceeded, skip it
# for this long so we don't waste a failing call on every request.
_QUOTA_COOLDOWN_SECONDS = 3600
_skip_until: dict[str, float] = {}  # provider -> epoch
_key_skip_until: dict[str, float] = {}  # elevenlabs api key -> epoch


class TTSError(Exception):
    """Raised with a user-facing message when synthesis fails."""


def _has_key(provider: str) -> bool:
    if provider == "elevenlabs":
        return bool(config.ELEVENLABS_KEYS)
    if provider == "openai":
        return bool(config.OPENAI_API_KEY)
    return False


def _is_quota_error(msg: str) -> bool:
    m = msg.lower()
    return "402" in m or "quota" in m or "limit" in m


def _call(provider: str, text: str) -> tuple[bytes, str]:
    if provider == "elevenlabs":
        return _elevenlabs(text)
    if provider == "openai":
        return _openai(text)
    raise TTSError(f"Unknown TTS provider '{provider}'.")


def synthesize(text: str) -> tuple[bytes, str]:
    """Synthesize speech, trying the primary provider then falling back.

    Primary = TTS_PROVIDER (default elevenlabs). On failure (esp. quota) it falls
    back to the other provider if that one's key is configured.
    """
    text = (text or "").strip()
    if not text:
        raise TTSError("Nothing to speak.")

    primary = config.TTS_PROVIDER.strip().lower() or "elevenlabs"
    if primary not in ("elevenlabs", "openai"):
        raise TTSError(f"Unknown TTS_PROVIDER '{primary}' (use 'elevenlabs' or 'openai').")

    order = [primary] + [p for p in ("elevenlabs", "openai") if p != primary]
    errors: list[str] = []
    for provider in order:
        if not _has_key(provider):
            continue
        if time.time() < _skip_until.get(provider, 0.0):  # in quota cooldown
            continue
        try:
            return _call(provider, text)
        except TTSError as exc:
            if _is_quota_error(str(exc)):
                _skip_until[provider] = time.time() + _QUOTA_COOLDOWN_SECONDS
            errors.append(f"{provider}: {exc}")

    raise TTSError(" · ".join(errors) or "TTS providers are over quota — using the browser voice.")


def _elevenlabs_call(api_key: str, text: str) -> tuple[bytes, str]:
    url = (
        f"https://api.elevenlabs.io/v1/text-to-speech/{config.ELEVENLABS_VOICE_ID}"
        "?output_format=mp3_44100_128"
    )
    try:
        resp = httpx.post(
            url,
            headers={
                "xi-api-key": api_key,
                "accept": "audio/mpeg",
                "content-type": "application/json",
            },
            json={
                "text": text,
                "model_id": config.ELEVENLABS_MODEL,
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            },
            timeout=30,
        )
    except httpx.HTTPError as exc:
        raise TTSError(f"ElevenLabs request failed: {exc}") from exc
    if resp.status_code != 200:
        raise TTSError(f"ElevenLabs error {resp.status_code}: {resp.text[:200]}")
    return resp.content, "audio/mpeg"


def _elevenlabs(text: str) -> tuple[bytes, str]:
    """Try each configured ElevenLabs key, skipping ones in quota cooldown."""
    keys = config.ELEVENLABS_KEYS
    if not keys:
        raise TTSError("ELEVENLABS_API_KEY is not set (see backend/.env).")
    now = time.time()
    errors: list[str] = []
    for i, key in enumerate(keys):
        if now < _key_skip_until.get(key, 0.0):
            continue
        try:
            return _elevenlabs_call(key, text)
        except TTSError as exc:
            if _is_quota_error(str(exc)):
                _key_skip_until[key] = time.time() + _QUOTA_COOLDOWN_SECONDS
            errors.append(f"key{i + 1}: {str(exc)[:70]}")
    detail = " | ".join(errors) if errors else "all keys in quota cooldown"
    # "quota" in the message makes synthesize() apply the provider cooldown + fallback.
    raise TTSError(f"ElevenLabs quota — all keys exhausted ({detail}).")


def _openai(text: str) -> tuple[bytes, str]:
    if not config.OPENAI_API_KEY:
        raise TTSError("OPENAI_API_KEY is not set (see backend/.env).")
    try:
        resp = httpx.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
            json={
                "model": config.OPENAI_TTS_MODEL,
                "voice": config.OPENAI_TTS_VOICE,
                "input": text,
                "response_format": "mp3",
            },
            timeout=30,
        )
    except httpx.HTTPError as exc:
        raise TTSError(f"OpenAI TTS request failed: {exc}") from exc
    if resp.status_code != 200:
        raise TTSError(f"OpenAI TTS error {resp.status_code}: {resp.text[:200]}")
    return resp.content, "audio/mpeg"
