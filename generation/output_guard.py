from __future__ import annotations

import re

from ingestion.pii_filter import mask_pii
from models import GeneratedAnswer, GuardResult

CLINICAL_NUMBER = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|g|kg|ml|mL|l|L|mmol|days?|hours?|hrs?|minutes?|mins?|%|"
    r"mL/min(?:/1\.73\s*m(?:2|²))?|mmhg|cm|mm)\b",
    re.I,
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().replace("²", "2")).strip()


def validate_answer(answer: GeneratedAnswer, evidence_map: dict[str, dict]) -> GuardResult:
    errors: list[str] = []
    pii_masked = False

    for sentence in answer.sentences:
        if not sentence.citations:
            errors.append("UNCITED_SENTENCE")
            continue
        missing = [eid for eid in sentence.citations if eid not in evidence_map]
        if missing:
            errors.append("UNKNOWN_CITATION:" + ",".join(missing))
            continue

        support = "\n".join(
            (evidence_map[eid].get("text", "") + "\n" + (evidence_map[eid].get("parent_context") or "") + "\n" + str(evidence_map[eid]))
            for eid in sentence.citations
        )
        support_norm = _norm(support)
        for quantity in CLINICAL_NUMBER.findall(sentence.text):
            if _norm(quantity) not in support_norm:
                errors.append(f"UNGROUNDED_NUMBER:{quantity}")

        masked, found = mask_pii(sentence.text)
        if found:
            sentence.text = masked
            pii_masked = True

    return GuardResult(passed=not errors, answer=answer if not errors else None, errors=errors, pii_masked=pii_masked)
