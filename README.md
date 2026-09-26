# Healthcare Enterprise RAG — Architecture-Aligned Hackathon MVP

This codebase implements the **Revision 3 Healthcare Enterprise RAG architecture** around one rule: retrieval is not permission to answer. Search runs first, access control removes what the role may not see, the **Clinical Evidence Trust Engine** decides whether the evidence is safe and sufficient, and only `ANSWER` / `ANSWER_WITH_WARNING` may reach the language model.

**Storage: PostgreSQL + pgvector.** Documents, chunks, embeddings, roles, the audit log and evaluation results live in one database, and the database itself enforces access control with row-level security. Setup takes one command (`docker compose up -d`); see **[DATABASE.md](DATABASE.md)**. The original FAISS + BM25 + JSONL setup is kept as a fallback (`RETRIEVAL_BACKEND=files`).

> **Hackathon prototype:** use synthetic/demo questions only. This repository is not a medical device and is not intended for real patient-care decisions.

## What changed from the earlier code

The original single-file modules were refactored into the architecture's stages:

```text
User / Streamlit
  -> Query understanding
  -> PostgreSQL: corpus-wide vector + full-text + exact-code search (RRF),
     returning only chunks this role may see; text read under row-level security
  -> Withheld summary (count + best similarity only) for RESTRICTED
  -> Optional cross-encoder reranker
  -> Deterministic trust rules
  -> Evidence sufficiency/conflict judge
  -> Fixed decision precedence
       ANSWER | ANSWER_WITH_WARNING | CONFLICT | REFUSE | RESTRICTED
  -> Grounded generation OR fixed template
  -> Output guard
  -> Audit (audit_log table, append-only)
  -> UI
```

Key corrections from Revision 2 are implemented: **search before ACL partition**, withheld text never leaves retrieval, deterministic population checks, structured renal-range table rows where extraction is possible, `SUPERSEDED` handling, authority levels, fixed decision precedence, non-answer templates, PII masking, output citation/number checks, and audit logging on every path.

## Project structure

```text
healthcare-rag/
├── app.py
├── pipeline.py
├── models.py
├── docker-compose.yml       # PostgreSQL 16 + pgvector
├── db/
│   ├── init/01_schema.sql   # tables and indexes
│   ├── init/02_security.sql # app user, grants, row-level security, search functions
│   ├── init/03_seed.sql     # collections
│   ├── connection.py        # connection pool, role-scoped transactions
│   └── reports.sql          # audit / evaluation queries
├── config/
│   ├── settings.py
│   └── prompts.py
├── data/
│   ├── manifest.yaml
│   └── <12 PDFs already provided>
├── ingestion/
│   ├── loader.py
│   ├── table_parser.py
│   ├── chunker.py
│   ├── pii_filter.py
│   ├── metadata.py
│   ├── extract.py           # manifest + files -> chunks (both backends)
│   └── store.py             # write documents/chunks/roles to PostgreSQL
├── query/
│   └── understand.py
├── retrieval/
│   ├── embedder.py
│   ├── vector_search.py
│   ├── bm25_search.py
│   ├── acl.py
│   ├── hybrid.py            # retrieve(): picks the backend
│   ├── pg_search.py         # PostgreSQL backend
│   ├── sql/hybrid_search.sql
│   └── reranker.py
├── trust_engine/
│   ├── rules.py
│   ├── judge.py
│   └── decision.py
├── generation/
│   ├── generator.py
│   ├── templates.py
│   ├── citations.py
│   └── output_guard.py
├── audit/
│   └── logger.py
├── scripts/
│   ├── build_db.py          # load documents into PostgreSQL (default)
│   └── build_index.py       # FAISS/BM25 files (fallback backend)
├── indexes/                 # generated, fallback backend only
├── evaluation/
│   ├── questions.json
│   └── run_eval.py
├── tests/
│   ├── test_pii.py
│   ├── test_decision.py
│   ├── test_egfr.py
│   ├── test_population.py
│   └── test_db.py           # RLS, search function, audit (skips without a DB)
├── demo_questions.md
├── requirements.txt
└── .env.example
```

The repository keeps the **12 PDFs from the supplied code folder** rather than replacing them with the architecture document's fictional 10-document corpus. `data/manifest.yaml` maps those files into the same governance model (`collection`, `population`, `authority_level`, lifecycle status, etc.).

## 1. Setup

```bash
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate       # Windows
pip install -r requirements.txt
```

Configuration and database:

```bash
cp .env.example .env             # optional: add OPENAI_API_KEY=...
docker compose up -d             # PostgreSQL 16 + pgvector
```

Without an API key, the project still runs with deterministic judge and extractive-generation fallbacks. For the final hackathon demo, a hosted model is recommended because the architecture calls for one evidence-auditor judge call plus grounded generation.

## 2. Load the documents into PostgreSQL

```bash
python scripts/build_db.py          # re-run any time; unchanged files are skipped
python scripts/build_db.py --force  # re-parse and re-embed everything
```

`python ingest.py` also works (it builds whichever backend `RETRIEVAL_BACKEND` selects).
Roles and their collections are copied from `config/settings.py` on every run, so that
file stays the one place to change who can see what.

Fallback without a database: set `RETRIEVAL_BACKEND=files` in `.env` and run
`python scripts/build_index.py` (writes `indexes/faiss.index`, `bm25.pkl`, `chunks.jsonl`).

