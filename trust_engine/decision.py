from __future__ import annotations

from config.settings import DISCLOSE_RESTRICTED_EXISTENCE, RESTRICTED_THRESHOLD
from models import Decision, JudgeResult, QueryContext, RetrievalResult, RuleResult

WARNING_FLAGS = {"REVIEW_OVERDUE", "LOW_AUTHORITY", "HISTORICAL_VERSION"}


def decide(qc: QueryContext, rules: RuleResult, judge: JudgeResult, retrieval: RetrievalResult) -> Decision:
    # Fixed precedence: PHI -> insufficient/restricted -> conflict -> warning -> answer.
    if qc.requests_identifier:
        return Decision("REFUSE", ["PHI_REQUEST"])

    if not rules.eligible or not judge.sufficient:
        withheld_score = retrieval.withheld.max_score
        if (
            DISCLOSE_RESTRICTED_EXISTENCE
            and withheld_score is not None
            and withheld_score >= RESTRICTED_THRESHOLD
        ):
            return Decision("RESTRICTED", ["RELEVANT_EVIDENCE_WITHHELD"])
        reasons = ["INSUFFICIENT"]
        reasons.extend(sorted({x.get("reason") for x in rules.excluded if x.get("reason")}))
        return Decision("REFUSE", reasons)

    if judge.conflicts:
        return Decision("CONFLICT", ["CROSS_DOCUMENT_CONFLICT"])

    warning = sorted(rules.flags & WARNING_FLAGS)
    if warning:
        return Decision("ANSWER_WITH_WARNING", warning)

    return Decision("ANSWER", [])
