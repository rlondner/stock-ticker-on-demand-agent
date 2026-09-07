-- db/migrations/0002_add_depth.sql
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS depth TEXT NOT NULL DEFAULT 'quick'
  CHECK (depth IN ('quick','deep','full'));
