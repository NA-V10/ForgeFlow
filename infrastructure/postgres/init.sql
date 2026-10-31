-- Schema is created by Alembic migrations when the API starts (FORGEFLOW_AUTO_MIGRATE=true).
-- This file only prepares the database itself.
ALTER DATABASE forgeflow SET timezone TO 'UTC';
CREATE EXTENSION IF NOT EXISTS pgcrypto;
