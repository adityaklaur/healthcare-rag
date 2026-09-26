from __future__ import annotations

from functools import lru_cache

from config.settings import ENABLE_RERANKER, RERANKER_MODEL
from models import SearchHit


@lru_cache(maxsize=1)
def _model():
    if not ENABLE_RERANKER:
        return None
    from sentence_transformers import CrossEncoder
    return CrossEncoder(RERANKER_MODEL)


def rerank(query: str, hits: list[SearchHit], chunks: list[dict]) -> list[SearchHit]:
    model = _model()
    if model is None or not hits:
        return sorted(hits, key=lambda h: h.rrf_score, reverse=True)
    pairs = [(query, chunks[h.idx]["text"]) for h in hits]
    scores = model.predict(pairs)
    for h, score in zip(hits, scores):
        h.rerank_score = float(score)
    return sorted(hits, key=lambda h: h.rerank_score or -1e9, reverse=True)


def score_withheld(query: str, hits: list[SearchHit], chunks: list[dict]) -> float | None:
    if not hits:
        return None
    model = _model()
    if model is not None:
        pairs = [(query, chunks[h.idx]["text"]) for h in hits]
        scores = model.predict(pairs)
        return float(max(scores)) if len(scores) else None
    # Privacy-safe fallback: only return a scalar relevance score. Dense cosine is preferred.
    dense = [h.vector_score for h in hits if h.vector_rank is not None]
    if dense:
        return float(max(dense))
    return float(max((h.rrf_score for h in hits), default=0.0))
