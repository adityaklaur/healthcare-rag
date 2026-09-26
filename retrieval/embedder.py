from __future__ import annotations

from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer

from config.settings import EMBEDDING_MODEL


@lru_cache(maxsize=1)
def get_embedder() -> SentenceTransformer:
    return SentenceTransformer(EMBEDDING_MODEL)


def embed_query(text: str) -> np.ndarray:
    model = get_embedder()
    vec = model.encode([text], normalize_embeddings=True)
    return np.asarray(vec, dtype="float32")
