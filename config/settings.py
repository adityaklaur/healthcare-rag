from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
MANIFEST_FILE = DATA_DIR / "manifest.yaml"
INDEX_DIR = BASE_DIR / "indexes"
AUDIT_DIR = BASE_DIR / "audit"
AUDIT_FILE = AUDIT_DIR / "audit.jsonl"

# ---- Storage / retrieval backend -------------------------------------------------
# "postgres" (default): documents, chunks, embeddings, access rules, audit and evaluation
#                       live in PostgreSQL + pgvector (see db/ and docker-compose.yml).
# "files":              the original FAISS + BM25 + JSONL setup (fallback if no database).
RETRIEVAL_BACKEND = os.getenv("RETRIEVAL_BACKEND", "postgres").lower().strip()
DATABASE_URL = os.getenv("DATABASE_URL", "")              # app user (rag_app) - limited by RLS
OWNER_DATABASE_URL = os.getenv("OWNER_DATABASE_URL", "")  # ingestion user (rag_owner)
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "384"))    # must match vector(384) in db/init/01_schema.sql

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

DENSE_CANDIDATES = int(os.getenv("DENSE_CANDIDATES", "30"))
BM25_CANDIDATES = int(os.getenv("BM25_CANDIDATES", "30"))
TOP_K = int(os.getenv("TOP_K", "6"))
RRF_K = int(os.getenv("RRF_K", "60"))
ENABLE_RERANKER = os.getenv("ENABLE_RERANKER", "false").lower() in {"1", "true", "yes"}

# Conservative demo thresholds. Tune them using evaluation/run_eval.py.
MIN_RELEVANCE_SCORE = float(os.getenv("MIN_RELEVANCE_SCORE", "0.24"))
# Compared with the best cosine similarity of withheld chunks (both backends).
RESTRICTED_THRESHOLD = float(os.getenv("RESTRICTED_THRESHOLD", "0.42"))
DISCLOSE_RESTRICTED_EXISTENCE = os.getenv("DISCLOSE_RESTRICTED_EXISTENCE", "true").lower() in {"1", "true", "yes"}

PROSE_CHUNK_CHARS = int(os.getenv("PROSE_CHUNK_CHARS", "2600"))
PROSE_OVERLAP_CHARS = int(os.getenv("PROSE_OVERLAP_CHARS", "300"))

ROLES = ["doctor", "pharmacist", "nurse", "billing", "researcher", "admin"]
ROLE_COLLECTIONS: dict[str, set[str]] = {
    "doctor": {"clinical", "formulary"},
    "pharmacist": {"clinical", "formulary"},
    "nurse": {"clinical"},
    "billing": {"billing"},
    "researcher": {"clinical", "restricted_research"},
    "admin": {"clinical", "formulary", "billing", "restricted_research"},
}

PII_PLACEHOLDERS = {
    "MRN": "[MRN]",
    "DOB": "[DOB]",
    "PHONE": "[PHONE]",
    "EMAIL": "[EMAIL]",
    "POLICY": "[POLICY_ID]",
}
