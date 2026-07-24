"""C-Bot backend: FastAPI app exposing ingestion, chat, and product endpoints."""
import os

import config
import knowledge
import rag
import samples
import settings_store
import tts
import vision
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
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
from scraper import ScrapeError, scrape_open_tabs, scrape_products, scrape_urls

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

    codes = [c.strip() for c in item_codes if c.strip()]
    if not codes:
        return []
    return _index_scraped(codes, asyncio.run(scrape_products(codes)))


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "products": rag.count_products()}


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

    urls = [u.strip() for u in req.urls if u.strip()]
    if not urls:
        raise HTTPException(status_code=400, detail="No URLs provided.")
    return IndexResponse(results=_index_scraped(urls, asyncio.run(scrape_urls(urls))))


@app.post("/index/open-tabs", response_model=IndexResponse)
def index_open_tabs() -> IndexResponse:
    """Index Costco product pages currently open in the CDP Chrome (read-only)."""
    import asyncio

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
