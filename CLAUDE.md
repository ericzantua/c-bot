# CLAUDE.md — C-Bot project map

RAG chatbot for Costco products + policies: index by item code / URL / photo / CDP-tabs,
ask & compare, multilingual (en/yue/es/fr) via text or voice with a Lottie avatar.
Backend = FastAPI + ChromaDB + Playwright + Claude (Sonnet 4.6) + ElevenLabs TTS.
Frontend = React/Vite + Web Speech API (STT) + lottie-react. Pages: Chat · Products · Settings.

## 1. Structure
```
costco-c-bot/
├── backend/
│   ├── main.py            FastAPI app + all endpoints
│   ├── config.py          env/settings (models, dirs, delays)
│   ├── models.py          Pydantic request/response schemas
│   ├── scraper.py         Playwright costco.ca scraper (JSON-LD + fallbacks)
│   ├── vision.py          Claude vision → item-code extraction
│   ├── samples.py         canned mock products (local testing, no scrape)
│   ├── tts.py             server-side text-to-speech (ElevenLabs default, OpenAI swappable)
│   ├── settings_store.py  persisted editable settings (AI answer guidelines) → settings.json
│   ├── knowledge.py       reference-doc knowledge base (policies etc.): chunk/embed/store in separate Chroma collection; retrieval merged into chat
│   ├── rag.py             ChromaDB + embeddings + Claude chat (grounded, guideline-injected, bilingual)
│   ├── requirements.txt   Python deps (incl. pypdf for PDF knowledge docs)
│   └── .env.example       env template
├── frontend/
│   ├── index.html, vite.config.js, package.json
│   ├── public/store-bg.png  blurred store aisle → chat stage background
│   └── src/
│       ├── App.jsx        top nav (Chat·Products·Settings) + 🌐 language selector + view switch; owns product list
│       ├── api.js         fetch client → /api proxy
│       ├── languages.js   supported langs (en/yue/es/fr) + bcp47For()
│       ├── styles.css     all styling
│       ├── components/
│       │   ├── ChatWindow.jsx     Chat page: character stage (store bg) + conversation (RIGHT, bilingual tabs) + bottom voice bar
│       │   ├── Products.jsx       Products page: ingestion panel + editable product cards (save/delete)
│       │   ├── Settings.jsx       Settings page: AI guidance editor + Knowledge base (add text/file, list, delete)
│       │   ├── Message.jsx        one bubble + citation chips
│       │   └── CBotCharacter.jsx  Lottie avatar (transparent, red vest, "Major Sales"); PLAYS while talking, PAUSES while listening; tap = interrupt
│       ├── assets/cbot.json       active Lottie avatar (user's ericz.json; recolored red, bg layer removed)
│       └── hooks/useVoice.js      wake word + STT(locale) + backend-TTS + never-deaf recognizer + conversation mode
└── README.md
```

