CREATE TABLE IF NOT EXISTS jobs (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        TEXT NOT NULL DEFAULT 'demo-user',
  ticker         TEXT NOT NULL,
  status         TEXT NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending','running','complete','failed')),
  recommendation TEXT
                   CHECK (recommendation IN ('buy','hold','sell') OR recommendation IS NULL),
  result         JSONB,
  error          TEXT,
  sandbox_id     TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at     TIMESTAMPTZ,
  completed_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS jobs_user_status_created_idx
  ON jobs (user_id, status, created_at DESC);
