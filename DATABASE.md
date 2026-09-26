# Database setup (PostgreSQL + pgvector)

Everything the app stores lives in one PostgreSQL 16 database with the pgvector extension:
documents, chunks + embeddings, roles and access rules, the audit log and evaluation runs.

## First-time setup (about 5 minutes + embedding time)

Prerequisites: Docker Desktop (or Docker Engine) and Python 3.11.

```bash
pip install -r requirements.txt       # adds psycopg, psycopg-pool, pgvector
cp .env.example .env                  # defaults match docker-compose.yml
docker compose up -d                  # starts PostgreSQL, runs db/init/*.sql once
docker compose ps                     # wait until the db service shows "healthy"
python scripts/build_db.py            # parse the 12 PDFs, embed, load (a few minutes)
pytest -q                             # includes the database tests
python evaluation/run_eval.py         # 14 questions; run is saved in the database
streamlit run app.py
```

The sidebar should show **Database 🟢 · 12 documents · 4404 chunks**.

## Everyday commands

| Task | Command |
|---|---|
| Start / stop the database | `docker compose up -d` / `docker compose stop` |
| Load new or changed documents | `python scripts/build_db.py` (unchanged files are skipped) |
| Re-embed everything (e.g. new model or chunking) | `python scripts/build_db.py --force` |
| Change who can see what | edit `ROLE_COLLECTIONS` in `config/settings.py`, then run `python scripts/build_db.py` |
| Change a document's access, status or authority | edit `data/manifest.yaml`, then run `python scripts/build_db.py` |
| Wipe everything and start clean | `docker compose down -v && docker compose up -d && python scripts/build_db.py` |
| Open a SQL shell | `docker compose exec db psql -U rag_owner -d rag` |
| Reports (audit, evaluation, loaded docs) | run the queries in `db/reports.sql` |

## How it is wired

| File | Purpose |
|---|---|
| `docker-compose.yml` | PostgreSQL 16 + pgvector; mounts `db/init` |
| `db/init/01_schema.sql` | tables: `documents`, `chunks` (with `vector(384)` + generated `tsvector`), `roles`, `collections`, `role_collections`, `audit_log`, `eval_runs`, `eval_results` |
| `db/init/02_security.sql` | `rag_app` user, grants, row-level security, `search_candidates()` and `withheld_summary()` |
| `db/init/03_seed.sql` | the four collections |
| `db/connection.py` | connection pool; `role_transaction(role)` sets `app.role` for RLS |
| `ingestion/store.py` | writes documents, chunks and access rules (idempotent) |
| `scripts/build_db.py` | ingestion command |
| `retrieval/pg_search.py` + `retrieval/sql/hybrid_search.sql` | retrieval for the pipeline |

Two database users:

* **rag_owner** owns the tables. Only `scripts/build_db.py` uses it (`OWNER_DATABASE_URL`).
* **rag_app** is what the Streamlit app uses (`DATABASE_URL`). It can read documents and chunks
  only through row-level security, and it can INSERT into `audit_log` but not UPDATE or DELETE.

## Access control in one paragraph

Every request runs in a transaction that sets `app.role` (for example `doctor`). Row-level
security policies on `documents` and `chunks` hide every row outside that role's collections,
and with no role set nothing is visible. Search ranks the whole corpus inside the
`search_candidates()` function, as the earlier FAISS design did, but that function returns only
the IDs of chunks the role may see; their text is then read under RLS. `withheld_summary()`
returns just two numbers (how many other-collection documents matched, and how closely), which
is all the trust engine needs to decide `RESTRICTED`.

Proof you can show in a demo (`docker compose exec db psql -U rag_owner -d rag`):

```sql
BEGIN;
SET LOCAL ROLE rag_app;
SELECT set_config('app.role', 'doctor', true);
SELECT count(*) FROM chunks WHERE doc_version_id LIKE 'RES-FDA-PUMP@%';   -- 0
ROLLBACK;
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| App says "Cannot reach PostgreSQL" | `docker compose up -d`; check `DATABASE_URL` in `.env` |
| Port 5432 already in use | set `DB_PORT=5433` in `.env` and change both URLs to `:5433` |
| "no documents are loaded yet" | `python scripts/build_db.py` (or the **Build now** button) |
| `... gives N-d vectors but the database column is vector(384)` | a different embedding model; change `vector(384)` in `01_schema.sql` and in the two function signatures in `02_security.sql`, set `EMBEDDING_DIM`, then wipe and rebuild |
| Changed `db/init/*.sql` but nothing happened | init scripts only run on an empty volume: `docker compose down -v && docker compose up -d` |
| No Docker available | use any hosted PostgreSQL with the pgvector extension, run the three `db/init` files with `psql`, and point both URLs at it |
| Need to demo without a database | `RETRIEVAL_BACKEND=files` in `.env`, then `python scripts/build_index.py` |