Ingestion uses PyMuPDF for page text and pdfplumber for tables. Tables are stored as a parent Markdown chunk plus individual row chunks. If a row header contains `eGFR` or `CrCl`, numeric range metadata is added when the range can be parsed.

## 3. Run unit tests

```bash
pytest -q
```

The safety tests cover PII masking, renal-range selection, population rules and fixed decision precedence. `tests/test_db.py` checks row-level security, the search and withheld-summary functions, append-only audit and question masking; it is skipped when no database is configured.

## 4. Run the app

```bash
streamlit run app.py
```

The UI always shows the same blocks: decision banner, answer/template, citations, evidence, excluded evidence, and audit. **Withheld evidence is never shown**; only an aggregate document count and scalar relevance score can leave the retrieval module.

## 5. Run the 14-question evaluation

```bash
python evaluation/run_eval.py
```

This writes `evaluation/results.json` and `evaluation/results.md`, and (PostgreSQL backend) stores the run in `eval_runs` / `eval_results`. `db/reports.sql` has a pass-rate-per-run query.

Report the per-question results along with decision accuracy, evidence recall, ACL leakage count, and identifier leakage count. With a 14-question set, these are demo indicators rather than statistical validation.

## Five decision states

| Decision | Meaning | LLM generation? |
|---|---|---:|
| `ANSWER` | permitted, current, relevant, sufficient, consistent evidence | Yes |
| `ANSWER_WITH_WARNING` | answerable, but evidence has a review/authority/historical caveat | Yes |
| `CONFLICT` | different eligible documents give incompatible instructions | No — fixed template |
| `REFUSE` | insufficient evidence, population mismatch, PHI request, guard failure | No — fixed template |
| `RESTRICTED` | relevant evidence exists only outside this role's collections | No — fixed template |

Decision precedence is fixed in `trust_engine/decision.py`: PHI request → insufficient/restricted → conflict → warning → answer.

## Access control

`config/settings.py` contains the role-to-collection map; `scripts/build_db.py` copies it into the `role_collections` table. The app connects as `rag_app` and sets its role per transaction, so **row-level security** makes other collections' rows invisible to every query. Ranking is still corpus-wide: the `search_candidates()` database function scores the whole corpus and returns only IDs of chunks the role may see, and their text is then read under RLS. For the `RESTRICTED` state, `withheld_summary()` returns just a document count and a similarity; withheld text, titles and IDs never leave the database.

## Citation and output guard

The model sees application-assigned `E1..E6` IDs. It does not create document metadata. The application renders the citation from trusted chunk metadata: title, version, table/row or section, page and effective date.

Before an answer is returned, `generation/output_guard.py` checks that every sentence has a valid evidence ID, clinically meaningful numbers with units exist in cited evidence, and detected identifiers are masked. A failed LLM answer is retried once; a second failure becomes `REFUSE` with `GUARD_FAILED`.

## Audit

Every query inserts one row into the `audit_log` table (the app user may INSERT but not UPDATE or DELETE), including query entities, retrieved chunk IDs, withheld **summary only**, exclusions/reason codes, evidence map, judge result, decision, guard result, corpus version and stage latency. Identifiers typed into the question are masked before storage. If the database write fails, the record goes to `audit/audit.jsonl` so no query is unaudited. Admins see the latest rows in the app.

## Demo flow

See `demo_questions.md`. The most reliable scenarios with the retained 12-document corpus are:

- cross-document conflict: synthetic anticoagulation SOP vs perioperative guideline;
- role switch: Doctor → Researcher for the restricted FDA infusion-pump document;
- pediatric Drug A request → population mismatch/refusal;
- MRN request → pre-search `PHI_REQUEST` refusal;
- Billing historical CMS MRI search → `ANSWER_WITH_WARNING` for superseded evidence;
- Rivaroxaban prescribing information → table/drug-label retrieval.

## MVP vs production

The MVP already runs on PostgreSQL + pgvector, so production is mostly hardening the same design: a managed PostgreSQL with backups, an HNSW index (with `hnsw.iterative_scan`) once the corpus grows, the role taken from an OIDC token instead of a dropdown, the security-definer functions owned by a non-superuser, audit partitions exported to WORM storage/SIEM, and the Python pipeline behind FastAPI. OpenSearch is only needed if true BM25 or specialist medical analyzers are required.

## Known limitations

The 12 retained PDFs were not authored specifically for every scenario in the Revision 2 architecture, so some architecture examples (for example the exact fictional Formulary v5.1/v4.0 `eGFR 25` table and synthetic incident `INC-014`) are validated by unit-test fixtures rather than by replacing your corpus. PDF table extraction also depends on how each source encodes its tables; if a table is image-only, authoring that table as CSV/Markdown is the fastest hackathon fallback.

PostgreSQL's full-text ranking (`ts_rank_cd`) is not BM25. On the 14-question evaluation both backends reach the same decisions and cite the same documents, but the individual chunks differ for some questions (PostgreSQL favours longer paragraphs, BM25 favoured short table rows). Re-run `python evaluation/run_eval.py` after loading with the real embedding model and tune `MIN_RELEVANCE_SCORE` / `RESTRICTED_THRESHOLD` if needed.
