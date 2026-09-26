from __future__ import annotations

import json
from functools import lru_cache

from config.settings import BM25_CANDIDATES, DENSE_CANDIDATES, INDEX_DIR, RETRIEVAL_BACKEND, RRF_K, TOP_K
from models import QueryContext, RetrievalResult, SearchHit, WithheldSummary
from retrieval.acl import partition_hits
from retrieval.reranker import rerank, score_withheld


def retrieve(qc: QueryContext, role: str, top_k: int = TOP_K) -> RetrievalResult:
    """Entry point used by pipeline.py. Picks the backend from RETRIEVAL_BACKEND."""
    if RETRIEVAL_BACKEND == "files":
        return retrieve_files(qc, role, top_k)
    from retrieval.pg_search import retrieve_pg
    return retrieve_pg(qc, role, top_k)


@lru_cache(maxsize=1)
def load_chunks() -> list[dict]:
    path = INDEX_DIR / "chunks.jsonl"
    if not path.exists():
        raise FileNotFoundError("Chunk store not built. Run: python scripts/build_index.py")
    chunks = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                chunks.append(json.loads(line))
    return chunks


def _merge_hits(dense: list[SearchHit], lexical: list[SearchHit]) -> list[SearchHit]:
    by_idx: dict[int, SearchHit] = {}
    for h in dense + lexical:
        cur = by_idx.setdefault(h.idx, SearchHit(idx=h.idx))
        if h.vector_rank is not None:
            cur.vector_rank, cur.vector_score = h.vector_rank, h.vector_score
        if h.bm25_rank is not None:
            cur.bm25_rank, cur.bm25_score = h.bm25_rank, h.bm25_score
    for h in by_idx.values():
        if h.vector_rank is not None:
            h.rrf_score += 1.0 / (RRF_K + h.vector_rank)
        if h.bm25_rank is not None:
            h.rrf_score += 1.0 / (RRF_K + h.bm25_rank)
    return list(by_idx.values())


def _expand(hit: SearchHit, chunks: list[dict], by_id: dict[str, dict], rank: int) -> dict:
    chunk = dict(chunks[hit.idx])
    chunk.update({
        "rank": rank,
        "vector_score": round(hit.vector_score, 5),
        "bm25_score": round(hit.bm25_score, 5),
        "rrf_score": round(hit.rrf_score, 7),
        "rerank_score": None if hit.rerank_score is None else round(hit.rerank_score, 5),
    })
    parent_id = chunk.get("parent_id")
    if parent_id and parent_id in by_id:
        chunk["parent_context"] = by_id[parent_id].get("text", "")
    else:
        chunk["parent_context"] = None
    return chunk


def retrieve_files(qc: QueryContext, role: str, top_k: int = TOP_K) -> RetrievalResult:
    """File backend: FAISS + BM25 over the full index, then ACL partition in Python."""
    from retrieval.bm25_search import search_bm25
    from retrieval.vector_search import search_vector

    chunks = load_chunks()
    by_id = {c["chunk_id"]: c for c in chunks}

    dense = search_vector(qc.normalized, DENSE_CANDIDATES)
    lexical = search_bm25(qc.normalized, BM25_CANDIDATES)
    merged = _merge_hits(dense, lexical)

    permitted, withheld = partition_hits(merged, chunks, role)
    permitted = rerank(qc.normalized, sorted(permitted, key=lambda h: h.rrf_score, reverse=True)[:20], chunks)[:top_k]

    evidence = [_expand(h, chunks, by_id, rank) for rank, h in enumerate(permitted, start=1)]
    withheld_docs = {chunks[h.idx].get("document_id") for h in withheld}
    withheld_max = score_withheld(qc.normalized, withheld, chunks)
    retrieved_ids = [chunks[h.idx]["chunk_id"] for h in sorted(merged, key=lambda h: h.rrf_score, reverse=True)[:60]]

    return RetrievalResult(
        evidence=evidence,
        withheld=WithheldSummary(doc_count=len(withheld_docs), max_score=withheld_max),
        retrieved_chunk_ids=retrieved_ids,
        historical_intent=qc.historical_intent,
    )
