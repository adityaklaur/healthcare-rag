"""Write documents, chunks and access rules into PostgreSQL (runs as rag_owner)."""
from __future__ import annotations

import hashlib
import re
from typing import Iterable

from ingestion.metadata import DocumentMetadata

# Codes such as PA-MRI-204, IP-7, N18.4, ICD-10, COVID-19. PostgreSQL's text parser
# splits these ("pa-mri" + "204"), so they are also stored whole for exact matching.
_ID_CANDIDATE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:[-.][A-Za-z0-9]+)+\b")


def extract_identifiers(text: str) -> list[str]:
    """Exact codes, used at ingestion AND on the question. Needs a digit, or be all caps
    (so ordinary words like 'follow-up' or 'e.g' are ignored)."""
    out: set[str] = set()
    for m in _ID_CANDIDATE.findall(text or ""):
        if any(ch.isdigit() for ch in m) or (m.isupper() and len(m) >= 4):
            out.add(m.upper().rstrip("."))
    return sorted(out)


def _clean(text: str) -> str:
    return (text or "").replace("\x00", " ")  # PostgreSQL text cannot contain NUL


def fingerprint(path, extra: Iterable[str]) -> str:
    """sha256 of the file plus ingestion settings, so a changed chunker/model re-ingests."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    for item in extra:
        h.update(str(item).encode())
    return h.hexdigest()


# ------------------------------------------------------------------ access model
def sync_access_model(conn, role_collections: dict[str, set[str]], manifest_collections: set[str]) -> None:
    """Make roles / role_collections match config/settings.py exactly."""
    with conn.transaction():
        for name in sorted(manifest_collections | {c for cs in role_collections.values() for c in cs}):
            conn.execute("INSERT INTO collections (name) VALUES (%s) ON CONFLICT DO NOTHING", (name,))
        for role in role_collections:
            conn.execute("INSERT INTO roles (name) VALUES (%s) ON CONFLICT DO NOTHING", (role,))
        conn.execute("DELETE FROM role_collections")
        for role, collections in role_collections.items():
            for c in sorted(collections):
                conn.execute("INSERT INTO role_collections (role, collection) VALUES (%s, %s)", (role, c))
        conn.execute("DELETE FROM roles WHERE name <> ALL(%s)", (list(role_collections),))


# ------------------------------------------------------------------ documents
UPSERT_DOC = """
INSERT INTO documents (doc_version_id, document_id, version, title, document_type, status,
    effective_date, review_due, supersedes, superseded_by, authority_level, collection,
    population, owner_contact, synthetic, pii_test, notes, source_file, source_sha256)
VALUES (%(doc_version_id)s, %(document_id)s, %(version)s, %(title)s, %(document_type)s,
    %(status)s, %(effective_date)s, %(review_due)s, %(supersedes)s, %(superseded_by)s,
    %(authority_level)s, %(collection)s, %(population)s, %(owner_contact)s, %(synthetic)s,
    %(pii_test)s, %(notes)s, %(source_file)s, %(source_sha256)s)
ON CONFLICT (doc_version_id) DO UPDATE SET   -- source_sha256 is updated with the chunks
    title = EXCLUDED.title, document_type = EXCLUDED.document_type, status = EXCLUDED.status,
    effective_date = EXCLUDED.effective_date, review_due = EXCLUDED.review_due,
    supersedes = EXCLUDED.supersedes, superseded_by = EXCLUDED.superseded_by,
    authority_level = EXCLUDED.authority_level, collection = EXCLUDED.collection,
    population = EXCLUDED.population, owner_contact = EXCLUDED.owner_contact,
    synthetic = EXCLUDED.synthetic, pii_test = EXCLUDED.pii_test, notes = EXCLUDED.notes,
    source_file = EXCLUDED.source_file
