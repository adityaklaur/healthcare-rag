"""File backend (RETRIEVAL_BACKEND=files): build FAISS + BM25 + chunks.jsonl.

The default PostgreSQL backend uses scripts/build_db.py instead.
"""
from __future__ import annotations

import json
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import faiss
import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

from config.settings import BM25_CANDIDATES, EMBEDDING_MODEL, INDEX_DIR
from ingestion.extract import extract_chunks
from retrieval.bm25_search import tokenize


def build_index(chunks: list[dict]) -> None:
    if not chunks:
        raise RuntimeError("No chunks extracted. Check data/manifest.yaml and data files.")
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    texts = [c["text"] for c in chunks]
    model = SentenceTransformer(EMBEDDING_MODEL)
    embeddings = model.encode(texts, batch_size=32, show_progress_bar=True, normalize_embeddings=True)
    embeddings = np.asarray(embeddings, dtype="float32")

    faiss_index = faiss.IndexFlatIP(embeddings.shape[1])
    faiss_index.add(embeddings)
    faiss.write_index(faiss_index, str(INDEX_DIR / "faiss.index"))

    tokenized = [tokenize(t) for t in texts]
    bm25 = BM25Okapi(tokenized)
    with (INDEX_DIR / "bm25.pkl").open("wb") as f:
        pickle.dump({"bm25": bm25, "tokenized": tokenized}, f)

    with (INDEX_DIR / "chunks.jsonl").open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    stats = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "documents": len({(c["document_id"], c["version"]) for c in chunks}),
        "chunks": len(chunks),
        "tables": len([c for c in chunks if c.get("chunk_type") == "table"]),
        "table_rows": len([c for c in chunks if c.get("chunk_type") == "table_row"]),
        "embedding_model": EMBEDDING_MODEL,
        "dimension": int(embeddings.shape[1]),
        "bm25_candidates": BM25_CANDIDATES,
    }
    (INDEX_DIR / "index_stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(json.dumps(stats, indent=2))


def main() -> None:
    chunks = extract_chunks()
    print(f"Extracted {len(chunks)} chunks. Building indexes...")
    build_index(chunks)


if __name__ == "__main__":
    main()
