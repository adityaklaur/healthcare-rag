from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audit.logger import append_audit, new_query_id
from config.settings import INDEX_DIR, OPENAI_MODEL, RETRIEVAL_BACKEND
from generation.citations import citation_map
from generation.generator import generate_grounded
from generation.templates import render_conflict, render_refusal, render_restricted, warning_text
from models import Decision, JudgeResult, RetrievalResult, RuleResult, WithheldSummary
from query.understand import understand_query
from retrieval.hybrid import retrieve
from trust_engine.decision import decide
from trust_engine.judge import run_judge
from trust_engine.rules import apply_rules


def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _index_version() -> str | None:
    if RETRIEVAL_BACKEND != "files":
        from db.connection import database_status
        return database_status().get("ingested_at")
    path = INDEX_DIR / "index_stats.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("built_at")
    except Exception:
        return None


def _assign_evidence_ids(evidence: list[dict]) -> list[dict]:
    out: list[dict] = []
    for i, item in enumerate(evidence, start=1):
        item = dict(item)
        item["evidence_id"] = f"E{i}"
        out.append(item)
    return out


def _filter_judge_relevance(rules: RuleResult, judge: JudgeResult) -> RuleResult:
    relevant = {item.id for item in judge.items if item.relevant and item.population_ok}
    if not judge.items:
        return rules
    eligible: list[dict] = []
    excluded = list(rules.excluded)
    for e in rules.eligible:
        if e.get("evidence_id") in relevant:
            eligible.append(e)
        else:
            excluded.append({
                "chunk_id": e.get("chunk_id"),
                "document_id": e.get("document_id"),
                "title": e.get("title"),
                "page": e.get("page"),
                "reason": "NOT_RELEVANT",
            })
    return RuleResult(eligible=eligible, excluded=excluded, flags=set(rules.flags))


def _base_audit(query_id: str, role: str, qc, retrieval_result: RetrievalResult, rules: RuleResult, judge: JudgeResult, decision: Decision, latency: dict[str, int]) -> dict[str, Any]:
    return {
        "query_id": query_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_role": role,
        "query": qc.original,
        "entities": {
            "population": qc.population,
            "renal_metric": qc.renal_metric,
            "renal_value": qc.renal_value,
            "exact_ids": qc.exact_ids,
            "requests_identifier": qc.requests_identifier,
            "historical_intent": qc.historical_intent,
        },
        "retrieved": retrieval_result.retrieved_chunk_ids,
        "withheld": {
            "doc_count": retrieval_result.withheld.doc_count,
            "max_score": retrieval_result.withheld.max_score,
        },
        "excluded": [{"chunk": x.get("chunk_id"), "reason": x.get("reason")} for x in rules.excluded],
        "evidence_map": {e.get("evidence_id"): e.get("chunk_id") for e in rules.eligible},
        "document_versions": sorted({f"{e.get('document_id')}@{e.get('version')}" for e in rules.eligible}),
        "judge": judge.model_dump(),
        "decision": decision.state,
        "reason_codes": decision.reason_codes,
        "model": OPENAI_MODEL if judge.mode == "llm" else None,
        "retrieval_backend": RETRIEVAL_BACKEND,
        "index_version": _index_version(),
        "latency_ms": latency,
    }


def answer_query(question: str, role: str, force_historical: bool = False, write_audit: bool = True) -> dict[str, Any]:
    query_id = new_query_id()
    total_start = time.perf_counter()
    qc = understand_query(question, force_historical=force_historical)

    # Privacy request guard runs before search.
    if qc.requests_identifier:
        retrieval_result = RetrievalResult([], WithheldSummary(), [], historical_intent=qc.historical_intent)
        rules = RuleResult([], [], set())
        judge = JudgeResult(sufficient=False, missing="Identifier request blocked before retrieval.", mode="rules")
        decision = Decision("REFUSE", ["PHI_REQUEST"])
        latency = {"retrieval": 0, "judge": 0, "generation": 0, "total": _ms(total_start)}
        audit = _base_audit(query_id, role, qc, retrieval_result, rules, judge, decision, latency)
        audit["guard"] = {"passed": True, "retries": 0, "skipped": True}
        audit_destination = append_audit(audit) if write_audit else None
        return {
            "query_id": query_id, "decision": decision.state, "reason_codes": decision.reason_codes,
            "answer": render_refusal(decision, [], []), "warning": "", "evidence": [], "excluded": [],
            "citations": {}, "withheld": audit["withheld"], "audit": audit,
            "audit_destination": audit_destination,
        }

    t = time.perf_counter()
    retrieval_result = retrieve(qc, role)
    retrieval_ms = _ms(t)

    rules = apply_rules(qc, retrieval_result.evidence, role)
    rules.eligible = _assign_evidence_ids(rules.eligible)

    t = time.perf_counter()
    judge = run_judge(qc, rules.eligible)
    judge_ms = _ms(t)
    rules = _filter_judge_relevance(rules, judge)

    # If relevance filtering removed everything, sufficiency must not remain true.
    if not rules.eligible:
        judge.sufficient = False
        if not judge.missing:
            judge.missing = "No directly relevant eligible evidence remains after judging."

    decision = decide(qc, rules, judge, retrieval_result)
    generation_ms = 0
    guard_payload: dict[str, Any] = {"passed": True, "retries": 0, "skipped": True}
    warning = warning_text(decision.reason_codes, rules.eligible)

    if decision.state in {"ANSWER", "ANSWER_WITH_WARNING"}:
        t = time.perf_counter()
        guard = generate_grounded(qc, rules.eligible, decision)
        generation_ms = _ms(t)
        guard_payload = {
            "passed": guard.passed,
            "retries": guard.retries,
            "errors": guard.errors,
            "pii_masked": guard.pii_masked,
            "skipped": False,
        }
        if not guard.passed or guard.answer is None:
            decision = Decision("REFUSE", ["GUARD_FAILED"])
            answer: dict[str, Any] = render_refusal(decision, rules.excluded, rules.eligible)
        else:
            answer = {
                "sentences": [s.model_dump() for s in guard.answer.sentences],
                "mode": guard.answer.mode,
            }
    elif decision.state == "CONFLICT":
        answer = render_conflict(judge, rules.eligible)
    elif decision.state == "RESTRICTED":
        answer = render_restricted()
    else:
        answer = render_refusal(decision, rules.excluded, rules.eligible)

    latency = {"retrieval": retrieval_ms, "judge": judge_ms, "generation": generation_ms, "total": _ms(total_start)}
    audit = _base_audit(query_id, role, qc, retrieval_result, rules, judge, decision, latency)
    audit["guard"] = guard_payload
    audit_destination = append_audit(audit) if write_audit else None

    return {
        "query_id": query_id,
        "decision": decision.state,
        "reason_codes": decision.reason_codes,
        "answer": answer,
        "warning": warning,
        "evidence": rules.eligible,
        "excluded": rules.excluded,
        "citations": citation_map(rules.eligible),
        "withheld": {"doc_count": retrieval_result.withheld.doc_count, "max_score": retrieval_result.withheld.max_score},
        "audit": audit,
        "audit_destination": audit_destination,
    }
