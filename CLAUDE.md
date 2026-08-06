# CLAUDE.md — C-Bot project map

RAG chatbot for Costco products + policies: index by item code / URL / photo / CDP-tabs,
ask & compare, multilingual (en/yue/es/fr) via text or voice with a Lottie avatar.
Backend = FastAPI + Supabase (Postgres/pgvector) + Voyage embeddings + Claude (Sonnet 4.6) + ElevenLabs TTS.
Frontend = React/Vite PWA + Web Speech API (STT) + lottie-react. Pages: Chat · Products · Settings.
Deploy = all-Vercel (PWA static + Python serverless API) + Supabase; scraping stays local on the Mac.

## 1. Structure
```
costco-c-bot/
├── api/
│   └── index.py           Vercel serverless entry — mounts backend FastAPI app at /api
├── vercel.json            Vercel build (PWA) + /api/* → Python function, 60s maxDuration
├── middleware.js          Vercel Edge Middleware — gates WHOLE site (PWA + /api/*); serves /login page, verifies signed cookie (AUTH_SECRET), gates admin paths via cookie flag. Backend owns login/passwords.
├── requirements.txt       CLOUD (light) deps for the Vercel Python function
├── backend/
│   ├── main.py            FastAPI app + all endpoints (scraper imported lazily → cloud-safe)
│   ├── config.py          env/settings (Supabase, Voyage, models, TTS, scraper)
│   ├── models.py          Pydantic request/response schemas
│   ├── db.py              Supabase client (service-role; cached across warm invocations)
│   ├── embeddings.py      Voyage AI embeddings (embed / embed_query)
│   ├── supabase_schema.sql  pgvector tables + match_products/match_knowledge + RLS (run once)
│   ├── migrate_to_supabase.py  one-time: old ChromaDB → Supabase (re-embed via Voyage)
│   ├── scraper.py         Playwright costco.ca scraper (JSON-LD + fallbacks) — LOCAL only
│   ├── vision.py          Claude vision → item-code extraction
│   ├── samples.py         canned mock products (local testing, no scrape)
│   ├── tts.py             server-side text-to-speech (ElevenLabs default, OpenAI swappable)
│   ├── settings_store.py  editable AI guidelines → Supabase `settings` row
│   ├── auth.py            cookie-session auth + editable user store (Supabase `app_users`): PBKDF2 hashing, HMAC cookie sign/verify (format shared w/ middleware.js), CRUD + one-time seed
│   ├── knowledge.py       reference-doc KB (policies): chunk/Voyage-embed → Supabase; merged into chat
│   ├── rag.py             Supabase pgvector + Voyage + Claude chat (grounded, guideline-injected, bilingual)
│   ├── requirements.txt   LOCAL (full) deps: adds scraper + migration (chromadb/sentence-transformers)
│   └── .env.example       env template
├── frontend/
│   ├── index.html         + iOS PWA meta tags (apple-touch-icon, standalone)
│   ├── vite.config.js     Vite + vite-plugin-pwa (manifest, service worker) + /api dev proxy
│   ├── package.json
│   ├── public/store-bg.png  blurred store aisle → chat stage background
│   ├── public/pwa-192.png, pwa-512.png, pwa-512-maskable.png, apple-touch-icon.png  PWA icons
│   └── src/
│       ├── App.jsx        top nav + 🌐 language selector + Log out + view switch; owns product list. Brand removed. ROLE-AWARE (fetches /api/me): admin → Z-Bot·Products·Settings tabs; non-admin → Z-Bot·About tabs (Products/Settings hidden). About view rendered here.
│       │   └── components/About.jsx  About page (credits/app info); non-admin opens via top-nav tab, admin via a button in Settings (Settings takes onShowAbout prop)
│       ├── api.js         fetch client, BASE=/api (Vite proxy in dev; Vercel /api/* in prod)
│       ├── languages.js   supported langs (en/yue/es/fr) + bcp47For()
│       ├── styles.css     all styling
│       ├── components/
│       │   ├── ChatWindow.jsx     Chat page: character stage (store bg) + conversation (RIGHT, bilingual tabs) + bottom voice bar
│       │   ├── Products.jsx       Products page: manual-add form (works on any device, no scrape) + scrape/photo ingestion panel + editable product cards (save/delete)
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
- `_extract(html, code, url) → ProductData` — JSON-LD Product first, DOM/meta fallback. Parses the on-page "Item #### | Model ####" line and OVERRIDES `item_code` with the customer-facing item number (the URL/JSON-LD partNumber is a different internal id) + fills `model`. Then calls `_apply_pricing`
- `_apply_pricing(html, page_text, product)` — pricing from Costco's embedded Next.js `displayPrice` block (authoritative): `onlinePrice`=regular, `deliveredPrice`=current/effective, `aggregatedDiscountAmt`=savings. **JSON-LD's offer price is the REGULAR price, not the sale price** — so on-sale items must use `deliveredPrice`. On sale → `price`+`promo_price`=deliveredPrice, `regular_price`=onlinePrice; `price_valid_until` from the "Valid for orders placed .. to <date>" promo statement (`_norm_date` → YYYY-MM-DD)
- `_parse_json_ld / _iter_nodes / _is_product` — schema.org Product finder
- `_product_url(code)` = `{COSTCO_BASE}/product.{code}.html`; `_looks_blocked(html)` — bot-detect markers

`backend/vision.py`:
- `extract_item_codes(bytes, content_type) → (codes[], note)` — Claude vision, base64 image
- `_parse_codes(text) → (codes[], note)` — JSON array parse, regex `\d{6,7}` fallback
- `_detect_media_type(data, fallback)` — magic-byte sniff

`backend/rag.py` (Supabase pgvector + Voyage; public API unchanged from the Chroma version):
- `index_product(ProductData) → int` — upsert `products` row (full record as `data` jsonb) + delete/re-insert `product_chunks` with Voyage embeddings
- `_chunks_for(product) → str[]` — header + description + features chunks
- `list_products() → ProductData[]` (from `products.data`); `get_product(code)`; `update_product(p)` (re-index); `delete_product(code)` (chunks cascade); `count_products()` (exact count)
- `_product_from_row(row) → ProductData` — parse `products.data` jsonb
- `_retrieve(question, k) → (docs, metas)` — embed query (Voyage) → `match_products` RPC; metas carry item_code+title for citations
- `chat(question, history, language) → (answer, answer_en, question_foreign, question_en, citations, not_found)` — grounded Claude call; injects guidelines + knowledge chunks; English path = marker-based single answer; non-English = one call using a FORCED `provide_bilingual_answer` tool (`tool_choice`) → SDK returns a validated dict with both languages (robust; replaced the old fragile free-text-JSON parsing that intermittently left the English tab blank). Foreign-language name comes from `_LANG_NAMES` — add an entry for every new language code

`backend/db.py`: `client()` — cached Supabase client (SERVICE-ROLE key; bypasses RLS).
`backend/embeddings.py`: `embed(texts, input_type='document')`, `embed_query(text)` — Voyage `voyage-3.5-lite`, dim=`EMBED_DIM` (1024).

`backend/knowledge.py`: `add_document(title,text,source)` (Voyage-embed → `knowledge_docs`/`knowledge_chunks`), `extract_text(filename,data)` (pdf via pypdf), `list_documents()`, `delete_document(id)` (chunks cascade), `retrieve(query,k) → [(text,title)]` via `match_knowledge` RPC, `_chunk_text()`.

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
- **Supabase (Postgres + pgvector) is the single data store** — replaced local ChromaDB so data is cloud-managed/persistent and shared between the Vercel API and local Mac ingestion. Products (`products` + `product_chunks`), knowledge (`knowledge_docs` + `knowledge_chunks`), settings (`settings`). Retrieval via `match_products`/`match_knowledge` RPCs (cosine, hnsw). RLS on with no policies → only the service-role key (backend) can read/write.
- **Voyage AI embeddings (`voyage-3.5-lite`, 1024-dim)** — replaced local `sentence-transformers`; a plain API call so the serverless function stays light (no torch). Same model used for indexing + queries. Free 200M-token tier. `EMBED_DIM` must match `supabase_schema.sql`.
- **All-Vercel deploy** — PWA served static from Vercel CDN; FastAPI runs as a Python serverless function (`api/index.py` mounts the app at `/api`, so routes resolve at `/api/chat` etc.). `vercel.json` builds the frontend + routes `/api/*`, maxDuration 60s (Hobby). Single origin → no CORS, HTTPS for iPhone mic/PWA install. Chat streams to fit the timeout budget.
- **Ingestion stays local (Mac → Supabase)** — CDP scraping/photo run on the Mac and WRITE to Supabase (outbound only; computer never exposed). The cloud only reads. So scraper deps live in `backend/requirements.txt`, not the cloud `requirements.txt`; `main.py` imports scraper lazily.
- **Mobile/PWA can't scrape** — iOS browsers expose no remote-debugging (CDP), and a web page can't read other tabs (browser security), and the cloud has no browser. So from the phone only **manual add** (`/index/manual`, no scrape) works; photo-add also needs the browser → Mac-only. Bulk/accurate adds happen on the Mac (open-tabs → Supabase); they show up on the phone instantly since Supabase is the shared store.
- **PWA** — `vite-plugin-pwa` (Workbox) + web manifest + iOS meta tags → installable via Safari "Add to Home Screen". Icons in `frontend/public/`.
- **`[PRODUCT_NOT_FOUND]` marker** — Claude emits it when asked product isn't in retrieved context; backend strips it, sets flag → drives on-demand ingestion UI (feature 1c).
- **Grounding via system prompt** — Claude answers ONLY from CONTEXT block; context injected in user turn (per-turn, not cached system).
- **Model `claude-sonnet-4-6`** — pinned by spec for chat + vision; overridable via env.
- **Web Speech API for STT** (en-CA); **server-side TTS** (ElevenLabs `eleven_flash_v2_5`) played as audio, browser SpeechSynthesis fallback.
- **TTS voice = "River"** (`SAz9YHcvj6GT2YYXdXww`, neutral American) — default because ElevenLabs FREE tier can't use library/Canadian voices via API (402); Canadian needs a paid plan → then set `ELEVENLABS_VOICE_ID`.
- **Half-duplex by default** — mic pauses while the bot talks (fixes speaker echo feeding the bot's words back). Interrupt via tap-avatar / Stop. `toggleBargeIn` (Talk-over) keeps mic live for headphone users = true voice barge-in.
- **Conversation mode** — say "C-Bot" once, then talk freely; ~15s silence → wake-word standby.
- **Lottie avatar** (`lottie-react`) — PLAYS while speaking, PAUSES while listening. `assets/cbot.json` = user's ericz.json, recolored clothing red + "Major Sales" chest overlay (`.cbot-logo`; **white** text, `--logo-top`/font-size adjustable — base 15px is sized for the 500px desktop avatar, so mobile overrides it to 8px) + Background layer removed (transparent over store bg). Original backup: `/tmp/cbot.backup.json`. On mobile the avatar is bottom-aligned in a fixed-height stage; the lottie canvas has transparent padding below the character, so `.cbot` gets a negative `margin-bottom` (~-16px) clipped by the stage's `overflow:hidden` to seat it flush on the bottom (no floating gap).
- **Chat layout** — character stage (left) over blurred store background image, conversation panel (right), all voice buttons in a bottom voice bar. The bottom voice-status text line was removed (decluttered). "Listen" button (was "Stop") stops audio+anim and listens. On phones the stage stacks on top as a short fixed strip (~20vh) with the avatar seated at the bottom, and the conversation flexes to fill the rest.
- **Responsive / mobile+tablet UI** (`styles.css` `@media` blocks) — `.app` uses `100dvh` (tracks mobile browser chrome); `env(safe-area-inset-*)` padding on topnav (notch), voice-bar + composer (home indicator) since `viewport-fit=cover` is set. Touch text inputs forced ≥16px to stop iOS focus-zoom (the `<select>` is exempt — native pickers don't zoom). Tiers: **tablet 861–1024px** (chat convo `clamp`s instead of a hard 420px, panels tighten), **phone ≤860px** (stacked chat, single-column products/settings, bigger tap targets, smaller topnav fonts), **≤480px** (single-column edit fields, tighter voice bar), **landscape phone** (shorter stage). Servers for on-device testing: `npm run dev -- --host 0.0.0.0` + `uvicorn main:app --host 0.0.0.0`, reach via the Mac's LAN IP; voice needs HTTPS so it won't work over LAN, only on the deployed domain.
- **Knowledge base** — reference docs (policies/rules/returns) in separate Supabase tables (`knowledge_docs`/`knowledge_chunks`); chat retrieves top-4 knowledge chunks + products, prompt distinguishes PRODUCTS vs KNOWLEDGE. Loaded a real Costco returns/policy doc (15 chunks). RTF isn't accepted by the uploader (txt/md/pdf only) — convert via `textutil` first.
- **Multilingual (en/yue/es/fr/hi/it/ja/ko/pt)** — 🌐 selector; `/chat` `language` param → Claude answers in it (data stays grounded, translated; item#/brands kept). Languages live in `frontend/src/languages.js` (`code`/`label`/`bcp47`) AND `backend/rag.py` `_LANG_NAMES` (must add both for a new language). TTS auto-detects language (ElevenLabs). STT locale = `bcp47For(lang)`. Cantonese = Traditional Chinese text; voice/STT lean Mandarin (weaker). Non-English replies use a forced tool call so both language versions always return (see rag.chat in §2).
- **Bilingual tabs** — non-English shows [lang]|English tabs; each message stored in both languages; backend returns both per turn. "⌨️ Input" toggle: speak/type English while C-Bot answers in the selected language (STT switches to en).
- **Editable products** — full ProductData stored as `data` jsonb in Supabase `products` → edit (PUT) without re-scraping; re-embeds on save. Fields: `item_code`, `title`, `brand`, `model`, `price` (current) + `price_date`, `regular_price`, `promo_price` (sale) + `price_valid_until` (sale expiry), `description`, `features[]`, `rating`, `url`. All surfaced in the edit cards AND a **manual-add form** (Products page, admin-only, no scraping → the phone-friendly way to add). `rag._chunks_for` embeds model + price/date/sale into the header so chat can answer about them.
- **Settings/guidelines** — persisted in Supabase `settings` row (`settings_store`), injected into chat system prompt (category-specific clarifying questions).
- Online only (offline/Ollama idea dropped). Chat + vision = Claude Sonnet 4.6.
- **Vite `/api` proxy** — same-origin dev, no CORS friction. Mic needs HTTPS on non-localhost (Safari) → satisfied by the Vercel HTTPS domain in prod.

## 4. Status
**LIVE in production at https://c-bot-two.vercel.app** — all-Vercel (PWA + Python serverless) + Supabase (pgvector) + Voyage embeddings, private behind a cookie login with editable admin/user accounts, 9 languages, mobile-tuned PWA. Details below.
- **DONE — Supabase migration + verified live**: schema run in project `c-bot` (ref `eumhtymlowchfitvetho`); `migrate_to_supabase.py` loaded **7 products + 1 returns/policy doc (13 chunks)**. Verified end-to-end against Supabase: product retrieval + compare (citations correct), knowledge/policy Q&A — both grounded via Voyage query-embed → pgvector RPC → Claude. Settings on Supabase row.
- **Voyage free-tier rate limit (⚠️)**: no-payment-method accounts get ~3 req/min. Migration is paced (`MIGRATE_DELAY=25s`); `embeddings.embed` has 429 backoff; `rag.chat` now embeds the query ONCE (reused for product + knowledge retrieval). For real usage the user should **add a payment method to Voyage** (raises RPM; first 200M tokens still free).
- **GitHub — DONE**: pushed to `github.com/ericzantua/c-bot` (main). Credential helper = osxkeychain. (User pasted a PAT in chat once → advised to revoke.)
- **Deploy DONE — LIVE at https://c-bot-two.vercel.app** (Vercel project `c-bot`, org `ezantuas-projects`). `/` serves the PWA (200); `/api/health` → `{status:ok,products:7}` (serverless FastAPI ↔ Supabase). Env vars set in Vercel dashboard. **Deploy gotcha that cost a debug session**: the project's Framework Preset was auto-detected as **"FastAPI"** with no build command → Vercel deployed ONLY the Python function and never built the frontend, so every route hit FastAPI and 404'd. Fix = `vercel.json` `"framework": null` (override the dashboard preset) + `installCommand`/`buildCommand` that build the Vite PWA. Also: don't `pip install` in the build step — the build image's Python is uv-managed (externally-managed-environment error); the `api/` function's `requirements.txt` is installed automatically. Preview/immutable deployment URLs are behind Vercel Deployment Protection (302 → sso) — only the production alias `c-bot-two.vercel.app` is public.
- **Costco scraping**: unchanged, LOCAL only via **CDP open-tabs**; cloud never scrapes. Automated `/index`/`/index/url` still 403 (Akamai). Samples/manual/photo are always-on fallbacks.
- **App is PRIVATE — cookie login, accounts editable in Settings (DONE, verified live)**. Split responsibilities:
  - **Backend (`backend/auth.py` + endpoints in `main.py`)** owns accounts + passwords. Accounts live in Supabase **`app_users`** (`username` PK, `password_hash`, `is_admin`) — **PBKDF2-SHA256** hashed. **`POST /login`** (form) verifies and sets a signed **HttpOnly/Secure/SameSite=Lax** cookie `cbot_session` (`{u,admin,exp}`, HMAC-SHA256, 30d, `COOKIE_SECURE` env toggles Secure for local http). Admin-only user CRUD: **`GET/POST/PUT/DELETE /api/users`** (change password, toggle admin, rename via `new_username`, delete; guards block deleting yourself / the last admin). `GET /api/me` (backend copy, for local dev). `_ensure_seeded()` seeds `app_users` from the `AUTH_USERS`/`AUTH_ADMINS` env vars ONCE if the table is empty — after that those env vars are ignored and accounts are managed in the UI.
  - **`middleware.js` (Edge)** gates every request (static PWA + `/api/*`): verifies the cookie's HMAC signature (shares `AUTH_SECRET` with the backend — Python signs, JS verifies; format verified compatible), serves the branded `/login` page (form → `/api/login`), handles `/logout`, answers `/api/me` from the cookie, allows `/api/login` through unauthenticated, and gates admin-only paths `/api/(users|settings|products|index|knowledge)*` via the cookie's `admin` flag (non-admin → 403). No passwords or DB in the middleware. Fail-closed 503 if `AUTH_SECRET` unset.
  - **Frontend**: admin sees Z-Bot·Products·Settings tabs (Users panel = `components/Users.jsx`, in Settings); non-admin sees Z-Bot·About only. `api.js` bounces to `/login` on any 401. Current accounts: `eric` (admin) + `w552maj` (user); manage the rest in Settings → Users. About page = credits (Eric Zantua, Costco WH-552, 552 Major Sales).
  - **One-time setup**: `app_users` table must exist (added to `supabase_schema.sql`; run once in the Supabase SQL editor — DDL can't go through the service key).
- **Mobile/tablet UI pass (DONE, user-tested on iPhone)**: added responsive tiers + iOS safe-area/`100dvh`/input-zoom fixes; removed the topnav brand; renamed Chat tab → "Z-Bot"; removed the bottom voice-status text; shortened the chat stage and seated the avatar flush at the bottom; "Major Sales" logo scaled for mobile + recolored white. See the Responsive and Lottie-avatar decisions above.
- **Browser-not-verified-by-me**: voice end-to-end, bilingual tabs/toggle, PWA install on iPhone. User tests iteratively (mobile layout already iterated on device).
- Known constraints: Python 3.11–3.13 (`.venv` is 3.13); voice best in Chrome/Edge (Safari STT unreliable); Cantonese voice/STT lean Mandarin.
- **Multilingual + bilingual fix (DONE, verified live)**: 9 languages (en/yue/es/fr/hi/it/ja/ko/pt). Non-English chat uses a forced `provide_bilingual_answer` tool call so both language versions always return (fixed the intermittently-blank English tab). Add a new language in BOTH `frontend/src/languages.js` and `backend/rag.py` `_LANG_NAMES`.
- **Git**: pushed to `github.com/ericzantua/c-bot` (main); credential helper = osxkeychain. Deploys via `vercel --prod` from the repo ROOT (running it from `frontend/` once created a stray `frontend` project — since deleted). `.env`/`.vercel`/`.env.local` gitignored (no secrets committed — verified with `git grep`).

## 5. How to run
Local (Mac — for dev + ingestion; writes to Supabase):
```
cd backend && . .venv/bin/activate           # 3.13 venv exists; supabase installed
pip install -r requirements.txt && playwright install chromium   # (scraper)
cp .env.example .env   # set ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY, VOYAGE_API_KEY
python migrate_to_supabase.py                 # one-time: old chroma_db → Supabase
uvicorn main:app --reload --port 8000
```
Frontend (dev): `cd frontend && npm install && npm run dev`  → http://localhost:5173
Cloud deploy: push to GitHub → Vercel "Import Project" (auto-detects `vercel.json`) → set env vars in Vercel → deploy. `api/` + root `requirements.txt` = the serverless API; `frontend/dist` = static PWA.

## 6. Environment
- `.env` (backend, LOCAL): `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `VOYAGE_API_KEY` (required).
  Optional: `VOYAGE_MODEL`, `EMBED_DIM` (must match schema), `CHAT_MODEL`, `VISION_MODEL`, `TOP_K`, `CORS_ORIGINS`,
  `SCRAPE_DELAY_SECONDS`, `COSTCO_BASE`, `STEALTH_MODE`, `HEADLESS`, `CHROME_CHANNEL`, `USER_DATA_DIR`, `CDP_URL`,
  `ELEVENLABS_API_KEY`/`ELEVENLABS_API_KEYS`, `TTS_PROVIDER`, `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL`, `OPENAI_API_KEY`.
  `EMBED_MODEL`/`CHROMA_DIR` are legacy — only `migrate_to_supabase.py` reads them.
- **Vercel env vars** (same keys minus scraper/CDP): `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `VOYAGE_API_KEY`, `ELEVENLABS_API_KEY(S)`, `TTS_PROVIDER`, plus `AUTH_SECRET` (random cookie-signing key, shared by backend+middleware) and `AUTH_USERS`/`AUTH_ADMINS` (**one-time seed only** for the `app_users` table — after seeding, accounts are managed in Settings → Users, not env vars). Optional `COOKIE_SECURE=false` for local http dev. Supabase needs the `app_users` table (run the snippet in `supabase_schema.sql` once). **All set in production + chat verified live (2026-07-29).** ⚠️ **Gotcha**: Vercel does NOT bundle `backend/.env` into the serverless function — every key MUST be set as a Vercel env var (dashboard or `printf VAL | vercel env add NAME production`), else prod runs with empty keys (symptom: `VOYAGE_API_KEY is not set` on first chat, since `config.py` has no fallbacks). `load_dotenv()` uses `override=False`, so Vercel env vars win over any `.env`.
- Supabase: run `backend/supabase_schema.sql` once (enables pgvector, tables, `match_*` functions, RLS). Service-role key is server-side only.
- CDP scraping (local): start Chrome `--remote-debugging-port=9222 --user-data-dir="$HOME/.costco-chrome"`, browse to products by hand, set `CDP_URL=http://localhost:9222`, use "Read open Costco tab(s)".
- Deps: cloud (`requirements.txt`) = fastapi, anthropic, supabase, httpx, pypdf, pydantic, python-multipart. Local (`backend/requirements.txt`) adds uvicorn, playwright, beautifulsoup4, + chromadb/sentence-transformers (migration only). Node 18+ (react, vite, vite-plugin-pwa, lottie-react).
- Knowledge docs: uploader takes txt/md/pdf. For .rtf, convert first: `textutil -convert txt -stdout file.rtf`.
```
