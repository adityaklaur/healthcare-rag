from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.settings import AUDIT_FILE, RETRIEVAL_BACKEND
from ingestion.pii_filter import mask_pii

log = logging.getLogger(__name__)

INSERT_AUDIT = """
INSERT INTO audit_log (query_id, user_role, query_masked, decision, reason_codes,
                       evidence_map, document_versions, withheld_doc_count, record)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def _masked(record: dict[str, Any]) -> dict[str, Any]:
    """Never store an identifier the user typed into the question."""
    record = dict(record)
    record["query"], _ = mask_pii(str(record.get("query", "")))
    return record


def _append_jsonl(record: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def _insert_db(record: dict[str, Any]) -> None:
    from psycopg.types.json import Jsonb
    from db.connection import app_pool

    payload = json.loads(json.dumps(record, default=str))  # plain JSON types only
    with app_pool().connection() as conn:
        conn.execute(INSERT_AUDIT, (
            record["query_id"], record.get("user_role", ""), record.get("query", ""),
            record.get("decision", ""), list(record.get("reason_codes") or []),
            Jsonb(record.get("evidence_map") or {}), list(record.get("document_versions") or []),
            int((record.get("withheld") or {}).get("doc_count") or 0), Jsonb(payload),
        ))


def append_audit(record: dict[str, Any], path: Path = AUDIT_FILE) -> str:
    """Write one audit record. Returns where it went: 'audit_log', 'jsonl' or 'jsonl_fallback'.

    PostgreSQL backend: one row in audit_log (the app user can INSERT but not UPDATE/DELETE).
    If the database is unreachable the record goes to the JSONL file instead, so no
    query is ever left unaudited.
    """
    record = _masked(record)
    if RETRIEVAL_BACKEND != "files":
        try:
            _insert_db(record)
            return "audit_log"
        except Exception as exc:  # noqa: BLE001
            log.warning("audit_log insert failed, writing JSONL instead: %s", exc)
            record["audit_fallback"] = str(exc)[:300]
            _append_jsonl(record, path)
            return "jsonl_fallback"
    _append_jsonl(record, path)
    return "jsonl"


def new_query_id() -> str:
    now = datetime.now(timezone.utc)
    return f"q_{now.strftime('%Y%m%dT%H%M%SZ')}_{now.microsecond:06x}"[-36:]
