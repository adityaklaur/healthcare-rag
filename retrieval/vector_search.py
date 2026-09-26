from __future__ import annotations

from functools import lru_cache

import faiss

from config.settings import INDEX_DIR
from models import SearchHit
from retrieval.embedder import embed_query


@lru_cache(maxsize=1)
def _load_index():
    path = INDEX_DIR / "faiss.index"
    if not path.exists():
        raise FileNotFoundError("FAISS index not built. Run: python scripts/build_index.py")
    return faiss.read_index(str(path))


def search_vector(query: str, k: int = 30) -> list[SearchHit]:
    index = _load_index()
    q = embed_query(query)
    k = min(k, index.ntotal)
    scores, ids = index.search(q, k)
    out: list[SearchHit] = []
    for rank, (score, idx) in enumerate(zip(scores[0], ids[0]), start=1):
        if idx < 0:
            continue
        out.append(SearchHit(idx=int(idx), vector_score=float(score), vector_rank=rank))
    return out
