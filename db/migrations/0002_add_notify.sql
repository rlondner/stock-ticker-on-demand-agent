-- db/migrations/0002_add_notify.sql
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS notify_channel TEXT
  CHECK (notify_channel IN ('slack','gmail') OR notify_channel IS NULL);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS notify_destination TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS notified_at TIMESTAMPTZ;
