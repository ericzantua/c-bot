"""Pydantic request/response models shared across the API."""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ProductData(BaseModel):
    """Structured data for a single Costco product (all fields editable)."""

    item_code: str
    title: str = ""
    brand: str = ""
    model: str = ""
    price: str = ""  # current / effective price
    price_date: str = ""  # date the current price was recorded/valid, e.g. "2026-08-06"
    regular_price: str = ""
    promo_price: str = ""  # sale price
    price_valid_until: str = ""  # sale-price expiration, e.g. "2026-07-26"
    description: str = ""
    features: list[str] = Field(default_factory=list)
    specifications: dict[str, str] = Field(default_factory=dict)  # spec table: name -> value
    rating: str = ""
    url: str = ""


class IndexRequest(BaseModel):
    item_codes: list[str]


class ManualIndexRequest(BaseModel):
    """Index products from supplied data, bypassing the scraper (local testing)."""

    products: list[ProductData]


class UrlIndexRequest(BaseModel):
    """Scrape + index products from full costco.ca product URLs."""

    urls: list[str]


class IndexResult(BaseModel):
    item_code: str
    status: Literal["indexed", "error"]
    title: str = ""
    price: str = ""
    error: Optional[str] = None


class IndexResponse(BaseModel):
    results: list[IndexResult]


class PhotoIndexResponse(BaseModel):
    extracted_codes: list[str]
    results: list[IndexResult]
    vision_note: str = ""


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    question: str
    history: list[Message] = Field(default_factory=list)
    language: str = "en"  # en | yue | es | fr


class TTSRequest(BaseModel):
    text: str


class Citation(BaseModel):
    item_code: str
    title: str


class ChatResponse(BaseModel):
    answer: str  # in the selected language (English when language=en)
    answer_en: str = ""
    question_foreign: str = ""  # the user's question in the selected language
    question_en: str = ""
    citations: list[Citation] = Field(default_factory=list)
    product_not_found: bool = False


class ProductsResponse(BaseModel):
    products: list[ProductData]


class SettingsModel(BaseModel):
    answer_guidelines: str = ""


class KnowledgeAddText(BaseModel):
    title: str = ""
    text: str


class KnowledgeDoc(BaseModel):
    doc_id: str
    title: str
    source: str = ""
    chunks: int


class KnowledgeResponse(BaseModel):
    documents: list[KnowledgeDoc]
