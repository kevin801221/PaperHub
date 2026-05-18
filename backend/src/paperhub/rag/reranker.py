"""Lazy-loaded cross-encoder reranker (ms-marco-MiniLM by default)."""
from __future__ import annotations

from dataclasses import dataclass

from sentence_transformers import CrossEncoder

from paperhub.config import load_settings


@dataclass(frozen=True)
class RerankResult:
    index: int
    score: float


class _CrossEncoderReranker:
    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model: CrossEncoder | None = None

    def _load(self) -> CrossEncoder:
        if self._model is None:
            self._model = CrossEncoder(self._model_name)
        return self._model

    def rerank(self, query: str, texts: list[str], top_k: int) -> list[RerankResult]:
        if not texts:
            return []
        model = self._load()
        # CrossEncoder.predict accepts list[str | list[str]] at runtime despite
        # strict type stubs; cast suppresses the variance mismatch.
        pairs: list[str | list[str]] = [[query, t] for t in texts]
        scores = model.predict(pairs)  # type: ignore[arg-type]
        ranked = sorted(enumerate(scores), key=lambda x: float(x[1]), reverse=True)
        return [RerankResult(index=i, score=float(s)) for i, s in ranked[:top_k]]


_singleton: _CrossEncoderReranker | None = None


def get_reranker() -> _CrossEncoderReranker:
    global _singleton
    if _singleton is None:
        settings = load_settings()
        _singleton = _CrossEncoderReranker(settings.reranker_model)
    return _singleton
