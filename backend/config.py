"""Central configuration, loaded from the environment / .env file."""
import os

from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# The project brief pins chat to Claude Sonnet 4.6; vision reuses the same model.
CHAT_MODEL = os.getenv("CHAT_MODEL", "claude-sonnet-4-6")
VISION_MODEL = os.getenv("VISION_MODEL", "claude-sonnet-4-6")

# Local, free embeddings.
EMBED_MODEL = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")

# ChromaDB persists here so indexed products survive restarts.
CHROMA_DIR = os.getenv("CHROMA_DIR", "./chroma_db")
COLLECTION_NAME = "costco_products"

# Costco bot-detection etiquette.
COSTCO_BASE = os.getenv("COSTCO_BASE", "https://www.costco.ca")
SCRAPE_DELAY_SECONDS = float(os.getenv("SCRAPE_DELAY_SECONDS", "2"))


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


# --- Scraper / stealth options (see README "Making scraping work") ---
# Apply anti-detection tweaks (init script + automation flags off).
STEALTH_MODE = _flag("STEALTH_MODE", "true")
# Run a visible browser. headless=false is far less detectable — use it locally
# on a machine with a display / residential IP.
HEADLESS = _flag("HEADLESS", "true")
# Use installed Google Chrome instead of bundled Chromium (better fingerprint).
# e.g. CHROME_CHANNEL=chrome  (requires Chrome installed). Empty = bundled.
CHROME_CHANNEL = os.getenv("CHROME_CHANNEL", "").strip()
# Persistent profile dir so cookies / anti-bot tokens carry across requests.
# Empty = ephemeral context. e.g. USER_DATA_DIR=./.pw_profile
USER_DATA_DIR = os.getenv("USER_DATA_DIR", "").strip()
# Connect to an already-running Chrome (launched with --remote-debugging-port)
# instead of launching one. Most reliable vs Akamai: you clear any bot challenge
# manually in that Chrome, and the scraper reuses the live, cleared session.
# e.g. CDP_URL=http://localhost:9222
CDP_URL = os.getenv("CDP_URL", "").strip()

# Retrieval.
TOP_K = int(os.getenv("TOP_K", "8"))

# --- Text-to-speech (online, server-side so the key stays private) ---
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "elevenlabs")  # elevenlabs | openai | browser
# "browser" = /tts returns 204 and the frontend uses the device's built-in voice
# (free, no cloud). "elevenlabs"/"openai" auto-fall-back to each other on quota.
# ElevenLabs: natural voices + a free tier. Flash model = low latency for barge-in.
# Rotate through multiple keys to stretch free tiers: put extras (comma-separated)
# in ELEVENLABS_API_KEYS. On quota, the next key is used; all-exhausted → fallback.
# Accept keys on either var, each optionally comma-separated (tolerant of a
# user putting all keys on ELEVENLABS_API_KEY).
ELEVENLABS_KEYS: list[str] = []
for _k in (
    os.getenv("ELEVENLABS_API_KEY", "") + "," + os.getenv("ELEVENLABS_API_KEYS", "")
).split(","):
    _k = _k.strip()
    if _k and _k not in ELEVENLABS_KEYS:
        ELEVENLABS_KEYS.append(_k)
ELEVENLABS_API_KEY = ELEVENLABS_KEYS[0] if ELEVENLABS_KEYS else ""
# "River" — neutral American premade voice, usable on the ElevenLabs free tier
# (library/Canadian voices need a paid plan). Override via ELEVENLABS_VOICE_ID.
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "SAz9YHcvj6GT2YYXdXww")
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5")
# OpenAI TTS: cheaper at scale. Swap TTS_PROVIDER=openai to use.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
OPENAI_TTS_VOICE = os.getenv("OPENAI_TTS_VOICE", "alloy")

# Frontend dev server origins allowed by CORS.
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
).split(",")
