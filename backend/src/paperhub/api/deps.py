"""Shared FastAPI dependency helpers."""
from __future__ import annotations

from fastapi import Request

from paperhub.config import Settings
from paperhub.rag.chroma import ChromaStore


def get_chroma(request: Request, settings: Settings) -> ChromaStore:
    """Return the lifespan-warmed ChromaStore from app.state, or build a
    per-request fallback if app.state isn't set (e.g. in tests where
    ASGITransport bypasses lifespan)."""
    existing = getattr(request.app.state, "chroma", None)
    if isinstance(existing, ChromaStore):
        return existing
    return ChromaStore(settings.chroma_dir)
