"""Turn the files listed in data/manifest.yaml into chunk dicts.

Shared by both backends: scripts/build_db.py (PostgreSQL) and scripts/build_index.py (files).
"""
from __future__ import annotations

from config.settings import DATA_DIR, PROSE_CHUNK_CHARS, PROSE_OVERLAP_CHARS
from ingestion.chunker import make_prose_chunks
from ingestion.loader import load_document
from ingestion.metadata import DocumentMetadata, load_manifest
from ingestion.table_parser import table_to_chunks


def dedupe(chunks: list[dict]) -> list[dict]:
    """Drop empty chunks and repeated chunk_ids (first one wins)."""
    seen: set[str] = set()
    out: list[dict] = []
    for chunk in chunks:
        if chunk["chunk_id"] in seen or not chunk.get("text", "").strip():
            continue
        seen.add(chunk["chunk_id"])
        out.append(chunk)
    return out


def extract_document(meta: DocumentMetadata) -> list[dict]:
    loaded = load_document(DATA_DIR / meta.file)
    chunks: list[dict] = []
    for page in loaded.pages:
        chunks.extend(make_prose_chunks(meta, page.page, page.text, PROSE_CHUNK_CHARS, PROSE_OVERLAP_CHARS))
        for table_no, table in enumerate(page.tables, start=1):
            chunks.extend(table_to_chunks(meta, page.page, table_no, table))
    return dedupe(chunks)


def extract_chunks() -> list[dict]:
    manifest = load_manifest()
    chunks: list[dict] = []
    for meta in manifest.documents:
        path = DATA_DIR / meta.file
        if not path.exists():
            print(f"[WARN] missing: {path}")
            continue
        doc_chunks = extract_document(meta)
        print(f"[OK] {meta.file}: {len(doc_chunks)} chunks")
        chunks.extend(doc_chunks)
    return dedupe(chunks)
