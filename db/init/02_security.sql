-- db/init/02_security.sql
-- The Streamlit app connects as rag_app (limited by grants + row-level security).
-- Ingestion connects as rag_owner (owns the tables).
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rag_app') THEN
    CREATE ROLE rag_app LOGIN PASSWORD 'rag_app_dev';   -- dev only; use a secret in production
  END IF;
END $$;

GRANT USAGE ON SCHEMA public TO rag_app;
GRANT SELECT ON collections, roles, role_collections, documents, chunks TO rag_app;
GRANT INSERT, SELECT ON audit_log TO rag_app;          -- no UPDATE / DELETE: append-only
GRANT USAGE ON SEQUENCE audit_log_id_seq TO rag_app;
GRANT INSERT, SELECT ON eval_runs, eval_results TO rag_app;
GRANT USAGE ON SEQUENCE eval_runs_run_id_seq TO rag_app;

-- Row-level security: every request sets app.role inside its transaction.
-- Rows outside that role's collections are invisible. No role set -> no rows.
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE chunks    ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS documents_by_role ON documents;
CREATE POLICY documents_by_role ON documents FOR SELECT TO rag_app
  USING (collection IN (SELECT rc.collection FROM role_collections rc
                        WHERE rc.role = current_setting('app.role', true)));

DROP POLICY IF EXISTS chunks_by_role ON chunks;
CREATE POLICY chunks_by_role ON chunks FOR SELECT TO rag_app
  USING (collection IN (SELECT rc.collection FROM role_collections rc
                        WHERE rc.role = current_setting('app.role', true)));

-- Corpus-wide search for one role.
-- Ranks ALL chunks (vector, full-text and exact-code lists, fused with Reciprocal Rank
-- Fusion), exactly like the earlier FAISS + BM25 design, so a role only receives chunks
-- that are genuinely among the best matches in the whole corpus. It then returns ONLY
-- the IDs and scores of chunks this role may see. Text is read afterwards under RLS.
CREATE OR REPLACE FUNCTION search_candidates(
    q vector(384), qtext text, qids text[], p_role text,
    k_dense int DEFAULT 30, k_lexical int DEFAULT 30, rrf_k int DEFAULT 60, lim int DEFAULT 20)
RETURNS TABLE (chunk_id text, rrf_score float8, vector_score float8, lexical_score float8,
               vector_rank bigint, lexical_rank bigint, exact_rank bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  WITH p AS (
    -- OR the query terms together; plainto_tsquery's AND would match almost nothing
    SELECT replace(plainto_tsquery('english', qtext)::text, '&', '|')::tsquery AS tsq
  ),
  dense AS (
    SELECT c.chunk_id, 1 - (c.embedding <=> q) AS score,
           row_number() OVER (ORDER BY c.embedding <=> q) AS rnk
    FROM chunks c ORDER BY c.embedding <=> q LIMIT k_dense
  ),
  lexical AS (
    SELECT c.chunk_id, ts_rank_cd(c.tsv, p.tsq) AS score,
           row_number() OVER (ORDER BY ts_rank_cd(c.tsv, p.tsq) DESC) AS rnk
    FROM chunks c, p WHERE c.tsv @@ p.tsq
    ORDER BY ts_rank_cd(c.tsv, p.tsq) DESC LIMIT k_lexical
  ),
  exact AS (                                   -- codes the text parser would split
    SELECT c.chunk_id,
           row_number() OVER (ORDER BY cardinality(ARRAY(
             SELECT unnest(c.identifiers) INTERSECT SELECT unnest(qids))) DESC) AS rnk
    FROM chunks c WHERE c.identifiers && qids LIMIT k_lexical
  ),
  fused AS (
    SELECT chunk_id,
           (coalesce(1.0 / (rrf_k + d.rnk), 0) + coalesce(1.0 / (rrf_k + l.rnk), 0)
          + coalesce(1.0 / (rrf_k + x.rnk), 0))::float8 AS rrf_score,
           d.score::float8 AS vector_score, l.score::float8 AS lexical_score,
           d.rnk AS vector_rank, l.rnk AS lexical_rank, x.rnk AS exact_rank
    FROM dense d FULL JOIN lexical l USING (chunk_id) FULL JOIN exact x USING (chunk_id)
  )
  SELECT f.chunk_id, f.rrf_score, f.vector_score, f.lexical_score,
         f.vector_rank, f.lexical_rank, f.exact_rank
  FROM fused f JOIN chunks c ON c.chunk_id = f.chunk_id
  WHERE c.collection IN (SELECT rc.collection FROM role_collections rc WHERE rc.role = p_role)
  ORDER BY f.rrf_score DESC
  LIMIT lim
$$;
REVOKE ALL ON FUNCTION search_candidates(vector, text, text[], text, int, int, int, int) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION search_candidates(vector, text, text[], text, int, int, int, int) TO rag_app;

-- Withheld summary for the RESTRICTED decision.
-- Runs as the owner (so RLS does not hide rows from it) but returns ONLY two numbers:
-- among the k nearest chunks in the whole corpus, how many documents the role cannot
-- see, and the best cosine similarity among those. No text, titles or IDs leave the DB.
-- (Same semantics as the previous FAISS version: withheld hits within the top-k.)
CREATE OR REPLACE FUNCTION withheld_summary(q vector(384), p_role text, k int DEFAULT 30)
RETURNS TABLE (doc_count int, max_similarity real)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  WITH nearest AS (
    SELECT c.doc_version_id, c.collection, 1 - (c.embedding <=> q) AS sim
    FROM chunks c
    ORDER BY c.embedding <=> q
    LIMIT k
  )
  SELECT count(DISTINCT n.doc_version_id)::int, max(n.sim)::real
  FROM nearest n
  WHERE n.collection NOT IN (SELECT rc.collection FROM role_collections rc
                             WHERE rc.role = p_role)
$$;
REVOKE ALL ON FUNCTION withheld_summary(vector, text, int) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION withheld_summary(vector, text, int) TO rag_app;
