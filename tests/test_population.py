from query.understand import understand_query
from trust_engine.rules import apply_rules


def _chunk(cid, population, text):
    return {"chunk_id": cid, "document_id": cid, "title": cid, "version": "1", "status": "ACTIVE",
            "authority_level": 4, "collection": "clinical", "population": population, "text": text,
            "page": 1, "review_due": None}


def test_general_document_must_mention_the_population():
    qc = understand_query("What is the pediatric dose of Demo Drug A?")
    rules = apply_rules(qc, [
        _chunk("PUMP", ["all"], "Programming a bolus dose of the drug currently being administered."),
        _chunk("KIDS", ["all"], "Pediatric patients: weight-based dosing applies to children."),
        _chunk("ADULT", ["adult"], "Demo Drug A adult dose."),
    ], "doctor")
    assert [c["chunk_id"] for c in rules.eligible] == ["KIDS"]
    reasons = {x["chunk_id"]: x["reason"] for x in rules.excluded}
    assert reasons == {"PUMP": "POPULATION_NOT_ADDRESSED", "ADULT": "POPULATION_MISMATCH"}


def test_general_questions_are_unaffected():
    qc = understand_query("How do I program a bolus dose on the pump?")
    rules = apply_rules(qc, [_chunk("PUMP", ["all"], "Programming a bolus dose.")], "doctor")
    assert [c["chunk_id"] for c in rules.eligible] == ["PUMP"]
