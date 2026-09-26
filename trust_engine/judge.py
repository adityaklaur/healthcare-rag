from __future__ import annotations

import json
import os
import re

from pydantic import ValidationError

from config.prompts import JUDGE_SYSTEM_PROMPT
from config.settings import MIN_RELEVANCE_SCORE, OPENAI_MODEL
from models import ConflictPair, JudgeItem, JudgeResult, QueryContext

SOURCE_ANCHORS = {"fda", "cms", "ahrq", "nice", "nhs", "cdc"}

STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "what", "is", "are", "be",
    "does", "do", "should", "when", "how", "i", "it", "this", "that", "from", "as", "at", "by", "patient",
}


def _keywords(text: str) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(x) > 2 and x not in STOP}


def _relevant(qc: QueryContext, e: dict) -> bool:
    q = _keywords(qc.normalized)
    t = _keywords(e.get("text", "")) | _keywords(e.get("title", ""))
    anchors = q & SOURCE_ANCHORS
    if anchors and not (anchors & t):
        return False
    overlap = len(q & t)
    vector = float(e.get("rerank_score") if e.get("rerank_score") is not None else e.get("vector_score", 0.0) or 0.0)
    exact = any(x.lower() in (e.get("text", "") + " " + e.get("title", "")).lower() for x in qc.exact_ids)
    return exact or overlap >= 2 or (overlap >= 1 and vector >= MIN_RELEVANCE_SCORE)


def _day_values(text: str) -> set[int]:
    return {int(x) for x in re.findall(r"\b(\d{1,3})\s+(?:calendar\s+)?days?\b", text or "", re.I)}


def _heuristic_conflicts(qc: QueryContext, evidence: list[dict], relevant_ids: set[str]) -> list[ConflictPair]:
    q = qc.normalized.lower()
    if not ({"day", "days", "surgery", "stop", "stopped", "withhold", "hold", "before"} & set(re.findall(r"[a-z]+", q))):
        return []
    conflicts: list[ConflictPair] = []
    for i, a in enumerate(evidence):
        if a.get("evidence_id") not in relevant_ids or int(a.get("authority_level") or 0) < 3:
            continue
        av = _day_values(a.get("text", ""))
        if not av:
            continue
        for b in evidence[i + 1:]:
            if b.get("evidence_id") not in relevant_ids or int(b.get("authority_level") or 0) < 3:
                continue
            if a.get("document_id") == b.get("document_id"):
                continue
            bv = _day_values(b.get("text", ""))
            if not bv or av == bv:
                continue
            shared = _keywords(a.get("text", "")) & _keywords(b.get("text", "")) & _keywords(qc.normalized)
            if len(shared) >= 2 or ("surgery" in a.get("text", "").lower() and "surgery" in b.get("text", "").lower()):
                conflicts.append(ConflictPair(
                    a=a["evidence_id"], b=b["evidence_id"],
                    topic="pre-operative hold duration",
                    summary=f"{a['evidence_id']} contains {sorted(av)} day(s); {b['evidence_id']} contains {sorted(bv)} day(s)",
                ))
                return conflicts
    return conflicts


def heuristic_judge(qc: QueryContext, evidence: list[dict]) -> JudgeResult:
    items: list[JudgeItem] = []
    relevant_ids: set[str] = set()
    for e in evidence:
        rel = _relevant(qc, e)
        eid = e["evidence_id"]
        items.append(JudgeItem(id=eid, relevant=rel, population_ok=True))
        if rel:
            relevant_ids.add(eid)

    sufficient = bool(relevant_ids)
    if qc.renal_metric and qc.renal_value is not None:
        ranged = [e for e in evidence if e.get("evidence_id") in relevant_ids and (e.get("row_fields") or {}).get(f"{qc.renal_metric}_min") is not None]
        if ranged:
            sufficient = True

    return JudgeResult(
        items=items,
        sufficient=sufficient,
        missing="" if sufficient else "No directly relevant eligible evidence was found.",
        conflicts=_heuristic_conflicts(qc, evidence, relevant_ids),
        mode="heuristic",
    )


def _evidence_prompt(qc: QueryContext, evidence: list[dict]) -> str:
    blocks = []
    for e in evidence:
        blocks.append(
            f"[{e['evidence_id']}] {e.get('title')} | v{e.get('version')} | p.{e.get('page')} | "
            f"population={e.get('population')} | authority={e.get('authority_level')}\n{e.get('text','')}"
        )
    return f"QUESTION:\n{qc.original}\n\nEVIDENCE:\n" + "\n\n".join(blocks)


def run_judge(qc: QueryContext, evidence: list[dict]) -> JudgeResult:
    if not evidence:
        return JudgeResult(sufficient=False, missing="No eligible evidence.", mode="rules")
    if not os.getenv("OPENAI_API_KEY"):
        return heuristic_judge(qc, evidence)

    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        for _ in range(2):
            response = client.responses.create(
                model=OPENAI_MODEL,
                instructions=JUDGE_SYSTEM_PROMPT,
                input=_evidence_prompt(qc, evidence),
                temperature=0,
            )
            raw = response.output_text.strip()
            try:
                data = json.loads(raw)
                result = JudgeResult.model_validate(data)
                result.mode = "llm"
                return result
            except (json.JSONDecodeError, ValidationError):
                continue
    except Exception:
        pass

    # Safe degraded mode for a hackathon/network failure: use deterministic checks,
    # never a free-form model answer.
    result = heuristic_judge(qc, evidence)
    result.mode = "heuristic_fallback"
    return result
