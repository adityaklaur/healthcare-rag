from models import QueryContext
from trust_engine.rules import apply_rules


def _chunk(cid, lo, hi):
    return {
        "chunk_id": cid, "document_id": "FORM", "title": "Formulary", "version": "5.1",
        "status": "ACTIVE", "authority_level": 5, "collection": "formulary", "population": ["adult"],
        "chunk_type": "table_row", "row_fields": {"egfr_min": lo, "egfr_max": hi},
        "text": f"eGFR range {lo} to {hi}", "page": 1, "review_due": None,
    }


def test_egfr_25_keeps_only_matching_row():
    qc = QueryContext("eGFR 25", "eGFR 25", ["egfr", "25"], renal_metric="egfr", renal_value=25)
    rules = apply_rules(qc, [_chunk("R2", 30, 59.99), _chunk("R3", 0, 29.99)], "pharmacist")
    assert [x["chunk_id"] for x in rules.eligible] == ["R3"]
    assert any(x["reason"] == "EGFR_OUT_OF_RANGE" for x in rules.excluded)
