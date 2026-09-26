-- db/reports.sql  - handy queries (psql, DBeaver, pgAdmin ...)
-- Connect as rag_owner, or as rag_app after: SELECT set_config('app.role','admin',false);

-- Decisions in the last hour
SELECT decision, count(*) FROM audit_log
WHERE created_at > now() - interval '1 hour'
GROUP BY decision ORDER BY 2 DESC;

-- RESTRICTED outcomes by role
SELECT user_role, count(*) FROM audit_log
WHERE decision = 'RESTRICTED' GROUP BY user_role;

-- Document versions cited today
SELECT doc, count(*) AS citations
FROM audit_log, unnest(document_versions) AS doc
WHERE created_at::date = current_date
GROUP BY doc ORDER BY citations DESC;

-- Pass rate per evaluation run
SELECT r.run_id, r.started_at, r.backend,
       round(100.0 * avg(e.decision_pass::int)) AS pct_decisions_passed,
       count(*) AS questions
FROM eval_runs r JOIN eval_results e USING (run_id)
GROUP BY r.run_id ORDER BY r.run_id DESC;

-- What is loaded
SELECT d.doc_version_id, d.status, d.collection, d.authority_level, count(c.*) AS chunks
FROM documents d LEFT JOIN chunks c USING (doc_version_id)
GROUP BY d.doc_version_id ORDER BY d.doc_version_id;

-- Row-level security proof: as a doctor, the restricted FDA document is invisible
BEGIN;
SET LOCAL ROLE rag_app;
SELECT set_config('app.role', 'doctor', true);
SELECT count(*) AS doctor_can_see FROM chunks WHERE doc_version_id LIKE 'RES-FDA-PUMP@%';
ROLLBACK;
