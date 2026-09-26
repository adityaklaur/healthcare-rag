from __future__ import annotations

from datetime import date

from ingestion.pii_filter import mask_pii
from models import QueryContext, RuleResult
from query.understand import SPECIFIC_POPULATION_TERMS
from retrieval.acl import is_permitted


def _exclude(excluded: list[dict], chunk: dict, reason: str) -> None:
    excluded.append({
        "chunk_id": chunk.get("chunk_id"),
        "document_id": chunk.get("document_id"),
        "title": chunk.get("title"),
        "page": chunk.get("page"),
        "reason": reason,
    })


def _population_problem(qc: QueryContext, chunk: dict) -> str | None:
    """None if the chunk may answer for the asked population, else an exclusion reason."""
    if not qc.population:
        return None
    pops = {str(x).lower() for x in chunk.get("population", ["all"])}
    if qc.population in pops:
        return None
    if "all" not in pops:
        return "POPULATION_MISMATCH"
    # A general document only counts for a pediatric / pregnancy question if it actually
    # talks about that population (e.g. a pump manual's "bolus dose" is not pediatric dosing).
    pattern = SPECIFIC_POPULATION_TERMS.get(qc.population)
    if pattern and not pattern.search(f"{chunk.get('text', '')} {chunk.get('parent_context') or ''}"):
        return "POPULATION_NOT_ADDRESSED"
    return None


def _numeric_ok(qc: QueryContext, chunk: dict) -> bool:
    if qc.renal_metric is None or qc.renal_value is None:
        return True
    fields = chunk.get("row_fields") or {}
    lo = fields.get(f"{qc.renal_metric}_min")
    hi = fields.get(f"{qc.renal_metric}_max")
    if lo is None or hi is None:
        return True
    return float(lo) <= float(qc.renal_value) <= float(hi)


def apply_rules(qc: QueryContext, candidates: list[dict], role: str) -> RuleResult:
    eligible: list[dict] = []
    excluded: list[dict] = []
    flags: set[str] = set()
    today = date.today()

    for source in candidates:
        chunk = dict(source)

        if not is_permitted(chunk, role):
            _exclude(excluded, chunk, "SECURITY_ACL_VIOLATION")
            continue

        status = str(chunk.get("status", "ACTIVE")).upper()
        if status == "DRAFT":
            _exclude(excluded, chunk, "DRAFT")
            continue
        if status == "RETIRED":
            _exclude(excluded, chunk, "RETIRED")
            continue
        if status == "SUPERSEDED":
            if qc.historical_intent:
                flags.add("HISTORICAL_VERSION")
            else:
                _exclude(excluded, chunk, "SUPERSEDED")
                continue

        authority = int(chunk.get("authority_level") or 0)
        if authority <= 1:
            _exclude(excluded, chunk, "LOW_AUTHORITY_EXCLUDED")
            continue

        population_problem = _population_problem(qc, chunk)
        if population_problem:
            _exclude(excluded, chunk, population_problem)
            continue

        if not _numeric_ok(qc, chunk):
            _exclude(excluded, chunk, f"{(qc.renal_metric or 'NUMERIC').upper()}_OUT_OF_RANGE")
            continue

        review_due = chunk.get("review_due")
        if review_due:
            try:
                if date.fromisoformat(str(review_due)) < today:
                    flags.add("REVIEW_OVERDUE")
            except ValueError:
                pass

        masked, pii_types = mask_pii(chunk.get("text", ""))
        if pii_types:
            chunk["text"] = masked
            chunk["pii_masked_runtime"] = True
            chunk["pii_types_runtime"] = pii_types
            flags.add("PHI_MASKED")
        else:
            chunk["pii_masked_runtime"] = False

        parent = chunk.get("parent_context")
        if parent:
            masked_parent, parent_types = mask_pii(parent)
            chunk["parent_context"] = masked_parent
            if parent_types:
                flags.add("PHI_MASKED")

        eligible.append(chunk)

    if eligible and max(int(e.get("authority_level") or 0) for e in eligible) <= 2:
        flags.add("LOW_AUTHORITY")

    return RuleResult(eligible=eligible, excluded=excluded, flags=flags)
