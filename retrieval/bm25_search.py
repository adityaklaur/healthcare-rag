from __future__ import annotations

import pickle
import re
from functools import lru_cache

import numpy as np

from config.settings import INDEX_DIR
from models import SearchHit

TOKEN = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*", re.I)


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in TOKEN.findall(text or "")]


@lru_cache(maxsize=1)
def _load_bm25():
    path = INDEX_DIR / "bm25.pkl"
    if not path.exists():
        raise FileNotFoundError("BM25 index not built. Run: python scripts/build_index.py")
    with path.open("rb") as f:
        payload = pickle.load(f)
    return payload["bm25"]


def search_bm25(query: str, k: int = 30) -> list[SearchHit]:
    bm25 = _load_bm25()
    scores = np.asarray(bm25.get_scores(tokenize(query)), dtype=float)
    if scores.size == 0:
        return []
    order = np.argsort(scores)[::-1][: min(k, scores.size)]
    return [SearchHit(idx=int(i), bm25_score=float(scores[i]), bm25_rank=rank) for rank, i in enumerate(order, start=1)]
