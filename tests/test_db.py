"""PostgreSQL integration tests: row-level security, search function, withheld summary,
append-only audit. Skipped automatically when the database is not configured/loaded.

    docker compose up -d && python scripts/build_db.py && pytest -q
"""
from __future__ import annotations

import pytest

from config.settings import OWNER_DATABASE_URL, RETRIEVAL_BACKEND

pytestmark = pytest.mark.skipif(RETRIEVAL_BACKEND == "files", reason="file backend selected")

RESTRICTED_DOC = "RES-FDA-PUMP"          # collection restricted_research (see data/manifest.yaml)


@pytest.fixture(scope="module")
def db():
    from db.connection import app_pool, database_status, query_as_role, withheld_summary
    status = database_status()
    if not status.get("ok") or not status.get("chunks"):
        pytest.skip(f"database not reachable or empty: {status.get('error', 'no chunks')}")
    return {"pool": app_pool(), "q": query_as_role, "withheld": withheld_summary}


def _restricted_vector(db):
    """Embedding of a restricted chunk, read as admin: a query that is 'about' that document."""
    row = db["q"]("admin", "SELECT embedding FROM chunks WHERE doc_version_id LIKE %s LIMIT 1",
                  (f"{RESTRICTED_DOC}@%",))
    assert row, f"{RESTRICTED_DOC} is not loaded"
    return row[0][0]


def test_doctor_cannot_read_restricted_rows(db):
    sql = "SELECT count(*) FROM chunks WHERE doc_version_id LIKE %s"
    assert db["q"]("doctor", sql, (f"{RESTRICTED_DOC}@%",))[0][0] == 0
    assert db["q"]("researcher", sql, (f"{RESTRICTED_DOC}@%",))[0][0] > 0


def test_no_role_means_no_rows(db):
    with db["pool"].connection() as conn:
        assert conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 0


def test_search_function_never_returns_restricted_ids(db):
    qvec = _restricted_vector(db)
    for role, allowed in [("doctor", False), ("researcher", True)]:
        ids = [r[0] for r in db["q"](role,
               "SELECT chunk_id FROM search_candidates(%s, %s, %s::text[], %s)",
               (qvec, "FDA infusion pump improvement initiative", [], role))]
        assert any(i.startswith(RESTRICTED_DOC) for i in ids) is allowed, role


def test_withheld_summary_returns_only_aggregates(db):
    qvec = _restricted_vector(db)
    doc_count, max_sim = db["withheld"](qvec, "doctor", 30)
    assert doc_count >= 1 and max_sim is not None and max_sim > 0.99   # the chunk itself is nearest
    assert db["withheld"](qvec, "admin", 30) == (0, None)


def test_every_role_in_settings_is_synced(db):
    from config.settings import ROLE_COLLECTIONS
    rows = db["q"]("admin", "SELECT role, collection FROM role_collections")
    assert {(r, c) for r, c in rows} == {(r, c) for r, cs in ROLE_COLLECTIONS.items() for c in cs}


def test_audit_log_is_append_only_for_the_app(db):
    import psycopg
    with db["pool"].connection() as conn:
        for sql in ("UPDATE audit_log SET decision = 'X'", "DELETE FROM audit_log"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with conn.transaction():
                    conn.execute(sql)


def test_audit_insert_masks_the_question(db):
    from audit.logger import append_audit, new_query_id
    qid = new_query_id() + "_test"
    where = append_audit({"query_id": qid, "user_role": "doctor", "decision": "REFUSE",
                          "reason_codes": ["PHI_REQUEST"], "query": "What is MRN 00482913?"})
    assert where == "audit_log"
    stored = db["q"]("admin", "SELECT query_masked FROM audit_log WHERE query_id = %s", (qid,))[0][0]
    assert "00482913" not in stored and "[MRN]" in stored
    if OWNER_DATABASE_URL:  # tidy up (only the owner may delete)
        from db.connection import owner_connection
        with owner_connection() as conn:
            conn.execute("DELETE FROM audit_log WHERE query_id = %s", (qid,))


def test_chunk_collections_match_their_documents(db):
    """RLS filters chunks by their own collection column; it must equal the document's."""
    mismatched = db["q"]("admin", "SELECT count(*) FROM chunks c JOIN documents d USING (doc_version_id)"
                                  " WHERE c.collection <> d.collection")[0][0]
    assert mismatched == 0