## 2. Function / endpoint index
Backend endpoints (`backend/main.py`):
- `GET /health` → `{status, products}` — liveness + count
- `POST /index` `{item_codes[]}` → `IndexResponse` — scrape→embed→store each code
- `POST /index/url` `{urls[]}` → `IndexResponse` — scrape+index from full costco.ca product URLs (bypasses item#→URL guessing)
- `POST /index/open-tabs` → `IndexResponse` — index Costco product tabs open in CDP Chrome (the working scrape path)
- `POST /index/manual` `{products[]}` → `IndexResponse` — index supplied ProductData (no scrape)
- `POST /index/mock` → `IndexResponse` — index bundled samples.SAMPLE_PRODUCTS
- `POST /index/photo` multipart `image` → `PhotoIndexResponse` — vision codes → same pipeline
- `POST /chat` `{question, history[], language}` → `{answer, answer_en, question_foreign, question_en, citations[], product_not_found}` — RAG answer; non-English returns both language versions (for bilingual tabs)
- `GET/POST /knowledge`, `POST /knowledge/file` (multipart txt/md/pdf), `DELETE /knowledge/{doc_id}` — reference-doc knowledge base
- `GET /products` → `{products[]}` — list full editable ProductData records
- `PUT /products/{item_code}` `ProductData` → edit fields (regular/promo price, valid-until, etc.); re-embeds
- `DELETE /products/{item_code}` → `{status,item_code}` — remove
- `POST /tts` `{text}` → audio/mpeg — server-side TTS (`tts.synthesize`, ElevenLabs/OpenAI via TTS_PROVIDER)
- `GET/PUT /settings` `{answer_guidelines}` — editable AI answering guidelines (`settings_store`), injected into chat system prompt
- `_index_scraped(labels, scraped) → IndexResult[]` — store scraped results (shared by code/URL paths)
- `_ingest(codes) → IndexResult[]` — scrape by item code then index
- `_index_direct(products) → IndexResult[]` — store supplied ProductData (manual/mock, no scrape)

`backend/scraper.py`:
- `scrape_products(codes) → list[ProductData|ScrapeError]` — scrape each w/ jittered delay
- `scrape_urls(urls) → list[ProductData|ScrapeError]` — scrape full product URLs directly
- `scrape_open_tabs() → list[ProductData|ScrapeError]` — read Costco tabs already open in CDP Chrome (no nav; beats Akamai). Needs CDP_URL
- `_is_product_url(url) → bool` — costco.ca + /p/ or .product.
- `_item_code_from_url(url) → str` — derive id from URL (partNumber query / `\d{5,}` in path). Note: Costco URL is `/p/-/<slug>/<partNumber>`, partNumber ≠ customer item number
- `_open_context(pw) → (context, closer)` — build browser ctx honouring stealth/channel/headless/profile flags
- `_warm_up(context)` — visit homepage first so Akamai sets clearance cookie before product pages
- `_scrape_one(context, url, code) → ProductData|ScrapeError` — goto url, extract/detect-block
- `_extract(html, code, url) → ProductData` — JSON-LD Product first, DOM/meta fallback
- `_parse_json_ld / _iter_nodes / _is_product` — schema.org Product finder
- `_product_url(code)` = `{COSTCO_BASE}/product.{code}.html`; `_looks_blocked(html)` — bot-detect markers

`backend/vision.py`:
- `extract_item_codes(bytes, content_type) → (codes[], note)` — Claude vision, base64 image
- `_parse_codes(text) → (codes[], note)` — JSON array parse, regex `\d{6,7}` fallback
- `_detect_media_type(data, fallback)` — magic-byte sniff

`backend/rag.py`:
- `get_collection()` — persistent Chroma collection + SentenceTransformer embed fn (cosine)
- `index_product(ProductData) → int` — delete-then-add chunks; stores full record as `_data` JSON in metadata; header chunk includes regular/promo/valid-until
- `_chunks_for(product) → str[]` — header + description + features chunks
- `list_products() → ProductData[]` (full, from `_data`); `get_product(code)`; `update_product(p)` (re-index); `delete_product(code)`; `count_products()`
- `_product_from_meta(meta) → ProductData` — parse `_data` JSON (legacy fallback to bare fields)
- `_retrieve(question, k) → (docs, metas)` — top-k product query
- `chat(question, history, language) → (answer, answer_en, question_foreign, question_en, citations, not_found)` — grounded Claude call; injects guidelines + knowledge chunks; English path = marker-based single answer; non-English = one call returning a JSON object with both languages (`_parse_json_obj`)

`backend/knowledge.py`: `get_kcollection()`, `add_document(title,text,source)`, `extract_text(filename,data)` (pdf via pypdf), `list_documents()`, `delete_document(id)`, `retrieve(query,k) → [(text,title)]`, `_chunk_text()`. Uses `rag.chroma_client()` + `rag.embedding_function()` (shared).

`frontend/src/api.js`: `indexCodes/indexUrls/indexOpenTabs/indexManual/indexPhoto/loadSamples`,
`sendChat(q,history,language)`, `listProducts/updateProduct/deleteProduct`, `ttsSynthesize(text)→Blob`,
`getSettings/saveSettings`, `listKnowledge/addKnowledgeText/addKnowledgeFile/deleteKnowledge`.

`frontend/src/hooks/useVoice.js`: `useVoice(onPrompt, lang)` → `{recognitionSupported, speechSupported,
enabled, state, error, debug, bargeIn, toggleBargeIn, toggle, triggerCapture, speak, cancelSpeak}`.
`lang` = BCP-47 (STT locale). Recognizer NEVER stops while enabled (onend always restarts w/ identity
guard); half-duplex = ignore results while speaking + flush recognizer on speech-end (kills the
Stop-self-answer bug); audio unlocked on mic tap (autoplay); animation starts on `onplaying` (audio↔mouth sync).

## 3. Key decisions
- **Playwright (headless Chromium) over requests** — costco.ca has Akamai bot detection; needs a real browser fingerprint + JS render.
- **Stealth mode** (config flags) — hides `navigator.webdriver` + automation tells, optional real-Chrome channel / headed / persistent profile, jittered pacing. Helped fingerprint but Akamai still 403'd (blocks automated navigation even on residential IP + real Chrome).
- **CDP open-tabs = the scrape that actually works** — Akamai blocks any Playwright-*navigated* page (403), but not a human-navigated one. So: user starts Chrome w/ `--remote-debugging-port=9222`, browses to product pages by hand (clearing challenges), sets `CDP_URL`; app connects via CDP and READS the open tabs' DOM (no navigation). Verified pulling real data.
- **JSON-LD first in scraper** — schema.org Product is stabler than CSS selectors across redesigns; DOM/meta are fallback.
- **ChromaDB persistent + local all-MiniLM-L6-v2** — free, offline embeddings; survives restarts (`chroma_db/`).
- **`[PRODUCT_NOT_FOUND]` marker** — Claude emits it when asked product isn't in retrieved context; backend strips it, sets flag → drives on-demand ingestion UI (feature 1c).
- **Grounding via system prompt** — Claude answers ONLY from CONTEXT block; context injected in user turn (per-turn, not cached system).
- **Model `claude-sonnet-4-6`** — pinned by spec for chat + vision; overridable via env.
- **Web Speech API for STT** (en-CA); **server-side TTS** (ElevenLabs `eleven_flash_v2_5`) played as audio, browser SpeechSynthesis fallback.
- **TTS voice = "River"** (`SAz9YHcvj6GT2YYXdXww`, neutral American) — default because ElevenLabs FREE tier can't use library/Canadian voices via API (402); Canadian needs a paid plan → then set `ELEVENLABS_VOICE_ID`.
- **Half-duplex by default** — mic pauses while the bot talks (fixes speaker echo feeding the bot's words back). Interrupt via tap-avatar / Stop. `toggleBargeIn` (Talk-over) keeps mic live for headphone users = true voice barge-in.
- **Conversation mode** — say "C-Bot" once, then talk freely; ~15s silence → wake-word standby.
- **Lottie avatar** (`lottie-react`) — PLAYS while speaking, PAUSES while listening. `assets/cbot.json` = user's ericz.json, recolored clothing red + "Major Sales" chest overlay (`.cbot-logo`, tweak `--logo-top`/font-size) + Background layer removed (transparent over store bg). Original backup: `/tmp/cbot.backup.json`.
- **Chat layout** — character stage (left) over blurred store background image, conversation panel (right), status + all voice buttons in a bottom voice bar. "Listen" button (was "Stop") stops audio+anim and listens.
- **Knowledge base** — reference docs (policies/rules/returns) in a SEPARATE Chroma collection (`costco_knowledge`); chat retrieves top-4 knowledge chunks + products, prompt distinguishes PRODUCTS vs KNOWLEDGE. Loaded a real Costco returns/policy doc (15 chunks). RTF isn't accepted by the uploader (txt/md/pdf only) — convert via `textutil` first.
- **Multilingual (en/yue/es/fr)** — 🌐 selector; `/chat` `language` param → Claude answers in it (data stays grounded, translated; item#/brands kept). TTS auto-detects language (ElevenLabs). STT locale = `bcp47For(lang)`. Cantonese = Traditional Chinese text; voice/STT lean Mandarin (weaker).
- **Bilingual tabs** — non-English shows [lang]|English tabs; each message stored in both languages; backend returns both per turn. "⌨️ Input" toggle: speak/type English while C-Bot answers in the selected language (STT switches to en).
- **Editable products** — full ProductData stored as `_data` JSON in Chroma metadata → edit (PUT) without re-scraping; re-embeds on save. Fields incl. regular/promo price + `price_valid_until`.
- **Settings/guidelines** — persisted in `settings.json` (`settings_store`), injected into chat system prompt (category-specific clarifying questions).
- Online only (offline/Ollama idea dropped). Chat + vision = Claude Sonnet 4.6.
- **Vite `/api` proxy** — same-origin dev, no CORS friction. Mic needs HTTPS on non-localhost (Safari).

## 4. Status
Fully built & running locally (user's Mac). Backend has real data: 7 products (incl. 3 real TVs via CDP open-tabs) + a Costco returns/policy knowledge doc.
- **Verified live** (backend TestClient / running server): chat (grounded, compare, not-found), editable products (`PUT`), settings/guidelines, knowledge add→retrieve→delete + policy Q&A, **multilingual chat** (es/fr/yue) + **bilingual** response (answer+answer_en, question both langs), **TTS** (`/tts` 200 MP3, River voice). Frontend builds clean every change.
- **Costco scraping**: works ONLY via **CDP open-tabs** (user opens product pages by hand in `--remote-debugging-port=9222` Chrome; app reads DOM). Automated `/index` & `/index/url` still 403 (Akamai blocks Playwright navigation even on residential IP). Samples/manual/photo are always-on fallbacks.
- **⚠️ Backend must be restarted** to pick up the latest multilingual/bilingual `/chat` changes (rag/models/main) — user was told.
- **Browser-not-verified-by-me** (need a live browser): Lottie render, voice end-to-end after the many fixes, bilingual tabs/toggle, store-bg layout. User is testing iteratively and reporting.
- Recent voice fixes (all shipped): never-deaf recognizer, half-duplex + flush-on-speech-end (Stop no longer self-answers), autoplay unlock (ElevenLabs plays on voice-triggered replies), animation↔audio sync via `onplaying`.
- Known constraints: Python 3.14 wheels may fail (use 3.11–3.13, `.venv` is 3.13); voice best in Chrome/Edge (Safari STT unreliable); Cantonese voice/STT lean Mandarin; mic needs HTTPS off-localhost.
- No git repo (user declined `git init`).

## 5. How to run
Backend:
```
cd backend && python3.13 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt && playwright install chromium
cp .env.example .env   # set ANTHROPIC_API_KEY
uvicorn main:app --reload --port 8000
```
Frontend:
```
cd frontend && npm install && npm run dev   # http://localhost:5173
```
A py3.13 `backend/.venv` already exists (deps installed; still run `playwright install chromium`).

## 6. Environment
- `.env` (backend): `ANTHROPIC_API_KEY` (required). Optional: `CHAT_MODEL`, `VISION_MODEL`,
  `EMBED_MODEL`, `CHROMA_DIR`, `SCRAPE_DELAY_SECONDS`, `COSTCO_BASE`, `TOP_K`, `CORS_ORIGINS`,
  `STEALTH_MODE`, `HEADLESS`, `CHROME_CHANNEL`, `USER_DATA_DIR`, `CDP_URL`,
  `ELEVENLABS_API_KEY` (TTS), `TTS_PROVIDER`, `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL`, `OPENAI_API_KEY`.
- CDP scraping: start Chrome via `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --remote-debugging-port=9222 --user-data-dir="$HOME/.costco-chrome"`, browse to products by hand, set `CDP_URL=http://localhost:9222`, use "Read open Costco tab(s)".
- `backend/settings.json` (git-ignored) holds editable AI guidelines; created on first PUT /settings, else defaults from `settings_store.DEFAULT_GUIDELINES`.
- Deps: Python 3.11–3.13 (fastapi, uvicorn, anthropic, chromadb, sentence-transformers,
  playwright, beautifulsoup4, httpx, pypdf); Node 18+ (react, vite, lottie-react). First run downloads embed model (~90MB).
- Knowledge docs: uploader takes txt/md/pdf. For .rtf, convert first: `textutil -convert txt -stdout file.rtf`.
```
