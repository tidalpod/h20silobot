-- Add NO_SHOW status to ShowingStatus enum
-- Run this SQL directly in your database

-- For PostgreSQL:
ALTER TYPE showingstatus ADD VALUE IF NOT EXISTS 'no_show';

-- If the above doesn't work (older PostgreSQL), use this approach:
-- ALTER TYPE showingstatus RENAME TO showingstatus_old;
-- CREATE TYPE showingstatus AS ENUM ('scheduled', 'confirmed', 'completed', 'cancelled', 'no_show');
-- ALTER TABLE showings ALTER COLUMN status TYPE showingstatus USING status::text::showingstatus;
-- DROP TYPE showingstatus_old;
