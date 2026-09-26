-- db/init/01_schema.sql
-- Runs once on a fresh database, as the owner role (rag_owner).
-- Tables for documents, chunks (+ embeddings), access control, audit and evaluation.
CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------- access model
CREATE TABLE IF NOT EXISTS collections (
  name        text PRIMARY KEY,
  description text
);

CREATE TABLE IF NOT EXISTS roles (
  name text PRIMARY KEY
);

-- Synced from config/settings.py ROLE_COLLECTIONS by scripts/build_db.py
CREATE TABLE IF NOT EXISTS role_collections (
  role       text REFERENCES roles(name) ON DELETE CASCADE,
  collection text REFERENCES collections(name) ON DELETE CASCADE,
  PRIMARY KEY (role, collection)
);

-- ---------------------------------------------------------------- documents
-- One row per document VERSION, loaded from data/manifest.yaml.
CREATE TABLE IF NOT EXISTS documents (
  doc_version_id  text PRIMARY KEY,                 -- 'PAY-MRI-HIST@1'
  document_id     text NOT NULL,                    -- 'PAY-MRI-HIST'
  version         text NOT NULL,
  title           text NOT NULL,
  document_type   text NOT NULL,
  status          text NOT NULL
                  CHECK (status IN ('DRAFT','ACTIVE','SUPERSEDED','RETIRED')),
  effective_date  date,
  review_due      date,
  supersedes      text REFERENCES documents(doc_version_id) DEFERRABLE INITIALLY DEFERRED,
  superseded_by   text REFERENCES documents(doc_version_id) DEFERRABLE INITIALLY DEFERRED,
  authority_level smallint NOT NULL CHECK (authority_level BETWEEN 1 AND 5),
  collection      text NOT NULL REFERENCES collections(name),
  population      text[] NOT NULL DEFAULT '{all}',
  owner_contact   text,
  synthetic       boolean NOT NULL DEFAULT false,
  pii_test        boolean NOT NULL DEFAULT false,
  notes           text,
  source_file     text NOT NULL,
  source_sha256   text NOT NULL,
  ingested_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (document_id, version)
);

-- ---------------------------------------------------------------- chunks
CREATE TABLE IF NOT EXISTS chunks (
  chunk_id       text PRIMARY KEY,                  -- 'FORM-RIVA@dataset-copy#T12.1.R3'
  doc_version_id text NOT NULL REFERENCES documents ON DELETE CASCADE,
  parent_id      text REFERENCES chunks(chunk_id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
  chunk_type     text NOT NULL CHECK (chunk_type IN ('prose','clause','table','table_row')),
  collection     text NOT NULL,                     -- copied from documents; used by RLS
  section        text,
  page           int,
  table_id       text,
  row_id         text,
  row_fields     jsonb NOT NULL DEFAULT '{}',       -- {"crcl_min":0,"crcl_max":14.99}
  text           text NOT NULL,
  pii_masked     boolean NOT NULL DEFAULT false,
  pii_types      text[] NOT NULL DEFAULT '{}',
  identifiers    text[] NOT NULL DEFAULT '{}',      -- exact codes: PA-MRI-204, IP-7, N18.4
  embedding      vector(384) NOT NULL,              -- BAAI/bge-small-en-v1.5
  tsv            tsvector GENERATED ALWAYS AS
                 (to_tsvector('english', coalesce(section, '') || ' ' || text)) STORED
);

CREATE INDEX IF NOT EXISTS chunks_tsv_gin    ON chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunks_ids_gin    ON chunks USING gin (identifiers);
CREATE INDEX IF NOT EXISTS chunks_doc        ON chunks (doc_version_id);
CREATE INDEX IF NOT EXISTS chunks_parent     ON chunks (parent_id);
CREATE INDEX IF NOT EXISTS chunks_collection ON chunks (collection);
-- No vector index: an exact scan of a few thousand 384-d vectors takes milliseconds
-- and never drops rows because of the RLS filter. For production scale add
--   CREATE INDEX ... USING hnsw (embedding vector_cosine_ops);  plus hnsw.iterative_scan.

-- ---------------------------------------------------------------- audit + evaluation
CREATE TABLE IF NOT EXISTS audit_log (
  id                 bigserial PRIMARY KEY,
  query_id           text UNIQUE NOT NULL,
  created_at         timestamptz NOT NULL DEFAULT now(),
  user_role          text NOT NULL,
  query_masked       text NOT NULL,                 -- PII-masked question
  decision           text NOT NULL,
  reason_codes       text[] NOT NULL DEFAULT '{}',
  evidence_map       jsonb NOT NULL DEFAULT '{}',
  document_versions  text[] NOT NULL DEFAULT '{}',
  withheld_doc_count int NOT NULL DEFAULT 0,
  record             jsonb NOT NULL                 -- full audit record
);
CREATE INDEX IF NOT EXISTS audit_created ON audit_log (created_at DESC);

CREATE TABLE IF NOT EXISTS eval_runs (
  run_id     serial PRIMARY KEY,
  started_at timestamptz NOT NULL DEFAULT now(),
  backend    text NOT NULL,
  settings   jsonb NOT NULL DEFAULT '{}',
  metrics    jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS eval_results (
  run_id             int REFERENCES eval_runs ON DELETE CASCADE,
  question_id        int NOT NULL,
  role               text NOT NULL,
  question           text NOT NULL,
  expected_decision  text NOT NULL,
  actual_decision    text NOT NULL,
  expected_documents text[] NOT NULL DEFAULT '{}',
  got_documents      text[] NOT NULL DEFAULT '{}',
  reason_codes       text[] NOT NULL DEFAULT '{}',
  decision_pass      boolean NOT NULL,
  evidence_pass      boolean NOT NULL,
  PRIMARY KEY (run_id, question_id)
);