"""


def document_row(meta: DocumentMetadata, known_versions: set[str], sha: str) -> dict:
    def link(v):
        if v and v not in known_versions:
            print(f"[WARN] {meta.version_id}: link '{v}' is not in the manifest; ignored")
            return None
        return v
    return {
        "doc_version_id": meta.version_id, "document_id": meta.document_id, "version": meta.version,
        "title": meta.title, "document_type": meta.document_type, "status": meta.status,
        "effective_date": meta.effective_date, "review_due": meta.review_due,
        "supersedes": link(meta.supersedes), "superseded_by": link(meta.superseded_by),
        "authority_level": meta.authority_level, "collection": meta.collection,
        "population": meta.population, "owner_contact": meta.owner_contact,
        "synthetic": meta.synthetic, "pii_test": meta.pii_test, "notes": meta.notes,
        "source_file": meta.file, "source_sha256": sha,
    }


def upsert_documents(conn, rows: list[dict]) -> None:
    """All documents in one transaction: supersedes links are checked at commit."""
    with conn.transaction():
        for row in rows:
            conn.execute(UPSERT_DOC, row)
        # Documents removed from the manifest are removed from the database (chunks cascade).
        keep = [r["doc_version_id"] for r in rows]
        conn.execute("UPDATE documents SET supersedes = NULL WHERE supersedes <> ALL(%s)", (keep,))
        conn.execute("UPDATE documents SET superseded_by = NULL WHERE superseded_by <> ALL(%s)", (keep,))
        conn.execute("DELETE FROM documents WHERE doc_version_id <> ALL(%s)", (keep,))
        # Chunks carry a copy of their document's collection for row-level security.
        # Keep it in step even when the file itself is unchanged (manifest-only edit).
        conn.execute(
            "UPDATE chunks c SET collection = d.collection FROM documents d "
            "WHERE c.doc_version_id = d.doc_version_id AND c.collection <> d.collection"
        )


def stored_fingerprints(conn) -> dict[str, str]:
    rows = conn.execute(
        "SELECT d.doc_version_id, d.source_sha256 FROM documents d "
        "WHERE EXISTS (SELECT 1 FROM chunks c WHERE c.doc_version_id = d.doc_version_id)"
    ).fetchall()
    return {r[0]: r[1] for r in rows}


# ------------------------------------------------------------------ chunks
INSERT_CHUNK = """
INSERT INTO chunks (chunk_id, doc_version_id, parent_id, chunk_type, collection, section,
    page, table_id, row_id, row_fields, text, pii_masked, pii_types, identifiers, embedding)
VALUES (%(chunk_id)s, %(doc_version_id)s, %(parent_id)s, %(chunk_type)s, %(collection)s,
    %(section)s, %(page)s, %(table_id)s, %(row_id)s, %(row_fields)s, %(text)s,
    %(pii_masked)s, %(pii_types)s, %(identifiers)s, %(embedding)s)
"""


def replace_chunks(conn, doc_version_id: str, chunks: list[dict], embeddings, sha: str) -> None:
    """Replace one document version's chunks in a single transaction (safe to re-run).

    The document's fingerprint is updated in the same transaction, so an interrupted
    run is simply re-done next time."""
    from psycopg.types.json import Jsonb
    rows = []
    for chunk, vec in zip(chunks, embeddings):
        text = _clean(chunk["text"])
        rows.append({
            "chunk_id": chunk["chunk_id"], "doc_version_id": doc_version_id,
            "parent_id": chunk.get("parent_id"), "chunk_type": chunk.get("chunk_type", "prose"),
            "collection": chunk["collection"], "section": chunk.get("section"),
            "page": chunk.get("page"), "table_id": chunk.get("table_id"), "row_id": chunk.get("row_id"),
            "row_fields": Jsonb(chunk.get("row_fields") or {}), "text": text,
            "pii_masked": bool(chunk.get("pii_masked")), "pii_types": list(chunk.get("pii_types") or []),
            "identifiers": extract_identifiers(text), "embedding": vec,
        })
    with conn.transaction():
        conn.execute("DELETE FROM chunks WHERE doc_version_id = %s", (doc_version_id,))
        with conn.cursor() as cur:
            cur.executemany(INSERT_CHUNK, rows)
        conn.execute("UPDATE documents SET source_sha256 = %s, ingested_at = now() WHERE doc_version_id = %s",
                     (sha, doc_version_id))
