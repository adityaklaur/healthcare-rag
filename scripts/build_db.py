"""Load data/manifest.yaml + the files in data/ into PostgreSQL + pgvector.

    python scripts/build_db.py            # ingest new/changed documents only
    python scripts/build_db.py --force    # re-parse and re-embed everything

Connects as rag_owner (OWNER_DATABASE_URL). Safe to run repeatedly.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np

from config.settings import (
    DATA_DIR, EMBEDDING_DIM, EMBEDDING_MODEL, PROSE_CHUNK_CHARS, PROSE_OVERLAP_CHARS, ROLE_COLLECTIONS,
)
from db.connection import owner_connection
from ingestion.extract import extract_document
from ingestion.metadata import load_manifest
from ingestion.store import (
    document_row, fingerprint, replace_chunks, stored_fingerprints, sync_access_model, upsert_documents,
)

INGEST_VERSION = "2"  # bump when chunking logic changes, so --force is not needed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="re-ingest every document")
    args = parser.parse_args()

    manifest = load_manifest()
    docs = [m for m in manifest.documents if (DATA_DIR / m.file).exists()]
    for m in manifest.documents:
        if m not in docs:
            print(f"[WARN] missing file, skipped: {m.file}")
    if not docs:
        raise SystemExit("No documents found. Check data/manifest.yaml and data/.")

    settings_fp = [EMBEDDING_MODEL, PROSE_CHUNK_CHARS, PROSE_OVERLAP_CHARS, INGEST_VERSION]
    shas = {m.version_id: fingerprint(DATA_DIR / m.file, settings_fp) for m in docs}
    known = {m.version_id for m in docs}

    from sentence_transformers import SentenceTransformer
    model = None
    t0 = time.time()
    stats = {"documents": len(docs), "ingested": 0, "unchanged": 0, "chunks_written": 0}

    with owner_connection() as conn:
        sync_access_model(conn, ROLE_COLLECTIONS, {m.collection for m in docs})
        before = stored_fingerprints(conn)
        upsert_documents(conn, [document_row(m, known, shas[m.version_id]) for m in docs])

        for meta in docs:
            if not args.force and before.get(meta.version_id) == shas[meta.version_id]:
                stats["unchanged"] += 1
                print(f"[SKIP] {meta.file}: unchanged")
                continue
            chunks = extract_document(meta)
            if not chunks:
                print(f"[WARN] {meta.file}: no text extracted")
                continue
            if model is None:
                model = SentenceTransformer(EMBEDDING_MODEL)
            vecs = np.asarray(model.encode([c["text"] for c in chunks], batch_size=32,
                                           normalize_embeddings=True, show_progress_bar=False), dtype="float32")
            if vecs.shape[1] != EMBEDDING_DIM:
                raise SystemExit(f"{EMBEDDING_MODEL} gives {vecs.shape[1]}-d vectors but the database column is "
                                 f"vector({EMBEDDING_DIM}). Change both together (db/init/01_schema.sql, EMBEDDING_DIM).")
            replace_chunks(conn, meta.version_id, chunks, list(vecs), shas[meta.version_id])
            stats["ingested"] += 1
            stats["chunks_written"] += len(chunks)
            print(f"[OK] {meta.file}: {len(chunks)} chunks")

        totals = conn.execute(
            "SELECT count(*), count(*) FILTER (WHERE chunk_type = 'table'),"
            " count(*) FILTER (WHERE chunk_type = 'table_row') FROM chunks"
        ).fetchone()
    stats.update({"chunks_total": totals[0], "tables": totals[1], "table_rows": totals[2],
                  "embedding_model": EMBEDDING_MODEL, "seconds": round(time.time() - t0, 1)})
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
