from __future__ import annotations

import json
import os

from pydantic import ValidationError

from config.prompts import GENERATION_SYSTEM_PROMPT
from config.settings import OPENAI_MODEL
from generation.output_guard import validate_answer
from generation.templates import warning_text
from models import AnswerSentence, Decision, GeneratedAnswer, GuardResult, QueryContext


def _evidence_block(evidence: list[dict]) -> str:
    blocks: list[str] = []
    for e in evidence:
        location = []
        if e.get("table_id"):
            location.append(str(e["table_id"]))
        if e.get("row_id"):
            location.append(str(e["row_id"]))
        if e.get("page"):
            location.append(f"p.{e['page']}")
        block = (
            f"[{e['evidence_id']}] {e.get('title')} | v{e.get('version')} | {' | '.join(location)}\n"
            f"{e.get('text','')}"
        )
        if e.get("parent_context"):
            block += f"\n[CONTEXT for {e['evidence_id']}]\n{e['parent_context']}"
        blocks.append(block)
    return "\n\n".join(blocks)


def _extractive_answer(evidence: list[dict], decision: Decision) -> GeneratedAnswer:
    top = evidence[0]
    text = " ".join(top.get("text", "").split())
    if len(text) > 520:
        text = text[:520].rsplit(" ", 1)[0] + "…"
    prefix = ""
    if decision.state == "ANSWER_WITH_WARNING":
        prefix = warning_text(decision.reason_codes, evidence) + " "
    return GeneratedAnswer(
        sentences=[AnswerSentence(text=(prefix + text).strip(), citations=[top["evidence_id"]])],
        mode="extractive_fallback",
    )


def _call_llm(qc: QueryContext, evidence: list[dict], decision: Decision) -> GeneratedAnswer:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    warnings = warning_text(decision.reason_codes, evidence) or "none"
    user = f"QUESTION:\n{qc.original}\n\nWARNINGS:\n{warnings}\n\nEVIDENCE:\n{_evidence_block(evidence)}"
    response = client.responses.create(
        model=OPENAI_MODEL,
        instructions=GENERATION_SYSTEM_PROMPT,
        input=user,
        temperature=0,
    )
    raw = response.output_text.strip()
    parsed = json.loads(raw)
    ans = GeneratedAnswer.model_validate(parsed)
    ans.mode = "llm"
    return ans


def generate_grounded(qc: QueryContext, evidence: list[dict], decision: Decision) -> GuardResult:
    if decision.state not in {"ANSWER", "ANSWER_WITH_WARNING"}:
        return GuardResult(passed=False, answer=None, errors=["DECISION_BLOCKS_GENERATION"])

    evidence_map = {e["evidence_id"]: e for e in evidence}
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        answer = _extractive_answer(evidence, decision)
        result = validate_answer(answer, evidence_map)
        result.retries = 0
        return result

    last_errors: list[str] = []
    for attempt in range(2):
        try:
            answer = _call_llm(qc, evidence, decision)
            guard = validate_answer(answer, evidence_map)
            guard.retries = attempt
            if guard.passed:
                return guard
            last_errors = guard.errors
        except (json.JSONDecodeError, ValidationError, KeyError, Exception) as exc:
            last_errors = [f"GENERATION_ERROR:{type(exc).__name__}"]

    return GuardResult(passed=False, answer=None, errors=last_errors or ["GUARD_FAILED"], retries=1)
