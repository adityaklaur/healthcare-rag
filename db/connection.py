"""PostgreSQL access for the app (rag_app, row-level security) and ingestion (rag_owner)."""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Iterator

from config.settings import DATABASE_URL, OWNER_DATABASE_URL        return {"ok": False, "error": f"{type(exc).__name__}: {exc!r}"}


def _configure(conn) -> None:
    from pgvector.psycopg import register_vector
    register_vector(conn)


@lru_cache(maxsize=1)
def app_pool():
    """Connection pool for the Streamlit app. Connects as rag_app."""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env and start the database.")
    from psycopg_pool import ConnectionPool
    return ConnectionPool(DATABASE_URL, configure=_configure, min_size=1, max_size=5, open=True, timeout=15)


@contextmanager
def role_transaction(role: str) -> Iterator[Any]:
    """A transaction in which row-level security is scoped to `role`.

    set_config(..., true) is transaction-local, so a pooled connection can never
    carry one user's role into another request.
    """
    with app_pool().connection() as conn, conn.transaction():
        conn.execute("SELECT set_config('app.role', %s, true)", (role.lower().strip(),))
        yield conn


def query_as_role(role: str, sql: str, params: Any = None) -> list[tuple]:
    with role_transaction(role) as conn:
        return conn.execute(sql, params).fetchall()


def withheld_summary(qvec, role: str, k: int) -> tuple[int, float | None]:
    """Count + best similarity of the role's withheld hits among the k nearest chunks.

    Runs a SECURITY DEFINER function: no withheld text, title or ID leaves the database.
    """
    with app_pool().connection() as conn:
        row = conn.execute(
            "SELECT doc_count, max_similarity FROM withheld_summary(%s, %s, %s)",
            (qvec, role.lower().strip(), int(k)),
        ).fetchone()
    return int(row[0] or 0), (None if row[1] is None else float(row[1]))


def owner_connection():
    """Direct connection for ingestion / migrations. Connects as rag_owner."""
    if not OWNER_DATABASE_URL:
        raise RuntimeError("OWNER_DATABASE_URL is not set. See .env.example.")
    import psycopg
    conn = psycopg.connect(OWNER_DATABASE_URL)
    _configure(conn)
    return conn


def database_status() -> dict[str, Any]:
    """Small health check for the UI: is the DB reachable and loaded?"""
    if not DATABASE_URL:
        return {"ok": False, "error": "DATABASE_URL is not set (copy .env.example to .env)."}
    try:
        # Fail fast with one direct attempt, so a stopped database does not leave the
        # pool retrying in the background.
        import psycopg
        psycopg.connect(DATABASE_URL, connect_timeout=15).close()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc!r}"}
    try:
        # Counted as 'admin' (sees every collection) inside a role-scoped transaction.
        with role_transaction("admin") as conn:
            docs, chunks, newest = conn.execute(
                "SELECT (SELECT count(*) FROM documents), (SELECT count(*) FROM chunks),"
                " (SELECT max(ingested_at) FROM documents)"
            ).fetchone()
        return {"ok": True, "documents": int(docs), "chunks": int(chunks),
                "ingested_at": newest.isoformat() if newest else None}
    except Exception as exc:  # noqa: BLE001 - surfaced in the UI
        return {"ok": False, "error": f"{type(exc).__name__}: {exc!r}"}
