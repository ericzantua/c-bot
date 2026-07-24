"""Vercel serverless entrypoint for the C-Bot API.

Vercel routes /api/* here (see vercel.json). We mount the existing FastAPI app
under /api so its routes (/chat, /products, ...) resolve at /api/chat, etc.
`app` is the ASGI callable Vercel's Python runtime serves.
"""
import os
import sys

# Make backend/ importable (its modules import each other by bare name).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from fastapi import FastAPI  # noqa: E402

from main import app as _inner  # noqa: E402

app = FastAPI()
app.mount("/api", _inner)
