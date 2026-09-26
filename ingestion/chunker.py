from __future__ import annotations

import re
from typing import Iterable

from ingestion.metadata import DocumentMetadata
from ingestion.pii_filter import mask_pii


def clean_text(text: str) -> str:
    text = (text or "").replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _windows(text: str, size: int, overlap: int) -> Iterable[str]:
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        yield text[start:end].strip()
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)


def split_prose(text: str, size: int, overlap: int) -> list[str]:
    text = clean_text(text)
    if not text:
        return []
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out: list[str] = []
    current = ""
    for para in paras:
        candidate = f"{current}\n\n{para}".strip() if current else para
        if len(candidate) <= size:
            current = candidate
            continue
        if current:
            out.append(current)
        if len(para) > size:
            out.extend(_windows(para, size, overlap))
            current = ""
        else:
            current = para
    if current:
        out.append(current)
    return out


def make_prose_chunks(meta: DocumentMetadata, page: int, text: str, size: int, overlap: int) -> list[dict]:
    chunks: list[dict] = []
    for idx, body in enumerate(split_prose(text, size, overlap), start=1):
        pii_masked = False
        pii_types: list[str] = []
        if not meta.pii_test:
            body, pii_types = mask_pii(body)
            pii_masked = bool(pii_types)
        chunks.append({
            "chunk_id": f"{meta.version_id}#P{page}.C{idx}",
            "parent_id": None,
            "document_id": meta.document_id,
            "title": meta.title,
            "document_type": meta.document_type,
            "version": meta.version,
            "status": meta.status,
            "effective_date": meta.effective_date.isoformat() if meta.effective_date else None,
            "review_due": meta.review_due.isoformat() if meta.review_due else None,
            "supersedes": meta.supersedes,
            "superseded_by": meta.superseded_by,
            "authority_level": meta.authority_level,
            "collection": meta.collection,
            "population": meta.population,
            "page": page,
            "section": None,
            "chunk_type": "prose",
            "table_id": None,
            "row_id": None,
            "row_fields": {},
            "text": body,
            "pii_masked": pii_masked,
            "pii_types": pii_types,
            "owner_contact": meta.owner_contact,
            "source_file": meta.file,
            "synthetic": meta.synthetic,
        })
    return chunks
