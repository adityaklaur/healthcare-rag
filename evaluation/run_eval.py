from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import (
    DENSE_CANDIDATES, ENABLE_RERANKER, EMBEDDING_MODEL, MIN_RELEVANCE_SCORE, RESTRICTED_THRESHOLD,
    RETRIEVAL_BACKEND, TOP_K,
)
from pipeline import answer_query

HERE = Path(__file__).resolve().parent
QUESTIONS = HERE / "questions.json"
RESULTS = HERE / "results.json"
RESULTS_MD = HERE / "results.md"


def main() -> None:
    questions = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    rows = []
    decision_pass = 0
    evidence_hits = 0
    evidence_total = 0
    acl_leaks = 0
    identifier_leaks = 0

    for q in questions:
        result = answer_query(
            q["question"], q["role"], force_historical=bool(q.get("force_historical")), write_audit=False
        )
        got_decision = result["decision"]
        decision_ok = got_decision == q["expected_decision"]
        decision_pass += int(decision_ok)

        docs = {e.get("document_id") for e in result.get("evidence", [])}
        expected_docs = set(q.get("expected_documents", []))
        evidence_ok = expected_docs.issubset(docs) if expected_docs else True
        if expected_docs:
            evidence_total += 1
            evidence_hits += int(evidence_ok)

        if got_decision == "RESTRICTED" and result.get("evidence"):
            acl_leaks += 1
        answer_blob = json.dumps(result.get("answer", {}), ensure_ascii=False)
        if "MRN" in answer_blob and q.get("expected_reason") == "PHI_REQUEST":
            # The phrase MRN can appear in the refusal explanation, so only count numeric MRN leakage.
            import re
            if re.search(r"MRN[:#\s]*\d{6,10}", answer_blob, re.I):
                identifier_leaks += 1

        rows.append({
            "id": q["id"], "role": q["role"], "question": q["question"],
            "expected_decision": q["expected_decision"], "got_decision": got_decision,
            "decision_pass": decision_ok, "expected_documents": sorted(expected_docs),
            "got_documents": sorted(d for d in docs if d), "evidence_pass": evidence_ok,
            "reason_codes": result.get("reason_codes", []),
        })
        print(f"{q['id']:>2}. {'PASS' if decision_ok and evidence_ok else 'FAIL'} | {q['expected_decision']} -> {got_decision} | {q['question']}")

    metrics = {
        "decision_accuracy": decision_pass / len(questions),
        "evidence_recall": (evidence_hits / evidence_total) if evidence_total else None,
        "acl_leakage_count": acl_leaks,
        "identifier_leakage_count": identifier_leaks,
        "questions": len(questions),
    }
    payload = {"metrics": metrics, "rows": rows}
    RESULTS.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    md = [
        "| # | Role | Expected | Got | Decision | Evidence |",
        "|---:|---|---|---|---|---|",
    ]
    for r in rows:
        md.append(
            f"| {r['id']} | {r['role']} | {r['expected_decision']} | {r['got_decision']} | "
            f"{'✅' if r['decision_pass'] else '❌'} | {'✅' if r['evidence_pass'] else '❌'} |"
        )
    md += ["", "```json", json.dumps(metrics, indent=2), "```", ""]
    RESULTS_MD.write_text("\n".join(md), encoding="utf-8")
    print("\n" + json.dumps(metrics, indent=2))
    if RETRIEVAL_BACKEND != "files":
        save_to_db(rows, metrics)


def save_to_db(rows: list[dict], metrics: dict) -> None:
    """Store this run in eval_runs / eval_results (see db/reports.sql for the pass-rate query)."""
    try:
        from psycopg.types.json import Jsonb
        from db.connection import app_pool
        settings = {"embedding_model": EMBEDDING_MODEL, "top_k": TOP_K, "dense_candidates": DENSE_CANDIDATES,
                    "min_relevance": MIN_RELEVANCE_SCORE, "restricted_threshold": RESTRICTED_THRESHOLD,
                    "reranker": ENABLE_RERANKER}
        with app_pool().connection() as conn, conn.transaction():
            run_id = conn.execute(
                "INSERT INTO eval_runs (backend, settings, metrics) VALUES (%s, %s, %s) RETURNING run_id",
                (RETRIEVAL_BACKEND, Jsonb(settings), Jsonb(metrics)),
            ).fetchone()[0]
            for r in rows:
                conn.execute(
                    "INSERT INTO eval_results (run_id, question_id, role, question, expected_decision,"
                    " actual_decision, expected_documents, got_documents, reason_codes, decision_pass, evidence_pass)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (run_id, r["id"], r["role"], r["question"], r["expected_decision"], r["got_decision"],
                     r["expected_documents"], r["got_documents"], r["reason_codes"],
                     r["decision_pass"], r["evidence_pass"]),
                )
        print(f"Saved as eval run {run_id} in PostgreSQL.")
    except Exception as exc:  # noqa: BLE001 - results files are already written
        print(f"[WARN] could not save the run to PostgreSQL: {exc}")


if __name__ == "__main__":
    main()
