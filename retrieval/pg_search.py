"""PostgreSQL + pgvector retrieval (RETRIEVAL_BACKEND=postgres).

Same contract as the file backend: returns a RetrievalResult whose evidence dicts carry
the fields the trust engine, generator and UI already use. Differences that matter:
  * row-level security removes other collections INSIDE the query, so withheld text never
    leaves the database (the file backend loads it into Python and partitions it there);
  * the withheld summary comes from a SECURITY DEFINER function that returns two numbers;
  * retrieved_chunk_ids lists permitted chunks only.
"""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

from config.settings import BM25_CANDIDATES, DENSE_CANDIDATES, RRF_K, TOP_K
from db.connection import role_transaction, withheld_summary
from ingestion.store import extract_identifiers
from models import QueryContext, RetrievalResult, SearchHit, WithheldSummary
from retrieval.embedder import embed_query
from retrieval.reranker import rerank

RERANK_POOL = 20


@lru_cache(maxsize=1)
def _hybrid_sql() -> str:
    return (Path(__file__).resolve().parent / "sql" / "hybrid_search.sql").read_text(encoding="utf-8")


COLUMNS = [
    "chunk_id", "rrf_score", "vector_score", "lexical_score", "vector_rank", "lexical_rank", "exact_rank",
    "parent_id", "chunk_type", "collection", "section", "page", "table_id", "row_id",
    "row_fields", "text", "pii_masked", "pii_types",
    "document_id", "title", "document_type", "version", "status",
    "effective_date", "review_due", "supersedes", "superseded_by",
    "authority_level", "population", "owner_contact", "source_file", "synthetic",
]


def _to_chunk(row: tuple) -> dict:
    c = dict(zip(COLUMNS, row))
    for key in ("effective_date", "review_due"):
        if isinstance(c.get(key), date):
            c[key] = c[key].isoformat()
    c["population"] = list(c.get("population") or ["all"])
    c["pii_types"] = list(c.get("pii_types") or [])
    c["row_fields"] = c.get("row_fields") or {}
    c["vector_score"] = float(c["vector_score"] or 0.0)
    c["bm25_score"] = float(c.pop("lexical_score") or 0.0)   # kept under the old key for the UI/judge
    return c


def retrieve_pg(qc: QueryContext, role: str, top_k: int = TOP_K) -> RetrievalResult:
    qvec = embed_query(qc.normalized)[0]
    params = {
        "qvec": qvec, "qtext": qc.normalized, "qids": extract_identifiers(qc.original),
        "k_dense": DENSE_CANDIDATES, "k_lexical": BM25_CANDIDATES, "rrf_k": RRF_K, "limit": RERANK_POOL,
    }

    with role_transaction(role) as conn:
        rows = conn.execute(_hybrid_sql(), params).fetchall()
        candidates = [_to_chunk(r) for r in rows]

        # Rerank (optional cross-encoder) on permitted text only, keep top_k.
        hits = [SearchHit(idx=i, vector_score=c["vector_score"], bm25_score=c["bm25_score"],
                          vector_rank=c["vector_rank"], bm25_rank=c["lexical_rank"], rrf_score=c["rrf_score"])
                for i, c in enumerate(candidates)]
        ranked = rerank(qc.normalized, hits, candidates)[:top_k]

        # Parent context (full table / section), fetched under the same role.
        parent_ids = sorted({candidates[h.idx]["parent_id"] for h in ranked if candidates[h.idx].get("parent_id")})
        parents = dict(conn.execute(
            "SELECT chunk_id, text FROM chunks WHERE chunk_id = ANY(%s)", (parent_ids,)
        ).fetchall()) if parent_ids else {}

    evidence = []
    for rank, h in enumerate(ranked, start=1):
        c = dict(candidates[h.idx])
        c.update({
            "rank": rank,
            "vector_score": round(c["vector_score"], 5),
            "bm25_score": round(c["bm25_score"], 5),
            "rrf_score": round(c["rrf_score"], 7),
            "rerank_score": None if h.rerank_score is None else round(h.rerank_score, 5),
            "parent_context": parents.get(c.get("parent_id")),
        })
        for k in ("vector_rank", "lexical_rank", "exact_rank"):
            c.pop(k, None)
        evidence.append(c)

    doc_count, max_sim = withheld_summary(qvec, role, DENSE_CANDIDATES)
    return RetrievalResult(
        evidence=evidence,
        withheld=WithheldSummary(doc_count=doc_count, max_score=max_sim),
        retrieved_chunk_ids=[c["chunk_id"] for c in candidates],
        historical_intent=qc.historical_intent,
    )
