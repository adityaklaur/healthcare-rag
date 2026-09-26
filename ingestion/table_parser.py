from __future__ import annotations

import re
from typing import Any

from ingestion.metadata import DocumentMetadata
from ingestion.pii_filter import mask_pii


def _cell(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\n", " ").split())


def _markdown(headers: list[str], rows: list[list[str]]) -> str:
    width = max([len(headers), *[len(r) for r in rows]] or [0])
    headers = headers + [f"col_{i+1}" for i in range(len(headers), width)]
    norm_rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * width) + " |"]
    lines += ["| " + " | ".join(r) + " |" for r in norm_rows]
    return "\n".join(lines)


def _numeric_range(text: str) -> tuple[float | None, float | None]:
    t = text.lower().replace("≤", "<=").replace("≥", ">=").replace("–", "-").replace("—", "-")
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", t)]
    if not nums:
        return None, None
    if re.search(r"(?:<|below|less than)\s*=?\s*\d", t):
        return 0.0, nums[0] - 0.01
    if re.search(r"(?:<=|up to|at most)\s*\d", t):
        return 0.0, nums[0]
    if re.search(r"(?:>=|at least|or more|and above)\s*\d", t):
        return nums[0], 99999.0
    if re.search(r">\s*\d", t):
        return nums[0] + 0.01, 99999.0
    if len(nums) >= 2 and re.search(r"\d\s*-\s*\d", t):
        return min(nums[0], nums[1]), max(nums[0], nums[1])
    return None, None


def _range_fields(headers: list[str], row: list[str]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for header, value in zip(headers, row):
        h = header.lower().replace(" ", "")
        if "egfr" in h:
            lo, hi = _numeric_range(value)
            if lo is not None:
                fields.update({"egfr_min": lo, "egfr_max": hi})
        if "crcl" in h or "creatinineclearance" in h:
            lo, hi = _numeric_range(value)
            if lo is not None:
                fields.update({"crcl_min": lo, "crcl_max": hi})
    return fields


def table_to_chunks(meta: DocumentMetadata, page: int, table_no: int, raw_table: list[list[Any]]) -> list[dict]:
    rows = [[_cell(v) for v in row] for row in (raw_table or []) if row]
    rows = [r for r in rows if any(r)]
    if len(rows) < 2:
        return []
    headers, data_rows = rows[0], rows[1:]
    table_id = f"T{page}.{table_no}"
    parent_id = f"{meta.version_id}#{table_id}"
    parent_text = _markdown(headers, data_rows)
    if not meta.pii_test:
        parent_text, _ = mask_pii(parent_text)

    base = {
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
        "table_id": table_id,
        "owner_contact": meta.owner_contact,
        "source_file": meta.file,
        "synthetic": meta.synthetic,
    }
    out = [{
        **base,
        "chunk_id": parent_id,
        "parent_id": None,
        "chunk_type": "table",
        "row_id": None,
        "row_fields": {},
        "text": parent_text,
        "pii_masked": False,
        "pii_types": [],
    }]

    for idx, row in enumerate(data_rows, start=1):
        row_id = f"R{idx}"
        pairs = [f"{h}: {v}" for h, v in zip(headers, row) if h or v]
        text = f"{meta.title}. {table_id} {row_id}. " + "; ".join(pairs)
        pii_masked = False
        pii_types: list[str] = []
        if not meta.pii_test:
            text, pii_types = mask_pii(text)
            pii_masked = bool(pii_types)
        out.append({
            **base,
            "chunk_id": f"{parent_id}.{row_id}",
            "parent_id": parent_id,
            "chunk_type": "table_row",
            "row_id": row_id,
            "row_fields": _range_fields(headers, row),
            "text": text,
            "pii_masked": pii_masked,
            "pii_types": pii_types,
        })
    return out
