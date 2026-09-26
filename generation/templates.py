from __future__ import annotations

from models import Decision, JudgeResult


def warning_text(reason_codes: list[str], evidence: list[dict]) -> str:
    parts: list[str] = []
    if "REVIEW_OVERDUE" in reason_codes:
        dates = sorted({e.get("review_due") for e in evidence if e.get("review_due")})
        parts.append("Source review is overdue" + (f" (review due {dates[0]})" if dates else ""))
    if "LOW_AUTHORITY" in reason_codes:
        parts.append("Only low-authority evidence supports this answer")
    if "HISTORICAL_VERSION" in reason_codes:
        parts.append("Historical/superseded evidence is being shown because historical mode is active")
    return "; ".join(parts) + ("." if parts else "")


def render_conflict(judge: JudgeResult, evidence: list[dict]) -> dict:
    by_id = {e.get("evidence_id"): e for e in evidence}
    sources = []
    if judge.conflicts:
        pair = judge.conflicts[0]
        for eid in [pair.a, pair.b]:
            e = by_id.get(eid)
            if not e:
                continue
            sources.append({
                "evidence_id": eid,
                "title": e.get("title"),
                "version": e.get("version"),
                "effective_date": e.get("effective_date"),
                "authority_level": e.get("authority_level"),
                "page": e.get("page"),
                "text": e.get("text", ""),
                "owner_contact": e.get("owner_contact"),
            })
    return {
        "text": "Accessible approved sources contain incompatible instructions. The system has not selected a recommendation; clinical review is required.",
        "sources": sources,
    }


def render_refusal(decision: Decision, excluded: list[dict], evidence: list[dict]) -> dict:
    reasons = set(decision.reason_codes)
    if "PHI_REQUEST" in reasons:
        return {"text": "This request asks for a patient identifier. The system does not return patient identifiers.", "escalate_to": "Privacy / Health Information Management"}
    if "POPULATION_MISMATCH" in reasons:
        return {"text": "No approved evidence in the available documents directly applies to the requested patient population.", "escalate_to": _owner(evidence) or "Clinical governance"}
    return {"text": "There is not enough permitted, current and directly relevant evidence to answer safely.", "escalate_to": _owner(evidence) or "Document owner / clinical governance"}


def render_restricted() -> dict:
    return {
        "text": "Relevant material exists in a collection your role cannot access. Contact the appropriate information owner to request access."
    }


def _owner(evidence: list[dict]) -> str | None:
    for e in evidence:
        if e.get("owner_contact"):
            return e["owner_contact"]
    return None
