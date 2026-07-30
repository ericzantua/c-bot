"""C-Bot backend: FastAPI app exposing ingestion, chat, and product endpoints."""
import os

import auth
import config
import knowledge
import rag
import samples
import settings_store
import tts
import vision
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from models import (
    ChatRequest,
    ChatResponse,
    IndexRequest,
    IndexResponse,
    IndexResult,
    KnowledgeAddText,
    KnowledgeDoc,
    KnowledgeResponse,
    ManualIndexRequest,
    PhotoIndexResponse,
    ProductData,
    ProductsResponse,
    SettingsModel,
    TTSRequest,
    UrlIndexRequest,
)

# NOTE: scraper (Playwright/BeautifulSoup) is imported lazily inside the index
# endpoints so the cloud/serverless deploy loads without those heavy deps —
# scraping only runs on a local machine with a browser.

app = FastAPI(title="C-Bot — Costco Product RAG API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _index_scraped(labels: list[str], scraped: list) -> list[IndexResult]:
    """Store scraped products; ``labels`` identify each entry in error results."""
    from scraper import ScrapeError  # lazy: keeps Playwright out of the cloud deploy

    results: list[IndexResult] = []
    for label, outcome in zip(labels, scraped):
        if isinstance(outcome, ScrapeError):
            results.append(IndexResult(item_code=label, status="error", error=str(outcome)))
            continue
        try:
            rag.index_product(outcome)
            results.append(
                IndexResult(
                    item_code=outcome.item_code,
                    status="indexed",
                    title=outcome.title,
                    price=outcome.price,
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                IndexResult(item_code=label, status="error", error=f"Indexing failed: {exc}")
            )
    return results


def _ingest(item_codes: list[str]) -> list[IndexResult]:
    """Scrape by item code → chunk → embed → store; return per-item results."""
    import asyncio

    from scraper import scrape_products

    codes = [c.strip() for c in item_codes if c.strip()]
    if not codes:
        return []
    return _index_scraped(codes, asyncio.run(scrape_products(codes)))


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "products": rag.count_products()}


# ---------------- Auth + user management ----------------
class UserIn(BaseModel):
    username: str
    password: str
    is_admin: bool = False


class UserPatch(BaseModel):
    new_username: str | None = None
    password: str | None = None
    is_admin: bool | None = None


def _require_admin(request: Request) -> dict:
    """Defense-in-depth: the Edge middleware already gates admin paths, but verify
    the session here too so these endpoints are safe even if hit directly."""
    current = auth.authenticate(request.cookies.get(config.SESSION_COOKIE, ""))
    if not current:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    if not current["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin access required.")
    return current


@app.post("/login")
def login(username: str = Form(...), password: str = Form(...)) -> Response:
    """Verify credentials and set the signed session cookie (used by /login form)."""
    auth._ensure_seeded()
    user = auth.get_user(username.strip())
    if not user or not auth.verify_password(password, user["password_hash"]):
        return RedirectResponse(url="/login?error=1", status_code=303)
    token = auth.sign_session(user["username"], bool(user.get("is_admin")))
    resp = RedirectResponse(url="/", status_code=303)
    resp.set_cookie(
        config.SESSION_COOKIE, token,
        httponly=True, secure=config.COOKIE_SECURE, samesite="lax",
        max_age=config.SESSION_DAYS * 86400, path="/",
    )
    return resp


@app.get("/me")
def me(request: Request) -> dict:
    """Identity for the SPA. In production the Edge middleware answers /api/me from
    the cookie; this backend copy makes local dev (no middleware) work too."""
    current = auth.authenticate(request.cookies.get(config.SESSION_COOKIE, ""))
    if not current:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return {"user": current["username"], "admin": current["is_admin"]}


@app.get("/users")
def list_users(request: Request) -> dict:
    _require_admin(request)
    return {"users": auth.list_users()}


@app.post("/users")
def create_user(u: UserIn, request: Request) -> dict:
    _require_admin(request)
    name = u.username.strip()
    if not name or not u.password:
        raise HTTPException(status_code=400, detail="Username and password are required.")
    if "," in name or ":" in name:
        raise HTTPException(status_code=400, detail="Username can't contain ',' or ':'.")
    try:
        return auth.create_user(name, u.password, u.is_admin)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/users/{username}")
def update_user(username: str, patch: UserPatch, request: Request) -> dict:
    current = _require_admin(request)
    name = (patch.new_username or "").strip()
    if name and ("," in name or ":" in name):
        raise HTTPException(status_code=400, detail="Username can't contain ',' or ':'.")
    # Don't let the last admin demote themselves and lock everyone out.
    if patch.is_admin is False:
        admins = [x for x in auth.list_users() if x["is_admin"]]
        if len(admins) <= 1 and any(x["username"] == username for x in admins):
            raise HTTPException(status_code=400, detail="Can't remove the last admin.")
    try:
        return auth.update_user(
            username,
            password=patch.password or None,
            is_admin=patch.is_admin,
            new_username=name or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/users/{username}")
def delete_user(username: str, request: Request) -> dict:
    current = _require_admin(request)
    if username == current["username"]:
        raise HTTPException(status_code=400, detail="You can't delete your own account.")
    users = auth.list_users()
    target = next((x for x in users if x["username"] == username), None)
    if target and target["is_admin"] and len([x for x in users if x["is_admin"]]) <= 1:
        raise HTTPException(status_code=400, detail="Can't delete the last admin.")
    auth.delete_user(username)
    return {"status": "deleted", "username": username}


@app.post("/index", response_model=IndexResponse)
def index(req: IndexRequest) -> IndexResponse:
    if not req.item_codes:
        raise HTTPException(status_code=400, detail="No item codes provided.")
    return IndexResponse(results=_ingest(req.item_codes))


def _index_direct(products: list[ProductData]) -> list[IndexResult]:
    """Store already-known product data (no scraping); used for manual/mock."""
    results: list[IndexResult] = []
    for p in products:
        if not p.item_code.strip():
            results.append(IndexResult(item_code="", status="error", error="Missing item_code."))
            continue
        try:
            rag.index_product(p)
            results.append(
                IndexResult(
                    item_code=p.item_code, status="indexed", title=p.title, price=p.price
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                IndexResult(item_code=p.item_code, status="error", error=f"Indexing failed: {exc}")
            )
    return results


@app.post("/index/url", response_model=IndexResponse)
def index_url(req: UrlIndexRequest) -> IndexResponse:
    """Scrape + index products from full costco.ca product URLs."""
    import asyncio

    from scraper import scrape_urls

    urls = [u.strip() for u in req.urls if u.strip()]
    if not urls:
        raise HTTPException(status_code=400, detail="No URLs provided.")
    return IndexResponse(results=_index_scraped(urls, asyncio.run(scrape_urls(urls))))


@app.post("/index/open-tabs", response_model=IndexResponse)
def index_open_tabs() -> IndexResponse:
    """Index Costco product pages currently open in the CDP Chrome (read-only)."""
    import asyncio

    from scraper import scrape_open_tabs

    scraped = asyncio.run(scrape_open_tabs())
    labels = [d.item_code if isinstance(d, ProductData) else "open tab" for d in scraped]
    return IndexResponse(results=_index_scraped(labels, scraped))


@app.post("/index/manual", response_model=IndexResponse)
def index_manual(req: ManualIndexRequest) -> IndexResponse:
    """Index products from supplied data, bypassing the scraper."""
    if not req.products:
        raise HTTPException(status_code=400, detail="No products provided.")
    return IndexResponse(results=_index_direct(req.products))


@app.post("/index/mock", response_model=IndexResponse)
def index_mock() -> IndexResponse:
    """Load the bundled sample products for local testing."""
    return IndexResponse(results=_index_direct(samples.SAMPLE_PRODUCTS))


@app.post("/index/photo", response_model=PhotoIndexResponse)
async def index_photo(image: UploadFile = File(...)) -> PhotoIndexResponse:
    data = await image.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty image upload.")
    try:
        codes, note = vision.extract_item_codes(data, image.content_type or "")
    except RuntimeError as exc:  # missing API key
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not codes:
        return PhotoIndexResponse(extracted_codes=[], results=[], vision_note=note)

    results = _ingest(codes)
    return PhotoIndexResponse(extracted_codes=codes, results=results, vision_note=note)


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Empty question.")
    try:
        answer, answer_en, q_foreign, q_en, citations, not_found = rag.chat(
            req.question, req.history, req.language
        )
    except RuntimeError as exc:  # missing API key
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ChatResponse(
        answer=answer,
        answer_en=answer_en,
        question_foreign=q_foreign,
        question_en=q_en,
        citations=citations,
        product_not_found=not_found,
    )


@app.post("/tts")
def tts_endpoint(req: TTSRequest) -> Response:
    """Synthesize speech (MP3). TTS_PROVIDER=browser → 204 so the client speaks."""
    if config.TTS_PROVIDER.strip().lower() == "browser":
        return Response(status_code=204)
    try:
        audio, media_type = tts.synthesize(req.text)
    except tts.TTSError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(content=audio, media_type=media_type)


@app.get("/products", response_model=ProductsResponse)
def products() -> ProductsResponse:
    return ProductsResponse(products=rag.list_products())


@app.put("/products/{item_code}", response_model=ProductData)
def update_product(item_code: str, product: ProductData) -> ProductData:
    """Save edited product fields (regular/promo price, validity, etc.)."""
    product.item_code = item_code  # path is authoritative
    return rag.update_product(product)


@app.delete("/products/{item_code}")
def delete_product(item_code: str) -> dict:
    rag.delete_product(item_code)
    return {"status": "deleted", "item_code": item_code}


@app.get("/settings", response_model=SettingsModel)
def get_settings() -> SettingsModel:
    return SettingsModel(answer_guidelines=settings_store.get_guidelines())


@app.put("/settings", response_model=SettingsModel)
def put_settings(s: SettingsModel) -> SettingsModel:
    return SettingsModel(answer_guidelines=settings_store.set_guidelines(s.answer_guidelines))


@app.get("/knowledge", response_model=KnowledgeResponse)
def list_knowledge() -> KnowledgeResponse:
    return KnowledgeResponse(documents=[KnowledgeDoc(**d) for d in knowledge.list_documents()])


@app.post("/knowledge", response_model=KnowledgeDoc)
def add_knowledge(req: KnowledgeAddText) -> KnowledgeDoc:
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="No text provided.")
    try:
        return KnowledgeDoc(**knowledge.add_document(req.title, req.text, source="pasted"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/knowledge/file", response_model=KnowledgeDoc)
async def add_knowledge_file(
    file: UploadFile = File(...), title: str = Form("")
) -> KnowledgeDoc:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")
    try:
        text = knowledge.extract_text(file.filename or "", data)
        return KnowledgeDoc(
            **knowledge.add_document(
                title or file.filename or "Document", text, source=file.filename or "file"
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not read file: {exc}") from exc


@app.delete("/knowledge/{doc_id}")
def delete_knowledge(doc_id: str) -> dict:
    knowledge.delete_document(doc_id)
    return {"status": "deleted", "doc_id": doc_id}


# Serve the built PWA frontend (frontend/dist) if present. Mounted last so all
# API routes above take precedence; this handles /, assets, manifest, sw.js, etc.
_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(_DIST):
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="app")
