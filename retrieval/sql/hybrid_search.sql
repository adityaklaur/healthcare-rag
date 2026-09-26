-- retrieval/sql/hybrid_search.sql
-- 1. search_candidates() ranks the WHOLE corpus (vector + full-text + exact codes, RRF)
--    and returns only IDs/scores of chunks this role may see.
-- 2. The text and metadata are then read from chunks/documents UNDER ROW-LEVEL SECURITY
--    (this runs as rag_app with app.role set), so restricted text cannot come back even
--    if the function had a bug.
SELECT f.chunk_id, f.rrf_score, f.vector_score, f.lexical_score,
       f.vector_rank, f.lexical_rank, f.exact_rank,
       c.parent_id, c.chunk_type, c.collection, c.section, c.page, c.table_id, c.row_id,
       c.row_fields, c.text, c.pii_masked, c.pii_types,
       d.document_id, d.title, d.document_type, d.version, d.status,
       d.effective_date, d.review_due, d.supersedes, d.superseded_by,
       d.authority_level, d.population, d.owner_contact, d.source_file, d.synthetic
FROM search_candidates(%(qvec)s::vector, %(qtext)s, %(qids)s::text[], current_setting('app.role', true),
                       %(k_dense)s, %(k_lexical)s, %(rrf_k)s, %(limit)s) AS f
JOIN chunks c    ON c.chunk_id = f.chunk_id
JOIN documents d ON d.doc_version_id = c.doc_version_id
ORDER BY f.rrf_score DESC;
