from __future__ import annotations


def render_citation(evidence: dict) -> str:
    parts = [str(evidence.get("title") or evidence.get("document_id") or "Source")]
    if evidence.get("version"):
        parts.append(f"v{evidence['version']}")
    if evidence.get("table_id"):
        parts.append(str(evidence["table_id"]))
    if evidence.get("row_id"):
        parts.append(str(evidence["row_id"]))
    elif evidence.get("section"):
        parts.append(str(evidence["section"]))
    if evidence.get("page"):
        parts.append(f"p.{evidence['page']}")
    if evidence.get("effective_date"):
        parts.append(f"effective {evidence['effective_date']}")
    return " · ".join(parts)


def citation_map(evidence: list[dict]) -> dict[str, str]:
    return {e["evidence_id"]: render_citation(e) for e in evidence if e.get("evidence_id")}
