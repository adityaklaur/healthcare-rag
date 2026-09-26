from models import Decision, JudgeResult, QueryContext, RetrievalResult, RuleResult, WithheldSummary, ConflictPair
from trust_engine.decision import decide


def qc(**kwargs):
    base = dict(original="q", normalized="q", tokens=["q"])
    base.update(kwargs)
    return QueryContext(**base)


def ev():
    return [{"chunk_id": "A", "authority_level": 4}]


def test_phi_has_highest_precedence():
    d = decide(qc(requests_identifier=True), RuleResult(ev(), [], set()), JudgeResult(sufficient=True), RetrievalResult(ev(), WithheldSummary(), ["A"]))
    assert d.state == "REFUSE" and "PHI_REQUEST" in d.reason_codes


def test_restricted_when_only_relevant_withheld_content_exists():
    d = decide(qc(), RuleResult([], [], set()), JudgeResult(sufficient=False), RetrievalResult([], WithheldSummary(1, 0.95), []))
    assert d.state == "RESTRICTED"


def test_conflict_precedes_warning():
    judge = JudgeResult(sufficient=True, conflicts=[ConflictPair(a="E1", b="E2")])
    d = decide(qc(), RuleResult(ev(), [], {"REVIEW_OVERDUE"}), judge, RetrievalResult(ev(), WithheldSummary(), ["A"]))
    assert d.state == "CONFLICT"


def test_warning_then_answer():
    d = decide(qc(), RuleResult(ev(), [], {"HISTORICAL_VERSION"}), JudgeResult(sufficient=True), RetrievalResult(ev(), WithheldSummary(), ["A"]))
    assert d.state == "ANSWER_WITH_WARNING"
