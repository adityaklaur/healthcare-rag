-- db/init/03_seed.sql
-- Collections are fixed here. Roles and role_collections are synced from
-- config/settings.py (ROLE_COLLECTIONS) every time scripts/build_db.py runs,
-- so settings.py stays the single place to change who can see what.
INSERT INTO collections (name, description) VALUES
  ('clinical',            'Guidelines, SOPs, toolkits, device manuals'),
  ('formulary',           'Drug formulary and prescribing information'),
  ('billing',             'Payer and coverage policies'),
  ('restricted_research', 'Research material with restricted access')
ON CONFLICT (name) DO NOTHING;
