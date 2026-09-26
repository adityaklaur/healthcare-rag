from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import streamlit as st

from config.settings import INDEX_DIR, RETRIEVAL_BACKEND, ROLE_COLLECTIONS, ROLES
from pipeline import answer_query

st.set_page_config(page_title="Clinical Evidence Assistant", page_icon="🏥", layout="wide")
st.title("🏥 Clinical Evidence Assistant")
st.caption("Evidence-first enterprise healthcare RAG — Clinical Evidence Trust Engine")
st.warning("Hackathon prototype only. Do not use for real patient-care decisions or real patient data.")

with st.sidebar:
    st.header("Session")
    role = st.selectbox("Role", ROLES, index=0)
    force_historical = st.checkbox("Historical / time-machine mode", value=False)
    st.caption("Visible collections: " + ", ".join(sorted(ROLE_COLLECTIONS.get(role, set()))))
    st.divider()
    st.markdown("**Decision states**")
    st.markdown("🟢 ANSWER  \n🟠 ANSWER WITH WARNING  \n🟣 CONFLICT  \n⚪ REFUSE / ESCALATE  \n🔴 RESTRICTED")

USE_DB = RETRIEVAL_BACKEND != "files"
BUILD_SCRIPT = "scripts/build_db.py" if USE_DB else "scripts/build_index.py"

if USE_DB:
    from db.connection import database_status, query_as_role
    status = database_status()
    with st.sidebar:
        st.divider()
        if status["ok"]:
            st.markdown(f"**Database** 🟢 PostgreSQL + pgvector  \n{status['documents']} documents · {status['chunks']} chunks")
            st.caption("Access control is enforced by row-level security in the database.")
        else:
            st.markdown("**Database** 🔴 not reachable")
    if not status["ok"]:
        st.error("Cannot reach PostgreSQL. Start it with `docker compose up -d` and check DATABASE_URL in .env.")
        st.code(status["error"][-1500:])
        st.stop()
    ready = status["chunks"] > 0
    not_ready_msg = "The database is running but no documents are loaded yet."
    build_label = "Loading documents into PostgreSQL (parse, embed, insert)…"
else:
    required = [INDEX_DIR / "faiss.index", INDEX_DIR / "bm25.pkl", INDEX_DIR / "chunks.jsonl"]
    ready = all(p.exists() for p in required)
    not_ready_msg = "Search indexes are not built yet."
    build_label = "Parsing documents and building FAISS + BM25 indexes…"

if not ready:
    st.error(not_ready_msg)
    st.code(f"python {BUILD_SCRIPT}", language="bash")
    if st.button("Build now"):
        with st.spinner(build_label):
            proc = subprocess.run(
                [sys.executable, BUILD_SCRIPT],
                cwd=str(Path(__file__).resolve().parent), capture_output=True, text=True,
            )
        if proc.returncode == 0:
            st.success("Build finished. Reloading…")
            st.code(proc.stdout[-4000:])
            st.rerun()
        else:
            st.error("Build failed.")
            st.code((proc.stdout + "\n" + proc.stderr)[-6000:])
    st.stop()

default_q = "How many days before elective surgery should Demo Drug A be stopped?"
question = st.text_area("Ask a question", value=default_q, height=90)

if st.button("Ask", type="primary", use_container_width=True):
    with st.spinner("Searching evidence, enforcing access control, and running trust checks…"):
        result = answer_query(question, role, force_historical=force_historical)

    decision = result["decision"]
    reason = ", ".join(result.get("reason_codes") or []) or "No warning flags"

    if decision == "ANSWER":
        st.success("🟢 ANSWER — evidence passed the trust checks")
    elif decision == "ANSWER_WITH_WARNING":
        st.warning("🟠 ANSWER WITH WARNING — " + (result.get("warning") or reason))
    elif decision == "CONFLICT":
        st.error("🟣 CLINICAL CONFLICT DETECTED — no recommendation was selected")
    elif decision == "RESTRICTED":
        st.error("🔴 RESTRICTED — relevant evidence exists outside this role's permitted collections")
    else:
        st.info("⚪ REFUSE / ESCALATE — insufficient or disallowed evidence")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Decision", decision)
    c2.metric("Eligible evidence", len(result.get("evidence", [])))
    c3.metric("Excluded", len(result.get("excluded", [])))
    c4.metric("Withheld docs", result.get("withheld", {}).get("doc_count", 0))
    st.caption("Reason codes: " + reason)

    st.subheader("Answer")
    answer = result.get("answer", {})
    if "sentences" in answer:
        for sentence in answer["sentences"]:
            refs = " ".join(f"[{x}]" for x in sentence.get("citations", []))
            st.markdown(f"{sentence.get('text','')} {refs}")
    else:
        st.write(answer.get("text", ""))
        if answer.get("escalate_to"):
            st.caption("Escalate to: " + answer["escalate_to"])
        for src in answer.get("sources", []):
            with st.expander(f"{src.get('evidence_id')} · {src.get('title')} · v{src.get('version')} · p.{src.get('page')}", expanded=True):
                st.write(src.get("text", ""))
                st.caption(f"Authority {src.get('authority_level')} · effective {src.get('effective_date')} · owner {src.get('owner_contact')}")

    if result.get("citations"):
        st.subheader("Citations")
        for eid, rendered in result["citations"].items():
            st.markdown(f"**[{eid}]** {rendered}")

    st.subheader("Evidence")
    if not result.get("evidence"):
        st.caption("No permitted eligible evidence is displayed for this decision.")
    for e in result.get("evidence", []):
        label = f"[{e['evidence_id']}] {e.get('title')} · v{e.get('version')} · p.{e.get('page')} · authority {e.get('authority_level')}"
        with st.expander(label, expanded=e.get("evidence_id") in {"E1", "E2"}):
            st.write(e.get("text", ""))
            if e.get("parent_context"):
                st.markdown("**Parent table / section context**")
                st.code(e["parent_context"])
            st.caption(
                f"chunk={e.get('chunk_id')} · collection={e.get('collection')} · status={e.get('status')} · "
                f"vector={e.get('vector_score')} · {'text' if USE_DB else 'BM25'}={e.get('bm25_score')} · RRF={e.get('rrf_score')}"
            )

    with st.expander("Excluded evidence", expanded=False):
        if not result.get("excluded"):
            st.caption("None")
        for x in result.get("excluded", []):
            st.write(f"{x.get('chunk_id')} — {x.get('reason')}")
        st.caption("Withheld ACL content is never listed here; only the aggregate count/score is retained.")

    with st.expander("Audit", expanded=False):
        where = {"audit_log": "Stored in the audit_log table (append-only).",
                 "jsonl_fallback": "Database write failed; stored in audit/audit.jsonl instead.",
                 "jsonl": "Stored in audit/audit.jsonl."}.get(result.get("audit_destination") or "", "")
        if where:
            st.caption(where)
        st.json(result.get("audit", {}))

if USE_DB and role == "admin":
    with st.expander("Recent audit log (admin)", expanded=False):
        recent = query_as_role(role, (
            "SELECT created_at, user_role, decision, array_to_string(reason_codes, ', '), query_masked"
            " FROM audit_log ORDER BY created_at DESC LIMIT 20"))
        st.dataframe(
            [{"time": r[0].strftime("%Y-%m-%d %H:%M:%S"), "role": r[1], "decision": r[2], "reasons": r[3], "question": r[4]}
             for r in recent],
            use_container_width=True, hide_index=True,
        )
